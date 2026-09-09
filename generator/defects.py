"""
Planted data defects — and only data defects.

What belongs here: problems with no natural generating process in the simulation,
where we want an exact found / missed / false-alarm count. Negatives, blanks, unit
errors, duplicate master records, orphan issues.

What deliberately does NOT belong here: overstock, obsolescence and
critical-below-reorder-point. Those emerge from the stale policy and from
equipment being decommissioned mid-history, and are scored against `truth`. If we
planted them too we would be grading the engine on our own injection rules rather
than on whether it can read a plant.

Every plant records itself in the answer key, which `engine/` never opens.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from contracts import schemas as S

# Share of rows to affect, per defect type. Small on purpose: a storeroom where
# 5% of rows are broken is a broken storeroom, not a realistic one.
RATES = {
    "NEGATIVE_STOCK": 0.004,
    "BLANK_MPN": 0.010,
    "BLANK_UOM": 0.003,
    "UOM_MISMATCH": 0.004,
    "DUPLICATE_MATERIAL": 0.006,
    "IMPOSSIBLE_LEAD_TIME": 0.003,
    "ISSUE_WITHOUT_WORK_ORDER": 0.002,
}

# How a description gets mangled when we create a duplicate master record — this
# is what the step-2 matcher has to see through.
_ABBREV = {
    "BEARING": "BRG", "ASSEMBLY": "ASSY", "CYLINDER": "CYL", "HYDRAULIC": "HYD",
    "TRANSMITTER": "XMTR", "TEMPERATURE": "TEMP", "PRESSURE": "PRESS",
    "ELECTRIC": "ELEC", "MEDIUM VOLTAGE": "MV", "STAINLESS": "SS",
    "MECHANICAL": "MECH", "CENTRIFUGAL": "CENTRIF", "CONVEYOR": "CONV",
}


def _mangle(desc: str, rng: np.random.Generator) -> str:
    out = desc.upper()
    for long, short in _ABBREV.items():
        if long in out:
            out = out.replace(long, short)
    style = rng.integers(0, 3)
    if style == 0:
        out = out.replace(", ", ",")
    elif style == 1:
        out = out.replace(", ", " ")
    return out


def _pick(n: int, rate: float, rng: np.random.Generator) -> np.ndarray:
    k = max(1, int(round(n * rate))) if n else 0
    return rng.choice(n, size=min(k, n), replace=False) if k else np.empty(0, dtype=int)


def inject(
    materials: pd.DataFrame,
    stock: pd.DataFrame,
    movements: pd.DataFrame,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict]]:
    """Return the mutated tables plus the list of everything we broke."""
    materials = materials.copy()
    stock = stock.copy()
    movements = movements.copy()
    key: list[dict] = []
    seq = 0

    def record(kind: str, table: str, keys: dict, detail: str) -> None:
        nonlocal seq
        seq += 1
        key.append(
            {
                "defect_id": f"D-{seq:06d}",
                "defect_type": kind,
                "table": table,
                "key": keys,
                "detail": detail,
            }
        )

    # ── stock: negative balances ────────────────────────────────────────────
    for i in _pick(len(stock), RATES["NEGATIVE_STOCK"], rng):
        row = stock.iloc[i]
        before = float(row["on_hand"])
        stock.iat[i, stock.columns.get_loc("on_hand")] = -abs(rng.integers(1, 40))
        record(
            "NEGATIVE_STOCK", "stock",
            {"material_id": row["material_id"], "storeroom_id": row["storeroom_id"]},
            f"on_hand set negative (was {before:.0f})",
        )

    # ── materials: blank manufacturer part number ───────────────────────────
    for i in _pick(len(materials), RATES["BLANK_MPN"], rng):
        row = materials.iloc[i]
        materials.iat[i, materials.columns.get_loc("mpn")] = ""
        record("BLANK_MPN", "materials", {"material_id": row["material_id"]}, "mpn blanked")

    # ── materials: blank unit of measure ────────────────────────────────────
    for i in _pick(len(materials), RATES["BLANK_UOM"], rng):
        row = materials.iloc[i]
        materials.iat[i, materials.columns.get_loc("uom")] = ""
        record("BLANK_UOM", "materials", {"material_id": row["material_id"]}, "uom blanked")

    # ── materials: UOM that contradicts the family (EA priced as a BOX etc) ──
    swap = {"EA": "BOX", "M": "EA", "KG": "EA", "L": "DR", "M2": "EA", "T": "KG", "PR": "EA"}
    for i in _pick(len(materials), RATES["UOM_MISMATCH"], rng):
        row = materials.iloc[i]
        was = row["uom"]
        materials.iat[i, materials.columns.get_loc("uom")] = swap.get(was, "BOX")
        record(
            "UOM_MISMATCH", "materials", {"material_id": row["material_id"]},
            f"uom changed {was} -> {swap.get(was, 'BOX')} without price adjustment",
        )

    # ── materials: duplicate master record under a mangled description ──────
    dupes = []
    for i in _pick(len(materials), RATES["DUPLICATE_MATERIAL"], rng):
        src = materials.iloc[i].copy()
        new_id = f"M-D{seq + len(dupes) + 1:05d}"
        src["material_id"] = new_id
        src["description"] = _mangle(str(src["description"]), rng)
        # a duplicate usually loses the MPN or gets it retyped
        if rng.random() < 0.5:
            src["mpn"] = ""
        dupes.append(src)
        record(
            "DUPLICATE_MATERIAL", "materials",
            {"material_id": new_id, "duplicate_of": materials.iloc[i]["material_id"]},
            f"duplicate of {materials.iloc[i]['material_id']} as {src['description']!r}",
        )
    if dupes:
        materials = pd.concat([materials, pd.DataFrame(dupes)], ignore_index=True)

    # ── materials: impossible lead time ─────────────────────────────────────
    for i in _pick(len(materials), RATES["IMPOSSIBLE_LEAD_TIME"], rng):
        row = materials.iloc[i]
        was = int(row["lead_time_days"])
        bad = int(rng.choice([0, 1, 1200, 3650]))
        materials.iat[i, materials.columns.get_loc("lead_time_days")] = bad
        record(
            "IMPOSSIBLE_LEAD_TIME", "materials", {"material_id": row["material_id"]},
            f"lead_time_days {was} -> {bad}",
        )

    # ── movements: issue with no work order behind it ───────────────────────
    issues = movements.index[movements["movement_type"] == "ISSUE"].to_numpy()
    if issues.size:
        n_orphan = max(1, int(len(issues) * RATES["ISSUE_WITHOUT_WORK_ORDER"]))
        chosen = rng.choice(issues, size=n_orphan, replace=False)
        col = movements.columns.get_loc("work_order_id")
        for idx in chosen:
            row = movements.loc[idx]
            movements.iat[movements.index.get_loc(idx), col] = ""
            record(
                "ISSUE_WITHOUT_WORK_ORDER", "movements",
                {"movement_id": int(row["movement_id"])},
                "issue stripped of its work order reference",
            )

    # stock rows for the duplicate materials, so they look genuinely stocked
    if dupes:
        extra = pd.DataFrame(
            {
                "material_id": [d["material_id"] for d in dupes],
                "storeroom_id": [
                    rng.choice(np.array(S.STOREROOMS)) for _ in dupes
                ],
                "on_hand": [float(rng.integers(1, 60)) for _ in dupes],
                "min_qty": 0.0,
                "max_qty": [float(rng.integers(5, 80)) for _ in dupes],
                "last_issue_date": pd.NaT,
                "last_receipt_date": pd.NaT,
                "avg_unit_cost_sar": [float(d["unit_price_sar"]) for d in dupes],
            }
        )
        stock = pd.concat([stock, extra], ignore_index=True)

    return materials, stock, movements, key
