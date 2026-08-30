"""Closed, bounded diversity cohorts and their history contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.bar_native_specs import BAR_NATIVE_SPECS
from research.factor_cohorts import (
    AM_PM_PERSONAL_EXECUTABLE_COHORT_IDS,
    AM_SIGNAL_PM_CLOSE_EXECUTION_CONTRACT,
    AM_SIGNAL_PM_CLOSE_EXECUTION_MODE,
    COMPACT_MARKET_AM_PM_COHORT_ID,
    COMPACT_MARKET_COHORT_ID,
    DEFAULT_FACTOR_COHORT_ID,
    LEGACY_DEFAULT_FACTOR_COHORT_ID,
    LEGACY_PERSONAL_EXECUTABLE_COHORT_IDS,
    PERSONAL_EXECUTABLE_COHORT_IDS,
    PERSONAL_SHORT_FINANCING_AM_PM_COHORT_ID,
    RESEARCH_COHORTS,
    get_research_cohort,
    personal_specs_for_cohort,
    validate_personal_cohort_universe,
)

_LEGACY_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "legacy_factor_cohort_documents.json"
)
_AM_PM_BY_LEGACY = {
    "price-relative-v1": "price-relative-am-pm-v1",
    "fundamental-relative-v1": "fundamental-relative-am-pm-v1",
    "diverse-core-v1": "diverse-core-am-pm-v1",
    "compact-market-diverse-v1": "compact-market-diverse-am-pm-v1",
    "sector-relative-ls-v1": "sector-relative-ls-am-pm-v1",
}
from research.dependency_closure import ContractDependency, build_strategy_dependency_closure
from strategies.spec import (
    FactorRankRule,
    STRATEGY_SPEC_VERSION_V4,
    iter_feature_refs,
)


def test_cohorts_are_small_closed_exact_four_batches() -> None:
    assert PERSONAL_EXECUTABLE_COHORT_IDS == (
        *LEGACY_PERSONAL_EXECUTABLE_COHORT_IDS,
        *AM_PM_PERSONAL_EXECUTABLE_COHORT_IDS,
    )
    assert set(RESEARCH_COHORTS) == {
        *LEGACY_PERSONAL_EXECUTABLE_COHORT_IDS,
        *AM_PM_PERSONAL_EXECUTABLE_COHORT_IDS,
        "vol-surface-relative-v1",
    }
    for cohort in RESEARCH_COHORTS.values():
        assert len(cohort.strategy_specs or cohort.logic_ids) == 4
        document = cohort.to_dict()
        assert document["cohort_digest"].startswith("sha256:")
        assert document["draft_only"] is True
        assert document["automatic_promotion"] is False
        spec_ids = [spec.strategy_id for spec in cohort.strategy_specs]
        assert len(spec_ids) == len(set(spec_ids))
    assert DEFAULT_FACTOR_COHORT_ID == "diverse-core-am-pm-v1"
    assert LEGACY_DEFAULT_FACTOR_COHORT_ID == "diverse-core-v1"
    assert get_research_cohort("diverse-core-v1").cohort_id == "diverse-core-v1"


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


def test_compact_universes_use_a_distinct_market_relative_cohort() -> None:
    specs = personal_specs_for_cohort(
        COMPACT_MARKET_COHORT_ID, universe_id="topix_core30"
    )

    assert len(specs) == 4
    assert all(
        isinstance(spec.rule, FactorRankRule)
        and spec.rule.group == "market"
        and spec.rule.min_eligible_count == 20
        and spec.strategy_id.startswith("personal_compact_market_")
        for spec in specs
    )
    with pytest.raises(ValueError, match="compact-market-diverse-v1"):
        validate_personal_cohort_universe("diverse-core-v1", "topix_core30")
    with pytest.raises(ValueError, match="requires one of"):
        validate_personal_cohort_universe(
            COMPACT_MARKET_COHORT_ID, "topix_all"
        )


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


def test_long_short_is_broad_sector_relative_and_compact_stays_rejected() -> None:
    specs = personal_specs_for_cohort(
        "sector-relative-ls-v1", universe_id="topix_all"
    )
    assert len(specs) == 4
    assert all(
        isinstance(spec.rule, FactorRankRule)
        and spec.rule.allow_short
        and spec.rule.group == "sector33"
        for spec in specs
    )
    with pytest.raises(ValueError, match="compact-market-diverse-v1"):
        personal_specs_for_cohort(
            "sector-relative-ls-v1", universe_id="topix_core30"
        )


def test_bar_native_vol_batch_cannot_enter_strategy_spec_service() -> None:
    with pytest.raises(ValueError, match="bar_native"):
        personal_specs_for_cohort("vol-surface-relative-v1")


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


def test_legacy_cohort_documents_and_digests_match_captured_fixtures() -> None:
    captured = json.loads(_LEGACY_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert set(captured) == set(_AM_PM_BY_LEGACY)
    for cohort_id, expected in captured.items():
        actual = get_research_cohort(cohort_id).to_dict()
        assert actual == expected
        assert "execution_contract" not in actual
        assert "document_version" not in actual
        assert actual["version"] == "personal-factor-cohorts/v2"


def test_am_pm_cohorts_are_exact_four_and_bind_the_same_canonical_contract() -> None:
    canonical = dict(AM_SIGNAL_PM_CLOSE_EXECUTION_CONTRACT)
    digests: set[str] = set()
    for legacy_id, am_id in _AM_PM_BY_LEGACY.items():
        legacy = get_research_cohort(legacy_id)
        am_cohort = get_research_cohort(am_id)
        assert len(am_cohort.strategy_specs) == 4
        assert am_cohort.strategy_specs == legacy.strategy_specs
        assert am_cohort.dataset_dependencies == legacy.dataset_dependencies
        assert am_cohort.short_financing_required == legacy.short_financing_required
        assert am_cohort.warmup_sessions == legacy.warmup_sessions
        document = am_cohort.to_dict()
        assert document["document_version"] == "personal-am-pm-cohort/v1"
        assert document["execution_contract"] == canonical
        assert document["cohort_digest"] != legacy.to_dict()["cohort_digest"]
        assert document["cohort_id"] != legacy.cohort_id
        assert canonical["id"]
        assert canonical["label"] == AM_SIGNAL_PM_CLOSE_EXECUTION_MODE
        assert canonical["contract_digest"].startswith("sha256:")
        assert canonical["execution_mode"] == AM_SIGNAL_PM_CLOSE_EXECUTION_MODE
        assert canonical["non_price_information_cutoff"] == "11:30:00+09:00"
        assert canonical["am_observation_acquisition_deadline"] == "12:30:00+09:00"
        assert canonical["am_observation_deadline_is_non_price_cutoff"] is False
        assert canonical["signal_price_field"] == "MAdjC"
        assert canonical["signal_price_dataset"] == "equities_bars_daily"
        assert canonical["order_sizing"] == "D_MAdjC_causal"
        assert canonical["fill_valuation_field"] == "AAdjC"
        assert canonical["fill_valuation_session"] == "same_trading_date"
        assert canonical["first_new_position_pnl"] == "D_PM_to_next_PM"
        assert canonical["current_d_final_market_cap_forbidden"] is True
        assert canonical["market_cap_lag"] == "D-1"
        assert canonical["fallback"] is False
        assert canonical["forward_fill"] is False
        assert canonical["live_trading_evidence"] is False
        assert "equities_bars_daily_am" not in am_cohort.dataset_dependencies
        assert "equities_bars_daily" in am_cohort.dataset_dependencies
        digests.add(str(document["execution_contract"]["contract_digest"]))
    assert digests == {canonical["contract_digest"]}
    assert DEFAULT_FACTOR_COHORT_ID == "diverse-core-am-pm-v1"


def test_am_pm_compact_and_short_financing_keep_legacy_universe_policy() -> None:
    specs = personal_specs_for_cohort(
        COMPACT_MARKET_AM_PM_COHORT_ID, universe_id="topix_core30"
    )
    assert len(specs) == 4
    assert all(spec.rule.group == "market" for spec in specs)
    ls = personal_specs_for_cohort(
        PERSONAL_SHORT_FINANCING_AM_PM_COHORT_ID, universe_id="topix_all"
    )
    assert all(spec.rule.allow_short for spec in ls)
    with pytest.raises(ValueError, match="compact-market-diverse-am-pm-v1"):
        validate_personal_cohort_universe("diverse-core-am-pm-v1", "topix_core30")
    with pytest.raises(ValueError, match="requires one of"):
        validate_personal_cohort_universe(COMPACT_MARKET_AM_PM_COHORT_ID, "topix_all")
    with pytest.raises(ValueError, match="compact-market-diverse-am-pm-v1"):
        personal_specs_for_cohort(
            PERSONAL_SHORT_FINANCING_AM_PM_COHORT_ID, universe_id="topix_core30"
        )


def test_am_pm_factor_closure_depends_on_full_daily_bars_not_tip_am() -> None:
    spec = personal_specs_for_cohort("diverse-core-am-pm-v1")[0]
    closure = build_strategy_dependency_closure(
        plan_id="am-pm-bars",
        plan_digest="sha256:" + "b" * 64,
        spec=spec,
        universe_dependencies=(
            ContractDependency(
                kind="universe",
                dependency_id="am-pm-universe",
                version="am-pm-universe/v1",
            ),
        ),
        evaluation_dependency=ContractDependency(
            kind="evaluation",
            dependency_id="am-pm-eval",
            version="am-pm-eval/v1",
            dataset_dependencies=("equities_bars_daily", "markets_calendar"),
        ),
        risk_dependency=ContractDependency(
            kind="risk",
            dependency_id="am-pm-risk",
            version="am-pm-risk/v1",
        ),
        cost_dependency=ContractDependency(
            kind="cost",
            dependency_id="am-pm-cost",
            version="am-pm-cost/v1",
        ),
        research_data_profile_id="personal-am-pm-v1",
        period_start="2008-07-07",
        period_end="2026-08-27",
    )
    assert "equities_bars_daily" in closure.required_datasets
    assert "equities_bars_daily_am" not in closure.required_datasets
