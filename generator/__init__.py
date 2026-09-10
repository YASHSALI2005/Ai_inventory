"""
The data maker. Writes the source tables and the answer key.

`engine/` must never import this package.
"""

from __future__ import annotations

import json
import subprocess
import warnings
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from contracts import schemas as S
from contracts.config import RunConfig
from generator import build as B
from generator import demand as D
from generator.defects import inject, plant_negative_stock


def git_sha() -> str:
    """
    Short SHA of the working tree, or "nogit".

    Every reported number needs a SHA to be traceable. We warn rather than fail:
    the pipeline has to run from a temp directory and from a CI checkout without
    history, and refusing to build there costs more than the missing SHA does.
    `config_hash` plus `seed` still pin the dataset exactly.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5
        )
        sha = out.stdout.strip()
    except Exception:
        sha = ""
    if not sha:
        warnings.warn(
            "not a git repository — run_manifest.git_sha will be 'nogit' and this run "
            "cannot be traced back to code",
            RuntimeWarning,
            stacklevel=2,
        )
        return "nogit"
    return sha


def generate(cfg: RunConfig) -> B.Generated:
    rng = np.random.default_rng(cfg.seed)

    fams = B.load_families(cfg)
    eq_types = B.load_equipment_types(cfg)

    equipment = B.build_equipment(cfg, eq_types, rng)
    materials, hidden = B.build_materials(cfg, fams, equipment, rng)
    positions = B.build_positions(cfg, materials, hidden, rng)
    shutdowns = D.build_shutdowns(cfg, rng)

    params = D.demand_params(cfg, positions, hidden, rng)

    # demand ceases the day the owning equipment is decommissioned; whatever stock
    # is left behind becomes genuinely obsolete
    decom = equipment.set_index("equipment_id")["decommissioned_date"]
    owner = materials.set_index("material_id")["equipment_id"]
    pos_decom = pd.to_datetime(decom.reindex(owner.reindex(positions["material_id"])).to_numpy())
    stop_day = np.where(
        pd.isna(pos_decom), cfg.n_days, (pos_decom - pd.Timestamp(cfg.history_start)).days
    ).astype(np.int64)

    demand_days, demand_qty = D.sample_demand(cfg, params, shutdowns, rng, stop_day=stop_day)

    def by_position(col: str, dtype=None):
        s = materials.set_index("material_id")[col].reindex(positions["material_id"])
        return s.to_numpy(dtype=dtype) if dtype else s.to_numpy()

    price = by_position("unit_price_sar", float)
    lead = by_position("lead_time_days", float)
    crit = by_position("criticality")

    min_qty, max_qty = D.stale_levels(cfg, params, demand_days, demand_qty, price, rng)
    opening, had_commissioning = D.commissioning_opening(cfg, params, max_qty, price, rng)

    # You cannot stock 2.5 bearings, and "on hand 2.5 EA" on a screen reads as a
    # bug in the system rather than as a quirk of invented data. Demand sizes were
    # already whole numbers; the fractions came from the fat-fingered min/max and
    # from partial returns. Both are rounded HERE, before the simulation runs, so
    # every receipt and issue that follows is whole too and `sum(qty) == on_hand`
    # still holds exactly. Rounding the finished ledger instead breaks that
    # identity — tried it, and it pushed 95 positions negative.
    whole = by_position("uom") == "EA"
    min_qty = np.where(whole, np.round(min_qty), min_qty)
    max_qty = np.where(whole, np.maximum(np.round(max_qty), min_qty + 1.0), max_qty)
    opening = np.where(whole, np.round(opening), opening)

    movements, _on_hand, _last_receipt = D.run_history(
        cfg, positions, price, lead, min_qty, max_qty, opening, demand_days, demand_qty, rng
    )
    movements = D.add_returns_and_adjustments(
        cfg, movements, rng, materials.set_index("material_id")["uom"]
    )
    work_orders, movements = D.build_work_orders(
        cfg, movements, materials, equipment, shutdowns, rng
    )
    movements.insert(0, "movement_id", np.arange(1, len(movements) + 1, dtype=np.int64))

    # ── stock, summed FROM the ledger so the two agree by construction ───────
    idx = pd.MultiIndex.from_arrays([positions["material_id"], positions["storeroom_id"]])
    ledger = movements.groupby(["material_id", "storeroom_id"])["qty"].sum()
    on_hand_final = ledger.reindex(idx).fillna(0.0).to_numpy()

    issues = movements[movements["movement_type"] == "ISSUE"]
    receipts = movements[movements["movement_type"] == "RECEIPT"]
    last_issue = issues.groupby(["material_id", "storeroom_id"])["date"].max().reindex(idx)
    last_recv = receipts.groupby(["material_id", "storeroom_id"])["date"].max().reindex(idx)

    stock = pd.DataFrame(
        {
            "material_id": positions["material_id"].to_numpy(),
            "storeroom_id": positions["storeroom_id"].to_numpy(),
            "on_hand": np.round(on_hand_final, 2),
            "min_qty": min_qty,
            "max_qty": max_qty,
            "last_issue_date": last_issue.to_numpy(),
            "last_receipt_date": last_recv.to_numpy(),
            # SAP moving average sits a little away from purchasing list price
            "avg_unit_cost_sar": np.round(price * rng.uniform(0.92, 1.06, len(positions)), 2),
        }
    )

    # ── truth, captured before any defect touches the tables ─────────────────
    years = max(cfg.n_days / 365.0, 1e-9)
    annual = np.array([q.sum() for q in demand_qty]) / years
    realised_interval = np.array(
        [cfg.n_days / len(d) if len(d) else float(cfg.n_days) for d in demand_days]
    )

    truth_positions = pd.DataFrame(
        {
            "material_id": positions["material_id"].to_numpy(),
            "storeroom_id": positions["storeroom_id"].to_numpy(),
            "true_annual_demand": annual,
            "true_justified_qty": cfg.dead_money.justified_qty(annual, crit),
            "true_opening_qty": opening,
            "true_had_commissioning": had_commissioning,
            "true_is_home_store": positions["is_home"].to_numpy(),
        }
    )

    # Per material, aggregated over its positions. `true_profile` is derived from
    # the REALISED interval rather than the seed family's label: 43% of items
    # labelled "consumable" had two issues in three years, so the label contradicted
    # the parameters printed beside it.
    per_mat = (
        pd.DataFrame(
            {
                "material_id": positions["material_id"].to_numpy(),
                "interval": realised_interval,
                "size_mean": params["size_mean"].to_numpy(),
                "size_cv": params["size_cv"].to_numpy(),
            }
        )
        .groupby("material_id")
        .agg(
            interval=("interval", "min"),      # the store that moves it most often
            size_mean=("size_mean", "mean"),
            size_cv=("size_cv", "mean"),
        )
    )
    mat_ids = materials["material_id"].to_numpy()
    per_mat = per_mat.reindex(mat_ids)
    h = hidden.set_index("material_id")
    eq_status = equipment.set_index("equipment_id")["status"]
    owner_ids = materials["equipment_id"].to_numpy()

    truth_materials = pd.DataFrame(
        {
            "material_id": mat_ids,
            "true_family_id": h["family_id"].reindex(mat_ids).to_numpy(),
            "seed_profile": h["seed_profile"].reindex(mat_ids).to_numpy(),
            "true_profile": cfg.demand.profile_of(per_mat["interval"].to_numpy()),
            "true_demand_interval_days": per_mat["interval"].to_numpy(),
            "true_demand_size_mean": per_mat["size_mean"].to_numpy(),
            "true_demand_size_cv": per_mat["size_cv"].to_numpy(),
            "true_mtbf_years": h["mtbf_years"].reindex(mat_ids).to_numpy(dtype=float),
            "true_equipment_status": eq_status.reindex(owner_ids).to_numpy(),
            "true_is_obsolete": decom.reindex(owner_ids).notna().to_numpy(),
            "true_lead_time_days": materials["lead_time_days"].to_numpy(),
            "true_manufacturer": h["canonical_manufacturer"].reindex(mat_ids).to_numpy(),
            "is_duplicate_of": "",
        }
    )

    materials, stock, movements, truth_materials, planted = inject(
        cfg, materials, stock, movements, truth_materials, rng
    )

    # Injection moves issues between masters and adds opening rows for the copies,
    # so balances are recomputed from the ledger and every position reconciles by
    # construction. Negative stock is planted last, because a negative balance IS a
    # ledger disagreement and the recompute would otherwise erase it.
    stock = _rebalance_from_ledger(stock, movements)
    seq = len(planted)

    def record(kind, table, keys, detail, shadowed_by=None):
        nonlocal seq
        seq += 1
        planted.append(
            {
                "defect_id": f"D-{seq:06d}",
                "defect_type": kind,
                "table": table,
                "key": keys,
                "detail": detail,
                "shadowed_by": shadowed_by,
            }
        )

    stock = plant_negative_stock(cfg, stock, rng, record)
    truth_positions = _truth_for_new_positions(cfg, truth_positions, stock, movements, materials)

    return B.Generated(
        materials=materials,
        equipment=equipment,
        stock=stock,
        movements=movements,
        work_orders=work_orders,
        shutdowns=shutdowns,
        truth_materials=truth_materials,
        truth_positions=truth_positions,
        planted_defects=planted,
    )


def _rebalance_from_ledger(stock, movements):
    """Balances come from the movement ledger, so the two can never disagree."""
    idx = pd.MultiIndex.from_arrays([stock["material_id"], stock["storeroom_id"]])
    ledger = movements.groupby(["material_id", "storeroom_id"])["qty"].sum()
    out = stock.copy()
    out["on_hand"] = np.round(ledger.reindex(idx).fillna(0.0).to_numpy(), 2)

    issues = movements[movements["movement_type"] == "ISSUE"]
    receipts = movements[movements["movement_type"] == "RECEIPT"]
    out["last_issue_date"] = (
        issues.groupby(["material_id", "storeroom_id"])["date"].max().reindex(idx).to_numpy()
    )
    out["last_receipt_date"] = (
        receipts.groupby(["material_id", "storeroom_id"])["date"].max().reindex(idx).to_numpy()
    )
    return out


def _truth_for_new_positions(cfg, truth_positions, stock, movements, materials):
    """
    Duplicate copies are positions too, and a position with no truth row scores as
    entirely unjustified — one such row put SAR 3.3m of phantom dead money on the
    board before this existed.
    """
    known = set(zip(truth_positions["material_id"], truth_positions["storeroom_id"], strict=True))
    missing = [
        (m, s)
        for m, s in zip(stock["material_id"], stock["storeroom_id"], strict=True)
        if (m, s) not in known
    ]
    if not missing:
        return truth_positions

    years = max(cfg.n_days / 365.0, 1e-9)
    issues = movements[movements["movement_type"] == "ISSUE"]
    used = issues.groupby(["material_id", "storeroom_id"])["qty"].sum().abs() / years
    crit = materials.set_index("material_id")["criticality"]

    mids = [m for m, _ in missing]
    sids = [s for _, s in missing]
    annual = np.array([float(used.get((m, s), 0.0)) for m, s in missing])
    rows = pd.DataFrame(
        {
            "material_id": mids,
            "storeroom_id": sids,
            "true_annual_demand": annual,
            "true_justified_qty": cfg.dead_money.justified_qty(
                annual, crit.reindex(mids).to_numpy()
            ),
            "true_opening_qty": 0.0,
            "true_had_commissioning": False,
            "true_is_home_store": False,
        }
    )
    return pd.concat([truth_positions, rows], ignore_index=True)


def write(cfg: RunConfig, g: B.Generated) -> dict:
    src, key = cfg.source_dir, cfg.answer_key_dir
    S.write(g.materials, S.MATERIALS, src)
    S.write(g.equipment, S.EQUIPMENT, src)
    S.write(g.stock, S.STOCK, src)
    S.write(g.movements, S.MOVEMENTS, src)
    S.write(g.work_orders, S.WORK_ORDERS, src)
    S.write(g.shutdowns, S.SHUTDOWNS, src)

    key.mkdir(parents=True, exist_ok=True)
    S.write(g.truth_materials, S.TRUTH_MATERIALS, key)
    S.write(g.truth_positions, S.TRUTH_POSITIONS, key)
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
        "git_sha": git_sha(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_materials": int(len(g.materials)),
        "n_positions": int(len(g.stock)),
        "n_movements": int(len(g.movements)),
        "n_work_orders": int(len(g.work_orders)),
        "n_planted_defects": len(g.planted_defects),
    }
    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    (cfg.results_dir / S.RUN_MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest
