"""
Guards on the scoreboard itself.

The scoreboard is the deliverable — "it found 94 of the 100 problems we hid" is
the sentence the whole POC is built to earn. A scorer that silently mis-keys a
defect type reports a working check as broken, or a broken one as unwritten, and
nobody notices until a client asks how it was measured.

These build a findings frame by hand and assert the exact counts, so the scorer is
tested against known input rather than against whatever the engine happens to do.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from contracts import schemas as S
from contracts.config import RunConfig
from scoring import defects


@pytest.fixture
def workspace(tmp_path):
    """A results/answer-key pair on disk, with a known set of planted defects."""
    cfg = RunConfig(preset="toy", data_dir=tmp_path)
    cfg.answer_key_dir.mkdir(parents=True, exist_ok=True)
    cfg.results_dir.mkdir(parents=True, exist_ok=True)

    planted = [
        # two negatives the engine will find
        {"defect_id": "D-1", "defect_type": "NEGATIVE_STOCK", "table": "stock",
         "key": {"material_id": "M-1", "storeroom_id": "SMELTER"}, "detail": "",
         "shadowed_by": None},
        {"defect_id": "D-2", "defect_type": "NEGATIVE_STOCK", "table": "stock",
         "key": {"material_id": "M-2", "storeroom_id": "CENTRAL"}, "detail": "",
         "shadowed_by": None},
        # one it will miss
        {"defect_id": "D-3", "defect_type": "NEGATIVE_STOCK", "table": "stock",
         "key": {"material_id": "M-3", "storeroom_id": "ROLLING"}, "detail": "",
         "shadowed_by": None},
        # a duplicate pair, which the engine will name in the opposite order
        {"defect_id": "D-4", "defect_type": "DUPLICATE_MATERIAL", "table": "materials",
         "key": {"material_id": "M-D1", "duplicate_of": "M-9"}, "detail": "", "shadowed_by": None},
        # an orphan issue, identified by movement
        {"defect_id": "D-5", "defect_type": "ISSUE_WITHOUT_WORK_ORDER", "table": "movements",
         "key": {"movement_id": 4242}, "detail": "", "shadowed_by": None},
        # a type with no check written yet
        {"defect_id": "D-6", "defect_type": "BLANK_UOM", "table": "materials",
         "key": {"material_id": "M-7"}, "detail": "", "shadowed_by": None},
    ]
    (cfg.answer_key_dir / S.PLANTED_DEFECTS_FILE).write_text(json.dumps(planted))

    rows = [
        ("F1", "NEGATIVE_STOCK", "stock", "M-1", "SMELTER", S.NO_MOVEMENT, "", "", 1.0),
        ("F2", "NEGATIVE_STOCK", "stock", "M-2", "CENTRAL", S.NO_MOVEMENT, "", "", 1.0),
        # a false alarm: nothing was planted here
        ("F3", "NEGATIVE_STOCK", "stock", "M-99", "BAITHA", S.NO_MOVEMENT, "", "", 1.0),
        # the duplicate, named the other way round — must still count as a hit
        ("F4", "DUPLICATE_MATERIAL", "materials", "M-9", "", S.NO_MOVEMENT, "M-D1", "", 0.8),
        ("F5", "ISSUE_WITHOUT_WORK_ORDER", "movements", "M-5", "SMELTER", 4242, "", "", 1.0),
        # informational: real finding, nothing planted for it
        ("F6", "LEDGER_MISMATCH", "stock", "M-8", "CENTRAL", S.NO_MOVEMENT, "", "", 1.0),
    ]
    findings = pd.DataFrame(rows, columns=S.FINDINGS.names)
    S.write(findings, S.FINDINGS, cfg.results_dir)

    (cfg.results_dir / S.IMPLEMENTED_CHECKS_FILE).write_text(
        json.dumps(
            {
                "defect_types": ["NEGATIVE_STOCK", "DUPLICATE_MATERIAL",
                                 "ISSUE_WITHOUT_WORK_ORDER", "LEDGER_MISMATCH"],
                "scored": ["DUPLICATE_MATERIAL", "ISSUE_WITHOUT_WORK_ORDER", "NEGATIVE_STOCK"],
                "informational": ["LEDGER_MISMATCH"],
            }
        )
    )
    return cfg


def test_scoreboard_is_exact(workspace):
    scores, summary = defects.score(workspace)
    by_type = {s.defect_type: s for s in scores}

    neg = by_type["NEGATIVE_STOCK"]
    assert (neg.planted, neg.found, neg.missed, neg.false_alarms) == (3, 2, 1, 1)

    dup = by_type["DUPLICATE_MATERIAL"]
    assert (dup.planted, dup.found, dup.false_alarms) == (1, 1, 0), (
        "a duplicate pair must match regardless of which master is named first"
    )

    orphan = by_type["ISSUE_WITHOUT_WORK_ORDER"]
    assert (orphan.planted, orphan.found, orphan.false_alarms) == (1, 1, 0), (
        "orphan issues are keyed by movement_id, not by material"
    )

    assert summary["planted"] == 5
    assert summary["found"] == 4
    assert summary["false_alarms"] == 1
    assert summary["recall"] == pytest.approx(0.8)
    assert summary["precision"] == pytest.approx(0.8)


def test_informational_findings_do_not_cost_precision(workspace):
    _scores, summary = defects.score(workspace)
    assert summary["informational"] == {"LEDGER_MISMATCH": 1}
    # 4 hits, 1 false alarm — the ledger finding is excluded entirely
    assert summary["precision"] == pytest.approx(4 / 5)


def test_unwritten_checks_are_listed_not_counted_as_missed(workspace):
    _scores, summary = defects.score(workspace)
    assert summary["not_yet_implemented"] == ["BLANK_UOM"]
    assert summary["planted"] == 5, "the unwritten check's defect must not inflate the denominator"


def test_a_check_that_ran_and_found_nothing_scores_zero(workspace):
    """
    The failure mode this guards: inferring "implemented" from the finding types
    present would report a 100% miss as work not started.
    """
    (workspace.results_dir / S.IMPLEMENTED_CHECKS_FILE).write_text(
        json.dumps({"defect_types": ["BLANK_UOM"], "scored": ["BLANK_UOM"],
                    "informational": []})
    )
    scores, summary = defects.score(workspace)
    assert [s.defect_type for s in scores] == ["BLANK_UOM"]
    assert scores[0].planted == 1
    assert scores[0].found == 0
    assert summary["recall"] == 0.0


def test_missing_declaration_is_an_error_not_a_silent_pass(workspace):
    (workspace.results_dir / S.IMPLEMENTED_CHECKS_FILE).unlink()
    with pytest.raises(FileNotFoundError, match="declare which checks ran"):
        defects.score(workspace)


def test_emergent_scorers_report_truth_while_unimplemented(workspace, tmp_path):
    """
    The step-6 scorers must return the true totals even before anything computes
    them, so the console shows the size of the prize we have not yet claimed.
    Dead money is claimed now (step 6a) and must grade itself against the truth.
    """
    cfg = RunConfig(preset="toy")
    for fn in (defects.score_obsolete, defects.score_critical_below_rop):
        r = fn(cfg)
        assert r["status"] == "not_implemented"
        assert len(r) > 1, "an unimplemented scorer must still report the truth totals"
    dm = defects.score_dead_money(cfg)
    if dm["status"] == "not_implemented":
        assert dm["true_dead_sar"] > 0
    else:
        assert dm["status"] == "scored" and dm["true_dead_sar"] > 0
