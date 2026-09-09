"""
Run configuration — the single source of truth for seed, dataset size, the
train/evaluate time split, and the cost model.

Two things here are load-bearing:

1. `cutoff_date` lives in config, not in a notebook. Every fitting step must call
   `cfg.train_slice()` and every evaluation step `cfg.eval_slice()`, so it is not
   possible to accidentally evaluate on data the model was fitted on.

2. `shortage_cost_per_unit()` is defined ONCE here and reused by the newsvendor
   service level (step 5), the work-queue SAR ranking (step 7) and dead-money
   valuation (step 6). Three places computing "what does being short cost" three
   different ways is how a demo ends up contradicting itself on stage.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, model_validator

Preset = Literal["toy", "full"]

ROOT = Path(__file__).resolve().parent.parent


class SizePreset(BaseModel):
    """Dataset dimensions. `toy` must build in seconds so tests can use it."""

    n_materials: int
    n_equipment: int
    n_shutdowns_per_year: int


PRESETS: dict[Preset, SizePreset] = {
    "toy": SizePreset(n_materials=300, n_equipment=20, n_shutdowns_per_year=1),
    "full": SizePreset(n_materials=20_000, n_equipment=420, n_shutdowns_per_year=3),
}


class CostModel(BaseModel):
    """Turns criticality into money. The only place shortage cost is defined."""

    holding_rate_per_year: float = 0.25          # storage, handling, insurance, write-down

    # Cost of being short for one unit for one day, as a multiple of unit price.
    # A-criticality means the plant stops; C means someone waits.
    shortage_multiplier: dict[str, float] = Field(
        default_factory=lambda: {"A": 40.0, "B": 6.0, "C": 1.0}
    )

    # Bounds on the newsvendor-derived service level, so the maths cannot produce
    # something operationally silly like 0.42 or 0.9999 for a real item.
    service_level_floor: float = 0.50
    service_level_cap: float = 0.995

    expedite_premium: float = 4.0                # 3-5x band, midpoint used for valuation

    def shortage_cost_per_unit_day(self, unit_price_sar: float, criticality: str) -> float:
        return unit_price_sar * self.shortage_multiplier.get(criticality, 1.0)

    def holding_cost_per_unit_day(self, unit_price_sar: float) -> float:
        return unit_price_sar * self.holding_rate_per_year / 365.0

    def critical_fractile(self, unit_price_sar: float, criticality: str) -> float:
        """Newsvendor service level for one item, from its own economics."""
        short = self.shortage_cost_per_unit_day(unit_price_sar, criticality)
        hold = self.holding_cost_per_unit_day(unit_price_sar)
        if short + hold <= 0:
            return self.service_level_floor
        raw = short / (short + hold)
        return min(max(raw, self.service_level_floor), self.service_level_cap)


class DemandShaping(BaseModel):
    """
    Controls how a family's demand is split across its variants.

    This is the single lever that decides whether the generated master looks like
    a real MRO storeroom (a minority of line items carrying most movement, 30-50%
    idle for two years) or like a supermarket (everything moving weekly).

    `breadth_exponent` stretches an item's demand interval by how broad its family
    is; `popularity_sigma` is the spread of the per-item lognormal on top. Both are
    driven off the seed file's variant_weight rather than the realised item count,
    so the toy preset behaves like the full one.
    """

    # tuned so the toy preset lands mid-band on idle-24-month share; see tests
    breadth_exponent: float = 0.85
    popularity_sigma: float = 1.30

    # Target the generator is tuned against, asserted in tests. Industry reports
    # 30-50% of MRO lines not moving in 24 months; we aim inside that band.
    target_idle_24m_share: tuple[float, float] = (0.30, 0.50)


class CommissioningStock(BaseModel):
    """
    Spares bought as a package when the plant was built, and never consumed.

    This is the largest single source of dead money in a real MRO storeroom and it
    is heavily weighted to expensive, slow-moving items — a commissioning package
    buys one of everything, including the spares for failures that never happened.
    Ma'aden's Ras Al Khair complex was commissioned 2013-15, so by our history
    window this stock is a decade old.

    It is not a planted defect. It is an opening balance, and whether an item is
    still carrying it at the end of history depends on whether demand ever showed
    up — which is exactly the judgement the engine has to make.
    """

    # Applies to capital spares only — the lumpy and insurance profiles. A
    # commissioning package buys one or two of the things that would stop the
    # plant, not forty years of gaskets. Sizing it in "years of demand" was wrong:
    # on an item with real turnover it produced 2,000 UPS batteries, and dead money
    # became an artefact of the generator rather than a property of the plant.
    share: float = 0.35                      # of capital-spare line items
    units: tuple[float, float] = (1.0, 4.0)  # absolute units bought, per item
    applies_to: tuple[str, ...] = ("lumpy", "insurance")


class StalePolicy(BaseModel):
    """
    The incumbent min/max the simulated plant runs on — deliberately mediocre.

    This is what produces emergent overstock and emergent stockouts, and it is the
    baseline our step-5 policy is measured against. It is stale in two ways: the
    levels were set from a snapshot of demand at `set_on_offset_days` and never
    revisited, and they ignore criticality entirely.
    """

    set_on_offset_days: int = 120        # levels frozen this far into history
    min_cover_days: float = 45.0         # one blanket cover figure for everything
    max_cover_days: float = 180.0
    round_up_to: float = 1.0
    # Fraction of items whose levels are additionally wrong by a large factor,
    # mimicking levels copied across sites or entered by hand.
    fat_finger_share: float = 0.12
    fat_finger_factor: float = 6.0
    # Error rate is damped for items above this price — expensive mistakes get
    # caught at purchase approval, cheap ones sit for years.
    fat_finger_value_pivot: float = 2000.0


class RunConfig(BaseModel):
    seed: int = 20260909
    preset: Preset = "toy"

    history_start: date = date(2023, 9, 1)
    history_end: date = date(2026, 8, 31)
    # Everything is FITTED on data up to and including this date, and EVALUATED
    # strictly after it. Two years train, one year evaluate.
    cutoff_date: date = date(2025, 8, 31)

    forecast_horizon_days: int = 180

    # Precomputed for the scenario slider; the UI interpolates between these.
    service_level_sweep: list[float] = Field(
        default_factory=lambda: [round(0.80 + 0.01 * i, 2) for i in range(20)]
    )

    costs: CostModel = Field(default_factory=CostModel)
    demand: DemandShaping = Field(default_factory=DemandShaping)
    commissioning: CommissioningStock = Field(default_factory=CommissioningStock)
    stale_policy: StalePolicy = Field(default_factory=StalePolicy)

    data_dir: Path = ROOT / "data"
    seeds_dir: Path = ROOT / "seeds"

    @model_validator(mode="after")
    def _check_dates(self) -> RunConfig:
        if not self.history_start < self.cutoff_date < self.history_end:
            raise ValueError(
                f"cutoff_date {self.cutoff_date} must fall strictly inside "
                f"[{self.history_start}, {self.history_end}]"
            )
        if (self.history_end - self.cutoff_date).days < self.forecast_horizon_days:
            raise ValueError(
                "evaluation window is shorter than the forecast horizon: "
                f"{(self.history_end - self.cutoff_date).days}d available, "
                f"{self.forecast_horizon_days}d needed"
            )
        return self

    # ── derived ──────────────────────────────────────────────────────────────

    @property
    def size(self) -> SizePreset:
        return PRESETS[self.preset]

    @property
    def n_days(self) -> int:
        return (self.history_end - self.history_start).days + 1

    @property
    def source_dir(self) -> Path:
        return self.data_dir / self.preset / "source"

    @property
    def answer_key_dir(self) -> Path:
        return self.data_dir / self.preset / "answer_key"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / self.preset / "results"

    def train_slice(self, df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
        """Rows a model is allowed to learn from."""
        d = pd.to_datetime(df[date_col])
        return df[(d >= pd.Timestamp(self.history_start)) & (d <= pd.Timestamp(self.cutoff_date))]

    def eval_slice(self, df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
        """Rows a model is only ever scored on."""
        d = pd.to_datetime(df[date_col])
        return df[(d > pd.Timestamp(self.cutoff_date)) & (d <= pd.Timestamp(self.history_end))]

    def day_index(self, when: date) -> int:
        return (when - self.history_start).days

    def date_of(self, day_index: int) -> date:
        return self.history_start + timedelta(days=int(day_index))

    def config_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"data_dir", "seeds_dir"})
        blob = json.dumps(payload, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:12]

    @classmethod
    def load(cls, path: Path | None = None, **overrides) -> RunConfig:
        base: dict = {}
        if path is not None and path.exists():
            import yaml

            base = yaml.safe_load(path.read_text()) or {}
        return cls(**{**base, **overrides})
