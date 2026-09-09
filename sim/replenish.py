"""
The inventory mechanics: stock falls when issued, a policy decides when to reorder,
the order arrives after a lead time.

Shared deliberately by two callers that must agree exactly:

  * `generator/` runs it forward with the plant's stale min/max policy, to produce
    three years of history in which overstock and stockouts EMERGE rather than
    being injected.
  * `scoring/` runs it again over the same demand with the engine's recommended
    policy, to produce the step-5 backtest.

If these two used different mechanics the backtest would be comparing two
different worlds, and any improvement it reported would be an artefact.

`engine/` must never import this module. The engine sees movements and stock, the
same as a real ERP extract would give it — not the rules that produced them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PolicyResult:
    """Outcome of walking one item's demand through one policy."""

    receipts_day: np.ndarray      # int32, day index the receipt lands
    receipts_qty: np.ndarray      # float64
    on_hand_end: float            # closing position at the end of the window
    stockout_days: int            # days with zero stock while demand was waiting
    units_short: float            # total demand that could not be met on time
    avg_on_hand: float            # mean daily position, for capital-employed
    n_orders: int


def walk(
    demand_by_day: np.ndarray,
    *,
    opening: float,
    reorder_point: float,
    order_up_to: float,
    lead_time_days: int,
    review_period_days: int = 1,
    n_days: int | None = None,
) -> PolicyResult:
    """
    Walk one item through one policy.

    `demand_by_day` is a dense daily demand vector for the window. It is dense on
    purpose: the vector is cheap (a few thousand float64 per item) and it keeps the
    mechanics obvious, whereas an event-sparse walk needs careful handling of
    orders landing between events.

    Unmet demand is treated as BACKORDERED, not lost: in an MRO storeroom the
    maintenance job waits for the part, it does not cancel. That makes
    `units_short` a measure of how long the plant waited, which is what we care
    about, and keeps stockout accounting honest across both policies.

    Ordering is (R, s, S): every `review_period_days`, if the inventory position
    (on hand + on order - backorders) is at or below `s`, order up to `S`.
    """
    n = int(n_days if n_days is not None else demand_by_day.size)
    if demand_by_day.size < n:
        demand_by_day = np.pad(demand_by_day, (0, n - demand_by_day.size))

    lead = max(int(lead_time_days), 0)
    review = max(int(review_period_days), 1)

    # Receipts land on a future day; a flat array indexed by day is enough because
    # the horizon is known up front.
    pipeline = np.zeros(n + lead + 1, dtype=np.float64)

    on_hand = float(opening)
    backorder = 0.0
    stockout_days = 0
    units_short = 0.0
    on_hand_total = 0.0
    receipt_days: list[int] = []
    receipt_qtys: list[float] = []

    for day in range(n):
        on_hand += pipeline[day]

        # clear backorders first — the waiting job gets the part before new demand
        if backorder > 0.0 and on_hand > 0.0:
            served = min(backorder, on_hand)
            backorder -= served
            on_hand -= served

        demand = float(demand_by_day[day])
        if demand > 0.0:
            served = min(demand, on_hand)
            on_hand -= served
            shortfall = demand - served
            if shortfall > 0.0:
                backorder += shortfall
                units_short += shortfall

        if backorder > 0.0:
            stockout_days += 1

        if day % review == 0:
            on_order = float(pipeline[day + 1 :].sum())
            position = on_hand + on_order - backorder
            if position <= reorder_point:
                qty = order_up_to - position
                if qty > 0.0:
                    arrival = day + lead
                    if arrival < pipeline.size:
                        pipeline[arrival] += qty
                    receipt_days.append(arrival)
                    receipt_qtys.append(qty)

        on_hand_total += on_hand

    return PolicyResult(
        receipts_day=np.asarray(receipt_days, dtype=np.int32),
        receipts_qty=np.asarray(receipt_qtys, dtype=np.float64),
        on_hand_end=on_hand,
        stockout_days=stockout_days,
        units_short=units_short,
        avg_on_hand=on_hand_total / n if n else 0.0,
        n_orders=len(receipt_days),
    )


def densify(event_days: np.ndarray, event_qty: np.ndarray, n_days: int) -> np.ndarray:
    """Turn sparse (day, qty) demand events into a dense daily vector."""
    out = np.zeros(n_days, dtype=np.float64)
    if event_days.size:
        keep = (event_days >= 0) & (event_days < n_days)
        np.add.at(out, event_days[keep].astype(np.int64), event_qty[keep])
    return out
