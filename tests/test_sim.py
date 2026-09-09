"""
Guards on the replenishment mechanics.

`sim` is shared by the generator and the backtest. If the two ran on different
mechanics the backtest would compare two different worlds and any improvement it
reported would be an artefact — so these tests pin conservation, ordering and
determinism rather than any particular policy outcome.
"""

from __future__ import annotations

import numpy as np
import pytest

from sim.replenish import densify, densify_many, walk, walk_one


def test_stock_is_conserved():
    """opening + receipts - served = closing, exactly."""
    demand = densify(np.array([2, 9, 15, 30]), np.array([5.0, 3.0, 8.0, 2.0]), 60)
    r = walk_one(
        demand, opening=20.0, reorder_point=5.0, order_up_to=25.0, lead_time=7,
        return_served=True,
    )
    received = float(r.receipt_qty[r.receipt_day < 60].sum())
    served = float(r.served_by_day.sum())
    assert r.on_hand_end[0] == pytest.approx(20.0 + received - served, abs=1e-6)


def test_served_never_exceeds_demand_or_stock():
    demand = densify(np.array([0, 1, 2]), np.array([100.0, 100.0, 100.0]), 20)
    r = walk_one(
        demand, opening=10.0, reorder_point=0.0, order_up_to=10.0, lead_time=90,
        return_served=True,
    )
    # only the opening 10 can ever be handed over, the rest is backordered
    assert float(r.served_by_day.sum()) == pytest.approx(10.0)
    assert r.units_short[0] == pytest.approx(290.0)


def test_backorders_clear_before_new_demand():
    """A waiting job gets the part before a fresh request does."""
    demand = np.zeros(40)
    demand[0] = 10.0        # backordered: nothing on hand
    demand[20] = 1.0        # fresh demand after the receipt lands
    r = walk_one(
        demand, opening=0.0, reorder_point=5.0, order_up_to=10.0, lead_time=5,
        return_served=True,
    )
    first_service = np.flatnonzero(r.served_by_day[0])[0]
    assert first_service < 20, "the backorder was not served before later demand"


def test_stochastic_lead_time_is_seeded_and_deterministic():
    demand = densify(np.arange(0, 200, 10), np.full(20, 4.0), 220)
    kw = dict(opening=5.0, reorder_point=4.0, order_up_to=20.0, lead_time=30,
              lead_time_cv=0.4)
    a = walk_one(demand, rng=np.random.default_rng(7), **kw)
    b = walk_one(demand, rng=np.random.default_rng(7), **kw)
    c = walk_one(demand, rng=np.random.default_rng(8), **kw)
    assert np.array_equal(a.receipt_day, b.receipt_day)
    assert not np.array_equal(a.receipt_day, c.receipt_day), "cv had no effect"


def test_fixed_lead_time_when_cv_is_zero():
    """Demand on day 0 triggers the order that day, so it lands exactly on day 14."""
    demand = densify(np.array([0]), np.array([50.0]), 60)
    r = walk_one(demand, opening=5.0, reorder_point=4.0, order_up_to=20.0, lead_time=14,
                 lead_time_cv=0.0)
    assert r.receipt_day.size
    assert int(r.receipt_day[0]) == 14


def test_order_multiple_rounds_up():
    demand = densify(np.array([5]), np.array([12.0]), 40)
    r = walk_one(demand, opening=10.0, reorder_point=8.0, order_up_to=23.0, lead_time=3,
                 order_multiple=10.0)
    assert r.receipt_qty.size
    assert np.allclose(r.receipt_qty % 10.0, 0.0), r.receipt_qty


def test_fixed_order_quantity_policy():
    """order_qty switches (s,S) to (s,Q) so an (s,Q) policy can be backtested."""
    demand = densify(np.arange(0, 100, 5), np.full(20, 3.0), 120)
    r = walk_one(demand, opening=10.0, reorder_point=6.0, order_up_to=99.0, lead_time=5,
                 order_qty=25.0)
    assert r.receipt_qty.size
    assert np.allclose(r.receipt_qty, 25.0)


def test_multi_item_walk_matches_item_by_item():
    """The vectorised path must agree with the single-item path exactly."""
    rng = np.random.default_rng(3)
    n, days = 6, 180
    events = [np.sort(rng.choice(days, size=rng.integers(2, 20), replace=False)) for _ in range(n)]
    sizes = [rng.integers(1, 9, size=e.size).astype(float) for e in events]
    dense = densify_many(events, sizes, days)

    opening = rng.uniform(2, 30, n)
    rop = rng.uniform(1, 10, n)
    up_to = rop + rng.uniform(5, 40, n)
    lead = rng.integers(3, 40, n).astype(float)

    together = walk(dense, opening=opening, reorder_point=rop, order_up_to=up_to,
                    lead_time=lead, review_period_days=7)
    for i in range(n):
        alone = walk_one(dense[i], opening=opening[i], reorder_point=rop[i],
                         order_up_to=up_to[i], lead_time=lead[i], review_period_days=7)
        assert alone.on_hand_end[0] == pytest.approx(together.on_hand_end[i])
        assert alone.stockout_days[0] == together.stockout_days[i]
        assert alone.units_short[0] == pytest.approx(together.units_short[i])
        assert alone.n_orders[0] == together.n_orders[i]


def test_no_order_when_position_is_healthy():
    r = walk_one(np.zeros(50), opening=100.0, reorder_point=10.0, order_up_to=120.0,
                 lead_time=5)
    assert r.n_orders[0] == 0
    assert r.on_hand_end[0] == pytest.approx(100.0)
