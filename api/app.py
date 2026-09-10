"""
The read-only API behind the dashboard.

Two rules, both load-bearing:

1. **It reads `results/` and nothing else.** No source tables, no answer key, no
   engine calls. Everything was computed during `build`/`run`/`score` and written
   to disk, so a request is a file read. A screen that recomputes can disagree with
   the scoreboard beside it, and on 25,000 positions it stalls while someone is
   watching.

2. **It serves what is there, or says plainly what is missing.** A 404 naming the
   command to run beats an empty screen that looks like a working system with no
   data in it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from contracts import schemas as S
from contracts.config import RunConfig
from engine.positions import POSITIONS_FILE, STOREROOM_FILE
from scoring.summary import SUMMARY_FILE

STATIC = Path(__file__).resolve().parent / "static"

PAGE_SIZE = 25

# Columns the list view needs. The two history arrays are large — 24,887 rows
# carrying 36 + 12 + 12 floats each — so they are served only by the detail
# endpoint, never by the list. Sending them with every page is how a fast screen
# becomes a slow one.
LIST_COLUMNS = [
    "material_id", "storeroom_id", "description", "manufacturer", "mpn", "uom",
    "criticality", "demand_class", "band", "on_hand", "min_qty", "max_qty",
    "reorder_point", "order_up_to", "value_sar", "value_at_risk_sar",
    "units_below_reorder", "forecast_6m", "last_issue_date", "issues_24m", "rank",
    "action", "order_now_qty", "cost_to_level_sar",
]


def _clean(value):
    """JSON has no NaN and no Timestamp; a screen showing `NaN` looks broken."""
    if isinstance(value, float) and (pd.isna(value) or value != value):
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.date().isoformat()
    if hasattr(value, "tolist"):
        return [_clean(v) for v in value.tolist()]
    if value is None or (not isinstance(value, list | dict) and pd.isna(value)):
        return None
    return value


def _records(frame: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in row.items()} for row in frame.to_dict("records")]


def _read(cfg: RunConfig, filename: str, missing_hint: str) -> dict:
    path = cfg.results_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found — run `{missing_hint}`")
    return json.loads(path.read_text(encoding="utf-8"))


def create_app(cfg: RunConfig) -> FastAPI:
    app = FastAPI(
        title="Ma'aden MRO Intelligence",
        description="Read-only view over precomputed results. Nothing is computed per request.",
        version="0.1.0",
    )

    @app.get("/api/summary")
    def summary() -> dict:
        """Headline inventory figures, written during `score`."""
        return _read(cfg, SUMMARY_FILE, f"python cli.py all --preset {cfg.preset}")

    @app.get("/api/scoreboard")
    def scoreboard() -> dict:
        """Defect detection, graded against the sealed answer key."""
        data = _read(cfg, "defect_score.json", f"python cli.py score --preset {cfg.preset}")
        checks_path = cfg.results_dir / S.IMPLEMENTED_CHECKS_FILE
        if checks_path.exists():
            data["declared"] = json.loads(checks_path.read_text(encoding="utf-8"))
        return data

    def _positions() -> pd.DataFrame:
        path = cfg.results_dir / POSITIONS_FILE
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"{POSITIONS_FILE} not found — run "
                       f"`python cli.py run --preset {cfg.preset}`",
            )
        return pd.read_parquet(path)

    @app.get("/api/positions")
    def positions(
        storeroom: str = "", band: str = "", demand_class: str = "",
        action: str = "", q: str = "", page: int = Query(1, ge=1),
    ) -> dict:
        """
        One page of the board, already ranked by what it costs to ignore.

        Every filter narrows a frame that was computed during `run`. Nothing here
        recalculates a level, a forecast or a band.
        """
        df = _positions()
        total_all = len(df)
        if storeroom:
            df = df[df["storeroom_id"] == storeroom]
        if band:
            df = df[df["band"] == band]
        if demand_class:
            df = df[df["demand_class"] == demand_class]
        if action:
            df = df[df["action"] == action]
        if q:
            needle = q.strip().lower()
            hay = (
                df["description"].fillna("") + " " + df["mpn"].fillna("") + " "
                + df["manufacturer"].fillna("") + " " + df["material_id"]
            ).str.lower()
            df = df[hay.str.contains(needle, regex=False)]

        total = len(df)
        pages = max(1, -(-total // PAGE_SIZE))
        start = (page - 1) * PAGE_SIZE
        window = df.iloc[start:start + PAGE_SIZE][LIST_COLUMNS]
        return {
            "page": page,
            "pages": pages,
            "page_size": PAGE_SIZE,
            "total": total,
            "total_unfiltered": total_all,
            "value_at_risk_sar": float(df["value_at_risk_sar"].sum()),
            "value_sar": float(df["value_sar"].sum()),
            "needs_action": int(df["action"].isin(
                ["order_now", "stocked_elsewhere", "below_safe_level"]).sum()),
            "cost_to_level_sar": float(
                df.loc[df["action"].isin(["order_now", "stocked_elsewhere"]),
                       "cost_to_level_sar"].sum()
            ),
            "actions": _positions()["action"].value_counts().to_dict(),
            "storerooms": sorted(_positions()["storeroom_id"].unique().tolist()),
            "bands": _positions()["band"].value_counts().to_dict(),
            "classes": _positions()["demand_class"].value_counts().to_dict(),
            "rows": _records(window),
        }

    @app.get("/api/positions/{material_id}/{storeroom_id}")
    def position(material_id: str, storeroom_id: str) -> dict:
        """Everything the drawer shows, including the two history arrays."""
        df = _positions()
        hit = df[(df["material_id"] == material_id)
                 & (df["storeroom_id"] == storeroom_id)]
        if hit.empty:
            known = df[df["material_id"] == material_id]["storeroom_id"].tolist()
            hint = (
                f"{material_id} is stocked in {', '.join(known)}, not {storeroom_id}"
                if known else
                f"no position {material_id} / {storeroom_id} — ids look like "
                f"{df['material_id'].iloc[0]} / {df['storeroom_id'].iloc[0]}"
            )
            raise HTTPException(status_code=404, detail=hint)
        row = _records(hit)[0]
        elsewhere = df[(df["material_id"] == material_id)
                       & (df["storeroom_id"] != storeroom_id)]
        row["elsewhere"] = _records(
            elsewhere[["storeroom_id", "on_hand", "reorder_point", "band",
                       "value_sar", "issues_24m"]]
        )
        return row

    @app.get("/api/storerooms")
    def storerooms() -> dict:
        return _read(cfg, STOREROOM_FILE, f"python cli.py run --preset {cfg.preset}")

    @app.get("/api/forecast_scores")
    def forecast_scores() -> dict:
        return _read(cfg, "forecast_report.json", f"python cli.py run --preset {cfg.preset}")

    @app.get("/api/backtest")
    def backtest() -> dict:
        return _read(cfg, "backtest_report.json", f"python cli.py score --preset {cfg.preset}")

    @app.get("/api/frontier")
    def frontier() -> dict:
        return _read(cfg, "frontier.json", f"python cli.py score --preset {cfg.preset}")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
