"""Closed, bounded diversity cohorts and their history contracts."""

from __future__ import annotations

import pytest

from research.bar_native_specs import BAR_NATIVE_SPECS
from research.factor_cohorts import (
    DEFAULT_FACTOR_COHORT_ID,
    PERSONAL_EXECUTABLE_COHORT_IDS,
    RESEARCH_COHORTS,
    get_research_cohort,
    personal_specs_for_cohort,
)
from research.dependency_closure import ContractDependency, build_strategy_dependency_closure
from strategies.spec import (
    FactorRankRule,
    STRATEGY_SPEC_VERSION_V4,
    iter_feature_refs,
)


def test_cohorts_are_small_closed_exact_four_batches() -> None:
    assert PERSONAL_EXECUTABLE_COHORT_IDS == (
        "price-relative-v1",
        "fundamental-relative-v1",
        "diverse-core-v1",
    )
    assert set(RESEARCH_COHORTS) == {
        "price-relative-v1",
        "fundamental-relative-v1",
        "diverse-core-v1",
        "sector-relative-ls-v1",
        "vol-surface-relative-v1",
    }
    all_ids: list[str] = []
    for cohort in RESEARCH_COHORTS.values():
        assert len(cohort.strategy_specs or cohort.logic_ids) == 4
        document = cohort.to_dict()
        assert document["cohort_digest"].startswith("sha256:")
        assert document["draft_only"] is True
        assert document["automatic_promotion"] is False
        all_ids.extend(spec.strategy_id for spec in cohort.strategy_specs)
    assert len(all_ids) == len(set(all_ids))


def test_personal_factor_specs_are_v4_sector_relative_and_exactly_pinned() -> None:
    specs = personal_specs_for_cohort(DEFAULT_FACTOR_COHORT_ID)
    assert len(specs) == 4
    for spec in specs:
        assert spec.version == STRATEGY_SPEC_VERSION_V4
        assert isinstance(spec.rule, FactorRankRule)
        assert spec.rule.group == "sector33"
        assert spec.rule.allow_short is False
        assert spec.rule.min_eligible_count == 100
        assert all(ref.version == "1.0.0" for ref in iter_feature_refs(spec))


def test_history_floor_is_dependency_specific_not_globally_truncated() -> None:
    price = get_research_cohort("price-relative-v1")
    fundamentals = get_research_cohort("fundamental-relative-v1")
    vol = get_research_cohort("vol-surface-relative-v1")
    assert price.history_data_start == "2008-07-07"
    assert "fins_summary" in price.dataset_dependencies
    assert fundamentals.history_data_start == "2008-07-07"
    assert vol.history_data_start == "2016-07-19"
    assert price.warmup_sessions == fundamentals.warmup_sessions == 253
    assert vol.warmup_sessions == 61


def test_price_ratio_long_window_is_bound_into_dependency_closure() -> None:
    spec = personal_specs_for_cohort("price-relative-v1")[0]

    def dependency(kind: str) -> ContractDependency:
        return ContractDependency(
            kind=kind,
            dependency_id=f"ratio-{kind}",
            version=f"ratio-{kind}/v1",
        )

    closure = build_strategy_dependency_closure(
        plan_id="ratio-lookback",
        plan_digest="sha256:" + "a" * 64,
        spec=spec,
        universe_dependencies=(dependency("universe"),),
        evaluation_dependency=dependency("evaluation"),
        risk_dependency=dependency("risk"),
        cost_dependency=dependency("cost"),
        research_data_profile_id="personal-ratio-v1",
        period_start="2008-07-07",
        period_end="2026-08-27",
    )

    assert closure.required_lookback_trading_days == 252
    assert next(
        scope
        for scope in closure.dataset_scopes
        if scope.dataset_id == "equities_bars_daily"
    ).required_lookback_trading_days == 252


def test_long_short_and_vol_batches_cannot_enter_long_only_personal_service() -> None:
    with pytest.raises(ValueError, match="short-financing"):
        personal_specs_for_cohort("sector-relative-ls-v1")
    with pytest.raises(ValueError, match="bar_native"):
        personal_specs_for_cohort("vol-surface-relative-v1")
    assert all(
        isinstance(spec.rule, FactorRankRule) and spec.rule.allow_short
        for spec in get_research_cohort("sector-relative-ls-v1").strategy_specs
    )


def test_vol_surface_cohort_reuses_only_live_bar_native_logic() -> None:
    cohort = get_research_cohort("vol-surface-relative-v1")
    assert cohort.logic_ids == (
        "opt225_basevol_term_ratio",
        "opt225_atm_iv_term_ratio",
        "opt225_skew_abs_level",
        "opt225_cm_term_ratio",
    )
    assert set(cohort.logic_ids) <= set(BAR_NATIVE_SPECS)


def test_unknown_cohort_fails_closed() -> None:
    with pytest.raises(KeyError, match="unknown research cohort"):
        get_research_cohort("generated-anything")
