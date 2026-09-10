"""
Grades the demand classifier against what the invented plant actually did.

Scored with `PROFILE_TO_SBC_CLASS`, a many-to-many tolerance table rather than a
1:1 mapping. A truth profile constrains which quadrant is reasonable without
determining it, because the quadrant also depends on how much the demand *size*
varies — and the profile says nothing about that. Demanding an exact match would
mark the classifier wrong for being right.

Two figures are reported, and the gap between them is the interesting part:
* **agreement** — the class falls inside the set the truth profile allows.
* **exact agreement** — it matches the first, most typical class for that profile.
"""

from __future__ import annotations

import json

import pandas as pd

from contracts import schemas as S
from contracts.config import RunConfig
from engine.classify import CV2_CUTOFF as S_CV2_CUTOFF

SCORE_FILE = "classifier_score.json"


def score(cfg: RunConfig) -> dict:
    path = cfg.results_dir / "classification.parquet"
    if not path.exists():
        return {"status": "not_implemented"}

    got = pd.read_parquet(path)
    truth = S.read(S.TRUTH_MATERIALS, cfg.answer_key_dir)

    per_material = (
        got.sort_values("adi").groupby("material_id", as_index=False).first()
        [["material_id", "demand_class", "adi", "cv2", "never_moved"]]
    )
    j = per_material.merge(
        truth[["material_id", "true_profile"]], on="material_id", how="inner"
    )

    allowed = S.PROFILE_TO_SBC_CLASS
    j["ok"] = [
        cls in allowed.get(prof, ()) for cls, prof in zip(j.demand_class, j.true_profile,
                                                          strict=True)
    ]
    j["exact"] = [
        cls == allowed.get(prof, ("",))[0]
        for cls, prof in zip(j.demand_class, j.true_profile, strict=True)
    ]

    by_profile = []
    for prof, grp in j.groupby("true_profile"):
        counts = grp["demand_class"].value_counts().to_dict()
        by_profile.append(
            {
                "true_profile": prof,
                "materials": int(len(grp)),
                "agreement": round(float(grp["ok"].mean()), 4),
                "allowed": list(allowed.get(prof, ())),
                "assigned": {k: int(v) for k, v in counts.items()},
            }
        )

    # the confusion table, which is what shows WHERE it disagrees
    confusion = (
        j.groupby(["true_profile", "demand_class"]).size().rename("n").reset_index()
    )

    # Where a disagreement is concentrated matters more than its size. If nearly
    # all of it is one profile landing in one class, that is a question about the
    # tolerance table, not a fault in the sorting.
    disagreements = j[~j["ok"]]
    top_pattern = None
    if len(disagreements):
        pattern = (
            disagreements.groupby(["true_profile", "demand_class"])
            .size()
            .sort_values(ascending=False)
        )
        (prof, cls), n = pattern.index[0], int(pattern.iloc[0])
        subset = disagreements[
            (disagreements.true_profile == prof) & (disagreements.demand_class == cls)
        ]
        above_cutoff = float((subset["cv2"] > S_CV2_CUTOFF).mean()) if len(subset) else 0.0
        top_pattern = {
            "true_profile": prof,
            "assigned": cls,
            "materials": n,
            "share_of_all_disagreements": round(n / len(disagreements), 4),
            "share_genuinely_above_cv2_cutoff": round(above_cutoff, 4),
        }

    out = {
        "materials_scored": int(len(j)),
        "agreement": round(float(j["ok"].mean()), 4),
        "exact_agreement": round(float(j["exact"].mean()), 4),
        "by_profile": sorted(by_profile, key=lambda r: -r["materials"]),
        "confusion": confusion.to_dict("records"),
        "largest_disagreement": top_pattern,
    }
    (cfg.results_dir / SCORE_FILE).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def render(result: dict) -> str:
    if result.get("status") == "not_implemented":
        return "  classifier                  not implemented yet"
    lines = [
        f"  scored {result['materials_scored']:,} materials · "
        f"agreement {result['agreement']:.0%} · exact {result['exact_agreement']:.0%}",
        "",
        f"  {'how it really behaves':<14} {'parts':>7} {'agrees':>8}   assigned to",
    ]
    for r in result["by_profile"]:
        assigned = ", ".join(
            f"{k} {v}" for k, v in sorted(r["assigned"].items(), key=lambda kv: -kv[1])
        )
        lines.append(
            f"  {r['true_profile']:<14} {r['materials']:>7,} {r['agreement']:>7.0%}   {assigned}"
        )
    pattern = result.get("largest_disagreement")
    if pattern:
        share = pattern.get("share_genuinely_above_cv2_cutoff", 0.0)
        lines += [
            "",
            f"  largest single disagreement: {pattern['materials']:,} parts that behave as "
            f"{pattern['true_profile']}",
            f"  were sorted {pattern['assigned']} "
            f"({pattern['share_of_all_disagreements']:.0%} of all disagreements).",
        ]
        # Only claim the reference table is at fault where the evidence supports it.
        # Printing the same sentence regardless would be an argument dressed up as a
        # finding.
        if share > 0.9:
            lines += [
                f"  {share:.0%} of those genuinely have size variability above the "
                "cutoff, so this reads",
                "  as a gap in the reference table rather than a sorting error.",
            ]
        else:
            lines += [
                "  These sit on the boundary between two groups rather than being "
                "clearly misplaced:",
                f"  only {share:.0%} have size variability above the cutoff, so the "
                "disagreement is about",
                "  where the line falls, not which side of it these parts belong on.",
            ]
    return "\n".join(lines)
