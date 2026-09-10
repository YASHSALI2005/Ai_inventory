"""
Step 3 — sorting every part by how it is actually used (SOW capability 1, part one).

Two numbers decide it, and they are the standard pair for spare parts:

* **ADI** — average demand interval, the mean gap in periods between one demand and
  the next. How *often* a part moves.
* **CV²** — the squared coefficient of variation of the demand size. How much the
  quantity *jumps about* when it does move.

Syntetos and Boylan's cutoffs (ADI = 1.32 periods, CV² = 0.49) split those two axes
into four quadrants: smooth, erratic, intermittent, lumpy. The cutoffs are not
arbitrary — they are where Croston's method stops beating a simple average — which
is exactly the decision the next step has to make.

Why this exists at all: a storeroom holds two populations. Gaskets move every week
and can be forecast from their own history; a spare mill drive moves twice a decade
and cannot. One method applied to both produces confident, well-formatted, wrong
numbers on the items where being wrong is most expensive. Sorting first is what
lets step 4 route each part to a method that suits it.

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

# Syntetos-Boylan cutoffs, in review periods.
ADI_CUTOFF = 1.32
CV2_CUTOFF = 0.49

# A period is a MONTH, which is how these cutoffs are normally applied — the
# original work is framed around monthly review. It also matters here for a
# concrete reason, measured rather than assumed: on weekly buckets an ADI cutoff of
# 1.32 falls at 9.2 days, and a fast-moving consumable used every eight to ten days
# sits directly on it. Only 17% of genuinely fast-moving parts were then sorted as
# fast-moving. On monthly buckets that rises to 80% and overall agreement from 89%
# to 91%.
#
# The cost is the other direction: 24 monthly buckets over the training window give
# a noisier estimate of size variability than 104 weekly ones. For the rarely-moving
# majority that makes little difference, because those parts have a handful of
# events either way.
PERIOD = "M"

REPORT_FILE = "classifier_report.json"


@dataclass(frozen=True)
class Classified:
    per_position: pd.DataFrame
    per_material: pd.DataFrame
    report: dict


def _demand_periods(movements: pd.DataFrame, cfg: RunConfig) -> pd.DataFrame:
    """
    Demand per position per period, over the training window only.

    Returns and adjustments are netted off: an issue that came back the same month
    was not consumption, and a system that counts it as consumption over-forecasts
    every part that is ever returned.
    """
    train = cfg.train_slice(movements)
    consumed = train[train["movement_type"].isin(["ISSUE", "RETURN"])].copy()
    if consumed.empty:
        return pd.DataFrame(columns=["material_id", "storeroom_id", "period", "qty"])

    # issues are negative, returns positive; net demand is the negation
    consumed["demand"] = -consumed["qty"]
    consumed["period"] = consumed["date"].dt.to_period(PERIOD)
    grouped = (
        consumed.groupby(["material_id", "storeroom_id", "period"], observed=True)["demand"]
        .sum()
        .reset_index()
    )
    return grouped[grouped["demand"] > 0]


def classify(cfg: RunConfig) -> Classified:
    movements = S.read(S.MOVEMENTS, cfg.source_dir)
    stock = S.read(S.STOCK, cfg.source_dir)
    materials = S.read(S.MATERIALS, cfg.source_dir)

    demand = _demand_periods(movements, cfg)
    n_periods = max(
        len(pd.period_range(cfg.history_start, cfg.cutoff_date, freq=PERIOD)), 1
    )

    if demand.empty:
        stats = pd.DataFrame(columns=["material_id", "storeroom_id", "events",
                                      "total_qty", "mean_qty", "sd_qty"])
    else:
        stats = (
            demand.groupby(["material_id", "storeroom_id"], observed=True)["demand"]
            .agg(events="size", total_qty="sum", mean_qty="mean",
                 sd_qty=lambda x: x.std(ddof=0))
            .reset_index()
        )

    # every stocked position is classified, including the ones that never moved
    positions = stock[["material_id", "storeroom_id"]].drop_duplicates()
    out = positions.merge(stats, on=["material_id", "storeroom_id"], how="left")
    # Cast explicitly. A position that never moved leaves these columns as objects
    # after the merge, and `np.where` evaluates BOTH branches — so the division by a
    # zero mean is performed in Python and raises, rather than being masked out.
    for col in ("events", "total_qty", "mean_qty", "sd_qty"):
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0).astype("float64")

    events = out["events"].to_numpy()
    mean_qty = out["mean_qty"].to_numpy()
    sd_qty = out["sd_qty"].to_numpy()

    adi = np.divide(
        float(n_periods), np.maximum(events, 1.0),
        out=np.full(len(out), np.inf), where=events > 0,
    )
    cv = np.divide(sd_qty, mean_qty, out=np.zeros(len(out)), where=mean_qty > 0)
    cv2 = cv ** 2

    out["adi"] = adi
    out["cv2"] = cv2
    out["demand_class"] = np.select(
        [
            events == 0,
            (adi < ADI_CUTOFF) & (cv2 < CV2_CUTOFF),
            (adi < ADI_CUTOFF) & (cv2 >= CV2_CUTOFF),
            (adi >= ADI_CUTOFF) & (cv2 < CV2_CUTOFF),
        ],
        ["intermittent", "smooth", "erratic", "intermittent"],
        default="lumpy",
    )
    # A position with no demand at all in two years is not "smooth"; it is the
    # extreme of intermittent, and step 4 must not try to fit a series to it.
    out["never_moved"] = events == 0

    crit = materials.set_index("material_id")["criticality"]
    out["criticality"] = crit.reindex(out["material_id"]).to_numpy()

    per_material = _roll_up_to_material(out)
    report = _build_report(cfg, out, per_material, n_periods)
    return Classified(per_position=out, per_material=per_material, report=report)


def _roll_up_to_material(per_position: pd.DataFrame) -> pd.DataFrame:
    """
    One class per material, taken from the position that moves it most often.

    A part stocked centrally and at the smelter can look intermittent in one place
    and smooth in the other. Step 5 sets levels per position and uses the position
    row; this roll-up exists for reporting and for the item screen, where a planner
    wants one answer about the part rather than three.
    """
    order = per_position.sort_values("adi")
    first = order.groupby("material_id", as_index=False).first()
    totals = (
        per_position.groupby("material_id", as_index=False)
        .agg(positions=("storeroom_id", "size"), total_qty=("total_qty", "sum"),
             events=("events", "sum"))
    )
    return first[["material_id", "demand_class", "adi", "cv2", "criticality",
                  "never_moved"]].merge(totals, on="material_id")


def _build_report(cfg, per_position, per_material, n_periods) -> dict:
    mix = per_material["demand_class"].value_counts().to_dict()

    by_store = []
    for store, grp in per_position.groupby("storeroom_id"):
        counts = grp["demand_class"].value_counts().to_dict()
        by_store.append({"storeroom_id": store, "total": int(len(grp)),
                         **{k: int(counts.get(k, 0)) for k in S.DEMAND_CLASS}})

    by_crit = []
    for crit, grp in per_position.groupby("criticality"):
        counts = grp["demand_class"].value_counts().to_dict()
        by_crit.append({"criticality": crit, "total": int(len(grp)),
                        **{k: int(counts.get(k, 0)) for k in S.DEMAND_CLASS}})

    slow = sum(mix.get(k, 0) for k in ("intermittent", "lumpy"))
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "period": "week",
        "train_periods": int(n_periods),
        "cutoff_date": cfg.cutoff_date.isoformat(),
        "adi_cutoff": ADI_CUTOFF,
        "cv2_cutoff": CV2_CUTOFF,
        "class_mix": {k: int(v) for k, v in mix.items()},
        "slow_share": slow / max(len(per_material), 1),
        "never_moved": int(per_material["never_moved"].sum()),
        "by_storeroom": sorted(by_store, key=lambda r: -r["total"]),
        "by_criticality": sorted(by_crit, key=lambda r: r["criticality"]),
        "limits": [
            "Every part is sorted using only the first two years of history, so a "
            "part whose use changed recently is sorted on how it used to behave. "
            "That is deliberate — it is the same handicap the system will have on "
            "the day it goes live.",
            "A part that never moved in two years is put in the rarest group. There "
            "is nothing in its history to sort it by, so the next step handles it "
            "from the failure rate of the machine it protects instead.",
            "Demand is counted by month. On a daily count almost every day is a "
            "zero and the standard cutoffs stop meaning anything; on a weekly count "
            "the boundary falls at nine days and lands directly on top of the "
            "fastest-moving parts.",
        ],
    }


def run(cfg: RunConfig) -> Classified:
    result = classify(cfg)
    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    result.per_position.to_parquet(cfg.results_dir / "classification.parquet", index=False)
    (cfg.results_dir / REPORT_FILE).write_text(
        json.dumps(result.report, indent=2), encoding="utf-8"
    )
    return result
