"""
The inventory mechanics: stock falls when issued, a policy decides when to
reorder, the order arrives after a lead time.

Shared deliberately by two callers that must agree exactly:

  * `generator/` runs it forward with the plant's stale min/max policy, producing
    three years of history in which overstock and stockouts EMERGE rather than
    being injected.
  * `scoring/` runs it again over the same demand with the engine's recommended
    policy, to produce the step-5 backtest.

If these two used different mechanics the backtest would be comparing two
different worlds, and any improvement it reported would be an artefact.

`engine/` must never import this module. The engine sees movements and stock, the
same as a real ERP extract would give it — not the rules that produced them.

Vectorised across items: the loop is over days, with numpy operating on all items
at once. The first version looped per item, which cost hours on the full preset
once the service-level sweep multiplied it by twenty.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PolicyResult:
    """
    Outcome of walking N items through one policy.

    Receipts are returned as three parallel arrays rather than per item, because
    the caller assembles them into a ledger and a ragged list of arrays would just
    be concatenated again.
    """

    receipt_item: np.ndarray      # int64 index into the item axis
    receipt_day: np.ndarray       # int32
    receipt_qty: np.ndarray       # float64
    on_hand_end: np.ndarray       # float64 (n,)
    stockout_days: np.ndarray     # int32   (n,)
    units_short: np.ndarray       # float64 (n,)
    avg_on_hand: np.ndarray       # float64 (n,) — capital employed
    n_orders: np.ndarray          # int32   (n,)
    last_receipt_day: np.ndarray  # int32   (n,), -1 if none
    on_hand_by_day: np.ndarray | None = None   # (n, n_days) when requested
    served_by_day: np.ndarray | None = None    # (n, n_days) when requested


def _draw_lead_times(
    mean_days: np.ndarray, cv: float, rng: np.random.Generator | None,
    lo: int, hi: int,
) -> np.ndarray:
    """
    Lead time for one batch of orders.

    Lead-time variance is half of what safety stock exists for. With a fixed lead
    time both the incumbent policy and ours look better than they should, and the
    backtest understates the value of carrying any buffer at all.
    """
    if cv <= 0 or rng is None:
        return np.clip(np.rint(mean_days), lo, hi).astype(np.int64)
    sigma = np.sqrt(np.log1p(cv * cv))
    mu = np.log(np.maximum(mean_days, 1e-6)) - 0.5 * sigma * sigma
    drawn = rng.lognormal(mu, sigma)
    return np.clip(np.rint(drawn), lo, hi).astype(np.int64)


def walk(
    demand: np.ndarray,
    *,
    opening: np.ndarray,
    reorder_point: np.ndarray,
    order_up_to: np.ndarray,
    lead_time: np.ndarray,
    review_period_days: int = 1,
    order_multiple: np.ndarray | None = None,
    order_qty: np.ndarray | None = None,
    lead_time_cv: float = 0.0,
    lead_time_bounds: tuple[int, int] = (1, 720),
    rng: np.random.Generator | None = None,
    lead_time_draws: np.ndarray | None = None,
    return_series: bool = False,
    return_served: bool = False,
) -> PolicyResult:
    """
    Walk N items through one policy. `demand` is (n_items, n_days), dense.

    Unmet demand is BACKORDERED, not lost: in an MRO storeroom the maintenance job
    waits for the part, it does not cancel. That makes `units_short` a measure of
    how long the plant waited, and keeps stockout accounting comparable across the
    two policies.

    Ordering is (R, s, S) by default: every `review_period_days`, if the inventory
    position (on hand + on order - backorders) is at or below `s`, order up to `S`.
    Passing `order_qty` switches to (R, s, Q) — a fixed quantity — so an (s, Q)
    policy from step 5 can be backtested on the same mechanics.

    `lead_time_draws` is an (n_items, max_orders) array of pre-drawn lead times. It
    exists so two policies can be compared in the SAME world: the k-th order for a
    given item waits exactly as long under both, whatever day it happened to be
    placed. Drawing from a shared generator instead would give the two runs
    different lead times as soon as their order timings diverged, and any difference
    in the result would be partly luck rather than policy.
    """
    demand = np.atleast_2d(np.asarray(demand, dtype=np.float64))
    n, n_days = demand.shape

    opening = np.asarray(opening, dtype=np.float64).reshape(n)
    reorder_point = np.asarray(reorder_point, dtype=np.float64).reshape(n)
    order_up_to = np.asarray(order_up_to, dtype=np.float64).reshape(n)
    lead_mean = np.asarray(lead_time, dtype=np.float64).reshape(n)
    review = max(int(review_period_days), 1)
    lo, hi = lead_time_bounds

    # Receipts landing after the horizon are recorded but never arrive, so the
    # pipeline only needs to span the window itself.
    pipeline = np.zeros((n, n_days + 1), dtype=np.float64)

    on_hand = opening.copy()
    on_order = np.zeros(n)                     # running, so no O(n_days^2) sum
    backorder = np.zeros(n)
    stockout_days = np.zeros(n, dtype=np.int32)
    units_short = np.zeros(n)
    on_hand_total = np.zeros(n)
    n_orders = np.zeros(n, dtype=np.int32)
    last_receipt = np.full(n, -1, dtype=np.int32)

    series = np.zeros((n, n_days), dtype=np.float64) if return_series else None
    # What was actually handed over the counter, which is not the same as what was
    # asked for: a backordered job waits, and SAP cannot post an issue against
    # stock that is not there. The ledger must be built from THIS, or the movement
    # history contains issues that never happened and no reconciliation check can
    # ever pass.
    served_out = np.zeros((n, n_days), dtype=np.float64) if return_served else None

    r_item: list[np.ndarray] = []
    r_day: list[np.ndarray] = []
    r_qty: list[np.ndarray] = []

    for day in range(n_days):
        arriving = pipeline[:, day]
        landed = arriving > 0
        if landed.any():
            on_hand += arriving
            on_order -= arriving
            last_receipt[landed] = day

        # backorders clear first — the waiting job gets the part before new demand
        served = np.minimum(backorder, on_hand)
        backorder -= served
        on_hand -= served

        today = demand[:, day]
        met = np.minimum(today, on_hand)
        on_hand -= met
        short = today - met
        backorder += short
        units_short += short

        if served_out is not None:
            served_out[:, day] = served + met

        stockout_days += (backorder > 0).astype(np.int32)

        if day % review == 0:
            position = on_hand + on_order - backorder
            need = position <= reorder_point
            if need.any():
                idx = np.flatnonzero(need)
                if order_qty is None:
                    qty = order_up_to[idx] - position[idx]
                else:
                    qty = np.asarray(order_qty, dtype=np.float64).reshape(n)[idx]
                if order_multiple is not None:
                    mult = np.asarray(order_multiple, dtype=np.float64).reshape(n)[idx]
                    safe = np.where(mult > 0, mult, 1.0)
                    qty = np.ceil(qty / safe) * safe
                place = qty > 0
                idx, qty = idx[place], qty[place]
                if idx.size:
                    if lead_time_draws is not None:
                        slot = np.minimum(n_orders[idx], lead_time_draws.shape[1] - 1)
                        lead = lead_time_draws[idx, slot].astype(np.int64)
                    else:
                        lead = _draw_lead_times(lead_mean[idx], lead_time_cv, rng, lo, hi)
                    arrival = day + lead
                    on_order[idx] += qty
                    n_orders[idx] += 1
                    inside = arrival < n_days
                    if inside.any():
                        np.add.at(pipeline, (idx[inside], arrival[inside]), qty[inside])
                    r_item.append(idx.astype(np.int64))
                    r_day.append(arrival.astype(np.int32))
                    r_qty.append(qty)

        on_hand_total += on_hand
        if series is not None:
            series[:, day] = on_hand

    def _cat(parts, dtype):
        return np.concatenate(parts).astype(dtype) if parts else np.empty(0, dtype)

    return PolicyResult(
        receipt_item=_cat(r_item, np.int64),
        receipt_day=_cat(r_day, np.int32),
        receipt_qty=_cat(r_qty, np.float64),
        on_hand_end=on_hand,
        stockout_days=stockout_days,
        units_short=units_short,
        avg_on_hand=on_hand_total / n_days if n_days else np.zeros(n),
        n_orders=n_orders,
        last_receipt_day=last_receipt,
        on_hand_by_day=series,
        served_by_day=served_out,
    )


def walk_one(demand_by_day: np.ndarray, **kwargs) -> PolicyResult:
    """Single-item convenience wrapper, for tests and for reasoning about one part."""
    scalars = ("opening", "reorder_point", "order_up_to", "lead_time", "order_multiple",
               "order_qty")
    kw = dict(kwargs)
    for name in scalars:
        if kw.get(name) is not None:
            kw[name] = np.asarray([kw[name]], dtype=np.float64)
    return walk(np.asarray(demand_by_day, dtype=np.float64)[None, :], **kw)


def densify(event_days: np.ndarray, event_qty: np.ndarray, n_days: int) -> np.ndarray:
    """Turn sparse (day, qty) demand events into a dense daily vector."""
    out = np.zeros(n_days, dtype=np.float64)
    if event_days.size:
        keep = (event_days >= 0) & (event_days < n_days)
        np.add.at(out, event_days[keep].astype(np.int64), event_qty[keep])
    return out


def densify_many(
    event_days: list[np.ndarray], event_qty: list[np.ndarray], n_days: int
) -> np.ndarray:
    """Dense (n_items, n_days) demand matrix from per-item sparse events."""
    out = np.zeros((len(event_days), n_days), dtype=np.float64)
    for i, (d, q) in enumerate(zip(event_days, event_qty, strict=True)):
        if d.size:
            keep = (d >= 0) & (d < n_days)
            np.add.at(out[i], d[keep].astype(np.int64), q[keep])
    return out
