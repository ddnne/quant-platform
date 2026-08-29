"""Small, closed research cohorts for one-person ratio-factor exploration.

This registry is intentionally a handful of four-candidate batches, not a
strategy catalog.  Each batch has one dependency-specific history floor so a
price-only idea can use the 2008 history without being truncated to the 2016
IV floor.  The personal service still uses its PIT ``Prime with financials``
universe, so the executable floor is the first financial-summary date rather
than the two-month-earlier raw price floor.  All entries are DRAFT research;
none promotes or trades.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from strategies.spec import FactorLeg, FeatureRef, StrategySpec

from research.paper_candidate_specs import build_factor_rank_strategy_spec


COHORT_REGISTRY_VERSION = "personal-factor-cohorts/v1"
DEFAULT_FACTOR_COHORT_ID = "diverse-core-v1"
LEG_VERSION = "1.0.0"
PERSONAL_EXECUTABLE_COHORT_IDS = (
    "price-relative-v1",
    "fundamental-relative-v1",
    DEFAULT_FACTOR_COHORT_ID,
)


def _price(
    mode: str,
    *,
    weight: float,
    direction: str,
    short_n: int = 20,
    long_n: int = 252,
) -> FactorLeg:
    return FactorLeg(
        feature=FeatureRef(
            id="retrospective_price_ratio",
            version=LEG_VERSION,
            params={"mode": mode, "short_n": short_n, "long_n": long_n},
        ),
        weight=weight,
        direction=direction,
    )


def _fund(mode: str, *, weight: float, direction: str) -> FactorLeg:
    return FactorLeg(
        feature=FeatureRef(
            id="pit_fundamental_ratio",
            version=LEG_VERSION,
            params={"mode": mode},
        ),
        weight=weight,
        direction=direction,
    )


def _spec(
    strategy_id: str,
    *legs: FactorLeg,
    allow_short: bool = False,
    group: str = "sector33",
    rationale: str,
) -> StrategySpec:
    return build_factor_rank_strategy_spec(
        strategy_id=strategy_id,
        legs=tuple(legs),
        hold_days=10,
        group=group,
        long_frac=0.2,
        short_frac=0.2,
        allow_short=allow_short,
        min_eligible_ratio=0.8,
        min_eligible_count=100,
        min_group_count=5,
        rationale=rationale,
    )


def _price_relative_specs() -> tuple[StrategySpec, ...]:
    return (
        _spec(
            "personal_sector_price_trend_ratio_v1",
            _price("return_ratio", weight=1.0, direction="high_good"),
            rationale="Within-sector 12-month adjusted-price relative strength.",
        ),
        _spec(
            "personal_sector_short_long_momentum_v1",
            _price(
                "short_long_momentum",
                weight=1.0,
                direction="high_good",
                short_n=20,
                long_n=120,
            ),
            rationale="Within-sector recent-versus-medium-horizon price ratio.",
        ),
        _spec(
            "personal_sector_low_vol_ratio_v1",
            _price(
                "realized_vol_ratio",
                weight=1.0,
                direction="low_good",
                short_n=20,
                long_n=120,
            ),
            rationale="Within-sector preference for contracting realized volatility.",
        ),
        _spec(
            "personal_sector_trend_liquidity_ratio_v1",
            _price("return_ratio", weight=0.65, direction="high_good"),
            _price(
                "turnover_ratio",
                weight=0.35,
                direction="high_good",
                short_n=20,
                long_n=120,
            ),
            rationale="Within-sector price strength confirmed by turnover expansion.",
        ),
    )


def _fundamental_relative_specs() -> tuple[StrategySpec, ...]:
    return (
        _spec(
            "personal_sector_value_quality_v1",
            _fund("book_to_price", weight=0.35, direction="high_good"),
            _fund("earnings_to_price", weight=0.20, direction="high_good"),
            _fund("roe", weight=0.25, direction="high_good"),
            _fund("asset_turnover", weight=0.20, direction="high_good"),
            rationale="Sector-relative value plus profitability and capital efficiency.",
        ),
        _spec(
            "personal_sector_growth_quality_v1",
            _fund("sales_growth", weight=0.35, direction="high_good"),
            _fund("net_margin", weight=0.25, direction="high_good"),
            _fund("roe", weight=0.20, direction="high_good"),
            _fund("equity_ratio", weight=0.20, direction="high_good"),
            rationale="Sector-relative sales growth backed by margin and balance sheet.",
        ),
        _spec(
            "personal_sector_small_quality_v1",
            _price(
                "market_cap",
                weight=0.40,
                direction="low_good",
                short_n=2,
                long_n=3,
            ),
            _fund("roe", weight=0.30, direction="high_good"),
            _fund("asset_turnover", weight=0.30, direction="high_good"),
            rationale="True market-cap size within sector, tempered by quality.",
        ),
        _spec(
            "personal_sector_growth_at_value_v1",
            _fund("sales_growth", weight=0.30, direction="high_good"),
            _fund("book_to_price", weight=0.30, direction="high_good"),
            _fund("roe", weight=0.25, direction="high_good"),
            _fund("assets_growth", weight=0.15, direction="low_good"),
            rationale="Sector-relative growth at value without aggressive asset growth.",
        ),
    )


def _diverse_core_specs(*, allow_short: bool = False) -> tuple[StrategySpec, ...]:
    suffix = "_ls" if allow_short else ""
    return (
        _spec(
            f"personal_sector_momentum_low_vol_v1{suffix}",
            _price("return_ratio", weight=0.60, direction="high_good"),
            _price(
                "realized_vol_ratio",
                weight=0.40,
                direction="low_good",
                short_n=20,
                long_n=120,
            ),
            allow_short=allow_short,
            rationale="Sector-relative long-horizon momentum with a low-vol ratio leg.",
        ),
        _spec(
            f"personal_sector_value_quality_core_v1{suffix}",
            _fund("book_to_price", weight=0.40, direction="high_good"),
            _fund("roe", weight=0.35, direction="high_good"),
            _fund("asset_turnover", weight=0.25, direction="high_good"),
            allow_short=allow_short,
            rationale="Sector-relative value and operating quality composite.",
        ),
        _spec(
            f"personal_sector_size_quality_core_v1{suffix}",
            _price(
                "market_cap",
                weight=0.40,
                direction="low_good",
                short_n=2,
                long_n=3,
            ),
            _fund("roe", weight=0.30, direction="high_good"),
            _fund("equity_ratio", weight=0.30, direction="high_good"),
            allow_short=allow_short,
            rationale="Within-sector market-cap size balanced by quality and leverage.",
        ),
        _spec(
            f"personal_sector_balanced_four_factor_v1{suffix}",
            _price("return_ratio", weight=0.25, direction="high_good"),
            _fund("book_to_price", weight=0.25, direction="high_good"),
            _fund("roe", weight=0.25, direction="high_good"),
            _price(
                "realized_vol_ratio",
                weight=0.25,
                direction="low_good",
                short_n=20,
                long_n=120,
            ),
            allow_short=allow_short,
            rationale="Equal-weight sector-relative momentum, value, quality, and risk.",
        ),
    )


@dataclass(frozen=True, slots=True)
class ResearchCohort:
    cohort_id: str
    backend: str
    history_data_start: str
    warmup_sessions: int
    dataset_dependencies: tuple[str, ...]
    strategy_specs: tuple[StrategySpec, ...] = ()
    logic_ids: tuple[str, ...] = ()
    short_financing_required: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if self.backend not in {"strategy_spec", "bar_native"}:
            raise ValueError("cohort backend must be strategy_spec|bar_native")
        if bool(self.strategy_specs) == bool(self.logic_ids):
            raise ValueError("cohort must declare exactly one executable surface")
        if len(self.strategy_specs or self.logic_ids) != 4:
            raise ValueError("every bounded cohort must contain exactly four candidates")

    def to_dict(self) -> dict[str, Any]:
        body = {
            "version": COHORT_REGISTRY_VERSION,
            "cohort_id": self.cohort_id,
            "backend": self.backend,
            "history_data_start": self.history_data_start,
            "warmup_sessions": self.warmup_sessions,
            "dataset_dependencies": list(self.dataset_dependencies),
            "strategy_specs": [spec.to_dict() for spec in self.strategy_specs],
            "logic_ids": list(self.logic_ids),
            "short_financing_required": self.short_financing_required,
            "description": self.description,
            "draft_only": True,
            "automatic_promotion": False,
        }
        encoded = json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return {
            **body,
            "cohort_digest": "sha256:" + hashlib.sha256(encoded).hexdigest(),
        }


_COHORTS: dict[str, ResearchCohort] = {
    "price-relative-v1": ResearchCohort(
        cohort_id="price-relative-v1",
        backend="strategy_spec",
        history_data_start="2008-07-07",
        warmup_sessions=253,
        dataset_dependencies=(
            "equities_master",
            "equities_bars_daily",
            "fins_summary",
            "markets_calendar",
        ),
        strategy_specs=_price_relative_specs(),
        description=(
            "Price, realized-volatility, and turnover ratios over the longest "
            "history supported by the PIT Prime-with-financials universe."
        ),
    ),
    "fundamental-relative-v1": ResearchCohort(
        cohort_id="fundamental-relative-v1",
        backend="strategy_spec",
        history_data_start="2008-07-07",
        warmup_sessions=253,
        dataset_dependencies=(
            "equities_master",
            "equities_bars_daily",
            "fins_summary",
            "markets_calendar",
        ),
        strategy_specs=_fundamental_relative_specs(),
        description="Sector-relative value, quality, growth, and true size.",
    ),
    DEFAULT_FACTOR_COHORT_ID: ResearchCohort(
        cohort_id=DEFAULT_FACTOR_COHORT_ID,
        backend="strategy_spec",
        history_data_start="2008-07-07",
        warmup_sessions=253,
        dataset_dependencies=(
            "equities_master",
            "equities_bars_daily",
            "fins_summary",
            "markets_calendar",
        ),
        strategy_specs=_diverse_core_specs(),
        description="One candidate each for momentum-risk, value, size, and balance.",
    ),
    "sector-relative-ls-v1": ResearchCohort(
        cohort_id="sector-relative-ls-v1",
        backend="strategy_spec",
        history_data_start="2008-07-07",
        warmup_sessions=253,
        dataset_dependencies=(
            "equities_master",
            "equities_bars_daily",
            "fins_summary",
            "markets_calendar",
        ),
        strategy_specs=_diverse_core_specs(allow_short=True),
        short_financing_required=True,
        description=(
            "Balanced within-sector long-short variants; blocked until borrow/"
            "financing cost evidence is enabled."
        ),
    ),
    "vol-surface-relative-v1": ResearchCohort(
        cohort_id="vol-surface-relative-v1",
        backend="bar_native",
        history_data_start="2016-07-19",
        warmup_sessions=61,
        dataset_dependencies=(
            "equities_bars_daily",
            "markets_calendar",
            "derivatives_bars_daily_options_225",
        ),
        logic_ids=(
            "opt225_basevol_term_ratio",
            "opt225_atm_iv_term_ratio",
            "opt225_skew_abs_level",
            "opt225_cm_term_ratio",
        ),
        short_financing_required=True,
        description="BaseVol, ATM IV, skew, and near/next maturity ratios.",
    ),
}

RESEARCH_COHORTS: Mapping[str, ResearchCohort] = MappingProxyType(_COHORTS)


def get_research_cohort(cohort_id: str) -> ResearchCohort:
    try:
        return RESEARCH_COHORTS[str(cohort_id)]
    except KeyError as exc:
        raise KeyError(
            f"unknown research cohort {cohort_id!r}; "
            f"available={sorted(RESEARCH_COHORTS)}"
        ) from exc


def personal_specs_for_cohort(cohort_id: str) -> tuple[StrategySpec, ...]:
    cohort = get_research_cohort(cohort_id)
    if cohort.backend != "strategy_spec":
        raise ValueError(
            f"cohort {cohort_id!r} uses {cohort.backend}, not personal StrategySpec"
        )
    if cohort.short_financing_required:
        raise ValueError(
            f"cohort {cohort_id!r} requires an explicit short-financing policy"
        )
    if cohort_id not in PERSONAL_EXECUTABLE_COHORT_IDS:
        raise ValueError(
            f"cohort {cohort_id!r} is not executable by personal StrategySpec "
            f"research; available={list(PERSONAL_EXECUTABLE_COHORT_IDS)}"
        )
    return cohort.strategy_specs


__all__ = [
    "COHORT_REGISTRY_VERSION",
    "DEFAULT_FACTOR_COHORT_ID",
    "PERSONAL_EXECUTABLE_COHORT_IDS",
    "RESEARCH_COHORTS",
    "ResearchCohort",
    "get_research_cohort",
    "personal_specs_for_cohort",
]
