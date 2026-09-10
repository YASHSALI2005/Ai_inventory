"""
Step 2 — data quality checks (SOW capability 4).

This module may import `contracts` and nothing else from the project. It sees the
source tables exactly as a real ERP extract would provide them: no access to how
they were produced, and none to the answer key.

Checks are registered in `CHECKS` and run by iteration, and the engine writes the
list of what ran to `implemented_checks.json`. Scoring reads that file rather than
inferring coverage from the findings present — otherwise a check that ran and
found nothing is indistinguishable from one nobody has written, and a 100% miss is
reported as work not started.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import numpy as np
import pandas as pd

from contracts import schemas as S
from contracts.config import RunConfig
from engine import duplicates

# Chosen from the score distribution on the full preset and checked unchanged on
# toy, which is an independent draw: 94% recall at 88% precision on full, 100/100
# on toy. Selected on our own data, so a real deployment would re-tune it on a
# labelled sample of the client's master — the number is a starting point, not a
# constant of nature.
DUPLICATE_THRESHOLD = 0.77


def _findings(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return S.empty(S.FINDINGS)
    df = pd.DataFrame(rows)
    for col, default in (
        ("material_id", ""),
        ("storeroom_id", ""),
        ("movement_id", S.NO_MOVEMENT),
        ("related_material_id", ""),
        ("confidence", 1.0),
    ):
        if col not in df.columns:
            df[col] = default
    return df[S.FINDINGS.names]


# ── checks ───────────────────────────────────────────────────────────────────


def check_negative_stock(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    A stock balance below zero is always wrong: issues were posted against material
    that was never received, so the balance and everything computed from it — cover,
    reorder point, valuation — are unreliable for that line.
    """
    stock = tables["stock"]
    bad = stock[stock["on_hand"] < 0]
    return _findings(
        [
            {
                "finding_id": f"F-NEG-{r.material_id}-{r.storeroom_id}",
                "defect_type": "NEGATIVE_STOCK",
                "table": "stock",
                "material_id": r.material_id,
                "storeroom_id": r.storeroom_id,
                "detail": f"on_hand is {r.on_hand:.0f}",
            }
            for r in bad.itertuples()
        ]
    )


