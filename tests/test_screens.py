"""
Guards on the position file, the endpoints behind the screens, and the screens.

The screens are the first part of this POC a person will judge it by, and the two
ways they fail are quiet: a position file that has drifted out of step with the
stock table so rows are silently missing, and a page that pulls a script from a
CDN and renders blank on a demo laptop with no network. Both are cheap to assert
and neither is visible in a screenshot taken on a machine that does have network.
"""

from __future__ import annotations

import pathlib
import re

import pandas as pd
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import cli  # noqa: E402
from api.app import PAGE_SIZE, create_app  # noqa: E402
from contracts import schemas as S  # noqa: E402
from contracts.config import RunConfig  # noqa: E402
from engine.positions import POSITIONS_FILE  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "api" / "static"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("screens")
    for cmd in ("build", "run", "score"):
        assert cli.main([cmd, "--preset", "toy", "--data-dir", str(data_dir)]) == 0
    return RunConfig(preset="toy", data_dir=data_dir)


@pytest.fixture(scope="module")
def client(built):
    return TestClient(create_app(built))


# ── the file behind the screens ──────────────────────────────────────────────


def test_one_row_per_position_no_more_no_less(built):
    """
    A position that exists in stock and not in this file is a line the planner
    cannot see at all, and nothing on the screen would reveal it was dropped.
    """
    stock = S.read(S.STOCK, built.source_dir)
    pos = pd.read_parquet(built.results_dir / POSITIONS_FILE)
    assert len(pos) == len(stock)
    key = lambda f: set(zip(f["material_id"], f["storeroom_id"], strict=True))  # noqa: E731
    assert key(pos) == key(stock)


def test_every_row_carries_its_reason(built):
    pos = pd.read_parquet(built.results_dir / POSITIONS_FILE)
    assert pos["reason"].str.len().min() > 20, "a level with no explanation is not usable"


def test_history_arrays_cover_the_whole_history(built):
    pos = pd.read_parquet(built.results_dir / POSITIONS_FILE)
    months = len(pd.period_range(built.history_start, built.history_end, freq="M"))
    assert all(len(a) == months for a in pos["usage_months"].head(50))
    assert pos["train_months"].iloc[0] < months, "the eval months must be in there too"


def test_a_negative_balance_does_not_take_over_the_ranking(built):
    """
    Ranking is by units missing below the reorder point. Before `on_hand` was
    clamped at zero, a planted balance of -29 against a reorder point of 5 scored
    as 34 units short and sat at the top of the board — a data defect masquerading
    as the plant's most urgent shortage.
    """
    pos = pd.read_parquet(built.results_dir / POSITIONS_FILE)
    assert (pos["units_below_reorder"] <= pos["reorder_point"] + 1e-9).all()


# ── the endpoints ────────────────────────────────────────────────────────────


def test_paging_walks_the_whole_board_without_repeating(client):
    first = client.get("/api/positions?page=1").json()
    assert first["page_size"] == PAGE_SIZE
    assert len(first["rows"]) == PAGE_SIZE

    seen, page = set(), 1
    while page <= first["pages"]:
        rows = client.get(f"/api/positions?page={page}").json()["rows"]
        for r in rows:
            key = (r["material_id"], r["storeroom_id"])
            assert key not in seen, f"{key} appears on two pages"
            seen.add(key)
        page += 1
    assert len(seen) == first["total"]


def test_the_board_is_ranked_by_what_it_costs_to_ignore(client):
    rows = client.get("/api/positions?page=1").json()["rows"]
    risk = [r["value_at_risk_sar"] for r in rows]
    assert risk == sorted(risk, reverse=True)


def test_filters_narrow_and_agree_with_their_own_counts(client):
    page = client.get("/api/positions").json()
    band = max(page["bands"], key=page["bands"].get)
    filtered = client.get("/api/positions?band=" + band).json()
    assert filtered["total"] == page["bands"][band]
    assert all(r["band"] == band for r in filtered["rows"])


def test_search_finds_a_part_by_its_own_description(client):
    row = client.get("/api/positions").json()["rows"][0]
    word = row["description"].split(",")[0]
    found = client.get("/api/positions?q=" + word).json()
    assert found["total"] >= 1
    assert any(word.lower() in r["description"].lower() for r in found["rows"])


def test_the_drawer_gets_the_history_the_list_does_not(client):
    row = client.get("/api/positions").json()["rows"][0]
    assert "usage_months" not in row, "the list must not carry 36 floats a row"
    detail = client.get(
        f"/api/positions/{row['material_id']}/{row['storeroom_id']}"
    ).json()
    for field in ("usage_months", "forecast_months", "planned_wo_months", "reason",
                  "elsewhere", "train_months", "months_start"):
        assert field in detail


def test_an_unknown_id_gets_a_404_that_helps(client):
    r = client.get("/api/positions/M-NOPE/NOWHERE")
    assert r.status_code == 404
    assert "ids look like" in r.json()["detail"]


def test_a_real_part_in_the_wrong_storeroom_is_told_where_it_is(client):
    row = client.get("/api/positions").json()["rows"][0]
    r = client.get(f"/api/positions/{row['material_id']}/NOWHERE")
    assert r.status_code == 404
    assert row["storeroom_id"] in r.json()["detail"]


