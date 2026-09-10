"""
Outage demand: what a shutdown draws from the storeroom, and when the next one is.

A planned outage is the most predictable demand in the plant and the buffer was
treating it as the least: one rolling-mill filter draws about 900 a month and
5,000-6,000 in each outage, and its reorder point was sized to absorb the outage
as if it might happen any week. This module separates the two. Anything issued to
a plant while that plant is in a scheduled shutdown — whatever the work order
says — or on a work order tagged to a shutdown, is outage demand. It leaves the
buffer distribution and comes back as scheduled demand, dated to the next outage
in the calendar, sized at what this position drew per outage in the past.

Used by `engine.levels` (to exclude it) and `engine.forecast` (to schedule it), so
the two cannot disagree about what an outage is.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def outage_mask(moves: pd.DataFrame, materials: pd.DataFrame,
                work_orders: pd.DataFrame, shutdowns: pd.DataFrame) -> np.ndarray:
    """True for every movement that belongs to a shutdown."""
    if moves.empty or shutdowns.empty:
        return np.zeros(len(moves), dtype=bool)
    area = moves["material_id"].map(materials.set_index("material_id")["area"]).to_numpy()
    tagged = moves["work_order_id"].map(
        work_orders.set_index("work_order_id")["shutdown_id"]
    ).fillna("").ne("").to_numpy()
    dates = moves["date"].to_numpy()
    in_window = np.zeros(len(moves), dtype=bool)
    for sd in shutdowns.itertuples():
        in_window |= (area == sd.plant) & (dates >= sd.start_date) & (dates <= sd.end_date)
    return in_window | tagged


def windows_per_area(shutdowns: pd.DataFrame, start, end) -> dict[str, int]:
    """How many outages each plant had between two dates."""
    s = shutdowns[(shutdowns["start_date"] >= pd.Timestamp(start))
                  & (shutdowns["start_date"] <= pd.Timestamp(end))]
    return s.groupby("plant").size().to_dict()


def draw_per_event(moves: pd.DataFrame, materials: pd.DataFrame,
                   work_orders: pd.DataFrame, shutdowns: pd.DataFrame,
                   start, end) -> pd.Series:
    """
    Units a position draws in one outage, on average, over the window given.

    Indexed by (material_id, storeroom_id). Zero for a position never issued during
    an outage, and for any area that had no outage in the window.
    """
    issued = moves[moves["movement_type"].isin(["ISSUE", "RETURN"])]
    m = outage_mask(issued, materials, work_orders, shutdowns)
    outage = issued[m]
    if outage.empty:
        return pd.Series(dtype=float)
    total = (-outage["qty"]).clip(lower=0).groupby(
        [outage["material_id"], outage["storeroom_id"]]
    ).sum()
    counts = windows_per_area(shutdowns, start, end)
    area = materials.set_index("material_id")["area"]
    n_events = total.index.get_level_values(0).map(area).map(counts).fillna(0).to_numpy()
    per_event = np.where(n_events > 0, total.to_numpy() / np.maximum(n_events, 1), 0.0)
    return pd.Series(per_event, index=total.index, name="shutdown_qty_per_event")


def next_shutdown(shutdowns: pd.DataFrame, after, known_by=None) -> pd.Series:
    """
    The next outage per plant after a date — only those already in the calendar by
    `known_by`, because a system cannot schedule demand for an outage nobody has
    announced yet. Indexed by plant; NaT where none is planned.
    """
    s = shutdowns[shutdowns["start_date"] > pd.Timestamp(after)]
    if known_by is not None:
        s = s[s["scheduled_on"] <= pd.Timestamp(known_by)]
    return s.sort_values("start_date").groupby("plant")["start_date"].first()
