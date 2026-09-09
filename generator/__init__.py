"""
The data maker. Writes the source tables and the answer key.

`engine/` must never import this package.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from contracts import schemas as S
from contracts.config import RunConfig
from generator import build as B
from generator.defects import inject


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or "nogit"
    except Exception:
        return "nogit"


def _work_orders_and_shutdowns(
    cfg: RunConfig, equipment: pd.DataFrame, movements: pd.DataFrame, rng: np.random.Generator
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Shutdowns are the planned spikes; work orders back the issues we generated."""
    years = max(1, cfg.n_days // 365)
    n_sd = cfg.size.n_shutdowns_per_year * years
    start = pd.Timestamp(cfg.history_start)
    plants = rng.choice(np.array(S.PLANTS), size=n_sd)
    offsets = np.sort(rng.integers(60, cfg.n_days - 20, size=n_sd))
    shutdowns = pd.DataFrame(
        {
            "shutdown_id": [f"SD-{i:03d}" for i in range(1, n_sd + 1)],
            "plant": plants,
            "start_date": start + pd.to_timedelta(offsets, "D"),
            "end_date": start + pd.to_timedelta(offsets + rng.integers(5, 21, n_sd), "D"),
        }
    )

    issues = movements[
        (movements["movement_type"] == "ISSUE") & (movements["work_order_id"] != "")
    ]
    eq_pool = equipment["equipment_id"].to_numpy()
    wo = pd.DataFrame(
        {
            "work_order_id": issues["work_order_id"].to_numpy(),
            "equipment_id": rng.choice(eq_pool, size=len(issues)),
            "date": issues["date"].to_numpy(),
            "wo_type": rng.choice(
                np.array(S.WORK_ORDER_TYPES), size=len(issues), p=[0.55, 0.40, 0.05]
            ),
            "shutdown_id": "",
        }
    ).drop_duplicates(subset="work_order_id")

    return wo.reset_index(drop=True), shutdowns


def generate(cfg: RunConfig) -> B.Generated:
    rng = np.random.default_rng(cfg.seed)

    fams = B._load_families(cfg)
    equipment = B._build_equipment(cfg, rng)
    materials = B._build_materials(cfg, fams, equipment, rng)
    params = B._demand_params(cfg, materials, fams, rng)
    params["unit_price_sar"] = materials["unit_price_sar"].to_numpy()

    # demand ceases the day the owning equipment is decommissioned; whatever stock
    # is left behind becomes genuinely obsolete
    decom = equipment.set_index("equipment_id")["decommissioned_date"]
    owner_decom = pd.to_datetime(decom.reindex(materials["equipment_id"]).to_numpy())
    stop_day = np.where(
        pd.isna(owner_decom),
        cfg.n_days,
        (owner_decom - pd.Timestamp(cfg.history_start)).days,
    ).astype(np.int64)

    demand_days, demand_qty = B._sample_demand(cfg, params, rng, stop_day=stop_day)
    min_qty, max_qty = B._stale_levels(cfg, params, demand_days, demand_qty, rng)
    opening = B.commissioning_opening(cfg, params, demand_qty, max_qty, rng)
    movements, stock = B._run_history(
        cfg, materials, params, demand_days, demand_qty, min_qty, max_qty, opening=opening
    )
    work_orders, shutdowns = _work_orders_and_shutdowns(cfg, equipment, movements, rng)

    # ── truth, before any defect touches the tables ──────────────────────────
    eq_status = equipment.set_index("equipment_id")["status"]
    eq_decom = equipment.set_index("equipment_id")["decommissioned_date"]
    owner = materials["equipment_id"]
    annual = np.array([q.sum() for q in demand_qty]) / max(cfg.n_days / 365.0, 1e-9)

    truth = pd.DataFrame(
        {
            "material_id": materials["material_id"].to_numpy(),
            "true_profile": params["profile"].to_numpy(),
            "true_demand_interval_days": params["interval"].to_numpy(),
            "true_demand_size_mean": params["size_mean"].to_numpy(),
            "true_demand_size_cv": params["size_cv"].to_numpy(),
            "true_annual_demand": annual,
            "true_equipment_status": eq_status.reindex(owner).to_numpy(),
            "true_is_obsolete": eq_decom.reindex(owner).notna().to_numpy(),
            "true_lead_time_days": materials["lead_time_days"].to_numpy(),
        }
    )

    materials, stock, movements, planted = inject(materials, stock, movements, rng)

    return B.Generated(
        materials=materials,
        equipment=equipment,
        stock=stock,
        movements=movements,
        work_orders=work_orders,
        shutdowns=shutdowns,
        truth=truth,
        planted_defects=planted,
    )


def write(cfg: RunConfig, g: B.Generated) -> dict:
    src, key = cfg.source_dir, cfg.answer_key_dir
    S.write(g.materials, S.MATERIALS, src)
    S.write(g.equipment, S.EQUIPMENT, src)
    S.write(g.stock, S.STOCK, src)
    S.write(g.movements, S.MOVEMENTS, src)
    S.write(g.work_orders, S.WORK_ORDERS, src)
    S.write(g.shutdowns, S.SHUTDOWNS, src)

    key.mkdir(parents=True, exist_ok=True)
    S.write(g.truth, S.TRUTH, key)
    (key / S.PLANTED_DEFECTS_FILE).write_text(
        json.dumps(g.planted_defects, indent=2), encoding="utf-8"
    )

    manifest = {
        "seed": cfg.seed,
        "preset": cfg.preset,
        "history_start": cfg.history_start.isoformat(),
        "history_end": cfg.history_end.isoformat(),
        "cutoff_date": cfg.cutoff_date.isoformat(),
        "config_hash": cfg.config_hash(),
        "git_sha": _git_sha(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_materials": int(len(g.materials)),
        "n_movements": int(len(g.movements)),
        "n_planted_defects": len(g.planted_defects),
    }
    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    (cfg.results_dir / S.RUN_MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest
