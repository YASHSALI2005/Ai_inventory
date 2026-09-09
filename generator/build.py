"""
The data maker: writes fake PiLog / CMMS / SAP tables plus the answer key.

Two rules shape everything here.

1. **Vectorised.** Demand is produced by sampling inter-demand gaps and demand
   sizes per item with numpy, then assembling a ledger — never by looping over
   days. The only per-item Python loop is the replenishment walk, which is
   inherently sequential and runs over a dense day vector inside `sim`.

2. **Emergent, not injected, where it matters.** Overstock, obsolescence and
   critical-items-below-reorder-point are NOT planted. They appear because the
   simulated plant runs a stale, mediocre min/max policy against demand that has
   drifted, and because some equipment gets decommissioned mid-history while its
   spares keep sitting there. Those are scored against `truth`.

   Only *data* defects are planted — negatives, blanks, UOM errors, duplicates,
   orphan issues — because those have no natural generating process here and we
   want an exact found/missed/false-alarm count for them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from contracts import schemas as S
from contracts.config import RunConfig
from sim.replenish import densify, walk

# Demand shape per seed-file profile.
#   interval_days: mean gap between demands
#   size_mean / size_cv: quantity when a demand occurs
#   drift: multiplicative change in rate across the 3 years — this is what makes
#          the plant's frozen min/max levels go stale, producing real overstock.
PROFILES = {
    "consumable": dict(interval=(2.0, 9.0), size=(4.0, 40.0), cv=(0.35, 0.8), drift=(0.7, 1.4)),
    "occasional": dict(interval=(25.0, 90.0), size=(1.0, 5.0), cv=(0.5, 1.1), drift=(0.5, 1.6)),
    "lumpy": dict(interval=(90.0, 300.0), size=(1.0, 8.0), cv=(0.9, 1.8), drift=(0.4, 1.8)),
    "insurance": dict(interval=(700.0, 3000.0), size=(1.0, 2.0), cv=(0.2, 0.6), drift=(0.8, 1.2)),
}

STOREROOM_BY_AREA = {
    "MINE": "BAITHA",
    "RAIL": "BAITHA",
    "REFINERY": "REFINERY",
    "SMELTER": "SMELTER",
    "ROLLING": "ROLLING",
    "SITEWIDE": "CENTRAL",
}

MANUFACTURERS = (
    "SKF", "Flexitallic", "Metso", "FLSmidth", "Weir", "ABB", "Siemens", "Danieli",
    "Alstom", "Sandvik", "Rio Tinto Alcan", "Outotec", "Emerson", "Parker", "Eaton",
)


@dataclass
class Generated:
    materials: pd.DataFrame
    equipment: pd.DataFrame
    stock: pd.DataFrame
    movements: pd.DataFrame
    work_orders: pd.DataFrame
    shutdowns: pd.DataFrame
    truth: pd.DataFrame
    planted_defects: list[dict]


# ── pieces ───────────────────────────────────────────────────────────────────


def _load_families(cfg: RunConfig) -> pd.DataFrame:
    fams = pd.read_csv(cfg.seeds_dir / "part_families.csv")
    bad = set(fams["profile"]) - set(PROFILES)
    if bad:
        raise ValueError(f"seed file has unknown profiles: {sorted(bad)}")
    return fams


def _build_equipment(cfg: RunConfig, rng: np.random.Generator) -> pd.DataFrame:
    n = cfg.size.n_equipment
    plants = np.array(S.PLANTS)
    # site-wide assets are fewer; weight towards the process plants
    weights = np.array([0.18, 0.06, 0.24, 0.26, 0.18, 0.08])
    plant = rng.choice(plants, size=n, p=weights)
    crit = rng.choice(np.array(S.CRITICALITY), size=n, p=[0.22, 0.43, 0.35])

    start = pd.Timestamp(cfg.history_start)
    # ~8% of equipment is decommissioned partway through history. Their spares stay
    # on the shelf — this is where genuine obsolescence comes from.
    decommissioned = rng.random(n) < 0.08
    offset = rng.integers(180, max(cfg.n_days - 30, 200), size=n)
    decom_date = np.where(
        decommissioned,
        (start + pd.to_timedelta(offset, "D")).values,
        np.datetime64("NaT", "ns"),
    )

    return pd.DataFrame(
        {
            "equipment_id": [f"EQ-{i:05d}" for i in range(1, n + 1)],
            "plant": plant,
            "storeroom_id": [STOREROOM_BY_AREA[p] for p in plant],
            "name": [f"{p} asset {i:04d}" for i, p in enumerate(plant, 1)],
            "criticality": crit,
            "status": np.where(decommissioned, "DECOMMISSIONED", "RUNNING"),
            "commissioned_date": start - pd.Timedelta(days=1),
            "decommissioned_date": pd.to_datetime(decom_date),
        }
    )


def _build_materials(
    cfg: RunConfig, fams: pd.DataFrame, equipment: pd.DataFrame, rng: np.random.Generator
) -> pd.DataFrame:
    """Expand each seed family into dimensioned variants, weighted by family size."""
    n_target = cfg.size.n_materials
    w = fams["variant_weight"].to_numpy(dtype=float)
    counts = np.maximum(1, np.round(w / w.sum() * n_target)).astype(int)

    fam_idx = np.repeat(np.arange(len(fams)), counts)[:n_target]
    # if rounding undershot, top up from the largest families
    if fam_idx.size < n_target:
        pad = rng.choice(np.arange(len(fams)), size=n_target - fam_idx.size, p=w / w.sum())
        fam_idx = np.concatenate([fam_idx, pad])
    rng.shuffle(fam_idx)

    f = fams.iloc[fam_idx].reset_index(drop=True)
    n = len(f)

    u = rng.random(n)
    price = f["price_min_sar"].to_numpy() + u * (
        f["price_max_sar"].to_numpy() - f["price_min_sar"].to_numpy()
    )
    lead = (
        f["lead_min_days"].to_numpy()
        + rng.random(n) * (f["lead_max_days"].to_numpy() - f["lead_min_days"].to_numpy())
    ).astype(np.int32)

    # a size/rating token, so variants inside a family read like a real master
    size_token = rng.integers(1, 400, size=n)
    mpn_num = rng.integers(10000, 999999, size=n)
    manufacturer = rng.choice(np.array(MANUFACTURERS), size=n)

    # attach each material to a piece of equipment in a matching plant where possible
    eq_by_plant: dict[str, np.ndarray] = {
        p: equipment.loc[equipment["plant"] == p, "equipment_id"].to_numpy()
        for p in equipment["plant"].unique()
    }
    all_eq = equipment["equipment_id"].to_numpy()
    owner = np.empty(n, dtype=object)
    for i, area in enumerate(f["area"].to_numpy()):
        pool = eq_by_plant.get(area, all_eq)
        owner[i] = rng.choice(pool if pool.size else all_eq)

    # Criticality follows what the part IS (the seed file's crit_bias), not the
    # equipment lottery. A spare power transformer is criticality A because it is a
    # transformer; assigning it randomly from its owning asset produced a B-rated
    # transformer and a A-rated washer, which then poisoned every downstream
    # judgement about what counts as dead money.
    #
    # The equipment link still matters — it decides obsolescence, and an item on an
    # A-rated asset gets bumped up a grade.
    bias = f["crit_bias"].to_numpy()
    jitter = rng.random(n)
    crit = np.where(jitter < 0.12, rng.choice(np.array(S.CRITICALITY), size=n), bias)

    eq_crit = equipment.set_index("equipment_id")["criticality"].reindex(owner).to_numpy()
    bump = {"C": "B", "B": "A", "A": "A"}
    crit = np.where(eq_crit == "A", [bump[c] for c in crit], crit)

    desc = (
        f["noun"].str.strip()
        + ", "
        + f["modifier"].str.strip()
        + ", "
        + pd.Series(size_token).astype(str)
        + "MM"
    )

    return pd.DataFrame(
        {
            "material_id": [f"M-{i:06d}" for i in range(1, n + 1)],
            "family_id": f["family_id"].to_numpy(),
            "noun": f["noun"].to_numpy(),
            "modifier": f["modifier"].to_numpy(),
            "description": desc.to_numpy(),
            "manufacturer": manufacturer,
            "mpn": [f"{m}-{v}" for m, v in zip(manufacturer, mpn_num, strict=True)],
            "uom": f["uom"].to_numpy(),
            "unit_price_sar": np.round(price, 2),
            "lead_time_days": lead,
            "area": f["area"].to_numpy(),
            "equipment_id": owner,
            "criticality": crit,
        }
    )


def _demand_params(
    cfg: RunConfig, materials: pd.DataFrame, fams: pd.DataFrame, rng: np.random.Generator
) -> pd.DataFrame:
    """
    Sample the true demand parameters per material. These become `truth`.

    The subtlety that makes this look like a real master: a *family* moves often,
    but any single variant inside it does not. "BEARING, BALL" is issued weekly;
    "BEARING, BALL, 6205, SKF" is issued twice a year. So each item's interval is
    stretched by how many variants share the family, times a heavy-tailed
    popularity draw — which reproduces the real pattern where a minority of line
    items carry most of the movement and the majority sit still for years.
    """
    prof_by_family = fams.set_index("family_id")["profile"]
    profile = prof_by_family.reindex(materials["family_id"]).to_numpy()

    n = len(materials)
    interval = np.empty(n)
    size_mean = np.empty(n)
    size_cv = np.empty(n)
    drift = np.empty(n)

    for name, spec in PROFILES.items():
        m = profile == name
        k = int(m.sum())
        if not k:
            continue
        lo, hi = spec["interval"]
        interval[m] = rng.uniform(lo, hi, k)
        lo, hi = spec["size"]
        size_mean[m] = rng.uniform(lo, hi, k)
        lo, hi = spec["cv"]
        size_cv[m] = rng.uniform(lo, hi, k)
        lo, hi = spec["drift"]
        drift[m] = rng.uniform(lo, hi, k)

    # Stretch by family breadth and per-item popularity.
    #
    # Breadth comes from the seed file's `variant_weight`, NOT from how many
    # variants this particular run happened to create. Using the realised count
    # would make the toy preset behave differently from the full one — items would
    # move far more often in toy — and a toy set that does not behave like the real
    # one is useless for testing the steps that come after it.
    weight = fams.set_index("family_id")["variant_weight"]
    breadth = np.power(
        np.maximum(weight.reindex(materials["family_id"]).to_numpy(dtype=float), 1.0),
        cfg.demand.breadth_exponent,
    )
    popularity = rng.lognormal(0.0, cfg.demand.popularity_sigma, n)
    interval = interval * breadth * popularity

    # a variant from a broad family also carries a smaller slice of the issue size
    size_mean = np.maximum(size_mean / np.sqrt(breadth) * 2.0, 1.0)

    return pd.DataFrame(
        {
            "material_id": materials["material_id"].to_numpy(),
            "profile": profile,
            "interval": interval,
            "size_mean": size_mean,
            "size_cv": size_cv,
            "drift": drift,
        }
    )


def _sample_demand(
    cfg: RunConfig,
    params: pd.DataFrame,
    rng: np.random.Generator,
    stop_day: np.ndarray | None = None,
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """
    Vectorised demand sampling: gaps then sizes, per item, no day loop.

    Demand rate drifts linearly across the window (`drift`), which is what makes a
    policy set in year 1 wrong by year 3 — the source of emergent excess.

    `stop_day` is the day the owning equipment was decommissioned. Demand ceases
    there and the stock left behind becomes genuinely obsolete — which is the only
    way obsolescence gets into this dataset. It is never injected.
    """
    n_days = cfg.n_days
    days_out: list[np.ndarray] = []
    qty_out: list[np.ndarray] = []

    interval = params["interval"].to_numpy()
    size_mean = params["size_mean"].to_numpy()
    size_cv = params["size_cv"].to_numpy()
    drift = params["drift"].to_numpy()

    # generous upper bound on event count so one draw covers the window
    max_events = np.maximum(4, np.ceil(n_days / np.maximum(interval, 1.0) * 3).astype(int))
    cap = int(min(max_events.max(), 4000))

    for i in range(len(params)):
        k = int(min(max_events[i], cap))
        gaps = rng.exponential(interval[i], size=k)
        days = np.cumsum(gaps)

        # apply drift by stretching/compressing the timeline
        if abs(drift[i] - 1.0) > 1e-6:
            frac = np.clip(days / n_days, 0, 1)
            rate_scale = 1.0 + (drift[i] - 1.0) * frac
            days = np.cumsum(gaps / np.maximum(rate_scale, 0.05))

        limit = n_days if stop_day is None else min(n_days, int(stop_day[i]))
        days = days[days < limit].astype(np.int32)
        if days.size == 0:
            days_out.append(np.empty(0, np.int32))
            qty_out.append(np.empty(0, np.float64))
            continue

        mean, cv = size_mean[i], size_cv[i]
        shape = max(1.0 / max(cv, 1e-3) ** 2, 0.05)
        qty = rng.gamma(shape, mean / shape, size=days.size)
        qty = np.maximum(np.round(qty), 1.0)

        days_out.append(days)
        qty_out.append(qty)

    return days_out, qty_out


def _stale_levels(
    cfg: RunConfig,
    params: pd.DataFrame,
    demand_days,
    demand_qty,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """
    The incumbent policy: cover-day levels frozen early in history, ignoring
    criticality, with a slice of hand-entry errors. Deliberately mediocre.
    """
    sp = cfg.stale_policy
    n = len(params)
    freeze = sp.set_on_offset_days

    daily_rate = np.zeros(n)
    for i in range(n):
        d, q = demand_days[i], demand_qty[i]
        early = q[d < freeze]
        daily_rate[i] = early.sum() / freeze if early.size else 0.0

    # items with no early demand still get a token level, as a planner would set
    daily_rate = np.where(daily_rate > 0, daily_rate, params["size_mean"].to_numpy() / 365.0)

    min_qty = np.ceil(daily_rate * sp.min_cover_days / sp.round_up_to) * sp.round_up_to
    max_qty = np.ceil(daily_rate * sp.max_cover_days / sp.round_up_to) * sp.round_up_to

    # A hand-entry error on a SAR 4 washer goes unnoticed for years; the same error
    # on a SAR 200k mill roll gets caught at the next purchase approval. Scale the
    # error rate down with value so dead money does not become an artefact of
    # fat-fingering the most expensive items in the plant.
    price = params["unit_price_sar"].to_numpy() if "unit_price_sar" in params else None
    if price is None:
        fat_prob = np.full(n, sp.fat_finger_share)
    else:
        damp = np.clip(sp.fat_finger_value_pivot / np.maximum(price, 1.0), 0.05, 1.0)
        fat_prob = sp.fat_finger_share * damp
    fat = rng.random(n) < fat_prob
    bump = rng.choice([sp.fat_finger_factor, 1.0 / sp.fat_finger_factor], size=n)
    min_qty = np.where(fat, min_qty * bump, min_qty)
    max_qty = np.where(fat, max_qty * bump, max_qty)

    min_qty = np.maximum(min_qty, 0.0)
    max_qty = np.maximum(max_qty, min_qty + 1.0)
    return min_qty, max_qty


def commissioning_opening(
    cfg: RunConfig,
    params: pd.DataFrame,
    demand_qty,
    max_qty: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Opening balance per item: normally the policy maximum, plus — for a slice of
    capital spares — a decade-old commissioning package that was never consumed.

    Only lumpy and insurance items are eligible. Those are the spares a
    commissioning package actually covers: the failures that would stop the plant
    and then, mostly, never happened. Consumables are excluded on purpose, because
    a package sized against a fast mover is consumed within a year and leaves no
    trace, while sizing one in "years of demand" produces quantities no storeroom
    has ever held.
    """
    cs = cfg.commissioning
    n = len(params)
    eligible = np.isin(params["profile"].to_numpy(), cs.applies_to)
    carries = eligible & (rng.random(n) < cs.share)
    package = np.round(rng.uniform(*cs.units, size=n))
    return np.where(carries, max_qty + package, max_qty)


