"""
The data maker: builds fake PiLog / CMMS / SAP tables plus the answer key.

Two rules shape everything here.

1. **Vectorised.** Demand comes from sampling inter-demand gaps and demand sizes
   per item with numpy, then assembling a ledger — never by looping over days. The
   replenishment walk runs over all positions at once inside `sim`.

2. **Emergent, not injected, where it matters.** Overstock, obsolescence and
   critical-items-below-reorder-point are NOT planted. They appear because the
   simulated plant runs a stale, mediocre min/max policy against demand that has
   drifted, and because equipment gets decommissioned mid-history while its spares
   keep sitting there. Those are scored against `truth`.

   Only *data* defects are planted — negatives, blanks, UOM errors, duplicates,
   orphan issues — because those have no natural generating process here and we
   want an exact found/missed/false-alarm count for them.

The unit of stocking is a POSITION: a material in a storeroom. A material can hold
positions in several storerooms, which is what gives capability 5 (transfers)
anything to work with.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from contracts import schemas as S
from contracts.config import RunConfig

STOREROOM_BY_AREA = {
    "MINE": "BAITHA",
    "RAIL": "BAITHA",
    "REFINERY": "REFINERY",
    "SMELTER": "SMELTER",
    "ROLLING": "ROLLING",
    "SITEWIDE": "CENTRAL",
}

# Base demand shape per seed profile. `drift` is a multiplicative change in rate
# across the three years — it is what makes a policy set in year one wrong by year
# three, and therefore the source of emergent excess.
PROFILES = {
    "consumable": dict(interval=(2.0, 9.0), size=(4.0, 40.0), cv=(0.35, 0.8), drift=(0.7, 1.4)),
    "occasional": dict(interval=(25.0, 90.0), size=(1.0, 5.0), cv=(0.5, 1.1), drift=(0.5, 1.6)),
    "lumpy": dict(interval=(90.0, 300.0), size=(1.0, 8.0), cv=(0.9, 1.8), drift=(0.4, 1.8)),
    "insurance": dict(interval=(700.0, 3000.0), size=(1.0, 2.0), cv=(0.2, 0.6), drift=(0.8, 1.2)),
}

# How a variant token is rendered, per seed `size_token_type`. Getting this right
# is most of what makes a material master read as real: "BEARING, BALL, 6205" is a
# part; "OIL, GEAR LUBRICATING, 188MM" is not.
_ISO_VG = (32, 46, 68, 100, 150, 220, 320, 460)
_BORE = (15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120)
_DN = (15, 20, 25, 32, 40, 50, 65, 80, 100, 125, 150, 200, 250, 300, 400, 500)
_M = (6, 8, 10, 12, 16, 20, 24, 30, 36)
_M_LEN = (20, 25, 30, 40, 50, 60, 80, 100, 120)
_KW = (0.75, 1.5, 2.2, 4, 7.5, 11, 18.5, 30, 45, 75, 110, 160, 250, 400, 630, 1000)
_AH = (7, 12, 26, 40, 65, 100, 150, 200)


def _size_token(kind: str, rng: np.random.Generator, n: int) -> np.ndarray:
    """Render n variant tokens of the given kind."""
    if kind == "bore_mm":
        series = rng.choice(np.array([62, 63, 60, 222, 223]), size=n)
        bore = rng.choice(np.array(_BORE), size=n)
        return np.array([f"{s}{b // 5:02d}" for s, b in zip(series, bore, strict=True)])
    if kind == "dn":
        return np.array([f"DN{v}" for v in rng.choice(np.array(_DN), size=n)])
    if kind == "od_mm":
        return np.array([f"{v}MM" for v in rng.choice(np.arange(20, 900, 5), size=n)])
    if kind == "iso_vg":
        return np.array([f"ISO VG {v}" for v in rng.choice(np.array(_ISO_VG), size=n)])
    if kind == "m_thread":
        th = rng.choice(np.array(_M), size=n)
        ln = rng.choice(np.array(_M_LEN), size=n)
        return np.array([f"M{t}X{ln_}" for t, ln_ in zip(th, ln, strict=True)])
    if kind == "kw":
        return np.array([f"{v:g}KW" for v in rng.choice(np.array(_KW), size=n)])
    if kind == "ah":
        return np.array([f"{v}AH" for v in rng.choice(np.array(_AH), size=n)])
    # "none": a rating or mark rather than a dimension
    return np.array([f"TYPE {c}" for c in rng.choice(np.array(list("ABCDEFGHJK")), size=n)])


# Second characteristic. ISO 8000 descriptions are noun + modifier + several
# characteristics, and one dimension is nowhere near enough to tell variants apart:
# a family of 300 valves drawn from 16 DN sizes produces the same description
# nineteen times over. That made 85% of the master share a description with some
# other row, which is not a material master — it is 82,000 duplicate pairs, and it
# made duplicate detection both impossible and pointless to measure.
_SPECS = {
    "seal": ("NBR", "VITON", "EPDM", "PTFE", "SILICONE", "HNBR"),
    "metal": ("SS316", "SS304", "CS", "DUCTILE IRON", "BRONZE", "INCONEL", "HARDOX"),
    "pressure": ("PN10", "PN16", "PN25", "PN40", "CL150", "CL300", "CL600"),
    "electrical": ("400V", "690V", "3.3KV", "6.6KV", "11KV", "IP55", "IP65", "IP66"),
    "wear": ("ALUMINA", "TUNGSTEN CARBIDE", "SIC", "RUBBER LINED", "CHROME CARBIDE"),
    "grade": ("GRADE A", "GRADE B", "GRADE C", "CLASS 1", "CLASS 2", "CLASS 3", "HD", "XHD"),
}

# which characteristic vocabulary suits which primary token type
_SPEC_FOR_TOKEN = {
    "bore_mm": ("metal", "grade"),
    "dn": ("pressure", "metal"),
    "od_mm": ("metal", "wear", "grade"),
    "m_thread": ("metal", "grade"),
    "kw": ("electrical", "grade"),
    "ah": ("electrical",),
    "iso_vg": ("grade",),
    "none": ("grade", "metal", "wear"),
}


def _unique_variants(kind: str, n: int, rng: np.random.Generator) -> list[str]:
    """
    n distinct characteristic strings for one family.

    Distinct by construction rather than by luck: the primary token and the
    characteristic are drawn as a set of unique combinations, and a running mark is
    appended only if the family is broader than the vocabulary allows. Two rows in
    the same family never read the same, so an identical description means what it
    should mean — that somebody entered the part twice.
    """
    primary = list(dict.fromkeys(_size_token(kind, rng, min(n * 4 + 32, 4000))))
    pools = _SPEC_FOR_TOKEN.get(kind, ("grade",))
    specs = [v for pool in pools for v in _SPECS[pool]]

    combos = [f"{p}, {q}" for p in primary for q in specs]
    rng.shuffle(combos)
    if len(combos) >= n:
        return combos[:n]

    out = list(combos)
    mark = 1
    while len(out) < n:
        out.extend(f"{c}, MK{mark}" for c in combos)
        mark += 1
    return out[:n]


@dataclass
class Generated:
    materials: pd.DataFrame
    equipment: pd.DataFrame
    stock: pd.DataFrame
    movements: pd.DataFrame
    work_orders: pd.DataFrame
    shutdowns: pd.DataFrame
    truth_materials: pd.DataFrame
    truth_positions: pd.DataFrame
    planted_defects: list[dict]


# ── seeds ────────────────────────────────────────────────────────────────────


def load_families(cfg: RunConfig) -> pd.DataFrame:
    fams = pd.read_csv(cfg.seeds_dir / "part_families.csv")
    bad = set(fams["profile"]) - set(PROFILES)
    if bad:
        raise ValueError(f"seed file has unknown profiles: {sorted(bad)}")
    return fams


def load_equipment_types(cfg: RunConfig) -> pd.DataFrame:
    return pd.read_csv(cfg.seeds_dir / "equipment_types.csv")


# ── equipment ────────────────────────────────────────────────────────────────


def build_equipment(cfg: RunConfig, eq_types: pd.DataFrame, rng: np.random.Generator):
    """
    Typed, named assets from the seed file.

    Names come from `name_pattern` ("Pot 042, Line 3"), not "SMELTER asset 0042",
    and the type is what lets a bearing attach to a pump rather than to a potline —
    the first thing a maintenance engineer checks.
    """
    n = cfg.size.n_equipment
    w = eq_types["weight"].to_numpy(dtype=float)

    # Every asset type gets at least one instance before weighting fills the rest.
    # Without this the toy preset misses types entirely and a crusher concave ends
    # up bolted to "General asset GA-001", which is the first thing a maintenance
    # engineer would notice.
    guaranteed = np.arange(len(eq_types))[: min(len(eq_types), n)]
    remaining = n - guaranteed.size
    if remaining > 0:
        drawn = rng.choice(np.arange(len(eq_types)), size=remaining, p=w / w.sum())
    else:
        drawn = np.empty(0, dtype=int)
    idx = np.concatenate([guaranteed, drawn])
    rng.shuffle(idx)
    t = eq_types.iloc[idx].reset_index(drop=True)

    names = []
    counters: dict[str, int] = {}
    for etype, pattern in zip(t["equipment_type"], t["name_pattern"], strict=True):
        counters[etype] = counters.get(etype, 0) + 1
        k = counters[etype]
        names.append(pattern.format(n=k, l=(k % 4) + 1, tag=f"{etype[:2]}{k:03d}"))

    crit = t["criticality_bias"].to_numpy()
    crit = np.where(rng.random(n) < 0.15, rng.choice(np.array(S.CRITICALITY), size=n), crit)

    # Ras Al Khair was commissioned 2013-15; a decade-old asset base is what makes
    # the commissioning-spares story coherent. Every asset built the day before
    # history starts contradicts it.
    early_lo, early_hi = cfg.equipment_commissioning_window
    late_lo, late_hi = cfg.equipment_late_window
    is_late = rng.random(n) < cfg.equipment_late_share
    day_ns = 86_400_000_000_000
    span_early = (pd.Timestamp(early_hi) - pd.Timestamp(early_lo)).days
    span_late = (pd.Timestamp(late_hi) - pd.Timestamp(late_lo)).days
    commissioned = np.where(
        is_late,
        pd.Timestamp(late_lo).value + rng.integers(0, span_late, n) * day_ns,
        pd.Timestamp(early_lo).value + rng.integers(0, span_early, n) * day_ns,
    )

    # A guaranteed floor of decommissioned assets: with one, every obsolescence
    # score comes out 0% or 100% by luck.
    n_decom = max(cfg.size.min_decommissioned, int(round(n * cfg.decommission_share)))
    decom_idx = rng.choice(n, size=min(n_decom, n), replace=False)
    decommissioned = np.zeros(n, dtype=bool)
    decommissioned[decom_idx] = True

    start = pd.Timestamp(cfg.history_start)
    offset = rng.integers(180, max(cfg.n_days - 60, 200), size=n)
    decom_date = np.where(
        decommissioned,
        (start + pd.to_timedelta(offset, "D")).values,
        np.datetime64("NaT", "ns"),
    )

    return pd.DataFrame(
        {
            "equipment_id": [f"EQ-{i:05d}" for i in range(1, n + 1)],
            "equipment_type": t["equipment_type"].to_numpy(),
            "plant": t["plant"].to_numpy(),
            "storeroom_id": [STOREROOM_BY_AREA[p] for p in t["plant"]],
            "name": names,
            "criticality": crit,
            "status": np.where(decommissioned, "DECOMMISSIONED", "RUNNING"),
            "commissioned_date": pd.to_datetime(commissioned),
            "decommissioned_date": pd.to_datetime(decom_date),
        }
    )


# ── materials ────────────────────────────────────────────────────────────────

# The same maker appears as "SKF", "S.K.F." and "SKF AB". Not a planted defect and
# not scored — it is background noise every real extract has, and normalising it is
# part of the matcher's job rather than a problem to report.
_MAKER_VARIANTS = {
    "SKF": ("SKF", "S.K.F.", "SKF AB"),
    "ABB": ("ABB", "A.B.B.", "ABB Ltd"),
    "Siemens": ("Siemens", "SIEMENS AG", "Siemens A.G."),
    "Parker": ("Parker", "Parker Hannifin", "PARKER-HANNIFIN"),
    "Metso": ("Metso", "Metso Outotec", "METSO CORP"),
    "Weir": ("Weir", "Weir Minerals", "WEIR MIN."),
    "Emerson": ("Emerson", "Emerson Process", "EMERSON ELEC"),
}


def build_materials(cfg: RunConfig, fams: pd.DataFrame, equipment: pd.DataFrame, rng):
    """Expand each seed family into dimensioned variants, weighted by family size."""
    n_target = cfg.size.n_materials
    pool = fams[fams["in_scope"] == 1].reset_index(drop=True)
    w = pool["variant_weight"].to_numpy(dtype=float)

    counts = np.maximum(1, np.round(w / w.sum() * n_target)).astype(int)
    fam_idx = np.repeat(np.arange(len(pool)), counts)[:n_target]
    if fam_idx.size < n_target:
        pad = rng.choice(np.arange(len(pool)), size=n_target - fam_idx.size, p=w / w.sum())
        fam_idx = np.concatenate([fam_idx, pad])
    rng.shuffle(fam_idx)

    f = pool.iloc[fam_idx].reset_index(drop=True)
    n = len(f)

    price = f["price_min_sar"].to_numpy() + rng.random(n) * (
        f["price_max_sar"].to_numpy() - f["price_min_sar"].to_numpy()
    )
    lead = (
        f["lead_min_days"].to_numpy()
        + rng.random(n) * (f["lead_max_days"].to_numpy() - f["lead_min_days"].to_numpy())
    ).astype(np.int32)

    # per-family manufacturer pool: never a bearing maker on a haul-truck tyre
    canonical = np.empty(n, dtype=object)
    for kind, grp in f.groupby("manufacturers").groups.items():
        makers = np.array(str(kind).split("|"))
        g = np.asarray(grp)
        canonical[g] = rng.choice(makers, size=len(g))

    # per-family characteristics: a bearing gets "6205, SS316", an oil "ISO VG 220,
    # GRADE B". Generated per family so that no two variants of the same family read
    # the same, which is what makes an identical description meaningful.
    token = np.empty(n, dtype=object)
    for (_fam, kind), grp in f.groupby(["family_id", "size_token_type"]).groups.items():
        g = np.asarray(grp)
        token[g] = _unique_variants(str(kind), len(g), rng)

    # attach materials only to assets of the type the family actually fits
    by_type = {
        t: equipment.loc[equipment["equipment_type"] == t, "equipment_id"].to_numpy()
        for t in equipment["equipment_type"].unique()
    }
    generic = equipment.loc[
        equipment["equipment_type"].isin(["GENERIC", "MECH_GENERIC"]), "equipment_id"
    ].to_numpy()
    fallback = generic if generic.size else equipment["equipment_id"].to_numpy()

    owner = np.empty(n, dtype=object)
    for etype, grp in f.groupby("equipment_type").groups.items():
        g = np.asarray(grp)
        pool_eq = by_type.get(str(etype))
        pool_eq = pool_eq if pool_eq is not None and pool_eq.size else fallback
        owner[g] = rng.choice(pool_eq, size=len(g))

    # Criticality follows what the part IS, not the equipment lottery: a spare
    # transformer is A because it is a transformer. Assigning it from the owning
    # asset produced B-rated transformers and A-rated washers, and because
    # dead-money valuation keys off criticality, one mis-grade was SAR 2.3m of
    # apparent waste. The equipment link still drives obsolescence, and an item on
    # an A-rated asset is bumped a grade.
    bias = f["crit_bias"].to_numpy()
    crit = np.where(rng.random(n) < 0.12, rng.choice(np.array(S.CRITICALITY), size=n), bias)
    eq_crit = equipment.set_index("equipment_id")["criticality"].reindex(owner).to_numpy()
    bump = {"C": "B", "B": "A", "A": "A"}
    crit = np.where(eq_crit == "A", [bump[c] for c in crit], crit)

    # scatter the manufacturer spelling for a share of rows
    shown = canonical.copy()
    for i, maker in enumerate(canonical):
        variants = _MAKER_VARIANTS.get(str(maker))
        if variants and rng.random() < 0.35:
            shown[i] = rng.choice(np.array(variants))

    desc = [f"{a}, {b}, {c}" for a, b, c in zip(f["noun"], f["modifier"], token, strict=True)]
    mpn_num = rng.integers(1000, 999999, size=n)
    prefix = [str(m).split()[0][:3].upper().replace(".", "") for m in canonical]

    materials = pd.DataFrame(
        {
            "material_id": [f"M-{i:06d}" for i in range(1, n + 1)],
            "material_group": f["material_group"].to_numpy(),
            "noun": f["noun"].to_numpy(),
            "modifier": f["modifier"].to_numpy(),
            "description": desc,
            "manufacturer": shown,
            "mpn": [f"{p}-{v}" for p, v in zip(prefix, mpn_num, strict=True)],
            "uom": f["uom"].to_numpy(),
            "unit_price_sar": np.round(price, 2),
            "lead_time_days": lead,
            "area": f["area"].to_numpy(),
            "equipment_id": owner,
            "criticality": crit,
            "is_mro": True,
        }
    )
    # family and behaviour stay out of the source tables; they live in the answer key
    hidden = pd.DataFrame(
        {
            "material_id": materials["material_id"].to_numpy(),
            "family_id": f["family_id"].to_numpy(),
            "seed_profile": f["profile"].to_numpy(),
            "mtbf_years": f["mtbf_years"].to_numpy(dtype=float),
            "multi_store_share": f["multi_store_share"].to_numpy(dtype=float),
            "shutdown_mult": f["shutdown_demand_mult"].to_numpy(dtype=float),
            "canonical_manufacturer": canonical,
            "area": f["area"].to_numpy(),
        }
    )
    return materials, hidden


# ── positions ────────────────────────────────────────────────────────────────


def build_positions(cfg: RunConfig, materials: pd.DataFrame, hidden: pd.DataFrame, rng):
    """
    One row per (material, storeroom). Most materials sit only in their home store;
    a share set per family also sit in CENTRAL or a sibling plant, splitting the
    item's demand between them.

    Without this, capability 5 has no data at all: there is no "one store holds 40
    idle while another is about to buy five" if every material exists exactly once.
    """
    home = materials["area"].map(STOREROOM_BY_AREA).to_numpy()
    share = hidden["multi_store_share"].to_numpy()
    ids = materials["material_id"].to_numpy()
    n = len(materials)

    rows: list[tuple[str, str, bool, float]] = []
    others_all = np.array(S.STOREROOMS)

    for i in range(n):
        extra: list[str] = []
        if rng.random() < share[i]:
            others = others_all[others_all != home[i]]
            k = min(1 + int(rng.random() < 0.35), cfg.multi_store.extra_stores_max, len(others))
            # CENTRAL is the usual second home for site-wide spares
            w = np.array([3.0 if s == "CENTRAL" else 1.0 for s in others])
            extra = list(rng.choice(others, size=k, replace=False, p=w / w.sum()))

        if not extra:
            rows.append((ids[i], home[i], True, 1.0))
            continue

        secondary = rng.uniform(*cfg.multi_store.secondary_demand_share, size=len(extra))
        if secondary.sum() > 0.75:                     # the home store keeps the majority
            secondary = secondary / secondary.sum() * 0.75
        rows.append((ids[i], home[i], True, float(1.0 - secondary.sum())))
        for s, frac in zip(extra, secondary, strict=True):
            rows.append((ids[i], str(s), False, float(frac)))

    return pd.DataFrame(rows, columns=["material_id", "storeroom_id", "is_home", "demand_share"])
