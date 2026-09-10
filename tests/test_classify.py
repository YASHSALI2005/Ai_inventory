"""
Guards on the demand classifier.

The classifier decides which forecasting method each part gets in step 4, so an
error here does not show up as a wrong class — it shows up as a wrong stock level
on the parts that matter most. These tests pin the two things that decide it and
the one rule that must never bend: it may only look at the training window.
"""

from __future__ import annotations

import pandas as pd
import pytest

from contracts import schemas as S
from contracts.config import RunConfig
from engine import classify as C


def _movements(dates, qty, material="M-1", store="S") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "movement_id": range(1, len(dates) + 1),
            "date": pd.to_datetime(dates),
            "material_id": material,
            "storeroom_id": store,
            "movement_type": "ISSUE",
            "qty": [-q for q in qty],
            "work_order_id": "WO-1",
            "unit_cost_sar": 1.0,
        }
    )


def test_cutoffs_are_the_published_ones():
    """
    These are not tuning knobs. They are where Croston's method stops beating a
    simple average, which is the decision the next step actually makes.
    """
    assert C.ADI_CUTOFF == pytest.approx(1.32)
    assert C.CV2_CUTOFF == pytest.approx(0.49)


def test_a_steady_frequent_part_is_smooth(monkeypatch, tmp_path):
    cfg = _tiny(tmp_path, monkeypatch,
                dates=pd.date_range("2023-09-05", "2025-08-01", freq="7D"),
                qty_fn=lambda n: [10.0] * n)
    out = C.classify(cfg).per_position
    assert out.demand_class.iloc[0] == "smooth"


def test_a_frequent_part_with_wild_quantities_is_erratic(monkeypatch, tmp_path):
    """
    Variation has to be visible at the period the classifier counts in.

    Demand is bucketed by month, so several small and large issues inside one month
    add up to a fairly ordinary monthly total — the variation cancels itself out and
    the part is correctly called steady. That is a real property of choosing a
    monthly bucket, not a defect: what matters to a stock level is how much the
    month-to-month requirement moves, not how it was split across four Tuesdays.
    """
    cfg = _tiny(tmp_path, monkeypatch,
                dates=pd.date_range("2023-09-05", "2025-08-01", freq="ME"),
                qty_fn=lambda n: [1.0 if i % 2 else 60.0 for i in range(n)])
    out = C.classify(cfg).per_position
    assert out.demand_class.iloc[0] == "erratic"
    assert out.cv2.iloc[0] > C.CV2_CUTOFF


def test_a_rare_steady_part_is_intermittent(monkeypatch, tmp_path):
    cfg = _tiny(tmp_path, monkeypatch,
                dates=pd.to_datetime(["2023-11-01", "2024-06-01", "2025-02-01"]),
                qty_fn=lambda n: [2.0] * n)
    out = C.classify(cfg).per_position
    assert out.demand_class.iloc[0] == "intermittent"
    assert out.adi.iloc[0] > C.ADI_CUTOFF


def test_a_rare_part_with_wild_quantities_is_lumpy(monkeypatch, tmp_path):
    cfg = _tiny(tmp_path, monkeypatch,
                dates=pd.to_datetime(["2023-11-01", "2024-06-01", "2025-02-01"]),
                qty_fn=lambda n: [1.0, 40.0, 3.0][:n])
    out = C.classify(cfg).per_position
    assert out.demand_class.iloc[0] == "lumpy"


def test_a_part_that_never_moved_is_not_called_smooth(monkeypatch, tmp_path):
    """
    Zero events means zero variability, and a naive reading of the two numbers puts
    it in the steady quadrant — the one quadrant where step 4 would happily fit a
    series to it. It is the extreme of intermittent instead.
    """
    cfg = _tiny(tmp_path, monkeypatch, dates=pd.DatetimeIndex([]), qty_fn=lambda n: [])
    out = C.classify(cfg).per_position
    assert bool(out.never_moved.iloc[0])
    assert out.demand_class.iloc[0] == "intermittent"


