"""
Demand sampling and the history walk.

Demand is sampled per POSITION as inter-arrival gaps plus sizes — no day loop.
Shutdowns then add extra events inside their window for the families that are
actually consumed during an outage, which is what gives step 4 a spike it is
allowed to know about in advance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from contracts import schemas as S
from contracts.config import RunConfig
from generator.build import PROFILES, STOREROOM_BY_AREA
from sim.replenish import densify_many, walk


def demand_params(cfg: RunConfig, positions: pd.DataFrame, hidden: pd.DataFrame, rng):
    """
    Sample the true demand parameters per position.

    The subtlety that makes this look like a real master: a *family* moves often,
    but any single variant inside it does not. "BEARING, BALL" is issued weekly;
    "BEARING, BALL, 6205, SKF" is issued twice a year. So each item's interval is
    stretched by how broad its family is, times a heavy-tailed popularity draw —
    reproducing the real pattern where a minority of line items carry most of the
    movement and the majority sit still for years.

    Breadth comes from the seed file's variant_weight, NOT from how many variants
    this run happened to create. Using the realised count would make the toy preset
    behave differently from the full one, and a toy set that does not behave like
    the real one is useless for testing the steps that come after it.
    """
    h = hidden.set_index("material_id")
    mat = positions["material_id"].to_numpy()
    prof = h["seed_profile"].reindex(mat).to_numpy()
    n = len(positions)

    interval = np.empty(n)
    size_mean = np.empty(n)
    size_cv = np.empty(n)
    drift = np.empty(n)
    for name, spec in PROFILES.items():
        m = prof == name
        k = int(m.sum())
        if not k:
            continue
        interval[m] = rng.uniform(*spec["interval"], k)
        size_mean[m] = rng.uniform(*spec["size"], k)
        size_cv[m] = rng.uniform(*spec["cv"], k)
        drift[m] = rng.uniform(*spec["drift"], k)

    fams = pd.read_csv(cfg.seeds_dir / "part_families.csv").set_index("family_id")
    weight = fams["variant_weight"].reindex(h["family_id"].reindex(mat)).to_numpy(dtype=float)
    breadth = np.power(np.maximum(weight, 1.0), cfg.demand.breadth_exponent)
    popularity = rng.lognormal(0.0, cfg.demand.popularity_sigma, n)

    # splitting an item's demand across storerooms lengthens each store's interval
    demand_share = np.maximum(positions["demand_share"].to_numpy(), 1e-3)
    interval = interval * breadth * popularity / demand_share
    size_mean = np.maximum(size_mean / np.sqrt(breadth) * 2.0, 1.0)

    return pd.DataFrame(
        {
            "material_id": mat,
            "storeroom_id": positions["storeroom_id"].to_numpy(),
            "seed_profile": prof,
            "interval": interval,
            "size_mean": size_mean,
            "size_cv": size_cv,
            "drift": drift,
            "shutdown_mult": h["shutdown_mult"].reindex(mat).to_numpy(dtype=float),
            "area": h["area"].reindex(mat).to_numpy(),
        }
    )


def sample_demand(cfg, params, shutdowns, rng, stop_day=None):
    """
    Sample demand events per position, then overlay shutdown consumption.

    `stop_day` is the day the owning equipment was decommissioned. Demand ceases
    there and the stock left behind becomes genuinely obsolete — the only way
    obsolescence gets into this dataset. It is never injected.
    """
    n_days = cfg.n_days
    interval = params["interval"].to_numpy()
    size_mean = params["size_mean"].to_numpy()
    size_cv = params["size_cv"].to_numpy()
    drift = params["drift"].to_numpy()
    n = len(params)

    max_events = np.maximum(4, np.ceil(n_days / np.maximum(interval, 1.0) * 3).astype(int))
    cap = int(min(max_events.max(), 4000))

    days_out: list[np.ndarray] = []
    qty_out: list[np.ndarray] = []
    for i in range(n):
        k = int(min(max_events[i], cap))
        gaps = rng.exponential(interval[i], size=k)
        days = np.cumsum(gaps)
        if abs(drift[i] - 1.0) > 1e-6:
            frac = np.clip(days / n_days, 0, 1)
            days = np.cumsum(gaps / np.maximum(1.0 + (drift[i] - 1.0) * frac, 0.05))

        limit = n_days if stop_day is None else min(n_days, int(stop_day[i]))
        days = days[days < limit].astype(np.int32)
        if days.size == 0:
            days_out.append(np.empty(0, np.int32))
            qty_out.append(np.empty(0, np.float64))
            continue

        shape = max(1.0 / max(size_cv[i], 1e-3) ** 2, 0.05)
        qty = np.maximum(np.round(rng.gamma(shape, size_mean[i] / shape, size=days.size)), 1.0)
        days_out.append(days)
        qty_out.append(qty)

    _overlay_shutdowns(cfg, params, shutdowns, days_out, qty_out, rng, stop_day)
    return days_out, qty_out


def _overlay_shutdowns(cfg, params, shutdowns, days_out, qty_out, rng, stop_day):
    """
    Extra consumption inside a planned outage.

    A shutdown is when the pot lining is dug out and the digester is opened up:
    cathode blocks and refractory move 15-20x, O-rings barely move at all. Without
    this the shutdown table is decoration — measured issues/day inside a smelter
    outage were 1.5 against a 2.0 baseline, i.e. no effect whatsoever, and step 4's
    "a planned shutdown is known demand, not a surprise" would have nothing behind it.
    """
    if shutdowns.empty:
        return
    start = pd.Timestamp(cfg.history_start)
    mult = params["shutdown_mult"].to_numpy(dtype=float)
    area = params["area"].to_numpy()
    interval = params["interval"].to_numpy()
    size_mean = params["size_mean"].to_numpy()

    for sd in shutdowns.itertuples():
        d0 = int((sd.start_date - start).days)
        d1 = int((sd.end_date - start).days)
        span = max(d1 - d0, 1)
        affected = np.flatnonzero((area == sd.plant) & (mult > 1.0))
        for i in affected:
            if stop_day is not None and d0 >= int(stop_day[i]):
                continue
            base_rate = 1.0 / max(interval[i], 1.0)
            extra = rng.poisson(base_rate * (mult[i] - 1.0) * span * cfg.shutdown_intensity)
            if extra <= 0:
                continue
            days = rng.integers(d0, d0 + span, size=int(extra)).astype(np.int32)
            qty = np.maximum(np.round(rng.gamma(2.0, size_mean[i] / 2.0, size=int(extra))), 1.0)
            days_out[i] = np.concatenate([days_out[i], days])
            qty_out[i] = np.concatenate([qty_out[i], qty])
            order = np.argsort(days_out[i], kind="stable")
            days_out[i] = days_out[i][order]
            qty_out[i] = qty_out[i][order]


def stale_levels(cfg, params, demand_days, demand_qty, price, rng):
    """
    The incumbent policy: cover-day levels frozen early in history, ignoring
    criticality, with a slice of hand-entry errors. Deliberately mediocre — this is
    the baseline the step-5 policy is measured against.
    """
    sp = cfg.stale_policy
    n = len(params)
    freeze = sp.set_on_offset_days

    daily_rate = np.array(
        [q[d < freeze].sum() / freeze if d.size else 0.0
         for d, q in zip(demand_days, demand_qty, strict=True)]
    )
    daily_rate = np.where(daily_rate > 0, daily_rate, params["size_mean"].to_numpy() / 365.0)

    min_qty = np.ceil(daily_rate * sp.min_cover_days / sp.round_up_to) * sp.round_up_to
    max_qty = np.ceil(daily_rate * sp.max_cover_days / sp.round_up_to) * sp.round_up_to

    # A hand-entry error on a SAR 4 washer goes unnoticed for years; the same error
    # on a SAR 200k mill roll is caught at purchase approval. Scaling the rate down
    # with value stops dead money becoming an artefact of fat-fingering the most
    # expensive items in the plant.
    damp = np.clip(sp.fat_finger_value_pivot / np.maximum(price, 1.0), 0.05, 1.0)
    fat = rng.random(n) < sp.fat_finger_share * damp
    bump = rng.choice([sp.fat_finger_factor, 1.0 / sp.fat_finger_factor], size=n)
    min_qty = np.where(fat, min_qty * bump, min_qty)
    max_qty = np.where(fat, max_qty * bump, max_qty)

    min_qty = np.maximum(min_qty, 0.0)
    max_qty = np.maximum(max_qty, min_qty + 1.0)
    return min_qty, max_qty


def commissioning_opening(cfg, params, max_qty, price, rng):
    """
    Opening balance: normally the policy maximum, plus — for a slice of capital
    spares — a decade-old commissioning package that was never consumed.

    Only lumpy and insurance items are eligible. Those are what a commissioning
    package actually covers: the failures that would stop the plant and then,
    mostly, never happened. Sizing it in "years of demand" was wrong — on an item
    with real turnover it produced 2,188 UPS batteries and pushed dead money to 91%
    of stock value.
    """
    cs = cfg.commissioning
    n = len(params)
    eligible = np.isin(params["seed_profile"].to_numpy(), cs.applies_to)
    carries = eligible & (rng.random(n) < cs.share)
    package = np.round(rng.uniform(*cs.units, size=n))
    # the more a unit costs, the fewer of it anyone buys "just in case"
    package = np.where(price >= cs.single_unit_above_sar, 1.0, package)
    return np.where(carries, max_qty + package, max_qty), carries


def run_history(cfg, positions, price, lead, min_qty, max_qty, opening, demand_days, demand_qty,
                rng):
    """
    Walk every position through the stale policy in blocks, then assemble the
    ledger: an opening ADJUST, the issues, and the receipts the policy generated.

    The opening row is what makes `sum(movements.qty) == on_hand` hold, and that
    identity is what a ledger-reconciliation check needs to exist at all.
    """
    n_days = cfg.n_days
    n = len(positions)
    start = pd.Timestamp(cfg.history_start)

    on_hand = np.zeros(n)
    last_receipt = np.full(n, -1, dtype=np.int64)
    r_item, r_day, r_qty = [], [], []
    s_item, s_day, s_qty = [], [], []

    for lo in range(0, n, cfg.sim_block_size):
        hi = min(lo + cfg.sim_block_size, n)
        dense = densify_many(demand_days[lo:hi], demand_qty[lo:hi], n_days)
        res = walk(
            dense,
            opening=opening[lo:hi],
            reorder_point=min_qty[lo:hi],
            order_up_to=max_qty[lo:hi],
            lead_time=lead[lo:hi],
            review_period_days=7,
            order_multiple=np.full(hi - lo, cfg.stale_policy.round_up_to),
            lead_time_cv=cfg.lead_time.cv,
            lead_time_bounds=(cfg.lead_time.min_days, cfg.lead_time.max_days),
            rng=rng,
            return_served=True,
        )
        on_hand[lo:hi] = res.on_hand_end
        last_receipt[lo:hi] = res.last_receipt_day
        si, sd_ = np.nonzero(res.served_by_day)
        s_item.append(si + lo)
        s_day.append(sd_)
        s_qty.append(res.served_by_day[si, sd_])
        keep = res.receipt_day < n_days
        r_item.append(res.receipt_item[keep] + lo)
        r_day.append(res.receipt_day[keep])
        r_qty.append(res.receipt_qty[keep])

    def cat(parts, dtype):
        return np.concatenate(parts).astype(dtype) if parts else np.empty(0, dtype)

    ri, rd, rq = cat(r_item, np.int64), cat(r_day, np.int64), cat(r_qty, float)

    i_idx, i_day, i_qty = cat(s_item, np.int64), cat(s_day, np.int64), cat(s_qty, float)

    mid = positions["material_id"].to_numpy()
    sid = positions["storeroom_id"].to_numpy()

    frames = [
        pd.DataFrame(
            {
                "date": start,
                "material_id": mid,
                "storeroom_id": sid,
                "movement_type": "ADJUST",
                "qty": opening,
                "work_order_id": "",
                "unit_cost_sar": price,
            }
        )
    ]
    if i_day.size:
        frames.append(
            pd.DataFrame(
                {
                    "date": start + pd.to_timedelta(i_day, "D"),
                    "material_id": mid[i_idx],
                    "storeroom_id": sid[i_idx],
                    "movement_type": "ISSUE",
                    "qty": -i_qty,
                    "work_order_id": "",          # filled in by the work-order builder
                    "unit_cost_sar": price[i_idx],
                }
            )
        )
    if rd.size:
        frames.append(
            pd.DataFrame(
                {
                    "date": start + pd.to_timedelta(rd, "D"),
                    "material_id": mid[ri],
                    "storeroom_id": sid[ri],
                    "movement_type": "RECEIPT",
                    "qty": rq,
                    "work_order_id": "",
                    "unit_cost_sar": price[ri],
                }
            )
        )

    movements = pd.concat(frames, ignore_index=True)
    movements = movements.sort_values(["date", "material_id"], kind="stable").reset_index(drop=True)
    return movements, on_hand, last_receipt


def add_returns_and_adjustments(cfg, movements, rng):
    """
    A share of issues come back within a month, and a few positions get counted.

    The engine's netting logic needs something to net: an ISSUE followed by a
    RETURN on the same work order is not consumption, and a system that treats it
    as consumption over-forecasts every part that is ever returned.
    """
    ra = cfg.returns
    issues = movements[movements["movement_type"] == "ISSUE"]
    out = [movements]

    if len(issues) and ra.return_share > 0:
        k = max(1, int(len(issues) * ra.return_share))
        picked = issues.sample(n=min(k, len(issues)), random_state=int(rng.integers(1 << 31)))
        gap = rng.integers(1, ra.return_window_days + 1, size=len(picked))
        ret = picked.copy()
        ret["date"] = picked["date"].to_numpy() + pd.to_timedelta(gap, "D")
        ret["movement_type"] = "RETURN"
        ret["qty"] = -picked["qty"].to_numpy() * rng.uniform(0.3, 1.0, len(picked)).round(2)
        ret = ret[ret["date"] <= pd.Timestamp(cfg.history_end)]
        out.append(ret)

    positions = movements[["material_id", "storeroom_id"]].drop_duplicates()
    if len(positions) and ra.adjustment_share > 0:
        k = max(1, int(len(positions) * ra.adjustment_share))
        picked = positions.sample(n=min(k, len(positions)),
                                  random_state=int(rng.integers(1 << 31)))
        day = rng.integers(cfg.n_days - 365, cfg.n_days, size=len(picked))
        # A count can find less than the books say, but never less than nothing.
        # Unclamped, this drove 77 positions negative at full scale — and those
        # would have been scored as false alarms against a check that was right.
        balance = movements.groupby(["material_id", "storeroom_id"])["qty"].sum()
        idx = pd.MultiIndex.from_arrays([picked["material_id"], picked["storeroom_id"]])
        held = balance.reindex(idx).fillna(0.0).to_numpy()
        delta = np.round(rng.normal(0, 3, len(picked)))
        delta = np.maximum(delta, -np.maximum(held, 0.0))

        adj = pd.DataFrame(
            {
                "date": pd.Timestamp(cfg.history_start) + pd.to_timedelta(day, "D"),
                "material_id": picked["material_id"].to_numpy(),
                "storeroom_id": picked["storeroom_id"].to_numpy(),
                "movement_type": "ADJUST",
                "qty": delta,
                "work_order_id": "",
                "unit_cost_sar": 0.0,
            }
        )
        out.append(adj[adj["qty"] != 0])

    merged = pd.concat(out, ignore_index=True)
    return merged.sort_values(["date", "material_id"], kind="stable").reset_index(drop=True)


def build_work_orders(cfg, movements, materials, equipment, shutdowns, rng):
    """
    Group issues into maintenance jobs, and give planned jobs advance notice.

    Fully vectorised: the first version called `.iloc[chunk].min()` once per work
    order, which cost 86% of the whole generation run at full scale (140s of 162s)
    for 105,000 jobs. Grouping and dating are now done with groupby aggregates.

    ponytail: issues are grouped by (equipment, month) as a proxy for one
    maintenance visit. Real work orders are per job, but demand here is sampled per
    material independently, so any grouping we impose is synthetic. Inverting the
    model — sample work orders, then draw parts from the asset's BOM — would be the
    honest fix and is a bigger change than this slice justifies. The grouping gives
    the forecaster multi-part jobs and real advance notice, which is what step 4
    actually consumes.
    """
    wo = cfg.work_orders
    issues = movements[movements["movement_type"] == "ISSUE"]
    if issues.empty:
        return S.empty(S.WORK_ORDERS), movements

    owner = materials.set_index("material_id")["equipment_id"]
    df = pd.DataFrame(
        {
            "row": issues.index.to_numpy(),
            "equipment_id": owner.reindex(issues["material_id"]).to_numpy(),
            "date": issues["date"].to_numpy(),
        }
    )
    df["bucket"] = pd.to_datetime(df["date"]).dt.to_period("M").astype(str)
    df = df.sort_values(["equipment_id", "bucket", "date"], kind="stable").reset_index(drop=True)

    # split each asset-month into jobs of a plausible size
    grp = df.groupby(["equipment_id", "bucket"], sort=False)
    within = grp.cumcount().to_numpy()
    n_groups = grp.ngroup().to_numpy()
    lo_b, hi_b = wo.parts_per_breakdown
    lo_p, hi_p = wo.parts_per_planned
    n_unique = int(n_groups.max()) + 1
    is_breakdown_grp = rng.random(n_unique) < wo.breakdown_share
    size_grp = np.where(
        is_breakdown_grp,
        rng.integers(lo_b, hi_b + 1, n_unique),
        rng.integers(lo_p, hi_p + 1, n_unique),
    )
    chunk = within // size_grp[n_groups]
    df["wo_key"] = n_groups.astype(np.int64) * 10_000 + chunk

    agg = df.groupby("wo_key", sort=False).agg(
        equipment_id=("equipment_id", "first"), date=("date", "min")
    )
    agg = agg.reset_index()
    n = len(agg)
    agg["work_order_id"] = [f"WO-{i:07d}" for i in range(1, n + 1)]

    # which jobs fall inside a planned outage
    plant_of = equipment.set_index("equipment_id")["plant"]
    agg["plant"] = plant_of.reindex(agg["equipment_id"]).to_numpy()
    agg["shutdown_id"] = ""
    agg["scheduled_on"] = pd.NaT
    agg["sd_start"] = pd.NaT
    for sd in shutdowns.itertuples():
        m = (
            (agg["plant"] == sd.plant)
            & (agg["date"] >= sd.start_date)
            & (agg["date"] <= sd.end_date)
        )
        agg.loc[m, "shutdown_id"] = sd.shutdown_id
        agg.loc[m, "scheduled_on"] = sd.scheduled_on
        agg.loc[m, "sd_start"] = sd.start_date

    in_shutdown = agg["shutdown_id"] != ""
    breakdown = (~in_shutdown) & (rng.random(n) < wo.breakdown_share)
    agg["wo_type"] = np.where(in_shutdown, "SHUTDOWN", np.where(breakdown, "BREAKDOWN", "PLANNED"))

    notice = rng.integers(*wo.planned_notice_days, size=n)
    agg["created_date"] = np.where(
        in_shutdown,
        agg["scheduled_on"].to_numpy(),
        np.where(
            breakdown,
            agg["date"].to_numpy(),                       # a breakdown is raised as it happens
            (agg["date"] - pd.to_timedelta(notice, "D")).to_numpy(),
        ),
    )
    slip = rng.integers(0, 5, size=n)
    agg["planned_date"] = np.where(
        in_shutdown,
        agg["sd_start"].to_numpy(),
        np.where(
            breakdown,
            np.datetime64("NaT", "ns"),
            (agg["date"] - pd.to_timedelta(slip, "D")).to_numpy(),
        ),
    )

    wo_id_by_key = dict(zip(agg["wo_key"], agg["work_order_id"], strict=True))
    movements = movements.copy()
    movements.loc[df["row"].to_numpy(), "work_order_id"] = (
        df["wo_key"].map(wo_id_by_key).to_numpy()
    )

    work_orders = agg[
        ["work_order_id", "equipment_id", "date", "created_date", "planned_date",
         "wo_type", "shutdown_id"]
    ].copy()
    for col in ("date", "created_date", "planned_date"):
        work_orders[col] = pd.to_datetime(work_orders[col])
    return work_orders.reset_index(drop=True), movements


def build_shutdowns(cfg, rng):
    years = max(1, cfg.n_days // 365)
    n = cfg.size.n_shutdowns_per_year * years
    start = pd.Timestamp(cfg.history_start)
    plants = rng.choice(np.array(["SMELTER", "REFINERY", "ROLLING", "MINE"]), size=n)
    offsets = np.sort(rng.integers(150, cfg.n_days - 40, size=n))
    notice = rng.integers(*cfg.work_orders.shutdown_notice_days, size=n)
    return pd.DataFrame(
        {
            "shutdown_id": [f"SD-{i:03d}" for i in range(1, n + 1)],
            "plant": plants,
            "start_date": start + pd.to_timedelta(offsets, "D"),
            "end_date": start + pd.to_timedelta(offsets + rng.integers(7, 22, n), "D"),
            "scheduled_on": start + pd.to_timedelta(np.maximum(offsets - notice, 0), "D"),
        }
    )


__all__ = [
    "STOREROOM_BY_AREA",
    "add_returns_and_adjustments",
    "build_shutdowns",
    "build_work_orders",
    "commissioning_opening",
    "demand_params",
    "run_history",
    "sample_demand",
    "stale_levels",
]
