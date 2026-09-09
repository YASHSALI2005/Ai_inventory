"""
End-to-end smoke test: build -> run -> score in a temp directory.

Cheap insurance against the failure that costs the most time: the pipeline works
in pieces but the stages no longer hand off to each other.
"""

from __future__ import annotations

import json

import pytest

import cli
from contracts import schemas as S
from contracts.config import RunConfig


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("mro-data")


def _run(argv, data_dir):
    """Invoke the CLI against a throwaway data directory."""
    return cli.main([*argv, "--data-dir", str(data_dir)])


def test_pipeline_runs_end_to_end(data_dir, capsys):
    assert _run(["build", "--preset", "toy"], data_dir) == 0
    assert _run(["run", "--preset", "toy"], data_dir) == 0
    assert _run(["score", "--preset", "toy"], data_dir) == 0

    out = capsys.readouterr().out
    assert "TOTAL (checks that ran)" in out
    assert "FAIL" not in out, "a dataset property drifted out of band"

    cfg = RunConfig(preset="toy", data_dir=data_dir)
    manifest = json.loads((cfg.results_dir / S.RUN_MANIFEST_FILE).read_text())
    assert manifest["n_materials"] > 0
    assert manifest["config_hash"]

    score = json.loads((cfg.results_dir / "defect_score.json").read_text())
    assert score["summary"]["planted"] > 0
    assert score["summary"]["recall"] is not None


def test_score_before_build_fails_cleanly(tmp_path):
    assert _run(["score", "--preset", "toy"], tmp_path) == 1


def test_run_before_build_fails_cleanly(tmp_path):
    assert _run(["run", "--preset", "toy"], tmp_path) == 1
