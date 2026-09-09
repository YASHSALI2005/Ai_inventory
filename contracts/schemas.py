"""
Table contracts for every Parquet file the pipeline reads or writes.

This module is the ONLY thing every layer is allowed to import. It deliberately
contains no logic beyond validation — so that `engine/` can depend on it without
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

# How an item behaves in the simulation. This is the *truth* label; the engine's
# classifier produces its own label in step 3 and is scored against this one.
DEMAND_PROFILE = ("consumable", "occasional", "lumpy", "insurance")

# Syntetos-Boylan-Croston quadrants, produced by the engine in step 3.
DEMAND_CLASS = ("smooth", "erratic", "intermittent", "lumpy")

MOVEMENT_TYPES = ("ISSUE", "RECEIPT", "TRANSFER_IN", "TRANSFER_OUT", "RETURN", "ADJUST")

WORK_ORDER_TYPES = ("PLANNED", "BREAKDOWN", "SHUTDOWN")

# Defect families we plant deliberately and score as found / missed / false alarm.
# Overstock, obsolescence and critical-below-ROP are NOT here: those must emerge
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
    doc="The PiLog side: what each part IS. No quantities live here.",
    key=("material_id",),
    columns={
        "material_id": "string",
        "family_id": "string",
        "noun": "string",              # ISO 8000 noun
        "modifier": "string",          # ISO 8000 modifier
        "description": "string",       # rendered short description
        "manufacturer": "string",
        "mpn": "string",               # manufacturer part number
        "uom": "string",
        "unit_price_sar": "float64",
        "lead_time_days": "int32",
        "area": "string",              # which plant area it serves
        "equipment_id": "string",      # owning equipment, "" if site-wide
        "criticality": "string",       # inherited from equipment
    },
)

EQUIPMENT = TableSchema(
    name="equipment",
    doc="The CMMS side: the machines, how critical they are, whether they still exist.",
    key=("equipment_id",),
    columns={
        "equipment_id": "string",
        "plant": "string",
        "storeroom_id": "string",
        "name": "string",
        "criticality": "string",
        "status": "string",
        "commissioned_date": "datetime64[ns]",
        "decommissioned_date": "datetime64[ns]",   # NaT while running
    },
)

STOCK = TableSchema(
    name="stock",
    doc=(
        "The SAP side: current position per material per storeroom, including the "
        "plant's existing (stale, mediocre) min/max policy. Excess and stockouts in "
        "the generated history are a consequence of this policy, not of injection."
    ),
    key=("material_id", "storeroom_id"),
    columns={
        "material_id": "string",
        "storeroom_id": "string",
        "on_hand": "float64",
        "min_qty": "float64",          # the incumbent policy we will be measured against
        "max_qty": "float64",
        "last_issue_date": "datetime64[ns]",
        "last_receipt_date": "datetime64[ns]",
        "avg_unit_cost_sar": "float64",
    },
)

MOVEMENTS = TableSchema(
    name="movements",
    doc="Three years of goods movements. qty is signed: issues negative, receipts positive.",
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
    doc="Maintenance jobs. Planned ones are known future demand; breakdowns are not.",
    key=("work_order_id",),
    columns={
        "work_order_id": "string",
        "equipment_id": "string",
        "date": "datetime64[ns]",
        "wo_type": "string",
        "shutdown_id": "string",       # "" unless part of a shutdown
    },
)

SHUTDOWNS = TableSchema(
    name="shutdowns",
    doc="Planned outages. These are the spikes a forecast is allowed to know about.",
    key=("shutdown_id",),
    columns={
        "shutdown_id": "string",
        "plant": "string",
        "start_date": "datetime64[ns]",
        "end_date": "datetime64[ns]",
    },
)

SOURCE_TABLES = (MATERIALS, EQUIPMENT, STOCK, MOVEMENTS, WORK_ORDERS, SHUTDOWNS)


# ── answer key — written by the generator, never read by the engine ──────────

TRUTH = TableSchema(
    name="truth",
    doc=(
        "Per-material ground truth: the parameters the simulation actually used. "
        "Dead money, obsolescence and stockout risk are scored against THIS, because "
        "they emerge from the simulation rather than being planted."
    ),
    key=("material_id",),
    columns={
        "material_id": "string",
        "true_profile": "string",          # DEMAND_PROFILE
        "true_demand_interval_days": "float64",   # mean gap between demands
        "true_demand_size_mean": "float64",
        "true_demand_size_cv": "float64",
        "true_annual_demand": "float64",
        "true_equipment_status": "string",  # RUNNING / DECOMMISSIONED
        "true_is_obsolete": "bool",         # owning equipment gone before history end
        "true_lead_time_days": "int32",
    },
)

# planted_defects.json — a list of objects with this shape:
#   {"defect_id": str, "defect_type": one of PLANTED_DEFECT_TYPES,
#    "table": str, "key": {...}, "detail": str}
PLANTED_DEFECTS_FILE = "planted_defects.json"


# ── result tables — written by the engine, read by the API ───────────────────

FINDINGS = TableSchema(
    name="findings",
    doc="Step 2 output: one row per data-quality problem the engine believes it found.",
    key=("finding_id",),
    columns={
        "finding_id": "string",
        "defect_type": "string",
        "table": "string",
        "material_id": "string",
        "storeroom_id": "string",
        "detail": "string",
        "confidence": "float64",
    },
)

RUN_MANIFEST_FILE = "run_manifest.json"
# {"seed": int, "preset": str, "cutoff_date": "YYYY-MM-DD", "history_start": ...,
#  "history_end": ..., "git_sha": str, "generated_at": ISO8601, "config_hash": str}


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
