"""
Writes `results/summary.json` — the headline figures the dashboard reads.

Everything here is computed once, during `score`, and written to disk. The API
never recomputes: a screen that recalculates on every request is a screen that can
disagree with the scoreboard sitting next to it, and on a demo laptop it is also a
screen that stalls on 25,000 positions while someone is watching.

**These figures are TRUTH-derived, and the file says so.** Dead value and idle
share come from the answer key via `cfg.dead_money`, because the engine does not
compute them yet (step 6). When it does, the engine's own numbers go in alongside
under `engine`, and the screen shows claimed against actual. Until then the panel
is labelled as the size of the prize, not as something the system found — showing
answer-key figures as engine output would be the single most dishonest thing this
POC could do.
"""

from __future__ import annotations

import json

import pandas as pd

from contracts import schemas as S
from contracts.config import RunConfig
from scoring.dataset_report import dead_money, measure

SUMMARY_FILE = "summary.json"


def build(cfg: RunConfig) -> dict:
    mats = S.read(S.MATERIALS, cfg.source_dir)
    stock = S.read(S.STOCK, cfg.source_dir)
    mov = S.read(S.MOVEMENTS, cfg.source_dir)
    wos = S.read(S.WORK_ORDERS, cfg.source_dir)
    tmat = S.read(S.TRUTH_MATERIALS, cfg.answer_key_dir)
    tpos = S.read(S.TRUTH_POSITIONS, cfg.answer_key_dir)

    dead_share, dead_sar, total_sar = dead_money(cfg, stock, mats, tmat, tpos)

    issues = mov[mov.movement_type == "ISSUE"]
    last = issues.groupby("material_id")["date"].max()
    end = pd.Timestamp(cfg.history_end)
    never = int((~mats.material_id.isin(issues.material_id)).sum())
    idle_count = int(((end - last).dt.days > 730).sum()) + never

    by_store = (
        stock.assign(value=stock.on_hand.clip(lower=0) * stock.avg_unit_cost_sar)
        .groupby("storeroom_id")
        .agg(positions=("material_id", "size"), value_sar=("value", "sum"))
        .reset_index()
        .sort_values("value_sar", ascending=False)
    )

    manifest = json.loads(
        (cfg.results_dir / S.RUN_MANIFEST_FILE).read_text(encoding="utf-8")
    )

    # The progress document reads results/ and nothing else, so anything it needs to
    # show has to be written here — including the realism checks and a sample of the
    # master, which otherwise live only in the source tables.
    checks = [
        {"name": c.name, "value": c.value, "target": c.target, "ok": c.ok, "detail": c.detail}
        for c in measure(cfg)
    ]

    sample_cols = ["material_id", "material_group", "description", "manufacturer",
                   "uom", "unit_price_sar", "lead_time_days", "criticality"]
    sample = (
        mats.merge(
            S.read(S.EQUIPMENT, cfg.source_dir)[["equipment_id", "name"]],
            on="equipment_id", how="left",
        )
        .sample(n=min(8, len(mats)), random_state=cfg.seed)[sample_cols + ["name"]]
        .rename(columns={"name": "fitted_to"})
    )

    summary = {
        "run": manifest,
        "dataset_checks": checks,
        "sample_materials": sample.to_dict("records"),
        "counts": {
            "materials": int(len(mats)),
            "positions": int(len(stock)),
            "movements": int(len(mov)),
            "work_orders": int(len(wos)),
            "storerooms": int(stock.storeroom_id.nunique()),
        },
        "inventory": {
            "total_stock_value_sar": total_sar,
            "idle_24m_count": idle_count,
            "idle_24m_share": idle_count / len(mats) if len(mats) else 0.0,
            "dead_value_sar": dead_sar,
            "dead_value_share": dead_share,
            "source": "truth",
            "note": (
                "Dead value uses cfg.dead_money: obsolete stock in full, otherwise "
                f"what exceeds {cfg.dead_money.years_of_demand_justified:g} years of "
                "demand above a criticality floor. Valued at SAP moving average. "
                "Measured from the answer key — the engine does not compute this yet."
            ),
        },
        "by_storeroom": by_store.to_dict("records"),
        "targets": {
            "idle_24m_share": list(cfg.demand.target_idle_24m_share),
            "dead_value_share": list(cfg.dead_money.target_dead_value_share),
        },
    }

    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    (cfg.results_dir / SUMMARY_FILE).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
