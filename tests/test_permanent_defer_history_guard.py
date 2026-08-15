"""Permanent DEFER exclude guard for research history loads (W48 T2)."""

from __future__ import annotations

import pytest

from data_contracts import (
    PERMANENT_DEFER_DATASETS,
    PermanentDeferHistoryError,
    filter_permanent_defer,
    is_permanent_defer,
    reject_permanent_defer_for_history,
    require_history_eligible,
)
from data_access.adapter import QuantDataAccess


def test_permanent_defer_set_is_exactly_five():
    assert len(PERMANENT_DEFER_DATASETS) == 5
    assert PERMANENT_DEFER_DATASETS == frozenset(
        {
            "equities_master",
            "equities_earnings_calendar",
            "equities_bars_daily_am",
            "fins_earnings_date",
            "jsda_otc_bond_reference_prices",
        }
    )


def test_filter_permanent_defer_removes_only_defer():
    mixed = [
        "equities_bars_daily",
        "equities_master",
        "markets_calendar",
        "jsda_otc_bond_reference_prices",
        "equities_bars_daily",  # de-dupe
    ]
    assert filter_permanent_defer(mixed) == [
        "equities_bars_daily",
        "markets_calendar",
    ]


def test_reject_permanent_defer_for_history_fail_closed():
    reject_permanent_defer_for_history(["equities_bars_daily", "fins_summary"])
    with pytest.raises(PermanentDeferHistoryError, match="PD-D2-MASTER"):
        reject_permanent_defer_for_history(
            ["equities_bars_daily", "equities_master"]
        )


def test_require_history_eligible():
    assert require_history_eligible("equities_bars_daily") == "equities_bars_daily"
    with pytest.raises(PermanentDeferHistoryError, match="PD-D4-BARS-AM"):
        require_history_eligible("equities_bars_daily_am")
    assert is_permanent_defer("fins_earnings_date") is True
    assert is_permanent_defer("markets_breakdown") is False


def test_quant_data_access_query_rejects_permanent_defer():
    access = QuantDataAccess()
    with pytest.raises(PermanentDeferHistoryError, match="permanent DEFER"):
        access.query_dataset(
            dataset="equities_master",
            as_of="2026-08-01T15:30:00+09:00",
            start="2026-07-01",
            end="2026-07-02",
        )


def test_quant_data_access_describe_still_allows_defer_metadata():
    """Discovery/metadata is allowed; only fact history loads are blocked."""
    access = QuantDataAccess()
    # May raise allowlist PermissionError only if master not in contracts —
    # master is a premium-core contract, so describe must succeed.
    desc = access.describe_dataset("equities_master")
    assert desc["dataset"]["dataset_id"] == "equities_master"