def _run_history(
    cfg: RunConfig,
    materials: pd.DataFrame,
    params: pd.DataFrame,
    demand_days,
    demand_qty,
    min_qty: np.ndarray,
    max_qty: np.ndarray,
    opening: np.ndarray | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Walk every item through the stale policy; emit movements and closing stock."""
    n_days = cfg.n_days
    leads = materials["lead_time_days"].to_numpy()
    store = materials["area"].map(STOREROOM_BY_AREA).to_numpy()
    price = materials["unit_price_sar"].to_numpy()
    mid = materials["material_id"].to_numpy()

    iss_day, iss_mat, iss_qty = [], [], []
    rec_day, rec_mat, rec_qty = [], [], []
    on_hand = np.zeros(len(materials))

    for i in range(len(materials)):
        dense = densify(demand_days[i], demand_qty[i], n_days)
        res = walk(
            dense,
            opening=float(max_qty[i] if opening is None else opening[i]),
            reorder_point=float(min_qty[i]),
            order_up_to=float(max_qty[i]),
            lead_time_days=int(leads[i]),
            review_period_days=7,
            n_days=n_days,
        )
        on_hand[i] = res.on_hand_end

        if demand_days[i].size:
            iss_day.append(demand_days[i])
            iss_qty.append(demand_qty[i])
            iss_mat.append(np.full(demand_days[i].size, i))
        if res.receipts_day.size:
            keep = res.receipts_day < n_days
            rec_day.append(res.receipts_day[keep])
            rec_qty.append(res.receipts_qty[keep])
            rec_mat.append(np.full(int(keep.sum()), i))

    def _cat(parts, dtype):
        return np.concatenate(parts).astype(dtype) if parts else np.empty(0, dtype)

    i_day, i_mat, i_qty = _cat(iss_day, np.int64), _cat(iss_mat, np.int64), _cat(iss_qty, float)
    r_day, r_mat, r_qty = _cat(rec_day, np.int64), _cat(rec_mat, np.int64), _cat(rec_qty, float)

    start = pd.Timestamp(cfg.history_start)
    frames = []
    if i_day.size:
        frames.append(
            pd.DataFrame(
                {
                    "date": start + pd.to_timedelta(i_day, "D"),
                    "material_id": mid[i_mat],
                    "storeroom_id": store[i_mat],
                    "movement_type": "ISSUE",
                    "qty": -i_qty,
                    "work_order_id": [f"WO-{d}-{m}" for d, m in zip(i_day, i_mat, strict=True)],
                    "unit_cost_sar": price[i_mat],
                }
            )
        )
    if r_day.size:
        frames.append(
            pd.DataFrame(
                {
                    "date": start + pd.to_timedelta(r_day, "D"),
                    "material_id": mid[r_mat],
                    "storeroom_id": store[r_mat],
                    "movement_type": "RECEIPT",
                    "qty": r_qty,
                    "work_order_id": "",
                    "unit_cost_sar": price[r_mat],
                }
            )
        )

    movements = (
        pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)
        if frames
        else pd.DataFrame(columns=S.MOVEMENTS.names)
    )
    movements.insert(0, "movement_id", np.arange(1, len(movements) + 1, dtype=np.int64))

    last_issue = (
        movements[movements["movement_type"] == "ISSUE"].groupby("material_id")["date"].max()
    )
    last_receipt = (
        movements[movements["movement_type"] == "RECEIPT"].groupby("material_id")["date"].max()
    )

    stock = pd.DataFrame(
        {
            "material_id": mid,
            "storeroom_id": store,
            "on_hand": np.round(on_hand, 2),
            "min_qty": min_qty,
            "max_qty": max_qty,
            "last_issue_date": last_issue.reindex(mid).to_numpy(),
            "last_receipt_date": last_receipt.reindex(mid).to_numpy(),
            "avg_unit_cost_sar": price,
        }
    )
    return movements, stock
