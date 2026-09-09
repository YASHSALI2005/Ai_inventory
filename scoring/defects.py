"""
Grades the engine's data-quality findings against the planted answer key.

This is the module that turns "the demo looks good" into "it found 94 of the 100
problems we hid, and raised 6 false alarms." It is the only place the answer key
is opened, and it runs after the engine, never alongside it.

Scoring is per defect type, not just overall. An engine that finds every negative
stock row and no duplicates has a fine overall recall and a useless duplicate
matcher; a single blended number would hide that.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from contracts import schemas as S
from contracts.config import RunConfig


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


def _key_of(defect: dict) -> tuple:
    """Canonical identity of a planted defect, for set comparison against findings."""
    k = defect["key"]
    return (
        defect["defect_type"],
        k.get("material_id", ""),
        k.get("storeroom_id", ""),
        str(k.get("movement_id", "")),
    )


def _key_of_finding(row) -> tuple:
    return (row.defect_type, row.material_id or "", row.storeroom_id or "", "")


def score(cfg: RunConfig) -> tuple[list[TypeScore], dict]:
    planted_raw = json.loads(
        (cfg.answer_key_dir / S.PLANTED_DEFECTS_FILE).read_text(encoding="utf-8")
    )
    findings = S.read(S.FINDINGS, cfg.results_dir)

    # Only score the types the engine actually implements a check for. Counting a
    # type nobody has written yet as 100% missed would make the scoreboard read as
    # failure rather than as work not started.
    implemented = set(findings.defect_type.unique())

    planted_keys: dict[str, set[tuple]] = {}
    for d in planted_raw:
        planted_keys.setdefault(d["defect_type"], set()).add(_key_of(d))

    found_keys: dict[str, set[tuple]] = {}
    for row in findings.itertuples():
        found_keys.setdefault(row.defect_type, set()).add(_key_of_finding(row))

    scores: list[TypeScore] = []
    for dtype in sorted(implemented):
        planted = planted_keys.get(dtype, set())
        flagged = found_keys.get(dtype, set())
        hit = planted & flagged
        scores.append(
            TypeScore(
                defect_type=dtype,
                planted=len(planted),
                found=len(hit),
                missed=len(planted - flagged),
                false_alarms=len(flagged - planted),
            )
        )

    total_planted = sum(s.planted for s in scores)
    total_found = sum(s.found for s in scores)
    total_false = sum(s.false_alarms for s in scores)
    summary = {
        "implemented_checks": sorted(implemented),
        "not_yet_implemented": sorted(set(planted_keys) - implemented),
        "planted": total_planted,
        "found": total_found,
        "missed": total_planted - total_found,
        "false_alarms": total_false,
        "recall": round(total_found / total_planted, 4) if total_planted else None,
        "precision": (
            round(total_found / (total_found + total_false), 4)
            if (total_found + total_false)
            else None
        ),
    }

    out = cfg.results_dir / "defect_score.json"
    out.write_text(
        json.dumps({"by_type": [asdict(s) for s in scores], "summary": summary}, indent=2),
        encoding="utf-8",
    )
    return scores, summary


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
        f"{'TOTAL (implemented checks)':<28} {summary['planted']:>8} {summary['found']:>6} "
        f"{summary['missed']:>7} {summary['false_alarms']:>6} "
        f"{(summary['recall'] or 0):>6.0%} {(summary['precision'] or 0):>6.0%}"
    )
    if summary["not_yet_implemented"]:
        lines.append("")
        lines.append("checks not written yet: " + ", ".join(summary["not_yet_implemented"]))
    return "\n".join(lines)
