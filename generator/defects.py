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

# Share of rows to affect, per defect type. Small on purpose: a storeroom where 5%
# of rows are broken is a broken storeroom, not a realistic one. Each type is also
# floored at `cfg.size.min_defects_per_type`, because a one-of-one test proves
# nothing — the score comes out 0% or 100% by luck.
RATES = {
    "NEGATIVE_STOCK": 0.004,
    "BLANK_MPN": 0.010,
    "BLANK_UOM": 0.003,
    "UOM_MISMATCH": 0.004,
    "DUPLICATE_MATERIAL": 0.010,
    "IMPOSSIBLE_LEAD_TIME": 0.003,
    "ISSUE_WITHOUT_WORK_ORDER": 0.002,
}

_ABBREV = {
    "BEARING": "BRG", "ASSEMBLY": "ASSY", "CYLINDER": "CYL", "HYDRAULIC": "HYD",
    "TRANSMITTER": "XMTR", "TEMPERATURE": "TEMP", "PRESSURE": "PRESS",
    "ELECTRIC": "ELEC", "MEDIUM VOLTAGE": "MV", "STAINLESS": "SS",
    "MECHANICAL": "MECH", "CENTRIFUGAL": "CENTRIF", "CONVEYOR": "CONV",
    "PROTECTIVE": "PROT", "LUBRICATING": "LUBE", "HEXAGON": "HEX",
}


