"""
Step 2 — data quality checks (SOW capability 4).

Vertical slice: NEGATIVE_STOCK only. The remaining rule checks and the duplicate
matcher land here next, one at a time, each scored before the next is added.

This module may import `contracts` and nothing else from the project. It sees the
source tables exactly as a real ERP extract would provide them — it has no access
to how they were produced, and none to the answer key.
"""

from __future__ import annotations

import pandas as pd

from contracts import schemas as S
from contracts.config import RunConfig


def find_negative_stock(stock: pd.DataFrame) -> pd.DataFrame:
    """
    A stock balance below zero is always wrong: it means issues were posted against
    material that was never received, so both the balance and everything computed
    from it — cover, reorder point, valuation — are unreliable for that line.
    """
    bad = stock[stock["on_hand"] < 0]
    return pd.DataFrame(
        {
            "finding_id": [
                f"F-NEG-{m}-{s}" for m, s in zip(bad.material_id, bad.storeroom_id, strict=True)
            ],
            "defect_type": "NEGATIVE_STOCK",
            "table": "stock",
            "material_id": bad.material_id.to_numpy(),
            "storeroom_id": bad.storeroom_id.to_numpy(),
            "detail": [f"on_hand is {v:.0f}" for v in bad.on_hand],
            "confidence": 1.0,
        }
    )


CHECKS = (find_negative_stock,)


def run(cfg: RunConfig) -> pd.DataFrame:
    """Run every check and write findings.parquet."""
    stock = S.read(S.STOCK, cfg.source_dir)

    frames = [find_negative_stock(stock)]
    findings = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=S.FINDINGS.names
    )
    S.write(findings, S.FINDINGS, cfg.results_dir)
    return findings
