"""
The second headline number: replaying the evaluation year under both sets of stock
levels, and counting what each one cost.

The only claim that matters here is a comparison, so the comparison has to be fair.
Both policies see:

* **the same demand** — the actual issues of the evaluation year, day by day;
* **the same lead times** — pre-drawn per position, so the k-th order waits exactly
  as long under both, whatever day it was placed;
* **the same opening stock** — what was actually on the shelf at the cut-off;
* **the same mechanics** — one `sim.walk`, shared with the generator, so neither
  policy is being simulated in a slightly different world.

Without the pre-drawn lead times the two runs diverge as soon as their order
timings differ, and part of any improvement would be luck. That is the single
easiest way to produce a flattering backtest by accident.

Reported by criticality and by storeroom rather than as one total, because "8%
fewer stockout days" means something quite different if the improvement is all on
C-class washers and the A-class spares got worse.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from contracts import schemas as S
from contracts.config import RunConfig
from engine.levels import REVIEW_PERIOD_DAYS
from sim.replenish import walk

REPORT_FILE = "backtest_report.json"
MAX_ORDERS = 64


def _daily_demand(cfg: RunConfig, movements: pd.DataFrame, positions: pd.DataFrame,
                  days: int) -> np.ndarray:
    """Actual daily demand of the evaluation year, one row per position."""
    evaluate = cfg.eval_slice(movements)
    consumed = evaluate[evaluate["movement_type"].isin(["ISSUE", "RETURN"])].copy()
    index = {
        (m, s): i for i, (m, s) in enumerate(
            zip(positions["material_id"], positions["storeroom_id"], strict=True)
        )
    }
    out = np.zeros((len(positions), days))
    if consumed.empty:
        return out

    start = pd.Timestamp(cfg.cutoff_date) + pd.Timedelta(days=1)
    day = (consumed["date"] - start).dt.days.to_numpy()
    qty = -consumed["qty"].to_numpy()
    rows = np.array([index.get((m, s), -1) for m, s in
                     zip(consumed["material_id"], consumed["storeroom_id"], strict=True)])
    keep = (rows >= 0) & (day >= 0) & (day < days)
    np.add.at(out, (rows[keep], day[keep]), qty[keep])
    return np.maximum(out, 0.0)


def summarise(result, price, criticality, cfg: RunConfig, days: int) -> dict:
    """
    Turn one policy's outcome into money and days.

    Placing an order costs money whatever is on it — raising it, chasing it,
    receiving it, matching the invoice — so `cfg.costs.order_cost_sar` is
    charged per order and lands in the total. Without it a policy that orders
    every week looks free, and the buying team pays for a number that never
    appeared in the comparison.
    """
    shortage_rate = np.array(
        [cfg.costs.shortage_cost_per_unit_day(p, c)
         for p, c in zip(price, criticality, strict=True)]
    )
    holding_rate = np.array([cfg.costs.holding_cost_per_unit_day(p) for p in price])
    return {
        "stockout_days": int(result.stockout_days.sum()),
        "positions_with_a_stockout": int((result.stockout_days > 0).sum()),
        "units_short": float(result.units_short.sum()),
        "avg_capital_sar": float((result.avg_on_hand * price).sum()),
        "holding_cost_sar": float((result.avg_on_hand * holding_rate * days).sum()),
        "shortage_cost_sar": float((result.units_short * shortage_rate).sum()),
        "orders_placed": int(result.n_orders.sum()),
        # The number a decision actually turns on. Service and capital pull against
        # each other, so either one on its own can be made to look good by
        # sacrificing the other; only their sum says whether the plant is better off.
        "ordering_cost_sar": float(cfg.costs.ordering_cost(result.n_orders.sum())),
        "total_cost_sar": float(
            (result.avg_on_hand * holding_rate * days).sum()
            + (result.units_short * shortage_rate).sum()
            + cfg.costs.ordering_cost(result.n_orders.sum())
        ),
    }


def _breakdown(result_a, result_b, keys, price, criticality, cfg, days, label) -> list:
    """Both policies, split by whatever `keys` names."""
    frame = pd.DataFrame(
        {
            label: keys,
            "price": price,
            "criticality": criticality,
            "base_stockout_days": result_a.stockout_days,
            "base_units_short": result_a.units_short,
            "base_capital": result_a.avg_on_hand * price,
            "ours_stockout_days": result_b.stockout_days,
            "ours_units_short": result_b.units_short,
            "ours_capital": result_b.avg_on_hand * price,
        }
    )
    rows = []
    for value, grp in frame.groupby(label):
        rows.append(
            {
                label: value,
                "positions": int(len(grp)),
                "baseline_stockout_days": int(grp.base_stockout_days.sum()),
                "policy_stockout_days": int(grp.ours_stockout_days.sum()),
                "baseline_units_short": float(grp.base_units_short.sum()),
                "policy_units_short": float(grp.ours_units_short.sum()),
                "baseline_capital_sar": float(grp.base_capital.sum()),
                "policy_capital_sar": float(grp.ours_capital.sum()),
            }
        )
    return sorted(rows, key=lambda r: -r["baseline_capital_sar"])


def prepare(cfg: RunConfig) -> dict:
    """
    Everything both policies must share, built once.

    The scenario sweep replays the same year at seven more service levels, and it
    has to do so in exactly this world — same demand, same opening stock, same
    lead-time draws — or its curve is not comparable to the backtest that sits
    beside it in the report.
    """
    movements = S.read(S.MOVEMENTS, cfg.source_dir)
    materials = S.read(S.MATERIALS, cfg.source_dir)
    stock = S.read(S.STOCK, cfg.source_dir)
    levels = pd.read_parquet(cfg.results_dir / "levels.parquet")

    days = (cfg.history_end - cfg.cutoff_date).days
    positions = levels[["material_id", "storeroom_id"]].copy()

    info = materials.set_index("material_id")
    price = info["unit_price_sar"].reindex(positions["material_id"]).to_numpy(float)
    lead = info["lead_time_days"].reindex(positions["material_id"]).to_numpy(float)
    criticality = info["criticality"].reindex(positions["material_id"]).to_numpy()

    opening = (
        stock.set_index(["material_id", "storeroom_id"])["on_hand"]
        .reindex(pd.MultiIndex.from_arrays(
            [positions["material_id"], positions["storeroom_id"]]))
        .fillna(0.0).clip(lower=0.0).to_numpy()
    )
    demand = _daily_demand(cfg, movements, positions, days)

    # ONE set of lead times, used by every policy. See the module docstring.
    rng = np.random.default_rng(cfg.seed + 77)
    sigma = np.sqrt(np.log1p(cfg.lead_time.cv ** 2))
    mu = np.log(np.maximum(lead, 1e-6)) - 0.5 * sigma ** 2
    draws = np.clip(
        np.rint(rng.lognormal(mu[:, None], sigma, size=(len(positions), MAX_ORDERS))),
        cfg.lead_time.min_days, cfg.lead_time.max_days,
    ).astype(np.int64)

    return {
        "levels": levels,
        "positions": positions,
        "price": price,
        "lead": lead,
        "criticality": criticality,
        "demand": demand,
        "days": days,
        "shared": dict(opening=opening, lead_time=lead,
                       review_period_days=REVIEW_PERIOD_DAYS, lead_time_draws=draws),
    }


def run(cfg: RunConfig) -> dict:
    setup = prepare(cfg)
    levels, positions = setup["levels"], setup["positions"]
    price, criticality = setup["price"], setup["criticality"]
    demand, days, shared = setup["demand"], setup["days"], setup["shared"]

    baseline = walk(
        demand,
        reorder_point=levels["min_qty"].fillna(0.0).to_numpy(float),
        order_up_to=levels["max_qty"].fillna(1.0).to_numpy(float),
        **shared,
    )
    ours = walk(
        demand,
        reorder_point=levels["reorder_point"].to_numpy(float),
        order_up_to=levels["order_up_to"].to_numpy(float),
        **shared,
    )

    base = summarise(baseline, price, criticality, cfg, days)
    new = summarise(ours, price, criticality, cfg, days)

    def change(key: str) -> float | None:
        if not base[key]:
            return None
        return round((new[key] - base[key]) / base[key], 4)

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "evaluated_days": int(days),
        "evaluated_from": (cfg.cutoff_date + pd.Timedelta(days=1)).isoformat(),
        "positions": int(len(positions)),
        "baseline": base,
        "policy": new,
        "change": {k: change(k) for k in
                   ("stockout_days", "units_short", "avg_capital_sar",
                    "shortage_cost_sar", "holding_cost_sar", "orders_placed",
                    "ordering_cost_sar", "total_cost_sar")},
        "positions_raised": int((ours.avg_on_hand > baseline.avg_on_hand * 1.05).sum()),
        "positions_lowered": int((ours.avg_on_hand < baseline.avg_on_hand * 0.95).sum()),
        "capital_moved_out_sar": float(
            np.maximum(baseline.avg_on_hand - ours.avg_on_hand, 0.0) @ price
        ),
        "capital_moved_in_sar": float(
            np.maximum(ours.avg_on_hand - baseline.avg_on_hand, 0.0) @ price
        ),
        "baseline_stockout_days": base["stockout_days"],
        "policy_stockout_days": new["stockout_days"],
        "baseline_capital_sar": base["avg_capital_sar"],
        "policy_capital_sar": new["avg_capital_sar"],
        "by_criticality": _breakdown(baseline, ours, criticality, price, criticality,
                                     cfg, days, "criticality"),
        "by_storeroom": _breakdown(baseline, ours, positions["storeroom_id"].to_numpy(),
                                   price, criticality, cfg, days, "storeroom_id"),
        "limits": [
            "Both policies are replayed against the demand that actually happened, "
            "which no forecast could have known in full. That is the point — it is "
            "the same test for both, and the question is which set of levels copes "
            "better with a year neither of them saw.",
            "Lead times are drawn once and shared, so the same order waits the same "
            "time under both. Without that, part of any difference would be luck.",
            "Unmet demand is treated as waiting, not lost: an MRO job waits for the "
            "part rather than cancelling. Days short therefore measures how long the "
            "plant waited.",
            "Placing an order costs SAR " + f"{cfg.costs.order_cost_sar:,.0f}" +
            " whatever is on it, and that is in the total. The figure is an "
            "assumption, not a measurement — on real data it comes from the "
            "purchasing team.",
            "Order quantities respect the pack the plant is already receiving in, "
            "read off its own receipt history. There is no pack-size column to "
            "read, so this is inference, and a purchasing extract would beat it.",
        ],
    }

    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    (cfg.results_dir / REPORT_FILE).write_text(json.dumps(report, indent=2),
                                               encoding="utf-8")
    return report


def render(report: dict) -> str:
    b, p, c = report["baseline"], report["policy"], report["change"]

    def line(label, key, fmt="{:,.0f}"):
        delta = c.get(key)
        arrow = "" if delta is None else f"  {delta:+.0%}"
        return (f"  {label:<26}{fmt.format(b[key]):>16}{fmt.format(p[key]):>16}{arrow:>9}")

    lines = [
        f"  replayed {report['evaluated_days']} days from {report['evaluated_from']} "
        f"over {report['positions']:,} positions",
        "",
        f"  {'':<26}{'their levels':>16}{'ours':>16}{'change':>9}",
        line("days waiting for a part", "stockout_days"),
        line("units short", "units_short"),
        line("capital on the shelf SAR", "avg_capital_sar"),
        line("cost of being short SAR", "shortage_cost_sar"),
        line("cost of holding SAR", "holding_cost_sar"),
        line("TOTAL COST SAR", "total_cost_sar"),
        line("orders placed", "orders_placed"),
        "",
        f"  capital moved off shelves where it did nothing: "
        f"SAR {report['capital_moved_out_sar']:,.0f} "
        f"({report['positions_lowered']:,} positions)",
        f"  capital moved onto shelves where it prevents downtime: "
        f"SAR {report['capital_moved_in_sar']:,.0f} "
        f"({report['positions_raised']:,} positions)",
        "",
        f"  {'by criticality':<14}{'their days':>12}{'our days':>10}"
        f"{'their SAR':>14}{'our SAR':>14}",
    ]
    for row in sorted(report["by_criticality"], key=lambda r: r["criticality"]):
        lines.append(
            f"  {row['criticality']:<14}{row['baseline_stockout_days']:>12,}"
            f"{row['policy_stockout_days']:>10,}"
            f"{row['baseline_capital_sar']:>14,.0f}{row['policy_capital_sar']:>14,.0f}"
        )
    return "\n".join(lines)
