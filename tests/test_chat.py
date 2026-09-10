"""
Guards on the thin chat.

The model is an external service and is not in the loop of these tests unless a
key is present. What IS always tested is everything that makes the chat honest:
the four tools answer from results/ and nothing else, their arguments are
validated, every figure a tool returns can be recomputed from the same files, and
the twenty golden questions each name the tool and the figure that answers them.
With a key in the environment, the model's routing is checked against the same
twenty — that part is skipped, not faked, without one.
"""

from __future__ import annotations

import json
import os
import pathlib

import pandas as pd
import pytest

import cli
from api import chat
from contracts.config import RunConfig

GOLDEN = json.loads(
    (pathlib.Path(__file__).parent / "golden_questions.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("chat")
    for cmd in ("build", "run", "score"):
        assert cli.main([cmd, "--preset", "toy", "--data-dir", str(data_dir)]) == 0
    return RunConfig(preset="toy", data_dir=data_dir)


def test_there_are_twenty_golden_questions_and_they_cover_every_tool():
    assert len(GOLDEN) == 20
    assert {g["tool"] for g in GOLDEN} == set(chat.TOOLS)


@pytest.mark.parametrize("g", GOLDEN, ids=[g["q"][:40] for g in GOLDEN])
def test_each_golden_question_has_an_answer_in_the_results(built, g):
    """The tool the question names returns the figure the question needs."""
    out = chat.run_tool(built, g["tool"], g["args"])
    assert "error" not in out, out
    assert g["figure"] in out, f"{g['tool']} does not return {g['figure']}"
    assert out[g["figure"]] is not None


def test_stockout_figures_match_the_position_file(built):
    pos = pd.read_parquet(built.results_dir / "positions.parquet")
    short = pos[pos["action"].isin(["order_now", "stocked_elsewhere"])]
    out = chat.run_tool(built, "get_stockouts", {"storeroom": "SMELTER"})
    mine = short[short["storeroom_id"] == "SMELTER"]
    assert out["count"] == len(mine)
    assert out["cost_to_level_sar"] == pytest.approx(mine["cost_to_level_sar"].sum())


def test_dead_money_figures_match_the_engine_file(built):
    dead = pd.read_parquet(built.results_dir / "dead_money.parquet")
    out = chat.run_tool(built, "get_dead_money", {"category": "never_used", "top_n": 3})
    mine = dead[dead["category"] == "never_used"]
    assert out["count"] == len(mine)
    assert out["dead_value_sar"] == pytest.approx(mine["dead_value_sar"].sum())
    assert len(out["rows"]) == min(3, len(mine))


def test_bad_arguments_are_a_clean_error_not_a_stack_trace(built):
    assert "error" in chat.run_tool(built, "get_stockouts", {"storeroom": "NARNIA"})
    assert "error" in chat.run_tool(built, "get_dead_money", {"top_n": 0})
    assert "error" in chat.run_tool(built, "get_item", {"material_id": "bearing"})
    assert "error" in chat.run_tool(built, "no_such_tool", {})


def test_an_unknown_part_is_said_not_invented(built):
    out = chat.run_tool(built, "get_item", {"material_id": "M-999999"})
    assert "error" in out and "M-999999" in out["error"]


def test_tools_read_results_only():
    """
    The chat must not be able to reach the source tables or the answer key: it
    could otherwise narrate truth as if the engine had found it.
    """
    text = pathlib.Path(chat.__file__).read_text(encoding="utf-8")
    for needle in ("source_dir", "answer_key_dir", "TRUTH_", "S.STOCK", "S.MATERIALS",
                   "S.MOVEMENTS"):
        assert needle not in text, f"chat.py references {needle}"


def test_without_a_key_the_chat_says_so(built, monkeypatch):
    monkeypatch.delenv(chat.KEY_VAR, raising=False)
    assert chat.status()["available"] is False
    out = chat.answer(built, "anything")
    assert out["status"] == "unavailable" and chat.KEY_VAR in out["detail"]


def test_the_system_prompt_forbids_arithmetic():
    assert "Never calculate" in chat.SYSTEM
    assert "cannot answer" in chat.SYSTEM


@pytest.mark.skipif(not os.environ.get(chat.KEY_VAR), reason="no API key in the environment")
@pytest.mark.parametrize("g", GOLDEN, ids=[g["q"][:40] for g in GOLDEN])
def test_live_model_routes_each_golden_question_to_the_expected_tool(built, g):
    try:
        out = chat.answer(built, g["q"])
    except RuntimeError as exc:
        # the provider's credit or rate limit is not a routing regression
        if any(code in str(exc) for code in ("402", "429")):
            pytest.skip(f"provider budget or rate limit: {str(exc)[:80]}")
        raise
    assert out["status"] == "ok"
    assert out["tool"] == g["tool"], f"routed to {out['tool']} with {out['args']}"
    assert len(out["answer"].split(". ")) <= 4, "two or three sentences"


def test_prior_turns_travel_as_plain_text_only():
    """
    A follow-up like "and in the smelter?" needs the previous exchange, but only
    the narrated answers go back to the model — never a tool result, so it must
    call the tool again rather than remember a figure. Junk history is dropped.
    """
    prior = chat._prior([
        {"question": "Which A-critical parts are out?", "answer": "There are 572."},
        {"question": "", "answer": "orphan"},
        {"question": "no answer yet"},
        {"question": "x" * 900, "answer": "y" * 2000},
    ])
    assert [m["role"] for m in prior] == ["user", "assistant", "user", "assistant"]
    assert prior[0]["content"] == "Which A-critical parts are out?"
    assert len(prior[2]["content"]) == 500 and len(prior[3]["content"]) == 1000
    assert chat._prior(None) == [] and chat._prior([{}]) == []
    # only the last six exchanges are kept
    many = [{"question": f"q{i}", "answer": f"a{i}"} for i in range(10)]
    assert len(chat._prior(many)) == 12 and chat._prior(many)[0]["content"] == "q4"
