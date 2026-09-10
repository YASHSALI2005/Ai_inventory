"""
Guards on the generated dataset.

The realism assertions matter more than they look. Every number the POC reports
downstream is measured against this data, so a generator that drifts into
producing a supermarket instead of an MRO storeroom would make the forecasts and
the backtest look excellent and mean nothing. These tests fail loudly instead.

Where a property has a target, the target lives in `RunConfig` and both this file
and the console report read it from there — so the test and the report cannot
disagree about what "in band" means.
"""

from __future__ import annotations

import ast
import pathlib
import warnings

import pandas as pd
import pytest

import generator
from contracts import schemas as S
from contracts.config import RunConfig
from scoring import dataset_report

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cfg() -> RunConfig:
    return RunConfig(preset="toy")


@pytest.fixture(scope="module")
def gen(cfg):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return generator.generate(cfg)


@pytest.fixture(scope="module")
def built(cfg, gen):
    """A written dataset, for the checks that read Parquet back."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        generator.write(cfg, gen)
    return cfg


# ── contracts ────────────────────────────────────────────────────────────────


def test_tables_match_their_contracts(gen):
    for df, schema in (
        (gen.materials, S.MATERIALS),
        (gen.equipment, S.EQUIPMENT),
        (gen.stock, S.STOCK),
        (gen.movements, S.MOVEMENTS),
        (gen.work_orders, S.WORK_ORDERS),
        (gen.shutdowns, S.SHUTDOWNS),
        (gen.truth_materials, S.TRUTH_MATERIALS),
        (gen.truth_positions, S.TRUTH_POSITIONS),
    ):
        S.coerce(df, schema)


def test_generation_is_deterministic(cfg):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        a = generator.generate(cfg)
        b = generator.generate(cfg)
    pd.testing.assert_frame_equal(a.materials, b.materials)
    pd.testing.assert_frame_equal(a.movements, b.movements)
    assert a.planted_defects == b.planted_defects


def test_toy_preset_stays_small_enough_for_tests(gen):
    assert len(gen.materials) < 400
    assert len(gen.movements) < 50_000


def test_family_id_is_not_in_the_source_tables(gen):
    """
    A real SAP/PiLog extract has no column saying "these rows are the same family",
    so leaving one in would let the duplicate matcher read the answer off the data.
    The coarse material_group (SAP MATKL analogue) stays, because a real extract
    does have one — it is a hint, not a giveaway.
    """
    assert "family_id" not in gen.materials.columns
    assert "material_group" in gen.materials.columns
    assert gen.materials.material_group.nunique() < gen.truth_materials.true_family_id.nunique()


# ── realism, read from the shared report so test and console agree ──────────


@pytest.mark.parametrize(
    "prop",
    [
        "idle >24 months",
        "dead value share",
        "shutdown issue-rate multiple",
        "issues per work order",
        "planned WOs raised in advance",
        "decommissioned assets",
        "consumables with interval >30d",
        "unexplained ledger mismatches",
        "unplanted negative balances",
        "materials in >1 storeroom",
    ],
)
def test_dataset_property(built, prop):
    checks = {c.name: c for c in dataset_report.measure(built)}
    c = checks[prop]
    assert c.ok, f"{prop}: measured {c.value:.4g}, target {c.target}. {c.detail}"


# ── behaviour the realism report cannot see ─────────────────────────────────


def test_criticality_reflects_what_the_part_is(gen):
    """A spare transformer must not come out criticality C because of a dice roll."""
    m = gen.materials.merge(
        gen.truth_materials[["material_id", "true_family_id"]], on="material_id"
    )
    heavy = m[m.true_family_id.isin(["EL-TRANSFORMER", "RL-BACKUP-ROLL", "EL-MOTOR-MV"])]
    if len(heavy):
        assert (heavy.criticality == "A").mean() >= 0.7
    trivial = m[m.true_family_id.isin(["CN-WASHER", "RT-ORING", "CN-NUT-HEX"])]
    if len(trivial):
        assert (trivial.criticality == "C").mean() >= 0.5


def test_holdings_are_physically_plausible(gen):
    """No storeroom holds 2,000 of a five-figure item."""
    j = gen.stock.merge(gen.materials[["material_id", "unit_price_sar"]], on="material_id")
    expensive = j[j.unit_price_sar > 50_000]
    if len(expensive):
        assert expensive.on_hand.max() <= 30


def test_materials_sit_on_equipment_that_could_hold_them(gen):
    """A bearing belongs on a pump or a drive, never on a potline."""
    j = gen.materials.merge(
        gen.equipment[["equipment_id", "equipment_type"]], on="equipment_id", how="left"
    )
    bearings = j[j.noun == "BEARING"]
    if len(bearings):
        assert not (bearings.equipment_type == "POT").any()
    anodes = j[j.noun.isin(["ANODE ASSEMBLY", "BLOCK"])]
    if len(anodes):
        assert anodes.equipment_type.isin(
            ["POT", "ANODE_ROD_SHOP", "CAST_HOUSE", "GENERIC"]
        ).all()


def test_manufacturers_come_from_the_family_pool(gen):
    """No hex bolts by Rio Tinto Alcan."""
    fams = pd.read_csv(ROOT / "seeds" / "part_families.csv").set_index("family_id")
    j = gen.materials.merge(
        gen.truth_materials[["material_id", "true_family_id", "true_manufacturer"]],
        on="material_id",
    )
    j = j[j.true_family_id.notna()]
    for row in j.itertuples():
        pool = set(str(fams.loc[row.true_family_id, "manufacturers"]).split("|"))
        assert row.true_manufacturer in pool, (
            f"{row.true_manufacturer} not a maker for {row.true_family_id}"
        )


def test_size_tokens_suit_the_part(gen):
    """
    An oil is graded ISO VG, a bolt is M16X60 — neither is '188MM'.

    Descriptions now carry a second characteristic after the dimension, because one
    dimension could not keep variants apart: a family of 300 valves drawn from 16 DN
    sizes repeated itself nineteen times over, and 85% of the whole master shared a
    description with some other row. So the dimension is asserted as present, not as
    the final token.
    """
    j = gen.materials.merge(
        gen.truth_materials[["material_id", "true_family_id"]], on="material_id"
    )
    oils = j[j.true_family_id.isin(["CN-GEAR-OIL", "CN-HYD-OIL"])]
    if len(oils):
        assert oils.description.str.contains("ISO VG").all()
    bolts = j[j.true_family_id == "CN-BOLT-HEX"]
    if len(bolts):
        assert bolts.description.str.contains(r"\bM\d+X\d+\b", regex=True).all()


def test_equipment_is_a_decade_old(cfg, gen):
    """The commissioning-spares story needs assets built in 2013-15, not yesterday."""
    lo, _hi = cfg.equipment_commissioning_window
    early = gen.equipment.commissioned_date < pd.Timestamp(cfg.history_start)
    assert early.all(), "an asset was commissioned after history began"
    assert (gen.equipment.commissioned_date <= pd.Timestamp("2016-01-01")).mean() >= 0.6
    assert gen.equipment.commissioned_date.min() >= pd.Timestamp(lo)


def test_obsolete_items_stop_being_issued(gen):
    """
    Demand must cease at decommissioning, or nothing is ever truly obsolete.

    Issues may still land after the cutoff, within the item's lead time: a job
    raised before the asset was scrapped is served when the part finally arrives.
    That is real, and it is itself a form of waste worth catching — but a *new*
    demand months later would mean the stop day was never applied.
    """
    obsolete = gen.truth_materials[gen.truth_materials.true_is_obsolete].material_id
    decom = gen.equipment.set_index("equipment_id")["decommissioned_date"]
    owner = gen.materials.set_index("material_id")["equipment_id"]
    lead = gen.materials.set_index("material_id")["lead_time_days"]
    issues = gen.movements[gen.movements.movement_type == "ISSUE"]
    last_issue = issues.groupby("material_id")["date"].max()

    checked = 0
    for mid in obsolete:
        if mid not in last_issue.index:
            continue
        cutoff = decom.get(owner.get(mid))
        if pd.isna(cutoff):
            continue
        grace = pd.Timedelta(days=int(lead.get(mid, 0)))
        assert last_issue[mid] <= cutoff + grace, (
            f"{mid} issued {(last_issue[mid] - cutoff).days}d after its equipment was "
            f"scrapped, beyond its {grace.days}d lead time"
        )
        checked += 1
    assert checked > 0, "no obsolete item had issues to check — fixture is not exercising this"


def test_returns_and_adjustments_exist(gen):
    kinds = set(gen.movements.movement_type)
    assert "RETURN" in kinds, "the engine's netting logic has nothing to net"
    assert "ADJUST" in kinds


def test_every_position_opens_with_a_balance(gen):
    """The opening ADJUST is what makes ledger reconciliation possible at all."""
    first_day = gen.movements.date.min()
    opens = gen.movements[
        (gen.movements.date == first_day) & (gen.movements.movement_type == "ADJUST")
    ]
    positions = set(zip(gen.stock.material_id, gen.stock.storeroom_id, strict=True))
    opened = set(zip(opens.material_id, opens.storeroom_id, strict=True))
    assert len(opened & positions) / len(positions) > 0.95


def test_time_split_partitions_history(cfg, gen):
    train = cfg.train_slice(gen.movements)
    evaluate = cfg.eval_slice(gen.movements)
    assert len(train) and len(evaluate)
    assert len(train) + len(evaluate) == len(gen.movements)
    assert train.date.max() <= pd.Timestamp(cfg.cutoff_date) < evaluate.date.min()


# ── answer-key discipline ───────────────────────────────────────────────────


def test_at_least_three_of_each_planted_type(cfg, gen):
    """A one-of-one test proves nothing: the score comes out 0% or 100% by luck."""
    counts: dict[str, int] = {}
    for d in gen.planted_defects:
        counts[d["defect_type"]] = counts.get(d["defect_type"], 0) + 1
    for t, n in counts.items():
        assert n >= cfg.size.min_defects_per_type, f"only {n} planted of {t}"


def test_planted_defects_are_recorded_with_a_findable_key(gen):
    assert gen.planted_defects
    for d in gen.planted_defects:
        assert d["defect_type"] in S.PLANTED_DEFECT_TYPES
        assert d["key"], "a planted defect with no key cannot be scored"


def test_duplicate_records_name_both_masters(gen):
    dupes = [d for d in gen.planted_defects if d["defect_type"] == "DUPLICATE_MATERIAL"]
    assert dupes
    ids = set(gen.materials.material_id)
    for d in dupes:
        assert d["key"]["material_id"] in ids
        assert d["key"]["duplicate_of"] in ids


def test_some_duplicates_split_the_consumption_history(gen):
    """
    The real Alcoa/Alba problem: consumption divided across two masters, so both
    forecasts are wrong and neither line looks anomalous on its own.
    """
    copies = [
        d["key"]["material_id"]
        for d in gen.planted_defects
        if d["defect_type"] == "DUPLICATE_MATERIAL"
    ]
    issues = gen.movements[gen.movements.movement_type == "ISSUE"]
    with_history = sum(1 for c in copies if (issues.material_id == c).any())
    assert with_history >= 1, "no duplicate carries any of the original's history"


def test_blank_mpn_on_a_duplicate_is_recorded(gen):
    """
    Otherwise every such row is a guaranteed false alarm the moment the BLANK_MPN
    check exists — the engine would be right and the scoreboard would say wrong.
    """
    blank_ids = {
        d["key"]["material_id"] for d in gen.planted_defects if d["defect_type"] == "BLANK_MPN"
    }
    actually_blank = set(gen.materials.loc[gen.materials.mpn == "", "material_id"])
    assert actually_blank <= blank_ids, actually_blank - blank_ids


def test_emergent_problems_are_not_in_the_planted_list(gen):
    """
    Overstock, obsolescence and critical-below-reorder must emerge from the
    simulation, or we grade the engine on our own injection rules rather than on
    whether it can read a plant.
    """
    planted = {d["defect_type"] for d in gen.planted_defects}
    assert not planted & {"OVERSTOCK", "OBSOLETE", "CRITICAL_BELOW_ROP"}


# ── structural isolation ────────────────────────────────────────────────────


def test_engine_cannot_reach_the_answer_key():
    """
    `engine/` must not import sim, generator or scoring, and must not name the
    answer key by path either. If it could see the answers the score would be
    meaningless, and we would not find out until a Ma'aden engineer asked how it
    was measured.
    """
    forbidden_imports = {"sim", "generator", "scoring"}
    forbidden_strings = ("answer_key", "truth_materials", "truth_positions",
                         "planted_defects")

    for path in (ROOT / "engine").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in forbidden_strings:
            assert needle not in text, f"{path.name} mentions {needle!r}"
        for node in ast.walk(ast.parse(text)):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in forbidden_imports, (
                    f"{path.name} imports {name!r} — engine must not"
                )


def test_newsvendor_service_levels_are_ordered_and_not_pinned(cfg):
    """
    A>B>C, and C well below the cap. The first cut mixed per-day shortage with
    per-day holding cost, which pinned all three to 0.995 and quietly disabled
    "service level from each item's own economics".
    """
    c = cfg.costs
    a = c.critical_fractile(1000.0, "A")
    b = c.critical_fractile(1000.0, "B")
    z = c.critical_fractile(1000.0, "C")
    assert a > b > z
    assert z < 0.9, f"C pinned high at {z}"
    assert a <= c.service_level_cap
    # scale-free: the fractile is a ratio, so price must not change it
    assert c.critical_fractile(5.0, "A") == pytest.approx(a)


def test_service_level_sweep_reaches_the_cap(cfg):
    assert max(cfg.service_level_sweep) == pytest.approx(cfg.costs.service_level_cap)


def test_descriptions_are_unique_apart_from_planted_copies(gen):
    """
    An identical description has to mean something, and what it should mean is that
    somebody entered the part twice.

    The first generator drew one dimension from a small vocabulary, so 85% of the
    master shared a description with another row and there were 82,000 accidental
    identical pairs against 140 planted ones. Duplicate detection was not merely
    hard on that data, it was meaningless.
    """
    copies = {
        d["key"]["material_id"]
        for d in gen.planted_defects
        if d["defect_type"] == "DUPLICATE_MATERIAL"
    }
    clean = gen.materials[~gen.materials.material_id.isin(copies)]
    repeated = clean.description.value_counts()
    repeated = repeated[repeated > 1]
    assert repeated.empty, (
        f"{len(repeated)} descriptions are used more than once, e.g. "
        f"{list(repeated.index[:2])}"
    )
