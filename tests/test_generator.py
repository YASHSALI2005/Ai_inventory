"""
Guards on the generated dataset.

The realism assertions matter more than they look. Every number the POC reports
downstream is measured against this data, so if the generator drifts into
producing a supermarket instead of an MRO storeroom, the forecasts and the
backtest will look excellent and mean nothing. These tests fail loudly instead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import generator
from contracts import schemas as S
from contracts.config import RunConfig


@pytest.fixture(scope="module")
def cfg() -> RunConfig:
    return RunConfig(preset="toy")


@pytest.fixture(scope="module")
def gen(cfg):
    return generator.generate(cfg)


def test_tables_match_their_contracts(gen):
    for df, schema in (
        (gen.materials, S.MATERIALS),
        (gen.equipment, S.EQUIPMENT),
        (gen.stock, S.STOCK),
        (gen.movements, S.MOVEMENTS),
        (gen.work_orders, S.WORK_ORDERS),
        (gen.shutdowns, S.SHUTDOWNS),
        (gen.truth, S.TRUTH),
    ):
        S.coerce(df, schema)


def test_generation_is_deterministic(cfg):
    a = generator.generate(cfg)
    b = generator.generate(cfg)
    pd.testing.assert_frame_equal(a.materials, b.materials)
    pd.testing.assert_frame_equal(a.movements, b.movements)
    assert a.planted_defects == b.planted_defects


def test_toy_preset_is_fast_enough_for_tests(cfg, gen):
    # the toy set exists so the whole pipeline can run in a test; keep it small
    assert len(gen.materials) < 400
    assert len(gen.movements) < 50_000


def test_idle_share_matches_industry_band(cfg, gen):
    """30-50% of MRO lines should not have moved in 24 months."""
    issues = gen.movements[gen.movements.movement_type == "ISSUE"]
    last = issues.groupby("material_id")["date"].max()
    end = pd.Timestamp(cfg.history_end)

    never = (~gen.materials.material_id.isin(issues.material_id)).sum()
    idle = int(((end - last).dt.days > 730).sum()) + int(never)
    share = idle / len(gen.materials)

    lo, hi = cfg.demand.target_idle_24m_share
    assert lo <= share <= hi, f"idle-24m share {share:.0%} outside {lo:.0%}-{hi:.0%}"


def test_dead_money_share_matches_industry_band(gen):
    """
    20-40% of MRO *value* should be excess or obsolete.

    Dead is defined here the way step 6 will have to define it: obsolete stock is
    dead in full, and otherwise only what exceeds three years of real demand above
    a criticality floor. An insurance spare holding one unit against zero demand is
    correct stocking, not waste — counting it would inflate the prize dishonestly.
    """
    j = gen.stock.merge(gen.truth, on="material_id").merge(
        gen.materials[["material_id", "unit_price_sar", "criticality"]], on="material_id"
    )
    on_hand = j.on_hand.clip(lower=0)
    floor = np.select([j.criticality == "A", j.criticality == "B"], [2.0, 1.0], default=0.0)
    justified = np.maximum(j.true_annual_demand * 3.0, floor)
    dead_units = np.where(j.true_is_obsolete, on_hand, np.maximum(on_hand - justified, 0.0))

    dead = float((dead_units * j.unit_price_sar).sum())
    total = float((on_hand * j.unit_price_sar).sum())
    share = dead / total
    assert 0.20 <= share <= 0.40, f"dead-money share {share:.0%} outside 20%-40%"


def test_criticality_reflects_what_the_part_is(gen):
    """A spare transformer must not come out criticality C because of a dice roll."""
    m = gen.materials
    heavy = m[m.family_id.isin(["EL-TRANSFORMER", "RL-BACKUP-ROLL", "EL-MOTOR-MV"])]
    if len(heavy):
        assert (heavy.criticality == "A").mean() >= 0.7

    trivial = m[m.family_id.isin(["CN-WASHER", "RT-ORING", "CN-NUT-HEX"])]
    if len(trivial):
        assert (trivial.criticality == "C").mean() >= 0.5


def test_holdings_are_physically_plausible(gen):
    """No storeroom holds 2,000 of a five-figure item."""
    j = gen.stock.merge(gen.materials[["material_id", "unit_price_sar"]], on="material_id")
    expensive = j[j.unit_price_sar > 50_000]
    if len(expensive):
        assert expensive.on_hand.max() <= 30


def test_obsolete_items_stop_being_issued(cfg, gen):
    """Demand must cease at decommissioning, or nothing is ever truly obsolete."""
    obsolete = gen.truth[gen.truth.true_is_obsolete].material_id
    decom = gen.equipment.set_index("equipment_id")["decommissioned_date"]
    owner = gen.materials.set_index("material_id")["equipment_id"]

    issues = gen.movements[gen.movements.movement_type == "ISSUE"]
    last_issue = issues.groupby("material_id")["date"].max()

    checked = 0
    for mid in obsolete:
        if mid not in last_issue.index:
            continue
        cutoff = decom.get(owner.get(mid))
        if pd.isna(cutoff):
            continue
        assert last_issue[mid] <= cutoff, f"{mid} issued after its equipment was scrapped"
        checked += 1
    assert checked > 0, "no obsolete item had issues to check — fixture is not exercising this"


def test_time_split_partitions_history(cfg, gen):
    train = cfg.train_slice(gen.movements)
    evaluate = cfg.eval_slice(gen.movements)
    assert len(train) and len(evaluate)
    assert len(train) + len(evaluate) == len(gen.movements)
    assert train.date.max() <= pd.Timestamp(cfg.cutoff_date) < evaluate.date.min()


def test_planted_defects_are_recorded_with_a_findable_key(gen):
    assert gen.planted_defects
    for d in gen.planted_defects:
        assert d["defect_type"] in S.PLANTED_DEFECT_TYPES
        assert d["key"], "a planted defect with no key cannot be scored"


def test_emergent_problems_are_not_in_the_planted_list(gen):
    """
    Overstock, obsolescence and critical-below-reorder must NOT be planted — they
    have to emerge from the simulation, or we are grading the engine on our own
    injection rules rather than on whether it can read a plant.
    """
    planted = {d["defect_type"] for d in gen.planted_defects}
    assert not planted & {"OVERSTOCK", "OBSOLETE", "CRITICAL_BELOW_ROP"}


def test_engine_cannot_reach_the_answer_key():
    """
    Structural guard: engine/ must not import sim/, generator/ or scoring/.

    If it could, the score would be meaningless and we would not find out until a
    Ma'aden engineer asked how it was measured.
    """
    import ast
    import pathlib

    forbidden = {"sim", "generator", "scoring"}
    root = pathlib.Path(__file__).resolve().parent.parent / "engine"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                assert top not in forbidden, f"{path.name} imports {name!r} — engine must not"
