"""
One row per position, everything a screen needs, computed once.

The screens are read-only views over this file. That is a design constraint, not
a convenience: a page that recalculates will disagree with the scoreboard printed
beside it, and on 25,000 positions it will stall while somebody is watching. So
every number a screen shows — the usage history, the forecast, the level, the
reason, the band, the ranking — is written here at the end of `run` and served as
a file read.

The band is one value per position, not a set of flags, and the order it is
decided in IS the priority a planner would use:

    stocked out  >  below our reorder point  >  below the plant's old minimum
                 >  never issued  >  idle for 24 months  >  well stocked

An insurance spare that has never been issued and sits below its criticality
floor reads as `below_reorder`, not as `never_issued`, because the first is the
thing to act on. Losing "never issued" as a label there is the right trade.

Ranking is by what it costs to ignore — the shortage cost of the units missing
below the reorder point — and never by quantity. That is the one line carried
over from the previous project's board, and it is the line that changes how the
screen is read.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from contracts import schemas as S
from contracts.config import RunConfig
from engine.classify import PERIOD

POSITIONS_FILE = "positions.parquet"
STOREROOM_FILE = "storeroom_report.json"

IDLE_MONTHS = 24


def _monthly_matrix(movements: pd.DataFrame, months: pd.PeriodIndex) -> pd.DataFrame:
    """Units issued per position per month, over the whole history."""
    used = movements[movements["movement_type"].isin(["ISSUE", "RETURN"])].copy()
    used["demand"] = -used["qty"]
    used["period"] = used["date"].dt.to_period(PERIOD)
    grid = (
        used.groupby(["material_id", "storeroom_id", "period"], observed=True)["demand"]
        .sum()
        .clip(lower=0)
        .unstack("period")
        .reindex(columns=months, fill_value=0.0)
        .fillna(0.0)
    )
    return grid


def _band(on_hand: np.ndarray, reorder: np.ndarray, min_qty: np.ndarray,
          never: np.ndarray, idle: np.ndarray) -> np.ndarray:
    band = np.full(len(on_hand), "well_stocked", dtype=object)
    band[idle] = "idle_24m"
    band[never] = "never_issued"
    band[on_hand < min_qty] = "below_old_min"
    band[on_hand < reorder] = "below_reorder"
    band[on_hand <= 0] = "stocked_out"
    return band


def build(cfg: RunConfig) -> pd.DataFrame:
    materials = S.read(S.MATERIALS, cfg.source_dir)
    stock = S.read(S.STOCK, cfg.source_dir)
    movements = S.read(S.MOVEMENTS, cfg.source_dir)
    levels = pd.read_parquet(cfg.results_dir / "levels.parquet")
    classes = pd.read_parquet(cfg.results_dir / "classification.parquet")
    forecast = pd.read_parquet(cfg.results_dir / "forecast.parquet")

    months = pd.period_range(cfg.history_start, cfg.history_end, freq=PERIOD)
    train_months = int(len(pd.period_range(cfg.history_start, cfg.cutoff_date, freq=PERIOD)))
    grid = _monthly_matrix(movements, months)

    df = levels.merge(
        classes[["material_id", "storeroom_id", "adi", "cv2", "events", "never_moved"]],
        on=["material_id", "storeroom_id"], how="left",
    )
    df = df.merge(
        materials[["material_id", "description", "manufacturer", "mpn", "uom",
                   "material_group", "area"]],
        on="material_id", how="left",
    )
    df = df.merge(
        stock[["material_id", "storeroom_id", "avg_unit_cost_sar", "last_issue_date",
               "last_receipt_date"]],
        on=["material_id", "storeroom_id"], how="left",
    )

    # usage history, aligned to the position order, as one list per row
    idx = pd.MultiIndex.from_frame(df[["material_id", "storeroom_id"]])
    usage = grid.reindex(idx, fill_value=0.0).to_numpy(dtype=float)
    df["usage_months"] = list(usage)
    df["months_start"] = str(months[0])
    df["train_months"] = train_months

    recent = usage[:, -IDLE_MONTHS:]
    df["issues_24m"] = (recent > 0).sum(axis=1)
    df["qty_24m"] = recent.sum(axis=1)

    # forecast and known work-order demand, in month order, per position
    fc = forecast.sort_values("ds")
    piv = fc.pivot_table(index=["material_id", "storeroom_id"], columns="ds",
                         values="forecast", aggfunc="sum")
    known = fc.pivot_table(index=["material_id", "storeroom_id"], columns="ds",
                           values="known_qty", aggfunc="sum")
    method = fc.groupby(["material_id", "storeroom_id"])["method"].first()

    horizon = piv.shape[1]
    df["forecast_months"] = list(
        piv.reindex(idx).to_numpy(dtype=float) if horizon else np.zeros((len(df), 0))
    )
    df["planned_wo_months"] = list(known.reindex(idx).to_numpy(dtype=float))
    df["forecast_months"] = [np.nan_to_num(a) for a in df["forecast_months"]]
    df["planned_wo_months"] = [np.nan_to_num(a) for a in df["planned_wo_months"]]
    df["forecast_method"] = method.reindex(idx).to_numpy()
    df["forecast_6m"] = [float(a[:6].sum()) for a in df["forecast_months"]]
    df["planned_wo_qty"] = [float(a.sum()) for a in df["planned_wo_months"]]

    df["value_sar"] = df["on_hand"].clip(lower=0) * df["avg_unit_cost_sar"].fillna(0.0)

    last_issue = pd.to_datetime(df["last_issue_date"])
    cutoff = pd.Timestamp(cfg.history_end) - pd.DateOffset(months=IDLE_MONTHS)
    never = df["never_moved"].fillna(True).to_numpy(dtype=bool) | last_issue.isna().to_numpy()
    idle = (last_issue < cutoff).to_numpy() & ~never

    df["band"] = _band(
        df["on_hand"].to_numpy(dtype=float),
        df["reorder_point"].to_numpy(dtype=float),
        df["min_qty"].fillna(0.0).to_numpy(dtype=float),
        never, idle,
    )

    # what it costs to ignore: the shortage cost of the units we are missing.
    # Same `shortage_cost_per_unit` the service level and the backtest use — three
    # different versions of this number is how a demo contradicts itself on stage.
    # on_hand is clamped at zero first: a planted negative balance of -29 against a
    # reorder point of 5 is not "34 units short", it is 5 units short plus a data
    # defect, and without the clamp those rows take over the top of the board.
    short_units = (df["reorder_point"] - df["on_hand"].clip(lower=0.0)).clip(lower=0.0)
    weight = df.apply(
        lambda r: cfg.costs.shortage_cost_per_unit(float(r["unit_price_sar"]),
                                                   str(r["criticality"])),
        axis=1,
    )
    df["units_below_reorder"] = short_units
    df["value_at_risk_sar"] = short_units * weight

    # what to bring it back up to, in money — the figure a planner can take to a
    # buyer. Not the same as what being short of it costs, which is much larger and
    # much less useful as an instruction.
    df["cost_to_level_sar"] = (
        (df["order_up_to"] - df["on_hand"].clip(lower=0.0)).clip(lower=0.0)
        * df["unit_price_sar"]
    )
    df["order_now_qty"] = (
        (df["order_up_to"] - df["on_hand"].clip(lower=0.0)).clip(lower=0.0).round()
    )

    df = df.sort_values(["value_at_risk_sar", "value_sar"], ascending=False)
    df["rank"] = np.arange(1, len(df) + 1)
    df = df.reset_index(drop=True)
    df["action"] = _actions(df)
    return df


def _actions(df: pd.DataFrame) -> np.ndarray:
    """
    One instruction per row, in the order a planner would take them.

    A board that says what is wrong is a report; a board that says what to do is a
    tool. "Stocked elsewhere" comes before "Order" on purpose — a transfer is free
    and a purchase is not, and a planner who orders a part that is already sitting
    in the next storeroom has been let down by the screen.
    """
    short = df["on_hand"].clip(lower=0.0) < df["reorder_point"]
    surplus = (df["on_hand"] - df["order_up_to"]).clip(lower=0.0)
    surplus_elsewhere = (
        df.assign(_s=surplus).groupby("material_id")["_s"].transform("sum") - surplus
    ) > 0
    idle = df["band"].isin(["idle_24m", "never_issued"]) & (df["value_sar"] > 0)
    below_old = df["on_hand"] < df["min_qty"].fillna(0.0)

    out = np.full(len(df), "nothing_needed", dtype=object)
    out[idle.to_numpy()] = "review_obsolete"
    out[below_old.to_numpy()] = "below_safe_level"
    out[short.to_numpy()] = "order_now"
    out[(short & surplus_elsewhere).to_numpy()] = "stocked_elsewhere"
    return out


def transfers(df: pd.DataFrame, limit: int = 60) -> list[dict]:
    """
    One storeroom is long while another is short of the same part.

    SOW capability 5, and the cheapest recommendation in the whole system: it frees
    stock that is already paid for and avoids a purchase entirely. Deliberately
    conservative — the sending storeroom only offers what it holds ABOVE its own
    order-up-to level, so nobody is stripped to fix somebody else.
    """
    df = df.copy()
    df["surplus"] = (df["on_hand"] - df["order_up_to"]).clip(lower=0.0)
    df["need"] = np.where(
        df["on_hand"].clip(lower=0.0) < df["reorder_point"],
        (df["order_up_to"] - df["on_hand"].clip(lower=0.0)).clip(lower=0.0),
        0.0,
    )
    rows = []
    both = df[df["material_id"].isin(
        set(df.loc[df["surplus"] > 0, "material_id"])
        & set(df.loc[df["need"] > 0, "material_id"])
    )]
    for material, grp in both.groupby("material_id"):
        givers = grp[grp["surplus"] > 0].sort_values("surplus", ascending=False)
        takers = grp[grp["need"] > 0].sort_values("need", ascending=False)
        pool = givers["surplus"].to_numpy(dtype=float).copy()
        for _, taker in takers.iterrows():
            want = float(taker["need"])
            for i, (_, giver) in enumerate(givers.iterrows()):
                if want <= 0 or pool[i] <= 0:
                    continue
                move = float(min(pool[i], want))
                pool[i] -= move
                want -= move
                rows.append(
                    {
                        "material_id": str(material),
                        "description": str(taker["description"]),
                        "from_storeroom": str(giver["storeroom_id"]),
                        "to_storeroom": str(taker["storeroom_id"]),
                        "qty": round(move, 2),
                        "uom": str(taker["uom"]),
                        "value_sar": float(move * taker["unit_price_sar"]),
                        "criticality": str(taker["criticality"]),
                        "to_on_hand": float(taker["on_hand"]),
                        "to_reorder_point": float(taker["reorder_point"]),
                    }
                )
    rows.sort(key=lambda r: -r["value_sar"])
    return rows[:limit]


def by_storeroom(df: pd.DataFrame) -> list[dict]:
    """The overview's storeroom table, rolled up once rather than per request."""
    out = []
    for store, grp in df.groupby("storeroom_id", observed=True):
        out.append(
            {
                "storeroom_id": str(store),
                "positions": int(len(grp)),
                "value_sar": float(grp["value_sar"].sum()),
                "value_at_risk_sar": float(grp["value_at_risk_sar"].sum()),
                "idle_count": int(grp["band"].isin(["idle_24m", "never_issued"]).sum()),
                "stocked_out": int((grp["band"] == "stocked_out").sum()),
                "needs_action": int(grp["action"].isin(
                    ["order_now", "stocked_elsewhere", "below_safe_level"]).sum()),
                "cost_to_level_sar": float(
                    grp.loc[grp["action"].isin(["order_now", "stocked_elsewhere"]),
                            "cost_to_level_sar"].sum()
                ),
                "class_mix": {k: int(v) for k, v in
                              grp["demand_class"].value_counts().items()},
            }
        )
    return sorted(out, key=lambda r: -r["value_sar"])


def run(cfg: RunConfig) -> pd.DataFrame:
    df = build(cfg)
    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cfg.results_dir / POSITIONS_FILE, index=False)
    moves = transfers(df)
    critical = df[(df["criticality"] == "A")
                  & (df["on_hand"].clip(lower=0.0) < df["reorder_point"])]
    payload = {
        "by_storeroom": by_storeroom(df),
        "transfers": moves,
        "transfer_total_sar": float(sum(r["value_sar"] for r in moves)),
        "transfer_count": len(moves),
        "action_counts": {k: int(v) for k, v in df["action"].value_counts().items()},
        "needs_action_count": int((df["action"].isin(
            ["order_now", "stocked_elsewhere", "below_safe_level"])).sum()),
        "cost_to_level_sar": float(
            df.loc[df["action"].isin(["order_now", "stocked_elsewhere"]),
                   "cost_to_level_sar"].sum()
        ),
        "critical_below_level_count": int(len(critical)),
        "critical_below_level_sar": float(critical["cost_to_level_sar"].sum()),
    }
    (cfg.results_dir / STOREROOM_FILE).write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return df
