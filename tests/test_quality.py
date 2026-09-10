"""
Guards on the data-quality checks and the duplicate matcher.

These use hand-built frames rather than the generator, so a failure points at the
check rather than at the dataset. The generator is exercised end to end by the
scoreboard in `test_cli.py`.
"""

from __future__ import annotations

import pandas as pd
import pytest

from contracts import schemas as S
from engine import duplicates as D
from engine import quality as Q


def _materials(**overrides) -> pd.DataFrame:
    base = {
        "material_id": ["M-1", "M-2", "M-3"],
        "material_group": ["MECH-BEARING"] * 3,
        "noun": ["BEARING"] * 3,
        "modifier": ["BALL"] * 3,
        "description": ["BEARING, BALL, 6205, SS316"] * 3,
        "manufacturer": ["SKF"] * 3,
        "mpn": ["SKF-1001", "SKF-1002", "SKF-1003"],
        "uom": ["EA"] * 3,
        "unit_price_sar": [100.0, 100.0, 100.0],
        "lead_time_days": [30, 30, 30],
        "area": ["SITEWIDE"] * 3,
        "equipment_id": ["EQ-1"] * 3,
        "criticality": ["C"] * 3,
        "is_mro": [True] * 3,
        "expected_life_years": [float("nan")] * 3,
    }
    base.update(overrides)
    return pd.DataFrame(base)


# ── individual checks ────────────────────────────────────────────────────────


def test_negative_stock_is_flagged():
    stock = pd.DataFrame(
        {"material_id": ["M-1", "M-2"], "storeroom_id": ["SMELTER", "SMELTER"],
         "on_hand": [-5.0, 12.0]}
    )
    out = Q.check_negative_stock({"stock": stock})
    assert list(out.material_id) == ["M-1"]
    assert out.defect_type.iloc[0] == "NEGATIVE_STOCK"


def test_blank_mpn_and_uom_are_separate_findings():
    mats = _materials(mpn=["", "SKF-2", "SKF-3"], uom=["EA", "", "EA"])
    assert list(Q.check_blank_mpn({"materials": mats}).material_id) == ["M-1"]
    assert list(Q.check_blank_uom({"materials": mats}).material_id) == ["M-2"]


def test_impossible_lead_time_catches_both_ends():
    mats = _materials(lead_time_days=[0, 30, 3650])
    out = Q.check_impossible_lead_time({"materials": mats})
    assert set(out.material_id) == {"M-1", "M-3"}
    assert "below" in out[out.material_id == "M-1"].detail.iloc[0]
    assert "beyond" in out[out.material_id == "M-3"].detail.iloc[0]


def test_orphan_issue_carries_its_movement_id():
    """
    Without movement_id on the finding, this defect can never be scored: the answer
    key identifies it by movement and a material-keyed finding will never match.
    """
    mov = pd.DataFrame(
        {
            "movement_id": [1, 2, 3],
            "date": pd.to_datetime(["2025-01-01"] * 3),
            "material_id": ["M-1", "M-1", "M-2"],
            "storeroom_id": ["SMELTER"] * 3,
            "movement_type": ["ISSUE", "ISSUE", "RECEIPT"],
            "qty": [-4.0, -2.0, 10.0],
            "work_order_id": ["WO-1", "", ""],
            "unit_cost_sar": [1.0] * 3,
        }
    )
    out = Q.check_issue_without_work_order({"movements": mov})
    assert len(out) == 1
    assert int(out.movement_id.iloc[0]) == 2, "a receipt with no WO is normal, not a defect"


