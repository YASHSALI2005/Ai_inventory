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

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from contracts import schemas as S
from contracts.config import RunConfig
from scoring.summary import SUMMARY_FILE

STATIC = Path(__file__).resolve().parent / "static"


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

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
