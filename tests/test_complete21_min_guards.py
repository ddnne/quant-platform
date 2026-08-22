"""COMPLETE 21 min features — dataset / DEFER fail-closed guards.

FeatureContext PIT readers must not run for permanent DEFER datasets.
Declared complete21_min dataset tuples stay COMPLETE-21-only.
Shared builders: ``tests/complete21_min_util.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from data_contracts import PERMANENT_DEFER_DATASETS, PermanentDeferHistoryError
from features import (
    COMPLETE_21_DATASETS,
    filter_feature_datasets,
    require_feature_dataset,
    require_feature_datasets,
)
from features.runtime import FeatureContext


def test_complete_21_count_and_no_overlap_with_defer():
    assert len(COMPLETE_21_DATASETS) == 21
    assert COMPLETE_21_DATASETS.isdisjoint(PERMANENT_DEFER_DATASETS)
    assert "equities_bars_daily" in COMPLETE_21_DATASETS
    assert "equities_master" not in COMPLETE_21_DATASETS


def test_require_feature_dataset_rejects_all_permanent_defer():
    for ds in sorted(PERMANENT_DEFER_DATASETS):
        with pytest.raises(PermanentDeferHistoryError):
            require_feature_dataset(ds, context="test")
    assert require_feature_dataset("equities_bars_daily") == "equities_bars_daily"


def test_require_feature_datasets_and_filter():
    require_feature_datasets(["equities_bars_daily", "fins_summary"])
    # W68: fins_earnings_date tip4 COMPLETE — history-eligible (not PD-MX-EARN-TIP).
    require_feature_datasets(
        ["equities_bars_daily", "fins_earnings_date"],
        context="feature test",
    )
    with pytest.raises(PermanentDeferHistoryError, match="PD-D4-EARN-CAL"):
        require_feature_datasets(
            ["equities_bars_daily", "equities_earnings_calendar"],
            context="feature test",
        )
    assert filter_feature_datasets(
        ["equities_bars_daily", "equities_master", "markets_calendar"]
    ) == ["equities_bars_daily", "markets_calendar"]


def test_feature_context_jquants_records_rejects_defer():
    def _never_read(resource, kwargs):
        raise AssertionError(f"PIT read must not run for DEFER: {resource} {kwargs}")

    ctx = FeatureContext(
        as_of="2026-08-01T15:30:00+09:00",
        _input_values={},
        _pit_reader=_never_read,
    )
    with pytest.raises(PermanentDeferHistoryError, match="PD-D4-BARS-AM"):
        ctx.get_jquants_records(dataset="equities_bars_daily_am")
    with pytest.raises(PermanentDeferHistoryError, match="PD-D2-MASTER"):
        ctx.get_equity_master()


def test_feature_context_jquants_records_allows_complete_dataset():
    calls: list[tuple[str, dict]] = []

    def _reader(resource, kwargs):
        calls.append((resource, dict(kwargs)))
        return SimpleNamespace(rows=[])

    ctx = FeatureContext(
        as_of="2026-08-01T15:30:00+09:00",
        _input_values={},
        _pit_reader=_reader,
    )
    ctx.get_jquants_records(dataset="fins_summary", code="8697")
    assert calls == [
        ("jquants_records", {"dataset": "fins_summary", "code": "8697"})
    ]
    ctx.get_equity_bars_daily(code="8697")
    assert calls[-1][0] == "equity_bars_daily"


def test_feature_context_jsda_repo_rates_guard_and_read():
    calls: list[tuple[str, dict]] = []

    def _reader(resource, kwargs):
        calls.append((resource, dict(kwargs)))
        return SimpleNamespace(rows=[])

    ctx = FeatureContext(
        as_of="2026-08-01T15:30:00+09:00",
        _input_values={},
        _pit_reader=_reader,
    )
    ctx.get_jsda_repo_rates(tenor="overnight")
    assert calls == [("jsda_repo_rates", {"tenor": "overnight"})]


def test_new_feature_dataset_constants_are_complete_only():
    """Every complete21_min declared dataset must be COMPLETE 21, never DEFER."""
    from features import complete21_min as mod

    constants = (
        mod._VOLUME_DATASETS,
        mod._TOPIX_REL_DATASETS,
        mod._DISC_DATASETS,
        mod._MARGIN_DATASETS,
        mod._SHORT_RATIO_DATASETS,
        mod._CALENDAR_DATASETS,
        mod._REPO_DATASETS,
        mod._RETURN_C21_DATASETS,
        mod._MARGIN_ALERT_DATASETS,
        mod._FUTURES_DATASETS,
        mod._FUND_VALUE_DATASETS,
    )
    for group in constants:
        for ds in group:
            assert ds in COMPLETE_21_DATASETS, ds
            assert ds not in PERMANENT_DEFER_DATASETS, ds


def test_complete21_min_declared_datasets_reject_each_permanent_defer():
    """Every declared feature dataset list fails closed when any DEFER is mixed in."""
    from features import complete21_min as mod

    groups = (
        mod._VOLUME_DATASETS,
        mod._TOPIX_REL_DATASETS,
        mod._DISC_DATASETS,
        mod._MARGIN_DATASETS,
        mod._SHORT_RATIO_DATASETS,
        mod._CALENDAR_DATASETS,
        mod._REPO_DATASETS,
        mod._RETURN_C21_DATASETS,
        mod._MARGIN_ALERT_DATASETS,
        mod._FUTURES_DATASETS,
        mod._FUND_VALUE_DATASETS,
    )
    for group in groups:
        for defer_ds in sorted(PERMANENT_DEFER_DATASETS):
            poisoned = list(group) + [defer_ds]
            with pytest.raises(PermanentDeferHistoryError):
                require_feature_datasets(poisoned, context="feature T5 DEFER")


def test_topix_relative_1d_rejects_if_internal_datasets_were_defer(monkeypatch):
    """Feature preflight uses require_feature_datasets — DEFER list must fail closed."""
    from features import complete21_min as mod

    with pytest.raises(PermanentDeferHistoryError):
        # Direct call of the guard with a poisoned list (simulates misdeclaration).
        require_feature_datasets(
            ["equities_bars_daily", "equities_bars_daily_am"],
            context="feature topix_relative_1d",
        )
    # Module constant must stay COMPLETE-only.
    for ds in mod._TOPIX_REL_DATASETS:
        assert ds in COMPLETE_21_DATASETS
        assert ds not in PERMANENT_DEFER_DATASETS


def test_margin_short_calendar_repo_reject_defer_poison(monkeypatch):
    """Each new feature's declared datasets stay DEFER-free; poison fails closed."""
    for poisoned in (
        ["markets_margin_interest", "equities_master"],
        ["markets_short_ratio", "equities_earnings_calendar"],  # W68: fins not DEFER
        ["markets_calendar", "equities_bars_daily_am"],
        ["jsda_tokyo_repo_rates", "jsda_otc_bond_reference_prices"],
        ["equities_bars_daily", "equities_bars_daily_am"],  # return_1d_c21 path
        ["markets_margin_alert", "equities_master"],
        ["derivatives_bars_daily_futures", "equities_earnings_calendar"],
    ):
        with pytest.raises(PermanentDeferHistoryError):
            require_feature_datasets(poisoned, context="feature test")