def test_storeroom_rollup_adds_up_to_the_board(client):
    stores = client.get("/api/storerooms").json()["by_storeroom"]
    total = client.get("/api/positions").json()["total_unfiltered"]
    assert sum(s["positions"] for s in stores) == total


# ── the page ─────────────────────────────────────────────────────────────────


def test_the_page_pulls_nothing_from_the_internet():
    """
    A demo laptop on a client site may have no route out. Every script and style
    the page needs is vendored, and this is the assertion that keeps it that way
    — a CDN tag added later renders a blank screen only in the meeting room.
    """
    text = (STATIC / "index.html").read_text(encoding="utf-8")
    for src in re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', text):
        assert not src.startswith(("http://", "https://", "//")), f"remote asset: {src}"
    for name in ("react.production.min.js", "react-dom.production.min.js",
                 "htm.umd.js"):
        assert (STATIC / "vendor" / name).exists()


def test_the_page_is_one_file_with_no_build_step():
    text = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "import " not in text.split("<script>")[-1][:400]
    assert 'id="root"' in text


def test_every_screen_and_the_drawer_are_reachable_by_url():
    """The progress document photographs them by URL, so the routes are a contract."""
    text = (STATIC / "index.html").read_text(encoding="utf-8")
    for route in ("board", "storerooms", "evidence"):
        assert f'"{route}"' in text, f"the {route} route disappeared"
    assert "hashchange" in text
    assert "parseHash" in text


def test_the_plain_pages_do_not_use_the_technical_words():
    """
    Pages 1-3 are read by somebody who has never seen inventory data. The technical
    name lives in a tooltip, which is why the words are allowed to appear in the
    file at all — but not as a heading, a column or a chip label.
    """
    text = (STATIC / "index.html").read_text(encoding="utf-8")
    evidence = text.index("function Evidence(")
    plain = text[:evidence]
    for word in ("MASE", "recall", "precision", "positions"):
        assert f'>{word}' not in plain, f"'{word}' is rendered on a plain page"
    assert "How to read this page" in text


def test_every_action_the_board_can_show_has_a_label():
    """An unlabelled action renders as an empty cell, which reads as 'nothing to do'."""
    from engine.positions import _actions  # noqa: PLC0415

    text = (STATIC / "index.html").read_text(encoding="utf-8")
    source = pathlib.Path(_actions.__code__.co_filename).read_text(encoding="utf-8")
    for name in ("order_now", "stocked_elsewhere", "below_safe_level",
                 "review_obsolete", "nothing_needed"):
        assert f'"{name}"' in source, f"{name} is no longer produced"
        assert f"{name}:" in text, f"{name} has no label on the screen"


def test_the_page_serves_and_mentions_the_board(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Stock board" in r.text


# ── recommendations ──────────────────────────────────────────────────────────


def test_recommendations_are_ranked_by_money_and_add_up(client):
    d = client.get("/api/recommendations?limit=20").json()
    assert d["today"], "the tab needs the data's own 'today' to say 'Now'"
    costs = [r["order_cost_sar"] for r in d["orders"]["rows"]]
    assert costs == sorted(costs, reverse=True)
    assert d["orders"]["total_sar"] >= sum(costs)
    assert d["writeoff"]["status"].startswith("coming"), (
        "the write-off tab must say it is not built yet, not show an empty list"
    )


def test_the_export_opens_in_excel(client):
    """A CSV with a byte-order mark; anything else and Excel guesses the encoding."""
    r = client.get("/api/recommendations/orders.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.startswith("﻿")
    header = r.text.splitlines()[0]
    for col in ("material_id", "order_now_qty", "order_by_date", "order_cost_sar"):
        assert col in header
    assert client.get("/api/recommendations/nothing.csv").status_code == 404


def test_the_board_says_now_when_the_order_is_already_late(client):
    d = client.get("/api/positions?action=order_now").json()
    assert d["today"]
    for r in d["rows"]:
        if r["on_hand"] <= 0:
            assert r["order_by_date"] <= d["today"], "an empty shelf cannot wait"


def test_an_older_position_file_degrades_to_a_blank_column_not_an_error(built, tmp_path):
    """
    The first report of a broken board came from a server whose position file
    predated the newest columns: a KeyError in the API turned the whole page into
    an error. The API now serves the columns it has.
    """
    old = pd.read_parquet(built.results_dir / POSITIONS_FILE).drop(
        columns=["usage_12m", "order_by_date", "runs_out_date", "order_cost_sar"]
    )
    data_dir = tmp_path / "older"
    (data_dir / "toy" / "results").mkdir(parents=True)
    import shutil

    for f in built.results_dir.iterdir():
        if f.name != POSITIONS_FILE:
            shutil.copy(f, data_dir / "toy" / "results" / f.name)
    old.to_parquet(data_dir / "toy" / "results" / POSITIONS_FILE, index=False)
    older = TestClient(create_app(RunConfig(preset="toy", data_dir=data_dir)))
    r = older.get("/api/positions?page=1")
    assert r.status_code == 200
    assert "usage_12m" not in r.json()["rows"][0]
    assert older.get("/api/recommendations").status_code == 409, (
        "recommendations need the new columns and should say so, not 500"
    )