def test_only_the_training_window_is_used(monkeypatch, tmp_path):
    """
    Demand after the cut-off must be invisible. If it leaked in, every later figure
    would be measured on data the model had already seen, and the whole comparison
    would be worthless.
    """
    cfg = _tiny(tmp_path, monkeypatch,
                dates=pd.to_datetime(["2023-11-01", "2024-06-01"]),
                qty_fn=lambda n: [5.0] * n,
                extra_dates=pd.date_range("2025-10-01", "2026-08-01", freq="7D"))
    out = C.classify(cfg).per_position
    # only the two training events count towards how often it moves
    assert out.events.iloc[0] == 2


def test_returns_are_netted_off_consumption(monkeypatch, tmp_path):
    """An issue that came back was not consumption, and counting it over-forecasts."""
    cfg = _tiny(tmp_path, monkeypatch,
                dates=pd.to_datetime(["2024-03-05"]), qty_fn=lambda n: [10.0])
    mov = S.read(S.MOVEMENTS, cfg.source_dir)
    ret = mov.iloc[[0]].copy()
    ret["movement_id"] = 999
    ret["movement_type"] = "RETURN"
    ret["qty"] = 6.0
    ret["date"] = pd.Timestamp("2024-03-20")
    S.write(pd.concat([mov, ret], ignore_index=True), S.MOVEMENTS, cfg.source_dir)

    out = C.classify(cfg).per_position
    assert out.total_qty.iloc[0] == pytest.approx(4.0), "10 issued, 6 returned, 4 used"


def test_report_records_the_mix_and_its_limits(monkeypatch, tmp_path):
    cfg = _tiny(tmp_path, monkeypatch,
                dates=pd.date_range("2023-09-05", "2025-08-01", freq="30D"),
                qty_fn=lambda n: [3.0] * n)
    rep = C.classify(cfg).report
    assert rep["period"] == "week" or rep["period"] == "month"
    assert rep["cutoff_date"] == cfg.cutoff_date.isoformat()
    assert sum(rep["class_mix"].values()) >= 1
    assert rep["limits"], "a step with no stated limits has not been thought about"


# ── fixture plumbing ─────────────────────────────────────────────────────────


def _tiny(tmp_path, monkeypatch, *, dates, qty_fn, extra_dates=None) -> RunConfig:
    """A one-part, one-storeroom dataset written to disk, so classify() can read it."""
    cfg = RunConfig(preset="toy", data_dir=tmp_path)
    cfg.source_dir.mkdir(parents=True, exist_ok=True)

    all_dates = list(dates) + (list(extra_dates) if extra_dates is not None else [])
    qty = qty_fn(len(dates)) + [1.0] * (len(all_dates) - len(dates))
    mov = _movements(all_dates, qty) if all_dates else S.empty(S.MOVEMENTS)

    S.write(mov, S.MOVEMENTS, cfg.source_dir)
    S.write(
        pd.DataFrame(
            {
                "material_id": ["M-1"], "storeroom_id": ["S"], "on_hand": [10.0],
                "min_qty": [1.0], "max_qty": [20.0],
                "last_issue_date": [pd.NaT], "last_receipt_date": [pd.NaT],
                "avg_unit_cost_sar": [100.0],
            }
        ),
        S.STOCK, cfg.source_dir,
    )
    S.write(
        pd.DataFrame(
            {
                "material_id": ["M-1"], "material_group": ["G"], "noun": ["N"],
                "modifier": ["M"], "description": ["N, M, 1"], "manufacturer": ["X"],
                "mpn": ["X-1"], "uom": ["EA"], "unit_price_sar": [100.0],
                "lead_time_days": [30], "area": ["SITEWIDE"], "equipment_id": ["EQ-1"],
                "criticality": ["B"], "is_mro": [True],
            }
        ),
        S.MATERIALS, cfg.source_dir,
    )
    return cfg