def check_ledger_mismatch(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    The movement ledger must sum to the stock balance.

    This is the strongest data-quality check there is, and the one Ma'aden's own
    auditors will recognise on sight: it needs no thresholds, no tuning and no
    judgement — either the arithmetic reconciles or the balance cannot be trusted.

    It has no planted counterpart, so it is scored as informational. It will catch
    every planted negative as well, which is correct: a negative balance IS a
    reconciliation failure, and a real system would surface it twice.
    """
    stock, movements = tables["stock"], tables["movements"]
    ledger = movements.groupby(["material_id", "storeroom_id"])["qty"].sum().rename("ledger")
    j = stock.merge(ledger, on=["material_id", "storeroom_id"], how="left")
    j["ledger"] = j["ledger"].fillna(0.0)
    gap = (j["on_hand"] - j["ledger"]).abs()
    bad = j[gap > 0.01]
    return _findings(
        [
            {
                "finding_id": f"F-LED-{r.material_id}-{r.storeroom_id}",
                "defect_type": "LEDGER_MISMATCH",
                "table": "stock",
                "material_id": r.material_id,
                "storeroom_id": r.storeroom_id,
                "detail": f"balance {r.on_hand:.2f} but movements sum to {r.ledger:.2f}",
            }
            for r in bad.itertuples()
        ]
    )


def check_blank_mpn(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    A part with no manufacturer part number cannot be matched to a catalogue, to a
    quotation, or to the same part sitting in another storeroom. It is the field
    that most often goes missing when a record is re-keyed by hand.
    """
    mats = tables["materials"]
    bad = mats[mats["mpn"].fillna("").str.strip() == ""]
    return _findings(
        [
            {
                "finding_id": f"F-MPN-{r.material_id}",
                "defect_type": "BLANK_MPN",
                "table": "materials",
                "material_id": r.material_id,
                "detail": f"no manufacturer part number ({r.manufacturer})",
            }
            for r in bad.itertuples()
        ]
    )


def check_blank_uom(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Without a unit of measure, a quantity means nothing: 10 of something is not a
    number until you know whether it is ten pieces or ten boxes. Every downstream
    figure for that line — cover, reorder point, valuation — is unusable.
    """
    mats = tables["materials"]
    bad = mats[mats["uom"].fillna("").str.strip() == ""]
    return _findings(
        [
            {
                "finding_id": f"F-UOM0-{r.material_id}",
                "defect_type": "BLANK_UOM",
                "table": "materials",
                "material_id": r.material_id,
                "detail": "unit of measure is empty",
            }
            for r in bad.itertuples()
        ]
    )


def check_impossible_lead_time(
    tables: dict[str, pd.DataFrame], *, floor_days: int = 2, ceiling_days: int = 720
) -> pd.DataFrame:
    """
    A lead time of zero or one day is not a lead time — it means the field was
    never filled in, and every reorder point computed from it will be far too low.
    At the other end, nothing in an MRO catalogue takes three years: the longest
    real item here is a power transformer at around eighteen months.

    Both bounds matter to step 5, because lead time sets the protection window. A
    zero silently produces a reorder point of nearly nothing on a critical spare.
    """
    mats = tables["materials"]
    lead = mats["lead_time_days"]
    bad = mats[(lead < floor_days) | (lead > ceiling_days)]
    return _findings(
        [
            {
                "finding_id": f"F-LT-{r.material_id}",
                "defect_type": "IMPOSSIBLE_LEAD_TIME",
                "table": "materials",
                "material_id": r.material_id,
                "detail": (
                    f"lead time {r.lead_time_days} days — "
                    + ("below the plausible minimum" if r.lead_time_days < floor_days
                       else "beyond any real procurement window")
                ),
            }
            for r in bad.itertuples()
        ]
    )


def check_issue_without_work_order(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Stock left the store and no maintenance job accounts for it.

    This is the check a storeroom supervisor cares about most, because it is the
    one that means the consumption history is wrong: an issue with no job behind it
    is either a booking error or material that walked, and either way the demand
    signal for that part now contains something that was never really used.
    """
    mov = tables["movements"]
    issues = mov[mov["movement_type"] == "ISSUE"]
    orphans = issues[issues["work_order_id"].fillna("").str.strip() == ""]
    return _findings(
        [
            {
                "finding_id": f"F-WO-{r.movement_id}",
                "defect_type": "ISSUE_WITHOUT_WORK_ORDER",
                "table": "movements",
                "material_id": r.material_id,
                "storeroom_id": r.storeroom_id,
                "movement_id": int(r.movement_id),
                "detail": (
                    f"{abs(r.qty):g} issued on {r.date:%Y-%m-%d} with no work order"
                ),
            }
            for r in orphans.itertuples()
        ]
    )


def check_uom_mismatch(
    tables: dict[str, pd.DataFrame],
    *,
    rare_below: float = 0.02,
    dominant_above: float = 0.70,
    min_group: int = 30,
) -> pd.DataFrame:
    """
    A unit of measure that disagrees with everything else of its kind.

    The signal is rarity within a material group that otherwise speaks one unit:
    if 594 of 596 fasteners are priced EA and two are BOX, those two are almost
    certainly EA parts whose unit was changed without the price being changed with
    it — so every quantity on them now means something different from what the
    price implies.

    Blank units are excluded on purpose. A blank is rarer than anything, so it
    would dominate this check's output, and it is already reported as BLANK_UOM.

    **Known limit, measured rather than assumed.** This catches an item swapped
    into a *rare* unit. It cannot catch one swapped into the group's dominant unit
    — an item labelled EA in a group that is mostly EA looks exactly like its
    peers. On the full preset that is 82% recall at 100% precision, and the misses
    are all of that shape. Price was tested as a second signal and abandoned: too
    few items share both a group and a unit for the comparison to have any power.
    """
    mats = tables["materials"]
    m = mats[mats["uom"].fillna("").str.strip() != ""]
    if m.empty:
        return _findings([])

    counts = m.groupby(["material_group", "uom"]).size().rename("n").reset_index()
    totals = m.groupby("material_group").size().rename("total")
    counts = counts.merge(totals, on="material_group")
    counts["share"] = counts["n"] / counts["total"]

    dominant = (
        counts.sort_values("n").groupby("material_group").tail(1)
        [["material_group", "uom", "share"]]
        .rename(columns={"uom": "dominant_uom", "share": "dominant_share"})
    )

    j = m.merge(counts[["material_group", "uom", "share", "total"]],
                on=["material_group", "uom"], how="left")
    j = j.merge(dominant, on="material_group", how="left")

    suspect = j[
        (j["share"] < rare_below)
        & (j["dominant_share"] >= dominant_above)
        & (j["total"] >= min_group)
    ]

    rows = []
    for r in suspect.itertuples():
        # more confident the more one-sided the group is
        conf = min(0.99, 0.5 + (r.dominant_share - dominant_above) * 1.5)
        rows.append(
            {
                "finding_id": f"F-UOMX-{r.material_id}",
                "defect_type": "UOM_MISMATCH",
                "table": "materials",
                "material_id": r.material_id,
                "detail": (
                    f"unit {r.uom!r} but {r.dominant_share:.0%} of {r.material_group} "
                    f"is {r.dominant_uom!r} — price likely still on the old unit"
                ),
                "confidence": round(conf, 2),
            }
        )
    return _findings(rows)


def check_duplicate_material(
    tables: dict[str, pd.DataFrame], *, threshold: float = DUPLICATE_THRESHOLD
) -> pd.DataFrame:
    """
    Two masters describing the same physical part. See `engine/duplicates.py` for
    the method; this wraps it into a finding per pair.

    Reported as an unordered pair, because the engine sees two records and has no
    way to know which one was the copy — and no reason to care. Both are named, so
    a planner can decide which survives.
    """
    pairs, _all_scored = duplicates.find(tables["materials"], threshold=threshold)
    desc = tables["materials"].set_index("material_id")["description"]
    rows = []
    for r in pairs.itertuples():
        rows.append(
            {
                "finding_id": f"F-DUP-{r.left_id}-{r.right_id}",
                "defect_type": "DUPLICATE_MATERIAL",
                "table": "materials",
                "material_id": r.left_id,
                "related_material_id": r.right_id,
                "detail": (
                    f"{desc.get(r.left_id, '')!r} and {desc.get(r.right_id, '')!r} "
                    f"look like the same part"
                ),
                "confidence": round(float(r.score), 3),
            }
        )
    return _findings(rows)


CHECKS: dict[str, Callable[[dict[str, pd.DataFrame]], pd.DataFrame]] = {
    "NEGATIVE_STOCK": check_negative_stock,
    "LEDGER_MISMATCH": check_ledger_mismatch,
    "BLANK_MPN": check_blank_mpn,
    "BLANK_UOM": check_blank_uom,
    "IMPOSSIBLE_LEAD_TIME": check_impossible_lead_time,
    "ISSUE_WITHOUT_WORK_ORDER": check_issue_without_work_order,
    "UOM_MISMATCH": check_uom_mismatch,
    "DUPLICATE_MATERIAL": check_duplicate_material,
}


def run(cfg: RunConfig) -> pd.DataFrame:
    """Run every registered check, write findings and declare what ran."""
    tables = {
        "materials": S.read(S.MATERIALS, cfg.source_dir),
        "stock": S.read(S.STOCK, cfg.source_dir),
        "movements": S.read(S.MOVEMENTS, cfg.source_dir),
        "work_orders": S.read(S.WORK_ORDERS, cfg.source_dir),
        "equipment": S.read(S.EQUIPMENT, cfg.source_dir),
    }

    frames = [fn(tables) for fn in CHECKS.values()]
    findings = (
        pd.concat(frames, ignore_index=True) if frames else S.empty(S.FINDINGS)
    )
    findings["movement_id"] = findings["movement_id"].fillna(S.NO_MOVEMENT).astype("int64")
    S.write(findings, S.FINDINGS, cfg.results_dir)

    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    (cfg.results_dir / S.IMPLEMENTED_CHECKS_FILE).write_text(
        json.dumps(
            {
                "defect_types": sorted(CHECKS),
                "scored": sorted(set(CHECKS) & set(S.PLANTED_DEFECT_TYPES)),
                "informational": sorted(set(CHECKS) - set(S.PLANTED_DEFECT_TYPES)),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return findings


__all__ = ["CHECKS", "run", "check_negative_stock", "check_ledger_mismatch", "np"]
