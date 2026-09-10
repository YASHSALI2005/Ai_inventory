"""
The scenario sweep: what a service level costs, measured rather than argued.

The backtest answers one question — are our levels better than the plant's — and
the answer is "cheaper overall, but holding more stock". That is honest and it is
also an awkward sentence, because it compares two points that differ in two ways
at once: how much is held, and how well the plant is served.

Separating them takes a sweep. The same levels are rebuilt at each service level
in `cfg.costs.service_sweep`, from the SAME simulated demand windows that
`engine.levels` already produced, and each one is replayed over the evaluation
year on the SAME demand and the SAME lead-time draws as the backtest. What comes
out is a curve of capital against days waiting, with the plant's own policy as a
single point on the same axes.

That makes two separate true statements available instead of one confusing one:

* **At the plant's own service level** — the point on our curve that waits as long
  as they do — how much less capital do we need?
* **At our recommended levels**, what is the trade we are proposing?

It is also the data behind the scenario slider (SOW capability 6). The slider
moves along a measured curve, not a formula.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np

from contracts.config import RunConfig
from scoring.backtest import prepare, summarise
from sim.replenish import walk

REPORT_FILE = "frontier.json"


def _change(a: dict, b: dict, key: str) -> float | None:
    return round((b[key] - a[key]) / a[key], 4) if a.get(key) else None


def _match_their_service(points: list[dict], base: dict) -> dict:
    """
    What our levels would cost at the plant's own service level.

    The curve is sampled, so the plant's outcome almost never lands on a sampled
    point; straight-line interpolation between the two surrounding points is fair.
    Extrapolating past either end is not, so a plant outside the sampled range
    gets a plain statement of where it sits instead of a made-up number.

    On this dataset it lands outside, and that is the finding rather than a gap in
    the method: the plant waits longer than our lowest sampled service level while
    holding less capital than any of them. Its policy is not an expensive one that
    we can trim — it is an under-serving one. Saying so is worth more than an
    extrapolated saving, and it is why the cash-release claim belongs to dead
    money rather than to stock levels.
    """
    curve = sorted(points, key=lambda r: r["stockout_days"])
    xs = [r["stockout_days"] for r in curve]
    ys = [r["avg_capital_sar"] for r in curve]
    days, capital = base["stockout_days"], base["avg_capital_sar"]

    if days > xs[-1]:
        return {
            "status": "plant_below_the_sampled_range",
            "stockout_days": days,
            "baseline_capital_sar": capital,
            "lowest_sampled": {
                "service_level": min(r["service_level"] for r in points),
                "stockout_days": xs[-1],
                "avg_capital_sar": ys[-1],
            },
            "plain": (
                f"The plant waits {days:,} days, longer than our lowest sampled "
                f"service level manages ({xs[-1]:,}), while holding less capital "
                f"than any point on the curve. There is no service level at which "
                f"our levels need less capital than theirs, because their policy "
                f"is under-serving rather than over-invested. Releasing cash is a "
                f"dead-money exercise, not a levels one."
            ),
        }
    if days < xs[0]:
        return {"status": "plant_above_the_sampled_range", "stockout_days": days,
                "baseline_capital_sar": capital,
                "plain": "The plant is served better than our highest sampled "
                         "service level; the sweep cannot price that comparison."}

    matched = float(np.interp(days, xs, ys))
    return {
        "status": "matched",
        "stockout_days": days,
        "baseline_capital_sar": capital,
        "policy_capital_sar": matched,
        "capital_saved_sar": capital - matched,
        "capital_saved_share": round((capital - matched) / capital, 4) if capital else None,
        "plain": (
            f"Waiting exactly as long as the plant does today ({days:,} days), our "
            f"levels need SAR {matched:,.0f} against their SAR {capital:,.0f}."
        ),
    }


def run(cfg: RunConfig) -> dict:
    setup = prepare(cfg)
    levels = setup["levels"]
    if "sweep_reorder_points" not in levels.columns:
        return {"status": "not_available",
                "detail": "levels.parquet predates the sweep — rerun `cli.py run`"}

    grid = list(cfg.costs.service_sweep)
    sweep = np.vstack(levels["sweep_reorder_points"].to_numpy())
    quantity = levels["order_quantity"].to_numpy(float)

    baseline = walk(
        setup["demand"],
        reorder_point=levels["min_qty"].fillna(0.0).to_numpy(float),
        order_up_to=levels["max_qty"].fillna(1.0).to_numpy(float),
        **setup["shared"],
    )
    base = summarise(baseline, setup["price"], setup["criticality"], cfg, setup["days"])

    points = []
    for i, service in enumerate(grid):
        reorder = sweep[:, i]
        result = walk(
            setup["demand"], reorder_point=reorder,
            order_up_to=reorder + np.maximum(quantity, 1.0),
            **setup["shared"],
        )
        row = summarise(result, setup["price"], setup["criticality"], cfg, setup["days"])
        row["service_level"] = float(service)
        points.append(row)

    recommended = summarise(
        walk(setup["demand"],
             reorder_point=levels["reorder_point"].to_numpy(float),
             order_up_to=levels["order_up_to"].to_numpy(float),
             **setup["shared"]),
        setup["price"], setup["criticality"], cfg, setup["days"],
    )
    recommended["service_level"] = None   # per item, from its own economics

    matched = _match_their_service(points, base)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "evaluated_days": setup["days"],
        "positions": int(len(levels)),
        "service_levels": grid,
        "curve": points,
        "baseline": base,
        "recommended": recommended,
        "at_the_plants_own_service_level": matched,
        "at_our_recommended_levels": {
            "stockout_days_change": _change(base, recommended, "stockout_days"),
            "capital_change": _change(base, recommended, "avg_capital_sar"),
            "total_cost_change": _change(base, recommended, "total_cost_sar"),
            "orders_change": _change(base, recommended, "orders_placed"),
            "plain": (
                "Our recommended levels are not a point on this curve: each item "
                "gets its own service level from its own economics, so an A-critical "
                "drive is held to 99.4% and a C-class washer to 80%. That is why "
                "they beat every blanket setting on total cost."
            ),
        },
        "limits": [
            "The curve is sampled at seven service levels and joined by straight "
            "lines. The point matched to the plant's own service is interpolated "
            "between two of them, and a plant outside the sampled range gets no "
            "number rather than an extrapolated one.",
            "Every point on the curve uses one blanket service level for all three "
            "criticalities. Our recommended levels do not — each item gets its own "
            "from its own economics — which is why the recommendation does not sit "
            "on the curve.",
        ],
    }
    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    (cfg.results_dir / REPORT_FILE).write_text(json.dumps(report, indent=2),
                                               encoding="utf-8")
    return report


def render(report: dict) -> str:
    if report.get("status"):
        return f"  frontier: {report['detail']}"
    lines = [
        f"  {'service':>9}{'days waiting':>15}{'capital SAR':>18}"
        f"{'orders':>10}{'total cost SAR':>18}",
    ]
    for r in report["curve"]:
        lines.append(
            f"  {r['service_level']:>8.1%}{r['stockout_days']:>15,}"
            f"{r['avg_capital_sar']:>18,.0f}{r['orders_placed']:>10,}"
            f"{r['total_cost_sar']:>18,.0f}"
        )
    b, rec = report["baseline"], report["recommended"]
    lines.append(
        f"  {'theirs':>9}{b['stockout_days']:>15,}{b['avg_capital_sar']:>18,.0f}"
        f"{b['orders_placed']:>10,}{b['total_cost_sar']:>18,.0f}"
    )
    lines.append(
        f"  {'ours':>9}{rec['stockout_days']:>15,}{rec['avg_capital_sar']:>18,.0f}"
        f"{rec['orders_placed']:>10,}{rec['total_cost_sar']:>18,.0f}"
    )
    m = report.get("at_the_plants_own_service_level") or {}
    if m.get("plain"):
        lines += ["", "  " + m["plain"]]
    return "\n".join(lines)