def _mangle(desc: str, rng: np.random.Generator) -> tuple[str, list[str]]:
    """
    Turn a description into the one a second person would have typed.

    The applied mangles are returned so a matcher miss can be analysed by
    difficulty: losing to a dropped size token is a different problem from losing
    to a one-character typo.
    """
    out = desc.upper()
    applied: list[str] = []

    for long, short in _ABBREV.items():
        if long in out:
            out = out.replace(long, short)
            applied.append("abbrev")
            break

    style = int(rng.integers(0, 3))
    if style == 0:
        out = out.replace(", ", ",")
        applied.append("no_space")
    elif style == 1:
        out = out.replace(", ", " ")
        applied.append("no_comma")

    parts = [p.strip() for p in out.replace(",", " ").split() if p.strip()]
    roll = rng.random()
    if roll < 0.20 and len(parts) > 2:
        out = " ".join([parts[-1]] + parts[:-1])          # size token moved to the front
        applied.append("token_front")
    elif roll < 0.35 and len(parts) > 2:
        out = " ".join(parts[:-1])                        # size token dropped entirely
        applied.append("token_dropped")

    if rng.random() < 0.25 and len(out) > 6:
        i = int(rng.integers(1, len(out) - 1))
        if out[i].isalnum():
            out = out[:i] + rng.choice(np.array(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"))) \
                + out[i + 1:]
            applied.append("typo")

    if rng.random() < 0.15:
        out += rng.choice(np.array([" -OLD", " (DUP)", " *DO NOT USE*"]))
        applied.append("suffix")

    return out, applied


def _pick(n: int, rate: float, floor: int, rng: np.random.Generator) -> np.ndarray:
    if n == 0:
        return np.empty(0, dtype=int)
    k = max(floor, int(round(n * rate)))
    return rng.choice(n, size=min(k, n), replace=False)


def inject(cfg, materials, stock, movements, truth_materials, rng):
    """Return the mutated tables, updated truth, and the list of everything we broke."""
    materials = materials.copy()
    stock = stock.copy()
    movements = movements.copy()
    truth_materials = truth_materials.copy()
    floor = cfg.size.min_defects_per_type

    key: list[dict] = []
    seq = 0

    def record(kind, table, keys, detail, shadowed_by=None) -> str:
        nonlocal seq
        seq += 1
        did = f"D-{seq:06d}"
        key.append(
            {
                "defect_id": did,
                "defect_type": kind,
                "table": table,
                "key": keys,
                "detail": detail,
                "shadowed_by": shadowed_by,
            }
        )
        return did

    # ── duplicates first: they add rows every later step must see ────────────
    dupes = []
    dupe_stock = []
    opening_rows: list[dict] = []
    # Prefer sources that actually have consumption: a duplicate of a never-issued
    # part cannot demonstrate split history, which is the whole point of the defect.
    issued = set(movements.loc[movements["movement_type"] == "ISSUE", "material_id"])
    with_history = np.flatnonzero(materials["material_id"].isin(issued).to_numpy())
    source_pool = with_history if with_history.size >= floor else np.arange(len(materials))

    picks = source_pool[_pick(source_pool.size, RATES["DUPLICATE_MATERIAL"], floor, rng)]
    for n_dupe, i in enumerate(picks):
        src = materials.iloc[i].copy()
        original_id = str(src["material_id"])
        new_id = f"M-D{len(dupes) + 1:05d}"
        desc, applied = _mangle(str(src["description"]), rng)
        src["material_id"] = new_id
        src["description"] = desc

        # a re-entered part usually loses or retypes the manufacturer part number
        blanked_mpn = rng.random() < 0.5
        if blanked_mpn:
            src["mpn"] = ""

        dupes.append(src)
        dup_defect = record(
            "DUPLICATE_MATERIAL",
            "materials",
            {"material_id": new_id, "duplicate_of": original_id},
            f"duplicate of {original_id} as {desc!r}; "
            f"mangles={'+'.join(applied) or 'none'}",
        )

        # A blanked MPN on a duplicate is a real BLANK_MPN row. Recording it here
        # means the BLANK_MPN check scores it as a hit instead of a guaranteed false
        # alarm — the shadow link says which defect created it.
        if blanked_mpn:
            record(
                "BLANK_MPN", "materials", {"material_id": new_id},
                "mpn lost when the duplicate was re-entered",
                shadowed_by=dup_defect,
            )

        # Human re-entry happens where the part is used, so the copy usually lands
        # in the original's own storeroom.
        rows = stock[stock["material_id"] == original_id]
        if len(rows) and rng.random() < 0.70:
            store = str(rows.iloc[0]["storeroom_id"])
        else:
            store = str(rng.choice(stock["storeroom_id"].unique()))

        moved_share = 0.0
        moved_qty = 0.0
        # Every other copy splits the history, rather than a coin flip per copy: at
        # toy scale three flips come up all-tails one run in eight, and the split is
        # the defect that matters most.
        if n_dupe % 2 == 0:
            # SPLIT HISTORY — the real Alcoa/Alba problem. Consumption is divided
            # across two masters, so both forecasts are wrong until they are merged,
            # and neither line looks anomalous on its own.
            moved_share = float(rng.uniform(0.2, 0.6))
            mask = (
                (movements["material_id"] == original_id)
                & (movements["movement_type"] == "ISSUE")
            )
            idx = movements.index[mask].to_numpy()
            if idx.size:
                take = rng.choice(idx, size=max(1, int(idx.size * moved_share)), replace=False)
                movements.loc[take, "material_id"] = new_id
                movements.loc[take, "storeroom_id"] = store
                moved_qty = float(movements.loc[take, "qty"].sum())   # negative: issues

        # The copy gets its own opening balance as a real ADJUST movement rather
        # than a hand-written on_hand. `stock` is recomputed from the ledger after
        # injection, so any balance not backed by movements would show up as a
        # ledger mismatch the engine is right to flag and we were wrong to create.
        # The opening must cover every issue the copy inherits, or its own ledger
        # goes negative — 52 positions did at full scale, and each one was scored as
        # a false alarm against a NEGATIVE_STOCK check that was entirely correct.
        on_hand = float(rows["on_hand"].sum()) if len(rows) else 0.0
        carved = round(on_hand * moved_share, 2) if moved_share else float(rng.integers(1, 40))
        opening_qty = max(carved, 1.0) + abs(moved_qty)
        opening_rows.append(
            {
                "date": movements["date"].min(),
                "material_id": new_id,
                "storeroom_id": store,
                "movement_type": "ADJUST",
                "qty": opening_qty,
                "work_order_id": "",
                "unit_cost_sar": float(src["unit_price_sar"]),
            }
        )
        dupe_stock.append(
            {
                "material_id": new_id,
                "storeroom_id": store,
                "on_hand": 0.0,                       # filled from the ledger below
                "min_qty": 0.0,
                "max_qty": float(rng.integers(5, 80)),
                "last_issue_date": pd.NaT,
                "last_receipt_date": pd.NaT,
                "avg_unit_cost_sar": float(src["unit_price_sar"]),
            }
        )

    if opening_rows:
        extra = pd.DataFrame(opening_rows)
        first_id = int(movements["movement_id"].max()) + 1
        extra["movement_id"] = np.arange(first_id, first_id + len(extra), dtype=np.int64)
        movements = pd.concat([movements, extra[movements.columns]], ignore_index=True)
        movements = movements.sort_values(
            ["date", "material_id"], kind="stable"
        ).reset_index(drop=True)

    if dupes:
        dup_df = pd.DataFrame(dupes)
        materials = pd.concat([materials, dup_df], ignore_index=True)
        stock = pd.concat([stock, pd.DataFrame(dupe_stock)], ignore_index=True)

        # truth rows for the copies, flagged so scoring can pair them
        dup_records = [d for d in key if d["defect_type"] == "DUPLICATE_MATERIAL"]
        originals = [d["key"]["duplicate_of"] for d in dup_records]
        copies = [d["key"]["material_id"] for d in dup_records]
        base = truth_materials.set_index("material_id").reindex(originals).reset_index(drop=True)
        base["material_id"] = copies
        base["is_duplicate_of"] = originals
        truth_materials = pd.concat([truth_materials, base], ignore_index=True)

    # ── materials: blank manufacturer part number ───────────────────────────
    already_blank = set(
        d["key"]["material_id"] for d in key if d["defect_type"] == "BLANK_MPN"
    )
    candidates = np.flatnonzero(~materials["material_id"].isin(already_blank).to_numpy())
    for i in candidates[_pick(candidates.size, RATES["BLANK_MPN"], floor, rng)]:
        row = materials.iloc[i]
        materials.iat[i, materials.columns.get_loc("mpn")] = ""
        record("BLANK_MPN", "materials", {"material_id": row["material_id"]}, "mpn blanked")

    # ── materials: blank unit of measure ────────────────────────────────────
    for i in _pick(len(materials), RATES["BLANK_UOM"], floor, rng):
        row = materials.iloc[i]
        materials.iat[i, materials.columns.get_loc("uom")] = ""
        record("BLANK_UOM", "materials", {"material_id": row["material_id"]}, "uom blanked")

    # ── materials: UOM contradicting the price (EA priced as a BOX) ──────────
    swap = {"EA": "BOX", "M": "EA", "KG": "EA", "L": "DR", "M2": "EA", "T": "KG", "PR": "EA"}
    for i in _pick(len(materials), RATES["UOM_MISMATCH"], floor, rng):
        row = materials.iloc[i]
        was = str(row["uom"])
        materials.iat[i, materials.columns.get_loc("uom")] = swap.get(was, "BOX")
        record(
            "UOM_MISMATCH", "materials", {"material_id": row["material_id"]},
            f"uom changed {was} -> {swap.get(was, 'BOX')} with no price adjustment",
        )

    # ── materials: impossible lead time ─────────────────────────────────────
    for i in _pick(len(materials), RATES["IMPOSSIBLE_LEAD_TIME"], floor, rng):
        row = materials.iloc[i]
        was = int(row["lead_time_days"])
        bad = int(rng.choice([0, 1, 1200, 3650]))
        materials.iat[i, materials.columns.get_loc("lead_time_days")] = bad
        record(
            "IMPOSSIBLE_LEAD_TIME", "materials", {"material_id": row["material_id"]},
            f"lead_time_days {was} -> {bad}",
        )

    # ── movements: issue with no work order behind it ───────────────────────
    issues = movements.index[
        (movements["movement_type"] == "ISSUE") & (movements["work_order_id"] != "")
    ].to_numpy()
    if issues.size:
        picks = _pick(issues.size, RATES["ISSUE_WITHOUT_WORK_ORDER"], floor, rng)
        col = movements.columns.get_loc("work_order_id")
        for idx in issues[picks]:
            row = movements.loc[idx]
            movements.iat[movements.index.get_loc(idx), col] = ""
            record(
                "ISSUE_WITHOUT_WORK_ORDER", "movements",
                {"movement_id": int(row["movement_id"])},
                "issue stripped of its work order reference",
            )

    return materials, stock, movements, truth_materials, key


def plant_negative_stock(cfg, stock, rng, record):
    """
    Applied AFTER `stock` has been recomputed from the ledger.

    A negative balance is precisely a position where the ledger and the balance
    disagree, so it has to be written last or the recompute would erase it. Every
    other position must reconcile, otherwise LEDGER_MISMATCH becomes a check that
    fires on our own bookkeeping rather than on a real problem.
    """
    stock = stock.copy()
    for i in _pick(len(stock), RATES["NEGATIVE_STOCK"], cfg.size.min_defects_per_type, rng):
        row = stock.iloc[i]
        before = float(row["on_hand"])
        stock.iat[i, stock.columns.get_loc("on_hand")] = -abs(float(rng.integers(1, 40)))
        record(
            "NEGATIVE_STOCK",
            "stock",
            {"material_id": row["material_id"], "storeroom_id": row["storeroom_id"]},
            f"on_hand set negative (was {before:.0f})",
        )
    return stock
