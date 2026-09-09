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


CHECKS: dict[str, Callable[[dict[str, pd.DataFrame]], pd.DataFrame]] = {
    "NEGATIVE_STOCK": check_negative_stock,
    "LEDGER_MISMATCH": check_ledger_mismatch,
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
