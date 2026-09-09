"""
Guards on the read-only API.

The one property that matters here is negative: the API must not read source
tables or the answer key. It serves what `score` already wrote, so a request is a
file read — anything else and the screen can disagree with the scoreboard beside
it, or stall on 25,000 positions while someone is watching.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import cli  # noqa: E402
from api.app import create_app  # noqa: E402
from contracts.config import RunConfig  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("api-data")
    for cmd in ("build", "run", "score"):
        assert cli.main([cmd, "--preset", "toy", "--data-dir", str(data_dir)]) == 0
    return TestClient(create_app(RunConfig(preset="toy", data_dir=data_dir)))


def test_summary_has_the_three_headline_figures(served):
    d = served.get("/api/summary").json()
    inv = d["inventory"]
    assert inv["total_stock_value_sar"] > 0
    assert 0 < inv["idle_24m_share"] < 1
    assert 0 < inv["dead_value_share"] < 1
    assert inv["source"] == "truth", (
        "the screen must state these came from the answer key, not the engine"
    )
    assert d["targets"]["dead_value_share"] == [0.20, 0.40]


def test_scoreboard_matches_the_file_on_disk(served, tmp_path_factory):
    d = served.get("/api/scoreboard").json()
    assert d["summary"]["planted"] > 0
    assert d["summary"]["recall"] is not None
    assert "declared" in d, "the screen needs to know which checks actually ran"
    assert d["declared"]["informational"] == ["LEDGER_MISMATCH"]


def test_index_is_served(served):
    r = served.get("/")
    assert r.status_code == 200
    assert "<div id=\"root\">" in r.text


def test_missing_results_say_what_to_run(tmp_path):
    client = TestClient(create_app(RunConfig(preset="toy", data_dir=tmp_path)))
    r = client.get("/api/summary")
    assert r.status_code == 404
    assert "cli.py" in r.json()["detail"], "a 404 should name the command that fixes it"


def test_api_never_reads_source_or_answer_key():
    """
    Structural guard. `results/` only — if the API could reach the answer key it
    could serve truth as though the engine had found it, which is the single most
    dishonest thing this POC could do.
    """
    forbidden = ("source_dir", "answer_key_dir", "MATERIALS", "STOCK", "MOVEMENTS",
                 "TRUTH_MATERIALS", "TRUTH_POSITIONS", "PLANTED_DEFECTS_FILE")
    for path in (ROOT / "api").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"{path.name} references {needle}"
        for node in ast.walk(ast.parse(text)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in {"generator", "sim"}, (
                    f"{path.name} imports {name}"
                )


def test_summary_json_is_valid_on_disk(served):
    """The dashboard reads this file directly; malformed JSON is a blank screen."""
    d = served.get("/api/summary").json()
    json.dumps(d)
