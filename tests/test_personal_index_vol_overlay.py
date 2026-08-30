"""Focused invariants for the predeclared index-volatility overlay core."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest

from research.personal_index_vol_overlay import (
    BASE_SLEEVE_ID,
    BASE_UNIVERSE_ID,
    EXPECTED_BASE_COHORT_DIGEST,
    EXPECTED_BASE_STRATEGY_SPEC_DIGEST,
    IndexVolOverlayObservation,
    ONE_WAY_COST_RATE,
    OVERLAY_CANDIDATES,
    PreparedIndexVolOverlayPanelManifest,
    build_prepared_panel_manifest,
    canonical_prepared_panel_digest,
    canonical_trading_calendar_digest,
    evaluate_index_vol_overlays,
)


def _panel(
    count: int = 150,
    *,
    beta: float = 4.0,
) -> tuple[list[IndexVolOverlayObservation], list[str]]:
    start = date(2024, 1, 1)
    dates = [(start + timedelta(days=index)).isoformat() for index in range(count)]
    proxy_returns = [0.0] + [
        (0.001 + (index % 5) * 0.0001) * (1.0 if index % 2 else -1.0)
        for index in range(1, count)
    ]
    closes = [100.0]
    for proxy_return in proxy_returns[1:]:
        closes.append(closes[-1] * (1.0 + proxy_return))
    rows = [
        IndexVolOverlayObservation(
            date=day,
            available_at=f"{day}T16:00:00+09:00",
            base_sleeve_return=beta * proxy_returns[index],
            topix_cash_close=closes[index],
            n225_base_vol=20.0,
            n225_atm_iv=20.0,
            topix_realized_vol_20=10.0,
            n225_front_atm_iv=30.0,
            n225_next_atm_iv=20.0,
            n225_front_downside_wing_iv=40.0,
            n225_next_downside_wing_iv=20.0,
            svi_equivalent_atm_term_ratio=1.45,
            svi_equivalent_downside_smile_term_ratio=1.90,
        )
        for index, day in enumerate(dates)
    ]
    return rows, dates


def _by_id(report: dict, candidate_id: str) -> dict:
    return next(
        candidate
        for candidate in report["candidates"]
        if candidate["candidate_id"] == candidate_id
    )


def _manifest(
    rows: list[IndexVolOverlayObservation],
) -> PreparedIndexVolOverlayPanelManifest:
    return build_prepared_panel_manifest(
        rows,
        snapshot_digest="sha256:" + "3" * 64,
        base_report_digest="sha256:" + "4" * 64,
    )


def _evaluate(rows: list[IndexVolOverlayObservation], **kwargs: Any) -> dict:
    return evaluate_index_vol_overlays(rows, manifest=_manifest(rows), **kwargs)


def test_scope_is_frozen_to_one_sleeve_four_index_vol_candidates() -> None:
    rows, dates = _panel()
    report = _evaluate(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )

    fields = set(IndexVolOverlayObservation.__dataclass_fields__)
    assert not any("stock" in field and "iv" in field for field in fields)
    assert report["base_sleeve"]["strategy_id"] == BASE_SLEEVE_ID
    assert report["base_sleeve"]["universe_id"] == BASE_UNIVERSE_ID
    assert report["base_sleeve"]["single_stock_option_iv"] == (
        "EXCLUDED_FROM_INPUT_SURFACE"
    )
    assert len(OVERLAY_CANDIDATES) == len(report["candidates"]) == 4
    assert report["candidate_policy"]["post_result_selection"] == "NOT_PERFORMED"
    assert report["candidate_policy"]["ranking"] is None
    assert report["candidate_policy"]["candidate_order"] == [
        candidate.candidate_id for candidate in OVERLAY_CANDIDATES
    ]
    assert report["topix_proxy"]["role"] == "NON_EXECUTABLE_HEDGE_APPROXIMATION"
    assert report["topix_proxy"]["etf_fill_claim"] is False


def test_prepared_panel_provenance_and_draft_lifecycle_are_required() -> None:
    rows, dates = _panel()
    manifest = _manifest(rows)
    report = evaluate_index_vol_overlays(
        rows,
        manifest=manifest,
        signal_start=dates[130],
        signal_end=dates[130],
    )

    provenance = report["prepared_panel_provenance"]
    assert provenance["strategy_spec_digest"] == EXPECTED_BASE_STRATEGY_SPEC_DIGEST
    assert provenance["cohort_digest"] == EXPECTED_BASE_COHORT_DIGEST
    assert provenance["snapshot_digest"] == manifest.snapshot_digest
    assert provenance["base_report_digest"] == manifest.base_report_digest
    assert provenance["trading_calendar_digest"] == manifest.trading_calendar_digest
    assert provenance["return_semantics"] == (
        "NET_AFTER_STOCK_EXECUTION_COSTS_AND_SHORT_FINANCING"
    )
    assert provenance["base_nav_semantics"] == (
        "CONTINUOUS_PRE_EXISTING_INVESTABLE_NAV"
    )
    assert provenance["source_slice_wrapper_cost_semantics"] == (
        "EXCLUDES_NAV_WRAPPER_ENTRY_AND_LIQUIDATION"
    )
    assert report["lifecycle"] == {
        "stage": "DRAFT_DIAGNOSTIC",
        "role": "DIAGNOSTIC_RESEARCH_ONLY",
        "paper_execution": False,
        "automatic_promotion": False,
    }
    assert report["cost_model"]["reported_cost_turnover_fill_scope"] == (
        "OVERLAY_INCREMENTAL_ONLY"
    )
    assert report["cost_model"]["not_total_strategy_cost_metrics"] is True
    assert report["cost_model"][
        "base_nav_source_slice_excludes_wrapper_entry_liquidation"
    ] is True

    with pytest.raises(ValueError, match="session_count mismatch"):
        evaluate_index_vol_overlays(
            rows,
            manifest=replace(manifest, session_count=len(rows) - 1),
            signal_start=dates[130],
            signal_end=dates[130],
        )
    with pytest.raises(ValueError, match="net of stock costs and financing"):
        replace(manifest, return_semantics="GROSS_BEFORE_COSTS")


def test_repo_definition_and_canonical_panel_digests_reject_drift() -> None:
    rows, dates = _panel()
    manifest = _manifest(rows)
    assert manifest.prepared_panel_digest == canonical_prepared_panel_digest(rows)
    assert manifest.trading_calendar_digest == canonical_trading_calendar_digest(rows)

    with pytest.raises(ValueError, match="repo definition"):
        replace(manifest, strategy_spec_digest="sha256:" + "a" * 64)
    with pytest.raises(ValueError, match="repo definition"):
        replace(manifest, cohort_digest="sha256:" + "b" * 64)

    mutated = list(rows)
    mutated[130] = replace(mutated[130], n225_base_vol=21.0)
    with pytest.raises(ValueError, match="prepared_panel_digest"):
        evaluate_index_vol_overlays(
            mutated,
            manifest=manifest,
            signal_start=dates[130],
            signal_end=dates[130],
        )

    omitted = list(rows)
    omitted[130] = replace(omitted[130], n225_atm_iv=None)
    with pytest.raises(ValueError, match="prepared_panel_digest"):
        evaluate_index_vol_overlays(
            omitted,
            manifest=manifest,
            signal_start=dates[130],
            signal_end=dates[130],
        )


def test_calendar_hash_and_strict_dplus1_availability_wall_are_verified() -> None:
    rows, dates = _panel()
    manifest = _manifest(rows)

    changed_calendar = list(rows)
    new_last_day = (date.fromisoformat(rows[-1].date) + timedelta(days=1)).isoformat()
    changed_calendar[-1] = replace(
        changed_calendar[-1],
        date=new_last_day,
        available_at=f"{new_last_day}T16:00:00+09:00",
    )
    calendar_manifest = replace(
        manifest,
        session_date_end=new_last_day,
        prepared_panel_digest=canonical_prepared_panel_digest(changed_calendar),
    )
    with pytest.raises(ValueError, match="trading_calendar_digest"):
        evaluate_index_vol_overlays(
            changed_calendar,
            manifest=calendar_manifest,
            signal_start=dates[130],
            signal_end=dates[130],
        )

    late = list(rows)
    late[130] = replace(
        late[130],
        available_at=f"{dates[131]}T15:00:00+09:00",
    )
    with pytest.raises(ValueError, match="strictly before"):
        evaluate_index_vol_overlays(
            late,
            manifest=manifest,
            signal_start=dates[130],
            signal_end=dates[130],
        )

    unavailable = list(rows)
    unavailable[130] = replace(unavailable[130], available_at=None)
    with pytest.raises(ValueError, match="available_at"):
        evaluate_index_vol_overlays(
            unavailable,
            manifest=manifest,
            signal_start=dates[130],
            signal_end=dates[130],
        )


def test_ratio_scale_beta_cap_and_d_dplus1_dplus2_timing() -> None:
    rows, dates = _panel(beta=4.0)
    # A sub-one term ratio must not lever the sleeve above 1.0.
    rows[130] = replace(rows[130], n225_front_atm_iv=10.0)
    report = _evaluate(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )
    base = _by_id(report, "n225_basevol_10_over_60_defensive_v1")
    atm = _by_id(report, "n225_observed_front_over_next_atm_v1")
    smile = _by_id(report, "n225_observed_downside_smile_front_over_next_v1")

    base_day = base["daily_path"][0]
    assert base_day["feature_ratio_x"] == pytest.approx(1.0)
    assert base_day["gross_scale"] == pytest.approx(1.0)
    assert base_day["estimated_beta"] == pytest.approx(4.0)
    assert base_day["topix_hedge_weight"] == pytest.approx(-1.5)
    assert base_day["signal_date"] == dates[130]
    assert base_day["rebalance_date"] == dates[131]
    assert base_day["pnl_date"] == dates[132]
    assert base_day["beta_window_last_return_date"] == dates[130]

    assert atm["daily_path"][0]["feature_ratio_x"] == pytest.approx(0.5)
    assert atm["daily_path"][0]["gross_scale"] == pytest.approx(1.0)
    # The raw wing term ratio is still 40/20=2.  Normalising each wing by its
    # ATM maturity level makes the intended smile term ratio (40/10)/(20/20)=4.
    assert smile["daily_path"][0]["feature_ratio_x"] == pytest.approx(4.0)
    assert smile["daily_path"][0]["feature_ratio_x"] != pytest.approx(2.0)
    assert smile["daily_path"][0]["gross_scale"] == pytest.approx(0.5)
    assert all(
        0.5 <= candidate["daily_path"][0]["gross_scale"] <= 1.0
        for candidate in report["candidates"]
    )


def test_ten_basis_point_turnover_and_terminal_close_are_in_performance() -> None:
    rows, dates = _panel(beta=4.0)
    report = _evaluate(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
        starting_capital=1_000_000.0,
    )
    result = _by_id(report, "n225_observed_downside_smile_front_over_next_v1")
    path = result["daily_path"][0]
    performance = result["performance"]

    assert path["feature_ratio_x"] == pytest.approx(4.0 / 3.0)
    assert path["sleeve_turnover_one_way"] == pytest.approx(0.75)
    assert path["topix_proxy_turnover_one_way"] == pytest.approx(1.5)
    assert path["rebalance_cost_amount"] == pytest.approx(
        1_000_000.0 * ONE_WAY_COST_RATE * 2.25
    )
    assert path["terminal_close"] is True
    assert path["target_sleeve_notional"] > 0.0
    assert path["target_topix_proxy_notional"] < 0.0
    assert path["terminal_turnover_one_way_amount"] == pytest.approx(
        abs(path["post_return_sleeve_notional"])
        + abs(path["post_return_topix_proxy_notional"])
    )
    assert path["terminal_close_cost_amount"] == pytest.approx(
        ONE_WAY_COST_RATE * path["terminal_turnover_one_way_amount"]
    )
    assert performance["cost_amount"] == pytest.approx(
        path["rebalance_cost_amount"] + path["terminal_close_cost_amount"]
    )
    assert performance["fill_count"] == 4
    assert performance["schema_version"] == "personal-performance/v1"
    assert performance["cost_turnover_fill_scope"] == "OVERLAY_INCREMENTAL_ONLY"
    assert performance["total_strategy_cost_turnover_fill_comparable"] is False
    terminal_trades = [
        trade for trade in result["trades"] if "terminal_close" in trade["side"]
    ]
    assert terminal_trades[0]["notional"] < 0.0
    assert terminal_trades[1]["notional"] > 0.0
    # One return observation deliberately preserves undefined dispersion ratios.
    assert performance["annualized_sharpe"] is None
    assert performance["annualized_volatility"] is None
    json.dumps(report, allow_nan=False)


def test_signed_notional_drift_drives_next_turnover_and_terminal_close() -> None:
    rows, dates = _panel(beta=1.25)
    report = _evaluate(
        rows,
        signal_start=dates[130],
        signal_end=dates[131],
    )
    result = _by_id(report, "n225_basevol_10_over_60_defensive_v1")
    first, second = result["daily_path"]

    assert second["pre_rebalance_sleeve_notional"] == pytest.approx(
        first["post_return_sleeve_notional"]
    )
    assert second["pre_rebalance_topix_proxy_notional"] == pytest.approx(
        first["post_return_topix_proxy_notional"]
    )
    assert second["sleeve_trade_notional"] == pytest.approx(
        second["target_sleeve_notional"]
        - second["pre_rebalance_sleeve_notional"]
    )
    assert second["topix_proxy_trade_notional"] == pytest.approx(
        second["target_topix_proxy_notional"]
        - second["pre_rebalance_topix_proxy_notional"]
    )
    assert second["sleeve_turnover_one_way_amount"] > 0.0
    assert second["topix_proxy_turnover_one_way_amount"] > 0.0
    assert second["terminal_turnover_one_way_amount"] == pytest.approx(
        abs(second["post_return_sleeve_notional"])
        + abs(second["post_return_topix_proxy_notional"])
    )
    assert second["terminal_close_cost_amount"] == pytest.approx(
        ONE_WAY_COST_RATE * second["terminal_turnover_one_way_amount"]
    )


def test_future_mutation_cannot_change_signal_or_beta() -> None:
    rows, dates = _panel(beta=1.25)
    original = _evaluate(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )
    mutated = list(rows)
    mutated[131] = replace(
        mutated[131],
        topix_cash_close=mutated[131].topix_cash_close * 20.0,
        n225_base_vol=999.0,
        n225_front_atm_iv=999.0,
    )
    mutated[132] = replace(
        mutated[132],
        topix_cash_close=mutated[132].topix_cash_close / 20.0,
        base_sleeve_return=-0.40,
        n225_next_downside_wing_iv=999.0,
    )
    changed = _evaluate(
        mutated,
        signal_start=dates[130],
        signal_end=dates[130],
    )

    for candidate_id in [candidate.candidate_id for candidate in OVERLAY_CANDIDATES]:
        before = _by_id(original, candidate_id)["daily_path"][0]
        after = _by_id(changed, candidate_id)["daily_path"][0]
        for field in (
            "feature_ratio_x",
            "gross_scale",
            "estimated_beta",
            "beta_observations",
            "beta_window_last_return_date",
            "topix_hedge_weight",
        ):
            if isinstance(before[field], float):
                assert after[field] == pytest.approx(before[field])
            else:
                assert after[field] == before[field]
    assert _by_id(changed, OVERLAY_CANDIDATES[0].candidate_id)["performance"] != (
        _by_id(original, OVERLAY_CANDIDATES[0].candidate_id)["performance"]
    )


def test_missing_required_observation_is_not_evaluated_and_never_filled() -> None:
    rows, dates = _panel()
    rows[130] = replace(rows[130], n225_front_downside_wing_iv=None)
    report = _evaluate(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )
    smile = _by_id(report, "n225_observed_downside_smile_front_over_next_v1")

    assert report["status"] == "NOT_EVALUATED"
    assert smile["status"] == "NOT_EVALUATED"
    assert smile["reason"] == "missing_required_row_no_forward_fill"
    assert smile["missing_required_rows"] == [
        {"date": dates[130], "reason": "observed_downside_smile_term_row_missing"}
    ]
    assert smile["daily_path"] == []
    assert smile["performance"] is None
    assert _by_id(report, "n225_observed_front_over_next_atm_v1")["status"] == (
        "EVALUATED"
    )


def test_beta_requires_63_returns_and_uses_at_most_126() -> None:
    rows, dates = _panel()
    too_early = _evaluate(
        rows,
        signal_start=dates[62],
        signal_end=dates[62],
    )
    observed = _by_id(too_early, "n225_observed_front_over_next_atm_v1")
    assert observed["status"] == "NOT_EVALUATED"
    assert observed["missing_required_rows"] == [
        {
            "date": dates[62],
            "reason": "beta_min_63_pairs_unavailable_in_last_126_source_sessions",
        }
    ]

    enough = _evaluate(
        rows,
        signal_start=dates[63],
        signal_end=dates[63],
    )
    observed_day = _by_id(
        enough, "n225_observed_front_over_next_atm_v1"
    )["daily_path"][0]
    assert observed_day["beta_observations"] == 63

    long_window = _evaluate(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )
    assert _by_id(
        long_window, "n225_observed_front_over_next_atm_v1"
    )["daily_path"][0]["beta_observations"] == 126


def test_beta_is_bounded_to_126_source_sessions_and_requires_fresh_pair() -> None:
    rows, dates = _panel(count=200)
    bounded = list(rows)
    # At signal index 180, source return sessions 55..180 are the exact last
    # 126.  Removing 64 leaves only 62, while older valid history must not be
    # pulled into the estimate.
    for index in range(55, 119):
        bounded[index] = replace(bounded[index], base_sleeve_return=None)
    report = _evaluate(
        bounded,
        signal_start=dates[180],
        signal_end=dates[180],
    )
    observed = _by_id(report, "n225_observed_front_over_next_atm_v1")
    assert observed["status"] == "NOT_EVALUATED"
    assert observed["missing_required_rows"] == [
        {
            "date": dates[180],
            "reason": "beta_min_63_pairs_unavailable_in_last_126_source_sessions",
        }
    ]

    stale = list(rows)
    stale[180] = replace(stale[180], base_sleeve_return=None)
    stale_report = _evaluate(
        stale,
        signal_start=dates[180],
        signal_end=dates[180],
    )
    stale_observed = _by_id(
        stale_report, "n225_observed_front_over_next_atm_v1"
    )
    assert stale_observed["missing_required_rows"] == [
        {"date": dates[180], "reason": "beta_current_signal_day_pair_unavailable"}
    ]


def test_base_g1_h0_control_is_diagnostic_and_outside_exact_four() -> None:
    rows, dates = _panel()
    report = _evaluate(
        rows,
        signal_start=dates[130],
        signal_end=dates[131],
    )
    control = report["diagnostic_control"]

    assert len(report["candidates"]) == 4
    assert report["candidate_policy"]["declared_count"] == 4
    assert report["candidate_policy"]["diagnostic_control_in_declared_count"] is False
    assert control["control_id"] == "base_g1_h0_control_v1"
    assert control["role"] == "NAV_WRAPPER_CONTROL_WITH_10BP_ENTRY_EXIT"
    assert control["ranking_role"] == "DIAGNOSTIC_CONTROL_NOT_RANKED"
    first, second = control["daily_path"]
    assert first["gross_scale"] == 1.0
    assert first["topix_hedge_weight"] == 0.0
    assert first["sleeve_trade_notional"] > 0.0
    assert first["terminal_close"] is False
    assert second["sleeve_trade_notional"] == pytest.approx(0.0)
    assert second["topix_proxy_trade_notional"] == pytest.approx(0.0)
    assert second["terminal_close"] is True
    assert control["performance"]["fill_count"] == 2
    assert control["control_id"] not in report["candidate_policy"]["candidate_order"]
    assert control["performance"]["cost_turnover_fill_scope"] == (
        "OVERLAY_INCREMENTAL_ONLY"
    )
    assert control["source_slice_wrapper_cost_semantics"] == (
        "EXCLUDES_NAV_WRAPPER_ENTRY_AND_LIQUIDATION"
    )


def test_svi_equivalents_are_diagnostic_only_and_cannot_change_results() -> None:
    rows, dates = _panel()
    original = _evaluate(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )
    changed_rows = list(rows)
    changed_rows[130] = replace(
        changed_rows[130],
        svi_equivalent_atm_term_ratio=-999.0,
        svi_equivalent_downside_smile_term_ratio=999.0,
    )
    changed = _evaluate(
        changed_rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )

    assert changed["candidates"] == original["candidates"]
    assert changed["candidate_policy"] == original["candidate_policy"]
    diagnostics = changed["svi_equivalent_diagnostics"]
    assert diagnostics["role"] == "DIAGNOSTIC_ONLY_NOT_RANKED"
    assert diagnostics["downside_smile_term_ratio_formula"] == (
        "(front_downside_wing_iv/front_atm_iv)/"
        "(next_downside_wing_iv/next_atm_iv)"
    )
    assert diagnostics["used_in_signals"] is False
    assert diagnostics["used_in_performance"] is False
    assert diagnostics["rows"][0]["svi_equivalent_atm_term_ratio"] is None
    assert diagnostics["rows"][0][
        "svi_equivalent_downside_smile_term_ratio"
    ] == 999.0


def test_missing_pnl_proxy_row_fails_all_candidates_without_partial_path() -> None:
    rows, dates = _panel()
    rows[132] = replace(rows[132], topix_cash_close=None)
    report = _evaluate(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )

    assert all(
        candidate["status"] == "NOT_EVALUATED"
        for candidate in report["candidates"]
    )
    assert all(candidate["performance"] is None for candidate in report["candidates"])
    assert all(candidate["daily_path"] == [] for candidate in report["candidates"])
    assert all(
        candidate["missing_required_rows"] == [
            {"date": dates[132], "reason": "topix_cash_return_missing"}
        ]
        for candidate in report["candidates"]
    )
