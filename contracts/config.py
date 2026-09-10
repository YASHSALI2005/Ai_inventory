"""
Run configuration — the single source of truth for seed, dataset size, the
train/evaluate time split, and the cost model.

Three things here are load-bearing:

1. `cutoff_date` lives in config, not in a notebook. Every fitting step calls
   `cfg.train_slice()` and every evaluation step `cfg.eval_slice()`, so it is not
   possible to accidentally evaluate on data a model was fitted on.

2. `CostModel` defines shortage cost ONCE. It feeds the newsvendor service level
   (step 5), the work-queue SAR ranking (step 7) and dead-money valuation (step 6).
   Three places computing "what does being short cost" three different ways is how
   a demo ends up contradicting itself on stage.

3. `DeadMoneyRule` defines what counts as dead ONCE, read by the generator tests,
   by scoring and by the engine — so the number in the test, the number on the
   dashboard and the number in the scoreboard cannot diverge.
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

    # Toy must be thick enough that a test proves something: with one
    # decommissioned asset and one planted defect per type, every score is 0% or
    # 100% by luck.
    min_decommissioned: int = 3
    min_defects_per_type: int = 3

    # Dead value is a VALUE-weighted share, so at 300 materials a handful of
    # expensive rows decide it and it swings several points on any reshuffle of the
    # random stream. The industry band is asserted where it means something — at
    # full scale — and toy gets a sanity range instead, so a genuinely broken
    # generator still fails there.
    dead_value_band: tuple[float, float] = (0.05, 0.60)

    # Same reasoning: with three shutdowns and 300 parts the measured multiple is a
    # small-sample statistic. The real target is asserted at full scale; toy only has
    # to show the outage has a visible effect at all.
    shutdown_multiple_min: float = 1.5


PRESETS: dict[Preset, SizePreset] = {
    "toy": SizePreset(n_materials=300, n_equipment=40, n_shutdowns_per_year=1),
    "full": SizePreset(
        n_materials=20_000,
        n_equipment=420,
        n_shutdowns_per_year=3,
        min_decommissioned=20,
        min_defects_per_type=10,
        dead_value_band=(0.20, 0.40),      # the industry band, asserted at scale
        shutdown_multiple_min=3.0,
    ),
}


class CostModel(BaseModel):
    """
    Turns criticality into money. The only place shortage cost is defined.

    The units matter, and were wrong in the first cut: shortage was expressed per
    unit-*day* and holding per unit-*day*, giving a ratio around 58,000 for an A
    item. The newsvendor fractile then pinned to its cap for all three
    criticalities, so "service level from each item's own economics" was doing
    nothing and the scenario slider would have drawn a flat line.

    Both sides of the fractile are now on the same footing: the cost of being short
    once, against the cost of holding one unit for a year.
    """

    holding_rate_per_year: float = 0.25          # storage, handling, insurance, write-down

    # What an hour of not having the part costs, by how badly its absence hurts.
    #
    # This replaces a multiple of unit price, which was wrong in a way the screens
    # made obvious: a SAR 2.2M spare transformer and a SAR 4 gasket can stop the
    # same potline, and pricing the shortage off the part made the transformer look
    # 550,000 times more urgent. Downtime does not care what the part cost.
    #
    # Defensible, and deliberately conservative. Ma'aden Aluminium turns over
    # roughly SAR 39bn a year across the integrated chain, on the order of SAR 100m
    # a day, and a real potline outage costs a large fraction of that. These figures
    # are far below it on purpose, and the reason is the unit they are in: this is
    # the production loss attributable to ONE UNIT of ONE part being unavailable for
    # one day — not the cost of a whole-plant stoppage. The synthetic plant runs
    # 644,232 unit-shortages a year under its own stale levels; charging a real
    # potline outage against each of them produces a shortage bill of SAR 10bn
    # against SAR 1.4bn of inventory, which is an arithmetic artefact and not a
    # finding. Calibrated instead so the shortage bill sits in the same order of
    # magnitude as the holding bill, which is where a cost model has to sit if the
    # total is going to mean anything.
    # Every one of these should be replaced by the plant's own figure in Phase 1.
    downtime_cost_per_day_sar: dict[str, float] = Field(
        default_factory=lambda: {"A": 30_000.0, "B": 4_000.0, "C": 100.0}
    )

    # How long the plant is down for before the missing part can be got hold of.
    # An A spare is air-freighted and fitted; nobody expedites a C-class washer.
    expedite_days: dict[str, float] = Field(
        default_factory=lambda: {"A": 7.0, "B": 14.0, "C": 21.0}
    )

    service_level_floor: float = 0.50
    service_level_cap: float = 0.995

    expedite_premium: float = 4.0                # 3-5x band, midpoint used for valuation

    # What it costs to place one purchase order at all — raising it, chasing it,
    # receiving it, matching the invoice. Independent of what is on it. Without
    # this the backtest is free to order every week, and "71% more orders placed"
    # looks like a footnote instead of a cost the buying team pays.
    order_cost_sar: float = 900.0

    # The service levels the scenario sweep is run at. This is the slider's axis:
    # the frontier of capital against days waiting, measured rather than assumed.
    #
    # The band that matters is 80-99.5%; the three points below it are anchors, not
    # recommendations. Without them the plant's own policy sits off the left end of
    # the curve — it waits longer than our worst sampled point — and the question
    # "what would OUR levels cost at THEIR service level" has no answer but an
    # extrapolation. Sampling low enough to bracket them is cheaper and honest.
    service_sweep: tuple[float, ...] = (
        0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 0.97, 0.99, 0.995
    )

    def ordering_cost(self, n_orders: float) -> float:
        return n_orders * self.order_cost_sar

    def shortage_cost_per_unit(self, unit_price_sar: float, criticality: str) -> float:
        """
        Cost of being one unit short, once: the stoppage plus the emergency buy.

        Two terms, and the first one is the point. Downtime is a property of the
        equipment, not of the part — it is the same whether the missing item cost
        SAR 4 or SAR 2.2M — so it enters as a flat figure per criticality. Only the
        second term, buying the part in a hurry at the expedite premium, scales
        with price.

        The consequence is deliberate and shows up in the service levels: within
        one criticality, an expensive part now gets a LOWER fractile than a cheap
        one, because holding it costs more while being short of it costs the same.
        That is the correct answer, and the old formula could not produce it.
        """
        downtime = (
            self.downtime_cost_per_day_sar.get(criticality, 0.0)
            * self.expedite_days.get(criticality, 0.0)
        )
        return downtime + self.expedite_premium * unit_price_sar

    def holding_cost_per_unit_year(self, unit_price_sar: float) -> float:
        return unit_price_sar * self.holding_rate_per_year

    def holding_cost_per_unit_day(self, unit_price_sar: float) -> float:
        return self.holding_cost_per_unit_year(unit_price_sar) / 365.0

    def shortage_cost_per_unit_day(self, unit_price_sar: float, criticality: str) -> float:
        """
        Per-day shortage penalty for the backtest, spread over a nominal month.

        Derived from the same `shortage_cost_per_unit`, and that matters more than
        it looks. Until 2026-09-10 the levels were set from one shortage cost and
        scored against a different one, so the policy was optimised for one
        objective and marked against another — it held more stock than the marking
        scheme rewarded and came out 8% WORSE on total cost than the plant's own
        levels while cutting days waiting by 65%. Two cost models is a way to lose
        an argument you are winning.
        """
        return self.shortage_cost_per_unit(unit_price_sar, criticality) / 30.0

    def critical_fractile(self, unit_price_sar: float, criticality: str) -> float:
        """
        Newsvendor service level for one item, from its own economics.

        Now varies with price WITHIN a criticality, which is the whole point of the
        change: a SAR 4 A-critical gasket sits at the cap, a SAR 2.2M A-critical
        transformer comes out near 0.97, because a year of holding the transformer
        costs SAR 550,000 and a year of holding the gasket costs one riyal. The
        stoppage they prevent is identical.
        """
        short = self.shortage_cost_per_unit(unit_price_sar, criticality)
        hold = self.holding_cost_per_unit_year(unit_price_sar)
        if short + hold <= 0:
            return self.service_level_floor
        raw = short / (short + hold)
        return min(max(raw, self.service_level_floor), self.service_level_cap)


class DeadMoneyRule(BaseModel):
    """
    What counts as dead money — defined once, read by generator tests, scoring and
    the engine's own valuation.

    Note what this is NOT: "value that has not been issued in 24 months". On the
    toy set that figure is 89.6%, because insurance spares correctly sit still for
    years. Reporting it would inflate the prize roughly 2.5x and collapse the first
    time a reliability engineer asked whether a spare transformer is waste.
    """

    years_of_demand_justified: float = 3.0
    criticality_floor: dict[str, float] = Field(
        default_factory=lambda: {"A": 2.0, "B": 1.0, "C": 0.0}
    )
    target_dead_value_share: tuple[float, float] = (0.20, 0.40)

    def justified_qty(self, annual_demand, criticality):
        """Units it is reasonable to hold. Accepts scalars or numpy arrays."""
        import numpy as np

        if np.isscalar(criticality):
            floor = self.criticality_floor.get(criticality, 0.0)
        else:
            floor = np.select(
                [np.asarray(criticality) == k for k in self.criticality_floor],
                list(self.criticality_floor.values()),
                default=0.0,
            )
        return np.maximum(np.asarray(annual_demand) * self.years_of_demand_justified, floor)


class DemandShaping(BaseModel):
    """
    Controls how a family's demand is split across its variants.

    This is the single lever deciding whether the generated master looks like a
    real MRO storeroom (a minority of line items carrying most movement, 30-50%
    idle for two years) or like a supermarket. Both parameters are driven off the
    seed file's variant_weight rather than the realised item count, so the toy
    preset behaves like the full one.
    """

    breadth_exponent: float = 0.85
    popularity_sigma: float = 1.30
    target_idle_24m_share: tuple[float, float] = (0.30, 0.50)

    # An item's REALISED interval decides its truth profile, not the seed family's
    # label — otherwise 43% of "consumables" turn out to have two issues in three
    # years and the truth label contradicts the truth parameters.
    profile_cuts_days: dict[str, float] = Field(
        default_factory=lambda: {"consumable": 10.0, "occasional": 90.0, "lumpy": 400.0}
    )

    def profile_of(self, interval_days):
        """Realised interval -> truth profile. Vectorised."""
        import numpy as np

        cuts = self.profile_cuts_days
        iv = np.asarray(interval_days, dtype=float)
        return np.select(
            [iv <= cuts["consumable"], iv <= cuts["occasional"], iv <= cuts["lumpy"]],
            ["consumable", "occasional", "lumpy"],
            default="insurance",
        )


class MultiStore(BaseModel):
    """Same material stocked in more than one storeroom — the data transfers need."""

    extra_stores_max: int = 2
    secondary_demand_share: tuple[float, float] = (0.15, 0.55)
    target_multi_store_share: float = 0.10       # asserted in tests


class CommissioningStock(BaseModel):
    """
    Spares bought as a package when the plant was built, and never consumed.

    The largest single source of dead money in a real storeroom, weighted to
    expensive slow movers: a commissioning package buys one of everything that
    would stop the plant, including spares for failures that never happened.
    """

    share: float = 0.35                      # of capital-spare line items
    units: tuple[float, float] = (1.0, 4.0)  # absolute units, NOT years of demand
    applies_to: tuple[str, ...] = ("lumpy", "insurance")
    # A package buys ONE spare transformer, not four. Above this price the package
    # shrinks towards a single unit; without the damping, five SAR 2m transformers
    # sat on the shelf and accounted for a third of all dead money on their own.
    single_unit_above_sar: float = 150_000.0


class StalePolicy(BaseModel):
    """
    The incumbent min/max the simulated plant runs on — deliberately mediocre, and
    the baseline our step-5 policy is measured against.
    """

    set_on_offset_days: int = 120        # levels frozen this far into history
    min_cover_days: float = 45.0         # one blanket cover figure for everything
    max_cover_days: float = 180.0
    round_up_to: float = 1.0
    fat_finger_share: float = 0.12
    fat_finger_factor: float = 6.0
    # Error rate damped above this price: expensive mistakes get caught at purchase
    # approval, cheap ones sit for years.
    fat_finger_value_pivot: float = 2000.0


class LeadTime(BaseModel):
    """Lead-time variability is half of what safety stock exists for."""

    cv: float = 0.25
    min_days: int = 1
    max_days: int = 720


class WorkOrderShaping(BaseModel):
    """
    How issues are grouped into maintenance jobs.

    A planned job raised on the day it consumes parts tells a forecaster nothing,
    so PLANNED and SHUTDOWN work orders carry a `created_date` well before the
    issue — that column is what "known future demand" actually means in step 4.
    """

    group_freq: str = "MS"                      # one maintenance visit per asset per month
    # Natural job sizes. These were briefly widened to (2,8)/(1,4) purely to clear a
    # >=2.0 issues-per-WO target, which was tuning the plant to fit the metric. The
    # target is now 1.5 and these are back to what a maintenance job actually
    # consumes — see DECISIONS.md for the deferred WO-first rewrite that would make
    # the number come out right for the right reason.
    parts_per_planned: tuple[int, int] = (1, 6)
    parts_per_breakdown: tuple[int, int] = (1, 3)
    planned_notice_days: tuple[int, int] = (14, 60)
    shutdown_notice_days: tuple[int, int] = (90, 240)
    breakdown_share: float = 0.40
    target_issues_per_wo: float = 1.5


class ReturnsAdjustments(BaseModel):
    return_share: float = 0.025                 # of issues, returned within 30 days
    return_window_days: int = 30
    adjustment_share: float = 0.005             # of positions, counted in the last year


class RunConfig(BaseModel):
    seed: int = 20260909
    preset: Preset = "toy"

    history_start: date = date(2023, 9, 1)
    history_end: date = date(2026, 8, 31)
    cutoff_date: date = date(2025, 8, 31)       # two years train, one year evaluate

    forecast_horizon_days: int = 180

    # Ras Al Khair was commissioned 2013-15; the commissioning-spares story depends
    # on the assets being a decade old, not built the day before history starts.
    equipment_commissioning_window: tuple[date, date] = (date(2013, 1, 1), date(2015, 12, 31))
    equipment_late_window: tuple[date, date] = (date(2018, 1, 1), date(2023, 6, 30))
    equipment_late_share: float = 0.20
    decommission_share: float = 0.08

    # Precomputed for the scenario slider; the UI interpolates between these. The
    # top of the sweep matches CostModel.service_level_cap, so the slider can reach
    # the highest level the policy engine will ever produce.
    service_level_sweep: list[float] = Field(
        default_factory=lambda: [round(0.80 + 0.01 * i, 3) for i in range(20)] + [0.995]
    )

    costs: CostModel = Field(default_factory=CostModel)
    dead_money: DeadMoneyRule = Field(default_factory=DeadMoneyRule)
    demand: DemandShaping = Field(default_factory=DemandShaping)
    multi_store: MultiStore = Field(default_factory=MultiStore)
    commissioning: CommissioningStock = Field(default_factory=CommissioningStock)
    stale_policy: StalePolicy = Field(default_factory=StalePolicy)
    lead_time: LeadTime = Field(default_factory=LeadTime)
    work_orders: WorkOrderShaping = Field(default_factory=WorkOrderShaping)
    returns: ReturnsAdjustments = Field(default_factory=ReturnsAdjustments)

    # Walking 20k positions x 1,100 days in one array would allocate GBs; the sim
    # processes this many positions per block.
    # How hard an outage bites, on top of each family's own shutdown multiplier.
    # Tuned so the measured issue rate inside a shutdown is at least 3x the plant's
    # baseline — below that the shutdown table is decoration and step 4's "a planned
    # shutdown is known demand" has nothing behind it.
    # Raised from 2.2 to 4.5 on 2026-09-10. Giving the transformer and haul-tyre families
    # their proper size tokens (kVA/MVA, OTR rim size) shifted the random stream, so
    # every position drew different demand parameters and the measured multiple fell
    # to 2.6. This knob exists to set exactly this property, so it was moved rather
    # than the dataset being accepted below its own design target — but it IS a knob
    # being turned to hit a number, and that is worth knowing when reading it.
    shutdown_intensity: float = 4.5

    sim_block_size: int = 4096

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
        if path is not None and Path(path).exists():
            import yaml

            base = yaml.safe_load(Path(path).read_text()) or {}
        return cls(**{**base, **overrides})
