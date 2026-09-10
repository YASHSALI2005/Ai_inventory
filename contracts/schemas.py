"""
Table contracts for every Parquet file the pipeline reads or writes.

This module is the ONLY thing every layer is allowed to import. It deliberately
contains no logic beyond validation — so `engine/` can depend on it without
gaining a path to `generator/`, `sim/` or the answer key.

Each schema declares its columns and pandas dtypes. `validate()` is strict about
missing columns, extra columns and dtype drift, because a silently renamed column
in a generated file surfaces four steps later as a wrong number in a demo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# ── enumerations, kept as plain tuples so they can be used in validation ──────

STOREROOMS = ("BAITHA", "REFINERY", "SMELTER", "ROLLING", "CENTRAL")
PLANTS = ("MINE", "RAIL", "REFINERY", "SMELTER", "ROLLING", "SITEWIDE")

CRITICALITY = ("A", "B", "C")
EQUIPMENT_STATUS = ("RUNNING", "DECOMMISSIONED")

# How an item behaves in the simulation. This is the *truth* label, derived from
# each item's realised demand interval rather than from its seed family, so the
# label cannot contradict the parameters beside it.
DEMAND_PROFILE = ("consumable", "occasional", "lumpy", "insurance")

# Syntetos-Boylan-Croston quadrants, produced by the engine's classifier in step 3.
DEMAND_CLASS = ("smooth", "erratic", "intermittent", "lumpy")

# Tolerance table for scoring the step-3 classifier against truth. Many-to-many on
# purpose: a truth profile constrains which SBC quadrant is reasonable but does not
# determine it, because the quadrant also depends on demand-size variability, which
# the profile says nothing about. Scoring an exact 1:1 match would punish the
# classifier for being right.
PROFILE_TO_SBC_CLASS: dict[str, tuple[str, ...]] = {
    "consumable": ("smooth", "erratic"),
    # `lumpy` added 2026-09-10 on measured evidence: a part used only occasionally
    # but in wildly varying amounts IS lumpy by the Syntetos-Boylan definition, and
    # every one of the 1,401 parts previously marked wrong genuinely had size
    # variability above the CV-squared cutoff. The table was one entry short.
    "occasional": ("intermittent", "erratic", "lumpy"),
    "lumpy": ("lumpy", "intermittent"),
    "insurance": ("intermittent", "lumpy"),
}

MOVEMENT_TYPES = ("ISSUE", "RECEIPT", "TRANSFER_IN", "TRANSFER_OUT", "RETURN", "ADJUST")

WORK_ORDER_TYPES = ("PLANNED", "BREAKDOWN", "SHUTDOWN")

# Defect families we plant deliberately and score as found / missed / false alarm.
# Overstock, obsolescence and critical-below-reorder are NOT here: those emerge
# from the simulation and are scored against `truth`, not against a planted list.
PLANTED_DEFECT_TYPES = (
    "NEGATIVE_STOCK",
    "BLANK_MPN",
    "BLANK_UOM",
    "UOM_MISMATCH",
    "DUPLICATE_MATERIAL",
    "IMPOSSIBLE_LEAD_TIME",
    "ISSUE_WITHOUT_WORK_ORDER",
)

# Findings the engine may legitimately raise that have no planted counterpart.
# They are reported with counts but excluded from precision, because counting them
# as false alarms would penalise the engine for finding real problems.
INFORMATIONAL_DEFECT_TYPES = (
    "LEDGER_MISMATCH",
    "WO_DATE_AFTER_ISSUE",
    "STALE_LEVELS",
)

# Sentinel for FINDINGS.movement_id: Parquet int64 has no null, and a nullable
# extension dtype would complicate every consumer for one column.
NO_MOVEMENT = -1


@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: dict[str, str]          # column name -> pandas dtype
    key: tuple[str, ...]             # uniqueness key
    doc: str = ""

    @property
    def names(self) -> list[str]:
        return list(self.columns)


# ── source tables — the three "notebooks" the generator fakes ────────────────

MATERIALS = TableSchema(
    name="materials",
    doc=(
        "The PiLog side: what each part IS. No quantities live here.\n\n"
        "There is deliberately no `family_id`. A real SAP/PiLog extract has no "
        "column that says 'these two rows are the same part family', and leaving "
        "one in would let the duplicate matcher and the UOM check read the answer "
        "off the data. What a real extract DOES have is a coarse material group "
        "(SAP MATKL), so `material_group` is present: it lumps several seed "
        "families together, which is a hint the engine can use and not a giveaway.\n\n"
        "`manufacturer` is intentionally un-normalised: the same maker appears as "
        "'SKF', 'S.K.F.' and 'SKF AB'. Normalising it is the matcher's job.\n\n"
        "`unit_price_sar` is the purchasing list price, used for replenishment "
        "cost. Dead money is valued at `stock.avg_unit_cost_sar` (SAP moving "
        "average), which is what the business would actually write off."
    ),
    key=("material_id",),
    columns={
        "material_id": "string",
        "material_group": "string",    # coarse, SAP MATKL analogue — not the family
        "noun": "string",              # ISO 8000 noun
        "modifier": "string",          # ISO 8000 modifier
        "description": "string",       # rendered short description
        "manufacturer": "string",      # un-normalised on purpose
        "mpn": "string",               # manufacturer part number
        "uom": "string",
        "unit_price_sar": "float64",
        "lead_time_days": "int32",
        "area": "string",              # which plant area it serves
        "equipment_id": "string",      # owning equipment, "" if site-wide
        "criticality": "string",       # from what the part IS, bumped on an A asset
        "is_mro": "bool",              # false for process raw materials
        # Planner's estimate of how long a capital spare lasts, in years. NaN for
        # anything that is not a capital spare. This is the only thing available for
        # a part that has never once been issued, and it is an ESTIMATE — noisy, and
        # deliberately not equal to the true failure interval in the answer key. A
        # planning system holds somebody's judgement, not the truth.
        "expected_life_years": "float64",
    },
)

EQUIPMENT = TableSchema(
    name="equipment",
    doc="The CMMS side: the machines, how critical they are, whether they still exist.",
    key=("equipment_id",),
    columns={
        "equipment_id": "string",
        "equipment_type": "string",    # POT, SLURRY_PUMP, MILL_STAND, ...
        "plant": "string",
        "storeroom_id": "string",
        "name": "string",              # from seeds/equipment_types.csv name_pattern
        "criticality": "string",
        "status": "string",
        "commissioned_date": "datetime64[ns]",
        "decommissioned_date": "datetime64[ns]",   # NaT while running
    },
)

STOCK = TableSchema(
    name="stock",
    doc=(
        "The SAP side: one row per POSITION — a material in a storeroom. A material "
        "can be stocked in several storerooms, which is what makes capability 5 "
        "(transfers) have anything to work with.\n\n"
        "`min_qty`/`max_qty` are the plant's existing stale policy. Excess and "
        "stockouts in the generated history are a consequence of running it, not of "
        "injection."
    ),
    key=("material_id", "storeroom_id"),
    columns={
        "material_id": "string",
        "storeroom_id": "string",
        "on_hand": "float64",
        "min_qty": "float64",
        "max_qty": "float64",
        "last_issue_date": "datetime64[ns]",
        "last_receipt_date": "datetime64[ns]",
        "avg_unit_cost_sar": "float64",   # SAP moving average — values dead money
    },
)

MOVEMENTS = TableSchema(
    name="movements",
    doc=(
        "Three years of goods movements. qty is signed: issues and returns-to-vendor "
        "negative, receipts positive.\n\n"
        "Every position opens with an ADJUST on day 0 carrying its opening balance, "
        "so `sum(qty) == on_hand` holds for every position that was not planted "
        "negative. That identity is what makes a ledger-reconciliation check "
        "possible, and it is the strongest data-quality check there is."
    ),
    key=("movement_id",),
    columns={
        "movement_id": "int64",
        "date": "datetime64[ns]",
        "material_id": "string",
        "storeroom_id": "string",
        "movement_type": "string",
        "qty": "float64",
        "work_order_id": "string",     # "" for receipts and for planted orphan issues
        "unit_cost_sar": "float64",
    },
)

WORK_ORDERS = TableSchema(
    name="work_orders",
    doc=(
        "Maintenance jobs. `created_date` is when the job was raised and "
        "`planned_date` when it was scheduled to happen — both well before the "
        "issue for PLANNED and SHUTDOWN work. Those two columns are what 'known "
        "future demand' means in step 4; a planned job created the day it consumes "
        "parts gives a forecaster nothing to know in advance."
    ),
    key=("work_order_id",),
    columns={
        "work_order_id": "string",
        "equipment_id": "string",
        "date": "datetime64[ns]",          # when the parts were issued
        "created_date": "datetime64[ns]",  # when the job was raised
        "planned_date": "datetime64[ns]",  # scheduled date; NaT for BREAKDOWN
        "wo_type": "string",
        "shutdown_id": "string",           # "" unless part of a shutdown
    },
)

SHUTDOWNS = TableSchema(
    name="shutdowns",
    doc=(
        "Planned outages, and the spikes a forecast is allowed to know about. "
        "`scheduled_on` is when the outage was put in the calendar."
    ),
    key=("shutdown_id",),
    columns={
        "shutdown_id": "string",
        "plant": "string",
        "start_date": "datetime64[ns]",
        "end_date": "datetime64[ns]",
        "scheduled_on": "datetime64[ns]",
    },
)

SOURCE_TABLES = (MATERIALS, EQUIPMENT, STOCK, MOVEMENTS, WORK_ORDERS, SHUTDOWNS)


# ── answer key — written by the generator, never read by the engine ──────────

TRUTH_MATERIALS = TableSchema(
    name="truth_materials",
    doc=(
        "Per-material ground truth: what the item actually is, and what the "
        "simulation actually used. `seed_profile` is the family's label from the "
        "seed file and is kept only for debugging; `true_profile` is derived from "
        "the realised interval and is what scoring uses."
    ),
    key=("material_id",),
    columns={
        "material_id": "string",
        "true_family_id": "string",         # removed from source on purpose
        "seed_profile": "string",           # family label, debugging only
        "true_profile": "string",           # derived from realised interval
        "true_demand_interval_days": "float64",
        "true_demand_size_mean": "float64",
        "true_demand_size_cv": "float64",
        "true_mtbf_years": "float64",       # NaN unless a capital spare
        "true_equipment_status": "string",
        "true_is_obsolete": "bool",
        "true_lead_time_days": "int32",
        "true_manufacturer": "string",      # canonical form, before mangling
        "is_duplicate_of": "string",        # "" unless this row is a planted copy
    },
)

TRUTH_POSITIONS = TableSchema(
    name="truth_positions",
    doc=(
        "Per-position ground truth, keyed the same way as `stock`. Dead money, "
        "obsolescence and stockout risk are scored against THIS, because they "
        "emerge from the simulation rather than being planted."
    ),
    key=("material_id", "storeroom_id"),
    columns={
        "material_id": "string",
        "storeroom_id": "string",
        "true_annual_demand": "float64",
        "true_justified_qty": "float64",    # from cfg.dead_money.justified_qty
        "true_opening_qty": "float64",
        "true_had_commissioning": "bool",
        "true_is_home_store": "bool",
    },
)

ANSWER_KEY_TABLES = (TRUTH_MATERIALS, TRUTH_POSITIONS)

# planted_defects.json — a list of objects with this shape:
#   {"defect_id": str, "defect_type": one of PLANTED_DEFECT_TYPES,
#    "table": str, "key": {...}, "detail": str, "shadowed_by": str | None}
PLANTED_DEFECTS_FILE = "planted_defects.json"


# ── result tables — written by the engine, read by the API ───────────────────

FINDINGS = TableSchema(
    name="findings",
    doc=(
        "Step 2 output: one row per data-quality problem the engine believes it "
        "found. `movement_id` is NO_MOVEMENT (-1) unless the finding is about a "
        "specific movement; `related_material_id` carries the other half of a "
        "duplicate pair. Without those two columns, orphan issues and duplicates "
        "cannot be scored at all."
    ),
    key=("finding_id",),
    columns={
        "finding_id": "string",
        "defect_type": "string",
        "table": "string",
        "material_id": "string",
        "storeroom_id": "string",
        "movement_id": "int64",
        "related_material_id": "string",
        "detail": "string",
        "confidence": "float64",
    },
)

RUN_MANIFEST_FILE = "run_manifest.json"
# {"seed": int, "preset": str, "cutoff_date": "YYYY-MM-DD", ...,
#  "git_sha": str, "generated_at": ISO8601, "config_hash": str}

# Written by the engine, listing every check that actually ran. Scoring reads this
# rather than inferring "implemented" from the finding types present — otherwise a
# check that ran and found nothing is indistinguishable from one nobody has
# written, and a 100% miss is reported as work-not-started.
IMPLEMENTED_CHECKS_FILE = "implemented_checks.json"


# ── validation ───────────────────────────────────────────────────────────────


class SchemaError(ValueError):
    """Raised when a frame does not match its declared contract."""


def validate(df: pd.DataFrame, schema: TableSchema, *, check_key: bool = True) -> pd.DataFrame:
    """Check `df` against `schema`, returning it with columns in declared order."""
    missing = [c for c in schema.names if c not in df.columns]
    extra = [c for c in df.columns if c not in schema.columns]
    if missing:
        raise SchemaError(f"{schema.name}: missing columns {missing}")
    if extra:
        raise SchemaError(f"{schema.name}: unexpected columns {extra}")

    out = df[schema.names]
    wrong = {
        c: (str(out[c].dtype), want)
        for c, want in schema.columns.items()
        if str(out[c].dtype) != want
    }
    if wrong:
        raise SchemaError(f"{schema.name}: dtype mismatch {wrong}")

    if check_key:
        dupes = int(out.duplicated(subset=list(schema.key)).sum())
        if dupes:
            raise SchemaError(f"{schema.name}: {dupes} rows duplicate key {schema.key}")
    return out


def coerce(df: pd.DataFrame, schema: TableSchema) -> pd.DataFrame:
    """Cast a frame to its declared dtypes, then validate. Use at write time."""
    out = df.copy()
    for col, dtype in schema.columns.items():
        if col not in out.columns:
            raise SchemaError(f"{schema.name}: cannot coerce, missing column {col!r}")
        out[col] = out[col].astype(dtype)
    return validate(out, schema)


def empty(schema: TableSchema) -> pd.DataFrame:
    """A correctly typed zero-row frame, so callers never build one by hand."""
    return pd.DataFrame({c: pd.Series(dtype=d) for c, d in schema.columns.items()})


def write(df: pd.DataFrame, schema: TableSchema, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{schema.name}.parquet"
    coerce(df, schema).to_parquet(path, index=False)
    return path


def read(schema: TableSchema, directory: Path) -> pd.DataFrame:
    path = directory / f"{schema.name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{schema.name} not generated yet: {path}")
    return validate(pd.read_parquet(path), schema)
