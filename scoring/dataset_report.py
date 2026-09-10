"""
Measures the generated dataset against the properties it is supposed to have.

Every number the POC reports is measured against this data, so a generator that
drifts into producing a supermarket instead of an MRO storeroom would make the
forecasts and the backtest look excellent and mean nothing. This module is the
one place those properties are computed, so the test suite and the console report
cannot disagree about them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from contracts import schemas as S
from contracts.config import RunConfig


@dataclass
class Check:
    name: str
    value: float
    target: str
    ok: bool
    detail: str = ""

    def render(self) -> str:
        mark = "OK  " if self.ok else "FAIL"
        return f"{mark} {self.name:<34} {self.value:>10.4g}   {self.target:<22} {self.detail}"


def measure(cfg: RunConfig) -> list[Check]:
    mats = S.read(S.MATERIALS, cfg.source_dir)
    stock = S.read(S.STOCK, cfg.source_dir)
    mov = S.read(S.MOVEMENTS, cfg.source_dir)
    wos = S.read(S.WORK_ORDERS, cfg.source_dir)
    sds = S.read(S.SHUTDOWNS, cfg.source_dir)
    equip = S.read(S.EQUIPMENT, cfg.source_dir)
    tmat = S.read(S.TRUTH_MATERIALS, cfg.answer_key_dir)
    tpos = S.read(S.TRUTH_POSITIONS, cfg.answer_key_dir)

    out: list[Check] = []
    issues = mov[mov.movement_type == "ISSUE"]
    end = pd.Timestamp(cfg.history_end)

    # ── idle share ──────────────────────────────────────────────────────────
    last = issues.groupby("material_id")["date"].max()
    never = int((~mats.material_id.isin(issues.material_id)).sum())
    idle = (int(((end - last).dt.days > 730).sum()) + never) / len(mats)
    lo, hi = cfg.demand.target_idle_24m_share
    out.append(Check("idle >24 months", idle, f"{lo:.0%}-{hi:.0%}", lo <= idle <= hi))

    # ── dead money, using the SHARED rule ───────────────────────────────────
    dead_share, dead_sar, total_sar = dead_money(cfg, stock, mats, tmat, tpos)
    lo, hi = cfg.size.dead_value_band
    industry = cfg.dead_money.target_dead_value_share
    note = "" if (lo, hi) == industry else " (sanity range; industry band checked at full)"
    out.append(
        Check("dead value share", dead_share, f"{lo:.0%}-{hi:.0%}", lo <= dead_share <= hi,
              f"SAR {dead_sar:,.0f} of {total_sar:,.0f}{note}")
    )

    # ── shutdown spike ──────────────────────────────────────────────────────
    ratio, base, inside = shutdown_spike(mats, issues, sds)
    floor = cfg.size.shutdown_multiple_min
    note = "" if floor >= 3.0 else " (sanity floor; 3x checked at full)"
    out.append(
        Check("shutdown issue-rate multiple", ratio, f">= {floor:g}x baseline",
              ratio >= floor,
              f"{inside:.2f}/day inside vs {base:.2f}/day baseline{note}")
    )

    # ── work orders ─────────────────────────────────────────────────────────
    linked = issues[issues.work_order_id != ""]
    per_wo = len(linked) / max(linked.work_order_id.nunique(), 1)
    out.append(
        Check("issues per work order", per_wo,
              f">= {cfg.work_orders.target_issues_per_wo}",
              per_wo >= cfg.work_orders.target_issues_per_wo)
    )

    planned = wos[wos.wo_type.isin(["PLANNED", "SHUTDOWN"])]
    notice = (planned["date"] - planned["created_date"]).dt.days
    ahead = float((notice > 0).mean()) if len(planned) else 0.0
    out.append(
        Check("planned WOs raised in advance", ahead, "= 100%", ahead > 0.999,
              f"median notice {notice.median():.0f} days" if len(planned) else "")
    )

    # ── obsolescence ────────────────────────────────────────────────────────
    n_decom = int((equip.status == "DECOMMISSIONED").sum())
    out.append(
        Check("decommissioned assets", n_decom, f">= {cfg.size.min_decommissioned}",
              n_decom >= cfg.size.min_decommissioned,
              f"{int(tmat.true_is_obsolete.sum())} obsolete materials")
    )

    # ── truth consistency ───────────────────────────────────────────────────
    bad = tmat[(tmat.true_profile == "consumable") & (tmat.true_demand_interval_days > 30)]
    out.append(
        Check("consumables with interval >30d", len(bad), "= 0", len(bad) == 0)
    )

    # ── ledger reconciliation ───────────────────────────────────────────────
    # Exactly the planted negatives may disagree with the ledger, and nothing else.
    # Comparing against a count threshold hid 52 positions that went negative on
    # their own, each of which the engine was right to flag and the scoreboard
    # counted as a false alarm.
    planted = json.loads(
        (cfg.answer_key_dir / S.PLANTED_DEFECTS_FILE).read_text(encoding="utf-8")
    )
    expected = {
        (d["key"]["material_id"], d["key"].get("storeroom_id"))
        for d in planted
        if d["defect_type"] == "NEGATIVE_STOCK"
    }
    recon = ledger_mismatch(stock, mov)
    actual = set(zip(recon.material_id, recon.storeroom_id, strict=True))
    unexplained = actual - expected
    out.append(
        Check(
            "unexplained ledger mismatches", len(unexplained), "= 0", not unexplained,
            f"{len(actual)} total, {len(expected)} planted, {len(stock)} positions checked",
        )
    )

    # ── negative balances ───────────────────────────────────────────────────
    negatives = set(
        zip(*stock.loc[stock.on_hand < 0, ["material_id", "storeroom_id"]].values.T, strict=True)
    ) if (stock.on_hand < 0).any() else set()
    stray = negatives - expected
    out.append(
        Check("unplanted negative balances", len(stray), "= 0", not stray,
              f"{len(negatives)} negative positions, {len(expected)} planted")
    )

    # ── multi-store ─────────────────────────────────────────────────────────
    multi = stock.groupby("material_id").size()
    share = float((multi > 1).mean())
    out.append(
        Check("materials in >1 storeroom", share,
              f">= {cfg.multi_store.target_multi_store_share:.0%}",
              share >= cfg.multi_store.target_multi_store_share)
    )

    # ── master data plausibility ────────────────────────────────────────────
    no_family = "material_group" in mats.columns and "family_id" not in mats.columns
    out.append(Check("family_id absent from source", float(no_family), "= true", no_family))

    return out


def dead_money(cfg, stock, materials, truth_materials, truth_positions):
    """
    The shared dead-money definition. Obsolete stock is dead in full; otherwise only
    what exceeds the justified quantity from `cfg.dead_money`.

    Valued at the SAP moving average, which is what would actually be written off.
    """
    j = (
        stock.merge(truth_positions, on=["material_id", "storeroom_id"], how="left")
        .merge(truth_materials[["material_id", "true_is_obsolete"]], on="material_id", how="left")
    )
    on_hand = j.on_hand.clip(lower=0)
    justified = j.true_justified_qty.fillna(0.0)
    obsolete = j.true_is_obsolete.fillna(False).to_numpy()
    dead_units = np.where(obsolete, on_hand, np.maximum(on_hand - justified, 0.0))

    dead = float((dead_units * j.avg_unit_cost_sar).sum())
    total = float((on_hand * j.avg_unit_cost_sar).sum())
    return (dead / total if total else 0.0), dead, total


def shutdown_spike(materials, issues, shutdowns):
    """Issues per day inside a shutdown window versus that plant's own baseline."""
    if shutdowns.empty or issues.empty:
        return 0.0, 0.0, 0.0
    area = materials.set_index("material_id")["area"]
    iss = issues.copy()
    iss["area"] = area.reindex(iss.material_id).to_numpy()

    inside_n = inside_days = base_n = base_days = 0.0
    for sd in shutdowns.itertuples():
        plant = iss[iss.area == sd.plant]
        if plant.empty:
            continue
        span = max((sd.end_date - sd.start_date).days, 1)
        during = plant[(plant.date >= sd.start_date) & (plant.date <= sd.end_date)]
        inside_n += len(during)
        inside_days += span
        outside = plant[(plant.date < sd.start_date) | (plant.date > sd.end_date)]
        total_days = (plant.date.max() - plant.date.min()).days or 1
        base_n += len(outside)
        base_days += max(total_days - span, 1)

    inside_rate = inside_n / inside_days if inside_days else 0.0
    base_rate = base_n / base_days if base_days else 0.0
    return (inside_rate / base_rate if base_rate else 0.0), base_rate, inside_rate


def ledger_mismatch(stock, movements, tolerance: float = 0.01) -> pd.DataFrame:
    """Positions where the movement ledger does not sum to the stock balance."""
    ledger = movements.groupby(["material_id", "storeroom_id"])["qty"].sum().rename("ledger")
    j = stock.merge(ledger, on=["material_id", "storeroom_id"], how="left")
    j["ledger"] = j["ledger"].fillna(0.0)
    j["gap"] = (j["on_hand"] - j["ledger"]).abs()
    return j[j["gap"] > tolerance]


def render(checks: list[Check]) -> str:
    head = f"{'':4} {'property':<34} {'measured':>10}   {'target':<22} detail"
    return "\n".join([head, "-" * 100, *(c.render() for c in checks)])