def test_uom_mismatch_needs_a_dominated_group():
    """
    Rare unit in a one-sided group is suspicious; a genuinely mixed group is not.

    The group has to be big enough for one odd row to count as rare — at forty rows
    a single outlier is 2.5%, which is above the threshold on purpose. Real material
    groups run to hundreds.
    """
    n = 200
    dominated = pd.DataFrame(
        {
            "material_id": [f"D-{i}" for i in range(n)],
            "material_group": ["CONS-FASTENER"] * n,
            "uom": ["EA"] * (n - 1) + ["BOX"],
            "unit_price_sar": [10.0] * n,
        }
    )
    mixed = pd.DataFrame(
        {
            "material_id": [f"X-{i}" for i in range(n)],
            "material_group": ["CONS-LUBRICANT"] * n,
            "uom": ["L"] * (n // 2) + ["KG"] * (n // 2),
            "unit_price_sar": [10.0] * n,
        }
    )
    mats = pd.concat([dominated, mixed], ignore_index=True)
    out = Q.check_uom_mismatch({"materials": mats})
    assert list(out.material_id) == [f"D-{n - 1}"]


def test_uom_mismatch_ignores_blanks():
    """A blank is rarer than anything and would swamp this check. It is BLANK_UOM."""
    n = 40
    mats = pd.DataFrame(
        {
            "material_id": [f"D-{i}" for i in range(n)],
            "material_group": ["CONS-FASTENER"] * n,
            "uom": ["EA"] * (n - 1) + [""],
            "unit_price_sar": [10.0] * n,
        }
    )
    assert Q.check_uom_mismatch({"materials": mats}).empty


def test_ledger_mismatch_reconciles_movements_against_the_balance():
    stock = pd.DataFrame(
        {"material_id": ["M-1", "M-2"], "storeroom_id": ["S", "S"], "on_hand": [10.0, 5.0]}
    )
    mov = pd.DataFrame(
        {
            "material_id": ["M-1", "M-1", "M-2"],
            "storeroom_id": ["S", "S", "S"],
            "qty": [20.0, -10.0, 99.0],
        }
    )
    out = Q.check_ledger_mismatch({"stock": stock, "movements": mov})
    assert list(out.material_id) == ["M-2"]


# ── the matcher ──────────────────────────────────────────────────────────────


def test_abbreviations_and_noise_are_normalised_away():
    assert D.normalise("BRG, BALL, 6205") == D.normalise("BEARING BALL 6205")
    assert D.normalise("VALVE, GATE, DN65 -OLD") == D.normalise("VALVE GATE DN65")
    assert D.normalise_maker("S.K.F.") == D.normalise_maker("SKF AB")


def test_characteristics_drop_the_noun_and_modifier():
    got = D.characteristics(D.normalise("BEARING, BALL, 6205, SS316"), "BEARING", "BALL")
    assert got == frozenset({"6205", "SS316"})


def test_different_part_numbers_are_evidence_against_not_a_gradient():
    """
    Two numbers from one maker share a prefix, so a plain character ratio scored
    unrelated parts at 0.67 and propped up every sibling pair in the catalogue.
    """
    left = pd.DataFrame(
        {"norm_mpn": ["SKF1001", "SKF1001", "62052RS1SKFEXPLORER", ""]}
    )
    right = pd.DataFrame(
        {"norm_mpn": ["SKF1001", "SKF1002", "62052RSISKFEXPLORER", "SKF1001"]}
    )
    got = D._score_mpn(left, right)
    assert got[0] == 1.0, "identical"
    assert got[1] == 0.0, (
        "SKF1001 and SKF1002 are sequential catalogue numbers, i.e. two different "
        "parts — not a mis-key"
    )
    assert got[2] == pytest.approx(0.75), (
        "one character in nineteen, an I read as a 1, is a plausible mis-key"
    )
    assert pd.isna(got[3]), "a blank part number is no evidence, not disagreement"


def test_a_rare_lookalike_token_is_forgiven_but_a_common_one_is_not():
    """
    "DN65" vs "KN65" and "GRADE A" vs "GRADE B" are both one character apart. The
    first is a typo, the second is a different product, and only catalogue frequency
    tells them apart.
    """
    left = pd.DataFrame({"characteristics": [frozenset({"DN65"}), frozenset({"GRADE", "A"})]})
    right = pd.DataFrame({"characteristics": [frozenset({"KN65"}), frozenset({"GRADE", "B"})]})
    left.attrs["vocab"] = {"DN65": 900, "KN65": 1, "GRADE": 5000, "A": 4000, "B": 4000}
    left.attrs["rare_at"] = 3
    got = D._score_characteristics(left, right)
    assert got[0] == pytest.approx(1.0), "a one-off lookalike token is a mis-key"
    assert got[1] < 0.7, "GRADE A and GRADE B are different products"


def test_matcher_finds_a_mangled_copy_and_leaves_siblings_alone():
    mats = pd.DataFrame(
        {
            "material_id": ["M-1", "M-2", "M-DUP"],
            "material_group": ["MECH-BEARING"] * 3,
            "noun": ["BEARING"] * 3,
            "modifier": ["BALL"] * 3,
            "description": [
                "BEARING, BALL, 6205, SS316",
                "BEARING, BALL, 6310, SS316",     # a different bearing
                "BRG,BALL,6205,SS316",            # the same part, re-keyed
            ],
            "manufacturer": ["SKF", "SKF", "S.K.F."],
            "mpn": ["SKF-1001", "SKF-2002", ""],  # the copy lost its part number
            "uom": ["EA"] * 3,
            "unit_price_sar": [100.0, 250.0, 100.0],
        }
    )
    hits, _ = D.find(mats, threshold=Q.DUPLICATE_THRESHOLD, neighbours=2)
    pairs = {frozenset({a, b}) for a, b in zip(hits.left_id, hits.right_id, strict=True)}
    assert frozenset({"M-1", "M-DUP"}) in pairs
    assert frozenset({"M-1", "M-2"}) not in pairs, "6205 and 6310 are different bearings"


def test_duplicate_finding_names_both_masters():
    """Scoring matches duplicates as an unordered pair, so both ids must be present."""
    mats = pd.DataFrame(
        {
            "material_id": ["M-1", "M-DUP"],
            "material_group": ["MECH-BEARING"] * 2,
            "noun": ["BEARING"] * 2,
            "modifier": ["BALL"] * 2,
            "description": ["BEARING, BALL, 6205, SS316", "BEARING BALL 6205 SS316"],
            "manufacturer": ["SKF"] * 2,
            "mpn": ["SKF-1001", "SKF-1001"],
            "uom": ["EA"] * 2,
            "unit_price_sar": [100.0, 100.0],
        }
    )
    out = Q.check_duplicate_material({"materials": mats})
    assert len(out) == 1
    assert out.material_id.iloc[0] and out.related_material_id.iloc[0]
    assert out.confidence.iloc[0] >= Q.DUPLICATE_THRESHOLD


# ── registry ─────────────────────────────────────────────────────────────────


def test_every_planted_defect_type_now_has_a_check():
    missing = set(S.PLANTED_DEFECT_TYPES) - set(Q.CHECKS)
    assert not missing, f"no check written for {sorted(missing)}"
