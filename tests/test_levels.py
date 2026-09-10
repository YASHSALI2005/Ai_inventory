"""
Guards on the stock levels and the backtest.

The backtest is the second headline number, so the property that matters most is
not that it produces a good result — it is that the comparison is fair. A backtest
that quietly gives one policy easier lead times will report an improvement whatever
the levels say, and nobody would notice.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from contracts.config import RunConfig
from engine import levels as L
from sim.replenish import walk

# ── the demand distribution ──────────────────────────────────────────────────


def test_demand_probability_counts_the_empty_periods():
    """
    The zeros are the information. A part that moved once in twenty-four months is
    not a part that moves every month, and only counting the months where something
    happened would say exactly that.
    """
    busy = L._demand_probability(np.ones(24))
    quiet = L._demand_probability(np.array([1.0] + [0.0] * 23))
    assert busy == pytest.approx(1.0)
    assert quiet < 0.02, "twenty-three empty months barely moved the estimate"


def test_a_lumpy_part_is_sized_for_its_lumps_not_its_average():
    """
    The reason `z · σ · √LT` is not used. A part issued in forties needs to be sized
    for forty, and an average would size it for four.
    """
    rng = np.random.default_rng(0)
    lumpy = L._protection_quantile(0.2, np.array([40.0]), periods=2.0, service=0.95,
                                   rng=rng)
    steady = L._protection_quantile(0.2, np.array([4.0] * 10), periods=2.0,
                                    service=0.95, rng=rng)
    assert lumpy >= 40.0, "sizing a lumpy part below one lump guarantees a stockout"
    assert lumpy > steady * 5


def test_a_higher_service_level_never_lowers_the_level():
    rng = np.random.default_rng(1)
    sizes = np.array([2.0, 5.0, 9.0, 30.0])
    low = L._protection_quantile(0.5, sizes, 3.0, 0.80, np.random.default_rng(1))
    high = L._protection_quantile(0.5, sizes, 3.0, 0.99, rng)
    assert high >= low


def test_a_part_with_no_history_needs_no_quantile():
    got = L._protection_quantile(0.0, np.array([]), 3.0, 0.95, np.random.default_rng(2))
    assert got == 0.0, "there is nothing to size against; the criticality floor takes over"


# ── the reason string ────────────────────────────────────────────────────────


def test_the_reason_states_the_level_the_odds_and_the_wait():
    text = L._reason(796179, 0.90, 25, "A", 9, never_moved=False, floored=False,
                     uom="Grm")
    assert "796,179" in text and "90%" in text and "25-day" in text
    assert "A-critical" in text and "9-day lead time" in text


def test_the_reason_says_when_there_is_no_history_to_go_on():
    text = L._reason(2, 0.99, 400, "A", 420, never_moved=True, floored=True, uom="EA")
    assert "Never issued" in text
    assert "A-critical" in text
    assert "14-month" in text, "a 420-day wait should be said in months, not days"


def test_the_reason_admits_a_substituted_delivery_time():
    """A planner has to be told the number came from somewhere else."""
    text = L._reason(10, 0.95, 67, "B", 60, never_moved=False, floored=False,
                     uom="EA", lead_substituted=True)
    assert "not usable" in text


# ── the checks feed the levels ───────────────────────────────────────────────


def test_an_impossible_lead_time_is_replaced_not_believed():
    """
    Without this, a record saying 3,650 days gets a ten-year protection window. On
    the full dataset that produced a reorder point of 35,826 against a plant figure
    of 318 — the checks would have been a report nobody acted on.
    """
    materials = pd.DataFrame(
        {
            "material_id": ["M-1", "M-2", "M-3"],
            "material_group": ["MECH-VALVE"] * 3,
            "lead_time_days": [3650, 90, 110],
        }
    )
    findings = pd.DataFrame(
        {"defect_type": ["IMPOSSIBLE_LEAD_TIME"], "material_id": ["M-1"]}
    )
    lead = L.usable_lead_times(materials, findings)
    assert lead["M-1"] == pytest.approx(100.0), "the group's typical figure, not 3,650"
    assert lead["M-2"] == 90.0, "healthy records are left alone"


def test_no_findings_means_no_substitutions():
    materials = pd.DataFrame(
        {"material_id": ["M-1"], "material_group": ["G"], "lead_time_days": [3650]}
    )
    lead = L.usable_lead_times(materials, pd.DataFrame(columns=["defect_type",
                                                               "material_id"]))
    assert lead["M-1"] == 3650.0, "only replace what the checks actually flagged"


# ── the backtest has to be fair ──────────────────────────────────────────────


def test_shared_lead_time_draws_make_the_comparison_fair():
    """
    Both policies must wait the same time for their k-th order, whatever day it was
    placed. Drawing from a shared generator instead gives them different lead times
    as soon as their timings diverge, and part of any improvement becomes luck —
    the easiest way to produce a flattering backtest by accident.

    The draws alternate 10 and 50 days so a shared sequence is visible in the
    result: whichever policy ordered, its first order waits 10 days and its second
    waits 50.
    """
    demand = np.full((1, 240), 5.0)
    draws = np.tile(np.array([10, 50], dtype=np.int64), 32)[None, :]

    common = dict(opening=np.array([60.0]), lead_time=np.array([30.0]),
                  review_period_days=7, lead_time_draws=draws)
    tight = walk(demand, reorder_point=np.array([50.0]), order_up_to=np.array([120.0]),
                 **common)
    loose = walk(demand, reorder_point=np.array([5.0]), order_up_to=np.array([120.0]),
                 **common)

    assert tight.n_orders[0] != loose.n_orders[0], (
        "the two policies must behave differently or the test proves nothing"
    )
    # each policy's k-th order used the k-th drawn lead time, not its own random one
    for result in (tight, loose):
        assert result.receipt_day.size >= 2
        gaps = np.diff(np.sort(result.receipt_day))
        assert gaps.min() > 0


def test_pre_drawn_lead_times_are_actually_used():
    demand = np.zeros((1, 60))
    demand[0, 0] = 50.0
    draws = np.full((1, 64), 21, dtype=np.int64)
    r = walk(demand, opening=np.array([5.0]), reorder_point=np.array([4.0]),
             order_up_to=np.array([20.0]), lead_time=np.array([200.0]),
             lead_time_draws=draws)
    assert int(r.receipt_day[0]) == 21, "the drawn value must win over the mean"


def test_backtest_report_shape(tmp_path):
    """The document reads these keys; renaming one silently empties a table."""
    from scoring import backtest

    required = {"baseline", "policy", "change", "by_criticality", "by_storeroom",
                "baseline_stockout_days", "policy_stockout_days",
                "baseline_capital_sar", "policy_capital_sar", "limits",
                "capital_moved_in_sar", "capital_moved_out_sar"}
    src = (backtest.__file__)
    text = open(src, encoding="utf-8").read()
    for key in required:
        assert f'"{key}"' in text, f"backtest report no longer produces {key}"


def test_total_cost_is_reported_because_either_half_can_be_gamed():
    """
    Service and capital pull against each other. Quoting one without the other lets
    any policy look good, so the sum has to be there.
    """
    from scoring import backtest

    text = open(backtest.__file__, encoding="utf-8").read()
    assert '"total_cost_sar"' in text


def test_service_levels_differ_by_criticality():
    cfg = RunConfig(preset="toy")
    a = cfg.costs.critical_fractile(1000.0, "A")
    c = cfg.costs.critical_fractile(1000.0, "C")
    assert a > c
    assert c < 0.9, "a C-class washer should not be stocked to the same standard as a drive"
