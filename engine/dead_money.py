"""
Step 6a — the money that will never come back, found by the engine (SOW capability 2).

Until now the dashboard's dead-money figure came from the sealed answer key: the
size of the prize, not a finding. This is the finding. It reads the same tables a
planner has — stock, equipment status, the maintenance schedule, the duplicate
matcher's output — and never the answer key; `scoring/` grades it afterwards.

One reason per position, in the order they are decided, and the order is the
priority a reviewer would use:

    obsolete — equipment gone     the machine it belongs to has been decommissioned;
                                  every unit is dead
    duplicate                     the matcher found this record is another part under
                                  a second number; what is above the justified level
                                  is dead, the rest should be consolidated
    never used                    not issued once in three years; what is above the
                                  criticality floor is dead — the floor itself is an
                                  insurance policy, not waste
    obsolete — idle, nothing due  no issue in 24 months and no planned job for its
                                  equipment ahead; what is above the justified level
    excess                        more on the shelf than three years of use and our
                                  own order-up-to justify

"Justified" is `cfg.dead_money.justified_qty` — the same rule the answer key was
built with, applied to what the engine can observe (three years of issues) rather
than to the true demand rate. Where our own order-up-to is higher, that wins: the
engine cannot call stock dead that its own level says to hold.

Valued at the SAP moving average (`avg_unit_cost_sar`), which is what the business
would actually write off.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from contracts import schemas as S
from contracts.config import RunConfig

DEAD_FILE = "dead_money.parquet"
REPORT_FILE = "dead_money_report.json"

IDLE_MONTHS = 24

CATEGORY_LABEL = {
    "obsolete_equipment": "Obsolete — equipment gone",
    "duplicate": "Duplicate",
    "never_used": "Never used",
    "obsolete_idle": "Obsolete — idle, nothing due",
    "excess": "Excess",
}


def compute(cfg: RunConfig) -> pd.DataFrame:
    pos = pd.read_parquet(cfg.results_dir / "positions.parquet")
    materials = S.read(S.MATERIALS, cfg.source_dir)
    equipment = S.read(S.EQUIPMENT, cfg.source_dir)
    work_orders = S.read(S.WORK_ORDERS, cfg.source_dir)
    findings_path = cfg.results_dir / "findings.parquet"
    findings = (S.read(S.FINDINGS, cfg.results_dir) if findings_path.exists()
                else S.empty(S.FINDINGS))

    today = pd.Timestamp(cfg.history_end)
    owner = materials.set_index("material_id")["equipment_id"]
    pos = pos.assign(equipment_id=pos["material_id"].map(owner).fillna(""))

    gone = set(equipment.loc[equipment["decommissioned_date"].notna(), "equipment_id"])
    due = set(work_orders.loc[work_orders["planned_date"] > today, "equipment_id"])
    dupes = findings.loc[findings["defect_type"] == "DUPLICATE_MATERIAL"]
    dup_of = dict(zip(dupes["material_id"], dupes["related_material_id"], strict=True))

    on_hand = pos["on_hand"].clip(lower=0.0).to_numpy()
    cost = pos["avg_unit_cost_sar"].fillna(pos["unit_price_sar"]).to_numpy(dtype=float)
    years = max(len(pos["usage_months"].iloc[0]) / 12.0, 1e-9) if len(pos) else 3.0
    annual = np.array([float(np.sum(a)) / years for a in pos["usage_months"]])
    floor = pos["criticality"].map(cfg.dead_money.criticality_floor).fillna(0.0).to_numpy()
    justified_rule = cfg.dead_money.justified_qty(annual, pos["criticality"].to_numpy())
    justified = np.maximum(justified_rule, pos["order_up_to"].to_numpy(dtype=float))
    last_issue = pd.to_datetime(pos["last_issue_date"])
    idle = ((last_issue < today - pd.DateOffset(months=IDLE_MONTHS)).to_numpy()
            | last_issue.isna().to_numpy())
    never = pos["never_moved"].fillna(False).to_numpy(dtype=bool) | last_issue.isna().to_numpy()
    eq = pos["equipment_id"].to_numpy()
    is_gone = np.array([e in gone for e in eq])
    nothing_due = np.array([e not in due for e in eq])
    is_dup = pos["material_id"].isin(dup_of.keys()).to_numpy()

    category = np.full(len(pos), "", dtype=object)
    dead_qty = np.zeros(len(pos))
    above_justified = np.maximum(on_hand - justified, 0.0)
    above_floor = np.maximum(on_hand - floor, 0.0)

    # decided in priority order; a position takes the first reason that fits
    rules = [
        ("obsolete_equipment", is_gone & (on_hand > 0), on_hand),
        ("duplicate", is_dup & (above_justified > 0), above_justified),
        ("never_used", never & (above_floor > 0), above_floor),
        ("obsolete_idle", idle & nothing_due & (above_justified > 0), above_justified),
        ("excess", above_justified > 0, above_justified),
    ]
    for name, mask, qty in rules:
        m = (category == "") & mask
        category[m] = name
        dead_qty[m] = qty[m]

    keep = category != ""
    out = pos.loc[keep, ["material_id", "storeroom_id", "description", "criticality", "uom",
                         "on_hand", "order_up_to", "last_issue_date"]].copy()
    out["category"] = category[keep]
    out["category_label"] = out["category"].map(CATEGORY_LABEL)
    out["dead_qty"] = dead_qty[keep]
    out["justified_qty"] = justified[keep]
    out["unit_cost_sar"] = cost[keep]
    out["dead_value_sar"] = out["dead_qty"] * out["unit_cost_sar"]
    out["duplicate_of"] = out["material_id"].map(dup_of).fillna("")
    out["annual_use"] = annual[keep]
    out["reason"] = [
        _reason(r, cfg) for r in out.itertuples()
    ]
    out = out.sort_values("dead_value_sar", ascending=False).reset_index(drop=True)
    return out


def _reason(r, cfg: RunConfig) -> str:
    uom = r.uom or "EA"
    held = f"{r.on_hand:,.0f} {uom} on the shelf"
    if r.category == "obsolete_equipment":
        return (f"{held}; the equipment it belongs to has been decommissioned, so nothing "
                f"will ever draw it. All of it is dead.")
    if r.category == "duplicate":
        return (f"{held}; the matcher says this is the same part as {r.duplicate_of} under a "
                f"second number. Consolidate under one record; the {r.dead_qty:,.0f} above "
                f"the justified {r.justified_qty:,.0f} is dead.")
    if r.category == "never_used":
        return (f"{held}, never issued in three years. {r.dead_qty:,.0f} above the "
                f"{r.criticality}-critical floor is dead; the floor is insurance, not waste.")
    if r.category == "obsolete_idle":
        return (f"{held}, nothing issued in two years and no planned job ahead for its "
                f"equipment. {r.dead_qty:,.0f} above the justified {r.justified_qty:,.0f} is dead.")
    return (f"{held} against about {r.annual_use:,.1f} a year; "
            f"{cfg.dead_money.years_of_demand_justified:.0f} years of use and our own "
            f"order-up-to justify {r.justified_qty:,.0f}. The {r.dead_qty:,.0f} above "
            f"that is dead.")


def run(cfg: RunConfig) -> pd.DataFrame:
    out = compute(cfg)
    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cfg.results_dir / DEAD_FILE, index=False)
    by_cat = out.groupby("category").agg(positions=("dead_value_sar", "size"),
                                         value_sar=("dead_value_sar", "sum"))
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "positions_flagged": int(len(out)),
        "dead_value_sar": float(out["dead_value_sar"].sum()),
        "by_category": [
            {"category": k, "label": CATEGORY_LABEL[k], "positions": int(v.positions),
             "value_sar": float(v.value_sar)}
            for k, v in by_cat.iterrows()
        ],
        "limits": [
            "Justified quantity is worked out from three years of observed issues, "
            "not from a true demand rate the engine cannot see; a part whose use "
            "has genuinely stopped still carries its old rate for a while.",
            "A duplicate is flagged on the matcher's word. Where the matcher is wrong "
            "the money is wrongly flagged, and that shows up in the score.",
            "The criticality floor is a business rule: two of every A-critical spare "
            "are never called dead, however long they sit.",
        ],
    }
    (cfg.results_dir / REPORT_FILE).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out
