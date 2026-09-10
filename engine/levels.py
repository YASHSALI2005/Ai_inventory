"""
Step 5 — how much to hold, and when to reorder (SOW capability 3).

The number that decides whether the part is on the shelf at 02:40.

**Not** `z · σ · √LT`. That formula assumes demand follows a bell curve, which is
reasonable for a gasket used every week and quietly wrong for a spare that moves
twice a decade — and the second group is where being wrong is most expensive. It
also needs a mean and a standard deviation, and for a part with four events in two
years neither of those means very much.

Instead the demand over the protection window is built up from what the part
actually does, using the two things TSB already separates:

* **p** — how often a period contains any demand at all
* **the sizes** — how much, when it does move

A protection window of k periods is then simulated many times: in each period,
demand occurs with probability p, and if it does, a size is drawn from that part's
own history. The reorder point is the quantile of that distribution at the item's
service level. No bell curve is assumed anywhere, so a part that moves in lumps of
forty is handled as a part that moves in lumps of forty.

Three things then override or bound the result:

* **Service level per item** from `cfg.costs.critical_fractile` — its own cost of
  being short against its own cost of holding, rather than one blanket 95%.
* **A criticality floor** from `cfg.dead_money.criticality_floor`, so a spare that
  has never once been issued is still stocked when losing it stops the plant. This
  is a business rule and it deliberately overrules the arithmetic.
* **A plain-English reason on every position.** A number a planner cannot question
  is a number they will not act on.

**The data-quality checks feed this step.** A lead time the checks flagged as
impossible is not used to size stock: a part whose record says 3,650 days would
otherwise be given a ten-year protection window, and on one B-critical item that
produced a reorder point of 35,826 units against a plant figure of 318. The
substitute is the typical lead time for that part's material group, and the reason
string says plainly that it was used. That is the difference between a data-quality
report and a data-quality check — the second one changes the answer.

Fitted on the training window only. `engine/` never sees the answer key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from contracts import schemas as S
from contracts.config import RunConfig
from engine.classify import PERIOD

LEVELS_FILE = "levels.parquet"
REPORT_FILE = "levels_report.json"

DAYS_PER_PERIOD = 30.0
REVIEW_PERIOD_DAYS = 7
N_SIMULATIONS = 600

# TSB's smoothing constant for the demand probability. The same value the
# forecaster uses, because this has to describe the same part.
ALPHA_P = 0.2


@dataclass(frozen=True)
class Levels:
    per_position: pd.DataFrame
    report: dict


def _demand_probability(occurred: np.ndarray, alpha: float = ALPHA_P) -> float:
    """
    TSB's estimate of how often a period contains demand.

    Exponentially smoothed over EVERY period, including the empty ones — which is
    the whole point, and what separates TSB from Croston. On a series that is mostly
    zeros, the zeros carry most of the information about how likely the next one is.
    """
    if not len(occurred):
        return 0.0
    p = float(occurred[0])
    for value in occurred[1:]:
        p += alpha * (float(value) - p)
    return float(np.clip(p, 0.0, 1.0))


def _protection_quantile(
    p: float, sizes: np.ndarray, periods: float, service: float,
    rng: np.random.Generator, n_sim: int = N_SIMULATIONS,
) -> float:
    """
    The empirical quantile of demand over the protection window.

    Compounding a Bernoulli occurrence with a bootstrap of the part's own demand
    sizes, rather than fitting a distribution to it. For a part whose history is
    "nothing, nothing, forty, nothing", that history IS the distribution and any
    smooth curve laid over it would be an invention.
    """
    if p <= 0 or not len(sizes) or periods <= 0:
        return 0.0
    whole = int(np.floor(periods))
    part = periods - whole

    draws = np.zeros(n_sim)
    if whole > 0:
        hits = rng.random((n_sim, whole)) < p
        picks = sizes[rng.integers(0, len(sizes), size=(n_sim, whole))]
        draws += (hits * picks).sum(axis=1)
    if part > 0:
        hits = rng.random(n_sim) < p * part
        picks = sizes[rng.integers(0, len(sizes), size=n_sim)]
        draws += hits * picks
    return float(np.quantile(draws, service))


def usable_lead_times(materials: pd.DataFrame, findings: pd.DataFrame) -> pd.Series:
    """
    Lead time per material, with the unusable ones replaced.

    A lead time of zero gives a protection window of one review cycle and a reorder
    point near nothing on a part that may take a year to arrive. A lead time of ten
    years gives the opposite. Both are already reported by the checks, so both are
    substituted here rather than being quietly believed.
    """
    lead = materials.set_index("material_id")["lead_time_days"].astype(float)
    bad = set(
        findings.loc[findings["defect_type"] == "IMPOSSIBLE_LEAD_TIME", "material_id"]
    )
    if not bad:
        return lead

    healthy = materials[~materials["material_id"].isin(bad)]
    by_group = healthy.groupby("material_group")["lead_time_days"].median()
    overall = float(healthy["lead_time_days"].median()) if len(healthy) else 60.0

    group_of = materials.set_index("material_id")["material_group"]
    for material in bad:
        replacement = by_group.get(group_of.get(material), overall)
        lead.loc[material] = float(replacement if pd.notna(replacement) else overall)
    return lead


def _reason(level: float, service: float, window_days: float, criticality: str,
            lead_days: int, never_moved: bool, floored: bool, uom: str,
            lead_substituted: bool = False) -> str:
    """One sentence a planner can argue with."""
    lead_text = (
        f"{lead_days / 30:.0f}-month lead time" if lead_days >= 60
        else f"{lead_days}-day lead time"
    )
    if never_moved:
        base = (
            f"Never issued in two years, so there is no usage to size against. "
            f"Holding {level:,.0f} {uom} because it is {criticality}-critical"
        )
    else:
        base = (
            f"Holding {level:,.0f} {uom} covers {service:.0%} of past "
            f"{window_days:,.0f}-day stretches; {criticality}-critical"
        )
    out = f"{base}, {lead_text}."
    if lead_substituted:
        out += (
            " The delivery time on the record was not usable, so the typical figure "
            "for this kind of part was used instead."
        )
    if floored and not never_moved:
        out += " Raised to the minimum this criticality requires."
    return out


def compute(cfg: RunConfig) -> Levels:
    movements = S.read(S.MOVEMENTS, cfg.source_dir)
    materials = S.read(S.MATERIALS, cfg.source_dir)
    stock = S.read(S.STOCK, cfg.source_dir)
    classes = pd.read_parquet(cfg.results_dir / "classification.parquet")

    findings_path = cfg.results_dir / "findings.parquet"
    findings = (
        S.read(S.FINDINGS, cfg.results_dir) if findings_path.exists() else S.empty(S.FINDINGS)
    )
    lead_by_material = usable_lead_times(materials, findings)
    substituted = set(
        findings.loc[findings["defect_type"] == "IMPOSSIBLE_LEAD_TIME", "material_id"]
    )

    train = cfg.train_slice(movements)
    consumed = train[train["movement_type"].isin(["ISSUE", "RETURN"])].copy()
    consumed["demand"] = -consumed["qty"]
    consumed["period"] = consumed["date"].dt.to_period(PERIOD)
    periods = (
        consumed.groupby(["material_id", "storeroom_id", "period"], observed=True)["demand"]
        .sum()
        .clip(lower=0)
    )
    all_periods = pd.period_range(cfg.history_start, cfg.cutoff_date, freq=PERIOD)
    n_periods = len(all_periods)

    by_position: dict[tuple[str, str], np.ndarray] = {}
    for (mat, store), grp in periods.groupby(level=[0, 1], observed=True):
        series = grp.droplevel([0, 1]).reindex(all_periods, fill_value=0.0)
        by_position[(mat, store)] = series.to_numpy(dtype=float)

    mat_idx = materials.set_index("material_id")
    rng = np.random.default_rng(cfg.seed + 5)

    rows = []
    for pos in classes.itertuples():
        key = (pos.material_id, pos.storeroom_id)
        series = by_position.get(key, np.zeros(n_periods))
        sizes = series[series > 0]

        info = mat_idx.loc[pos.material_id]
        price = float(info["unit_price_sar"])
        criticality = str(info["criticality"])
        uom = str(info["uom"]) or "EA"
        lead_days = int(lead_by_material.get(pos.material_id, info["lead_time_days"]))
        lead_fixed = pos.material_id in substituted

        service = cfg.costs.critical_fractile(price, criticality)
        window_days = lead_days + REVIEW_PERIOD_DAYS
        window_periods = window_days / DAYS_PER_PERIOD

        p = _demand_probability((series > 0).astype(float))
        reorder = _protection_quantile(p, sizes, window_periods, service, rng)

        floor = cfg.dead_money.criticality_floor.get(criticality, 0.0)
        floored = reorder < floor
        reorder = max(reorder, floor)

        # order-up-to covers the protection window plus one review cycle of demand
        cycle = _protection_quantile(
            p, sizes, REVIEW_PERIOD_DAYS / DAYS_PER_PERIOD, service, rng
        )
        order_up_to = reorder + max(cycle, 1.0 if reorder > 0 else 0.0)

        rows.append(
            {
                "material_id": pos.material_id,
                "storeroom_id": pos.storeroom_id,
                "criticality": criticality,
                "demand_class": pos.demand_class,
                "service_level": service,
                "demand_probability": p,
                "protection_days": float(window_days),
                "reorder_point": float(np.ceil(reorder)),
                "order_up_to": float(np.ceil(order_up_to)),
                "unit_price_sar": price,
                "lead_time_days": int(lead_days),
                "lead_time_substituted": bool(lead_fixed),
                "reason": _reason(np.ceil(reorder), service, window_days, criticality,
                                  lead_days, bool(pos.never_moved), floored, uom,
                                  lead_fixed),
            }
        )

    levels = pd.DataFrame(rows)
    current = stock[["material_id", "storeroom_id", "min_qty", "max_qty", "on_hand"]]
    levels = levels.merge(current, on=["material_id", "storeroom_id"], how="left")

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "positions": int(len(levels)),
        "review_period_days": REVIEW_PERIOD_DAYS,
        "simulations_per_position": N_SIMULATIONS,
        "service_level_by_criticality": {
            k: round(cfg.costs.critical_fractile(1000.0, k), 4) for k in S.CRITICALITY
        },
        "median_reorder_point": float(levels["reorder_point"].median()),
        "median_current_min": float(levels["min_qty"].median()),
        "positions_raised_by_criticality_floor": int(
            (levels["reorder_point"] > 0).sum()
            - (levels["demand_probability"] > 0).sum()
        ),
        "positions_with_lead_time_substituted": int(levels["lead_time_substituted"].sum()),
        "limits": [
            "Levels are set from the first two years only, so a part whose use "
            "changed in the last year is sized on how it used to behave. That is the "
            "same handicap the system would have on the day it goes live.",
            "The size of a future demand is drawn from that part's own past demands. "
            "A part that has only ever been issued in ones cannot be sized for a "
            "sudden requirement of ten.",
            "A part never issued in two years is held at the minimum its criticality "
            "requires, not at a calculated level — there is nothing to calculate "
            "from, and the alternative is holding none of it.",
            "Where the delivery time on the record was flagged as impossible, the "
            "typical figure for that kind of part is used instead and the reason says "
            "so. The substitute is a guess: it is better than a ten-year protection "
            "window, and it is not as good as somebody checking the contract.",
        ],
    }
    return Levels(per_position=levels, report=report)


def run(cfg: RunConfig) -> Levels:
    result = compute(cfg)
    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    result.per_position.to_parquet(cfg.results_dir / LEVELS_FILE, index=False)
    (cfg.results_dir / REPORT_FILE).write_text(
        json.dumps(result.report, indent=2), encoding="utf-8"
    )
    return result
