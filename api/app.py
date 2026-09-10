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
from fastapi.responses import FileResponse, PlainTextResponse
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
    "action", "order_now_qty", "cost_to_level_sar", "usage_12m", "order_cost_sar",
    "runs_out_date", "order_by_date",
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
        # Only the columns this position file actually has. A file written by an
        # older engine is missing the newest ones, and a KeyError here turned the
        # whole board into an error page instead of a board with a blank column.
        have = [c for c in LIST_COLUMNS if c in df.columns]
        window = df.iloc[start:start + PAGE_SIZE][have]
        return {
            "today": cfg.history_end.isoformat(),
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
        row["today"] = cfg.history_end.isoformat()
        elsewhere = df[(df["material_id"] == material_id)
                       & (df["storeroom_id"] != storeroom_id)]
        row["elsewhere"] = _records(
            elsewhere[["storeroom_id", "on_hand", "reorder_point", "band",
                       "value_sar", "issues_24m"]]
        )
        return row

    ORDER_COLUMNS = ["material_id", "storeroom_id", "description", "criticality",
                     "order_now_qty", "uom", "order_by_date", "order_cost_sar",
                     "cost_to_level_sar", "on_hand", "reorder_point", "reason"]

    def _orders() -> pd.DataFrame:
        df = _positions()
        if "order_cost_sar" not in df.columns:
            raise HTTPException(
                status_code=409,
                detail=f"{POSITIONS_FILE} predates the recommendations — run "
                       f"`python cli.py run --preset {cfg.preset}`",
            )
        orders = df[df["action"] == "order_now"].sort_values("order_cost_sar",
                                                             ascending=False)
        return orders[[c for c in ORDER_COLUMNS if c in orders.columns]]

    @app.get("/api/recommendations")
    def recommendations(limit: int = Query(60, ge=1, le=500)) -> dict:
        """
        The three lists a planner acts on, each ranked by money. Orders come from
        the position file, moves from the storeroom report; write-offs arrive with
        the dead-money step and say so until then.
        """
        orders = _orders()
        stores = _read(cfg, STOREROOM_FILE, f"python cli.py run --preset {cfg.preset}")
        moves = stores.get("transfers", [])
        return {
            "today": cfg.history_end.isoformat(),
            "orders": {
                "count": int(len(orders)),
                "total_sar": float(orders["order_cost_sar"].sum()),
                "rows": _records(orders.head(limit)),
            },
            "moves": {
                "count": int(len(moves)),
                "total_sar": float(sum(r["value_sar"] for r in moves)),
                "rows": moves[:limit],
            },
            "writeoff": _writeoff(limit),
        }

    def _writeoff(limit: int) -> dict:
        path = cfg.results_dir / "dead_money.parquet"
        if not path.exists():
            return {"status": "coming with dead-money step", "count": 0,
                    "total_sar": 0.0, "rows": []}
        dead = pd.read_parquet(path)
        return {
            "status": "ready",
            "count": int(len(dead)),
            "total_sar": float(dead["dead_value_sar"].sum()),
            "rows": _records(dead.head(limit)),
        }

    @app.get("/api/dead_money")
    def dead_money_figures() -> dict:
        """The engine's own dead-money figure, with its grade against the answer key."""
        report = _read(cfg, "dead_money_report.json", f"python cli.py run --preset {cfg.preset}")
        score_path = cfg.results_dir / "dead_money_score.json"
        if score_path.exists():
            report["score"] = json.loads(score_path.read_text(encoding="utf-8"))
        return report

    @app.get("/api/recommendations/{which}.csv")
    def recommendations_csv(which: str) -> PlainTextResponse:
        """
        The list as a spreadsheet. CSV with a byte-order mark opens straight in
        Excel; writing .xlsx would mean a new dependency for the same outcome.
        """
        if which == "orders":
            frame = _orders()
        elif which == "writeoff":
            path = cfg.results_dir / "dead_money.parquet"
            if not path.exists():
                raise HTTPException(status_code=409, detail="dead money not computed yet")
            frame = pd.read_parquet(path)
        elif which == "moves":
            stores = _read(cfg, STOREROOM_FILE, f"python cli.py run --preset {cfg.preset}")
            frame = pd.DataFrame(stores.get("transfers", []))
        else:
            raise HTTPException(status_code=404, detail="orders.csv, moves.csv or writeoff.csv")
        text = "\ufeff" + frame.to_csv(index=False, lineterminator="\r\n")
        return PlainTextResponse(
            text, media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{which}.csv"'},
        )

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
