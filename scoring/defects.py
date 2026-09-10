"""
Grades the engine's data-quality findings against the planted answer key.

This is the module that turns "the demo looks good" into "it found 94 of the 100
problems we hid, and raised 6 false alarms." It is the only place the answer key
is opened, and it runs after the engine, never alongside it.

Three things it gets right that a naive scorer does not:

* **Identity is per defect type.** An orphan issue is identified by its movement,
  a duplicate by the unordered PAIR of masters, a blank field by its material. A
  single key shape scores two of the seven types as permanently missed.
* **Implemented is declared, not inferred.** The engine writes the list of checks
  that ran. Inferring it from the finding types present would report a check that
  ran and found nothing as "not written yet", hiding a 100% miss.
* **Unplanted types are informational.** The engine should raise LEDGER_MISMATCH
  and similar; those have no planted counterpart and are reported with counts
  rather than counted as false alarms.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass

import numpy as np

from contracts import schemas as S
from contracts.config import RunConfig

NEWLINE = chr(10)


@dataclass
class TypeScore:
    defect_type: str
    planted: int
    found: int
    missed: int
    false_alarms: int

    @property
    def recall(self) -> float:
        return self.found / self.planted if self.planted else float("nan")

    @property
    def precision(self) -> float:
        flagged = self.found + self.false_alarms
        return self.found / flagged if flagged else float("nan")


def _planted_key(d: dict):
    """
    Identity of a planted defect, per type.

    A duplicate is an unordered pair: the engine sees two masters that describe the
    same part and cannot know which one was the copy. Scoring it as an ordered pair
    would fail every correct finding that named them the other way round.
    """
    k = d["key"]
    t = d["defect_type"]
    if t == "DUPLICATE_MATERIAL":
        return (t, frozenset({k["material_id"], k["duplicate_of"]}))
    if t == "ISSUE_WITHOUT_WORK_ORDER":
        return (t, int(k["movement_id"]))
    if t == "NEGATIVE_STOCK":
        return (t, k["material_id"], k.get("storeroom_id", ""))
    return (t, k["material_id"])


def _finding_key(row):
    t = row.defect_type
    if t == "DUPLICATE_MATERIAL":
        return (t, frozenset({row.material_id, row.related_material_id}))
    if t == "ISSUE_WITHOUT_WORK_ORDER":
        return (t, int(row.movement_id))
    if t == "NEGATIVE_STOCK":
        return (t, row.material_id, row.storeroom_id or "")
    return (t, row.material_id)


def score(cfg: RunConfig) -> tuple[list[TypeScore], dict]:
    planted_raw = json.loads(
        (cfg.answer_key_dir / S.PLANTED_DEFECTS_FILE).read_text(encoding="utf-8")
    )
    findings = S.read(S.FINDINGS, cfg.results_dir)

    checks_file = cfg.results_dir / S.IMPLEMENTED_CHECKS_FILE
    if not checks_file.exists():
        raise FileNotFoundError(
            f"{S.IMPLEMENTED_CHECKS_FILE} missing — the engine must declare which checks ran, "
            "otherwise a check that ran and found nothing is scored as work not started"
        )
    declared = json.loads(checks_file.read_text(encoding="utf-8"))
    # `scored` are the checks with a planted counterpart; `informational` are the
    # ones the engine is right to raise but which nothing was planted for. Mixing
    # them drags precision down for finding real problems.
    implemented = set(declared["scored"])
    informational_checks = set(declared.get("informational", []))

    # Counters, not sets: a material can legitimately carry several planted defects
    # (a blank MPN, being the source of a duplicate, and an impossible lead time).
    planted = Counter(_planted_key(d) for d in planted_raw)
    flagged = Counter(_finding_key(r) for r in findings.itertuples())

    scores: list[TypeScore] = []
    for dtype in sorted(implemented):
        p = Counter({k: v for k, v in planted.items() if k[0] == dtype})
        f = Counter({k: v for k, v in flagged.items() if k[0] == dtype})
        hits = sum((p & f).values())
        scores.append(
            TypeScore(
                defect_type=dtype,
                planted=sum(p.values()),
                found=hits,
                missed=sum(p.values()) - hits,
                false_alarms=sum(f.values()) - hits,
            )
        )

    informational = Counter(
        r.defect_type for r in findings.itertuples() if r.defect_type not in implemented
    )

    total_planted = sum(s.planted for s in scores)
    total_found = sum(s.found for s in scores)
    total_false = sum(s.false_alarms for s in scores)
    summary = {
        "implemented_checks": sorted(implemented),
        "informational_checks": sorted(informational_checks),
        "not_yet_implemented": sorted({k[0] for k in planted} - implemented),
        "informational": dict(informational),
        "planted": total_planted,
        "found": total_found,
        "missed": total_planted - total_found,
        "false_alarms": total_false,
        "recall": round(total_found / total_planted, 4) if total_planted else None,
        "precision": (
            round(total_found / (total_found + total_false), 4)
            if (total_found + total_false) else None
        ),
    }

    (cfg.results_dir / "defect_score.json").write_text(
        json.dumps({"by_type": [asdict(s) for s in scores], "summary": summary}, indent=2),
        encoding="utf-8",
    )
    return scores, summary


# ── emergent problems, scored against truth rather than a planted list ───────


def score_dead_money(cfg: RunConfig) -> dict:
    """
    SAR the engine flagged as dead, against SAR that actually is.

    Not implemented until step 6 writes a dead-money result; the interface exists
    now so the shape of the answer is fixed before anything is built to fit it.
    """
    from scoring.dataset_report import dead_money

    stock = S.read(S.STOCK, cfg.source_dir)
    mats = S.read(S.MATERIALS, cfg.source_dir)
    tm = S.read(S.TRUTH_MATERIALS, cfg.answer_key_dir)
    tp = S.read(S.TRUTH_POSITIONS, cfg.answer_key_dir)
    share, true_sar, total_sar = dead_money(cfg, stock, mats, tm, tp)

    path = cfg.results_dir / "dead_money.parquet"
    if not path.exists():
        return {"status": "not_implemented", "true_dead_sar": true_sar, "total_sar": total_sar}

    import pandas as pd

    found = pd.read_parquet(path)
    j = found.merge(tp, on=["material_id", "storeroom_id"], how="left").merge(
        tm[["material_id", "true_is_obsolete"]], on="material_id", how="left"
    )
    on_hand = stock.set_index(["material_id", "storeroom_id"])["on_hand"]
    idx = pd.MultiIndex.from_arrays([j.material_id, j.storeroom_id])
    held = on_hand.reindex(idx).clip(lower=0).to_numpy()
    truly_dead = np.where(
        j.true_is_obsolete.fillna(False),
        held,
        np.maximum(held - j.true_justified_qty.fillna(0.0), 0.0),
    )
    cost = stock.set_index(["material_id", "storeroom_id"])["avg_unit_cost_sar"].reindex(idx)
    correct = float((np.minimum(j.dead_qty.to_numpy(), truly_dead) * cost).sum())
    claimed = float((j.dead_qty.to_numpy() * cost).sum())
    return {
        "status": "scored",
        "claimed_sar": claimed,
        "correct_sar": correct,
        "over_claimed_sar": claimed - correct,
        "true_dead_sar": true_sar,
        "recall": correct / true_sar if true_sar else None,
        "precision": correct / claimed if claimed else None,
    }


def score_obsolete(cfg: RunConfig) -> dict:
    """Found / missed / false on `true_is_obsolete`. Awaiting step 6."""
    tm = S.read(S.TRUTH_MATERIALS, cfg.answer_key_dir)
    path = cfg.results_dir / "obsolete.parquet"
    truth = set(tm.loc[tm.true_is_obsolete, "material_id"])
    if not path.exists():
        return {"status": "not_implemented", "true_obsolete": len(truth)}

    import pandas as pd

    flagged = set(pd.read_parquet(path)["material_id"])
    return {
        "status": "scored",
        "true_obsolete": len(truth),
        "found": len(truth & flagged),
        "missed": len(truth - flagged),
        "false_alarms": len(flagged - truth),
    }


def score_critical_below_rop(cfg: RunConfig) -> dict:
    """Positions where criticality is A and on_hand is under the justified level."""
    stock = S.read(S.STOCK, cfg.source_dir)
    mats = S.read(S.MATERIALS, cfg.source_dir)
    tp = S.read(S.TRUTH_POSITIONS, cfg.answer_key_dir)
    j = stock.merge(tp, on=["material_id", "storeroom_id"], how="left").merge(
        mats[["material_id", "criticality"]], on="material_id", how="left"
    )
    at_risk = j[(j.criticality == "A") & (j.on_hand < j.true_justified_qty.fillna(0.0))]
    truth = set(zip(at_risk.material_id, at_risk.storeroom_id, strict=True))

    path = cfg.results_dir / "critical_risk.parquet"
    if not path.exists():
        return {"status": "not_implemented", "true_at_risk": len(truth)}

    import pandas as pd

    f = pd.read_parquet(path)
    flagged = set(zip(f.material_id, f.storeroom_id, strict=True))
    return {
        "status": "scored",
        "true_at_risk": len(truth),
        "found": len(truth & flagged),
        "missed": len(truth - flagged),
        "false_alarms": len(flagged - truth),
    }


def duplicate_miss_report(cfg: RunConfig) -> dict:
    """
    Which mangle styles the matcher loses to.

    A miss caused by a dropped size token is a different problem from one caused by
    a one-character typo, and a single recall number hides which. The generator
    records the styles it applied to each copy, so the loss can be attributed
    rather than guessed at.
    """
    import re

    planted = json.loads(
        (cfg.answer_key_dir / S.PLANTED_DEFECTS_FILE).read_text(encoding="utf-8")
    )
    findings = S.read(S.FINDINGS, cfg.results_dir)
    found = {
        frozenset({r.material_id, r.related_material_id})
        for r in findings.itertuples()
        if r.defect_type == "DUPLICATE_MATERIAL"
    }

    by_style: dict[str, dict[str, int]] = {}
    for d in planted:
        if d["defect_type"] != "DUPLICATE_MATERIAL":
            continue
        hit = frozenset({d["key"]["material_id"], d["key"]["duplicate_of"]}) in found
        m = re.search(r"mangles=([\w+]+)", d.get("detail", ""))
        styles = (m.group(1).split("+") if m else ["none"]) or ["none"]
        for style in styles:
            cell = by_style.setdefault(style, {"planted": 0, "found": 0})
            cell["planted"] += 1
            cell["found"] += int(hit)

    for cell in by_style.values():
        cell["missed"] = cell["planted"] - cell["found"]
        cell["recall"] = round(cell["found"] / cell["planted"], 3) if cell["planted"] else None
    return dict(sorted(by_style.items()))


def render_duplicate_misses(report: dict) -> str:
    if not report:
        return ""
    lines = ["duplicate recall by mangle style (a copy can carry several):",
             f"  {'style':<16} {'planted':>8} {'found':>6} {'missed':>7} {'recall':>7}"]
    for style, c in report.items():
        lines.append(
            f"  {style:<16} {c['planted']:>8} {c['found']:>6} {c['missed']:>7} "
            f"{(c['recall'] or 0):>6.0%}"
        )
    return NEWLINE.join(lines)


def render(scores: list[TypeScore], summary: dict) -> str:
    lines = [
        f"{'defect type':<28} {'planted':>8} {'found':>6} {'missed':>7} {'false':>6} "
        f"{'recall':>7} {'prec':>6}",
        "-" * 74,
    ]
    for s in scores:
        lines.append(
            f"{s.defect_type:<28} {s.planted:>8} {s.found:>6} {s.missed:>7} "
            f"{s.false_alarms:>6} {s.recall:>6.0%} {s.precision:>6.0%}"
        )
    lines.append("-" * 74)
    lines.append(
        f"{'TOTAL (checks that ran)':<28} {summary['planted']:>8} {summary['found']:>6} "
        f"{summary['missed']:>7} {summary['false_alarms']:>6} "
        f"{(summary['recall'] or 0):>6.0%} {(summary['precision'] or 0):>6.0%}"
    )
    if summary.get("informational"):
        lines.append("")
        lines.append(
            "informational (no planted counterpart, excluded from precision): "
            + ", ".join(f"{k}={v}" for k, v in sorted(summary["informational"].items()))
        )
    if summary["not_yet_implemented"]:
        lines.append("")
        lines.append("checks not written yet: " + ", ".join(summary["not_yet_implemented"]))
    return "\n".join(lines)
