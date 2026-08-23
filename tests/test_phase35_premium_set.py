"""Phase 3.5 — Premium core closed-loop dataset set.

Asserts that Premium core remains closed and both runtimes consume the same
checked-in contract document instead of maintaining duplicate catalogs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingestion.jquants.catalog import (
    DATASETS,
    PREMIUM_CORE_DATASETS,
    assert_catalog_coverage,
    is_premium_core,
    list_datasets,
)

REQUIRED_HANDOFF_IDS = {
    "equities_master", "equities_bars_daily", "equities_bars_daily_am",
    "fins_summary", "fins_details", "fins_dividend", "fins_earnings_date",
    "equities_earnings_calendar", "markets_calendar", "equities_investor_types",
    "indices_bars_daily_topix", "indices_bars_daily",
    "derivatives_bars_daily_options_225", "derivatives_bars_daily_futures",
    "derivatives_bars_daily_options",
    "markets_margin_interest", "markets_margin_alert", "markets_short_ratio",
    "markets_short_sale_report", "markets_breakdown",
    "edinet_major_shareholders", "edinet_cross_shareholdings",
    "edinet_large_volume_shareholders",
}

ADDON_IDS = {"equities_bars_minute", "equities_trades", "td_list", "td_files", "td_bulk"}

CONTRACT_JSON = Path(__file__).resolve().parents[1] / (
    "packages/data_plane/data_contracts/jquants_premium_core.json"
)


def _contract_entries() -> dict[str, dict]:
    document = json.loads(CONTRACT_JSON.read_text(encoding="utf-8"))
    return {entry["dataset_id"]: entry for entry in document["datasets"]}


def test_premium_core_is_exactly_the_required_set():
    """The Python filter must equal the handoff's required set."""
    assert set(PREMIUM_CORE_DATASETS) == REQUIRED_HANDOFF_IDS


def test_premium_core_excludes_addons():
    """Addon ids (minute/tick/TDnet) must NOT be in the required schedule."""
    leaked = set(PREMIUM_CORE_DATASETS) & ADDON_IDS
    assert not leaked, f"addon ids leaked into PREMIUM_CORE_DATASETS: {leaked}"


def test_premium_core_covers_all_core_and_edinet():
    """The filter is exactly (core ∪ edinet) groups from the catalog."""
    expected = set(list_datasets("core")) | set(list_datasets("edinet"))
    assert set(PREMIUM_CORE_DATASETS) == expected


def test_is_premium_core_predicate():
    for did in PREMIUM_CORE_DATASETS:
        assert is_premium_core(did)
    for aid in ADDON_IDS:
        assert not is_premium_core(aid)


def test_required_datasets_all_have_v2_paths():
    """Every required dataset has a usable /v2/ path (no stub-only entries)."""
    for did in PREMIUM_CORE_DATASETS:
        path = DATASETS[did]["path"]
        assert isinstance(path, str) and path.startswith("/v2/") and len(path) > 4, did


def test_contract_json_matches_premium_core_datasets():
    """Python PREMIUM_CORE_DATASETS must equal the shared JSON document ids."""
    assert set(_contract_entries()) == set(PREMIUM_CORE_DATASETS)


def test_typescript_paths_match_python():
    """The shared document feeding TypeScript agrees with Python catalog views."""
    entries = _contract_entries()
    for did in PREMIUM_CORE_DATASETS:
        assert entries[did]["path"] == DATASETS[did]["path"]


# ---------------------------------------------------------------------------
# dateMode contract — J-Quants V2 endpoint shape requirements.
#
# Many Premium endpoints reject bare ``from``/``to`` without a ``code`` and
# require ``date`` (or a sibling like ``disc_date``/``scheduled_date``) for
# market-wide pulls. The CF cron job has no code list to fan out over, so
# any dataset whose upstream rejects bare from/to MUST be configured with
# dateMode="today" — otherwise the scheduled run will fail with HTTP 400
# every hour. These ids are pinned from observed live API errors (Phase 3.5
# cron-param-fix); do not regress them without a live-API justification.
# ---------------------------------------------------------------------------
DATEMODE_EXPECTED = {
    # Endpoints that accept bare from/to without code (verified live).
    "markets_calendar": "range",
    "equities_investor_types": "range",
    "indices_bars_daily_topix": "range",
    # Everything else in the Premium core set is single-day market-wide.
    # Earnings calendar is a next-business-day snapshot (pagination_key only).
    "equities_earnings_calendar": "today",
    "equities_master": "today",
    "equities_bars_daily": "today",
    "equities_bars_daily_am": "today",
    "fins_summary": "today",
    "fins_details": "today",
    "fins_dividend": "today",
    "fins_earnings_date": "today",
    "indices_bars_daily": "today",
    "derivatives_bars_daily_options_225": "today",
    "derivatives_bars_daily_futures": "today",
    "derivatives_bars_daily_options": "today",
    "markets_margin_interest": "today",
    "markets_margin_alert": "today",
    "markets_short_ratio": "today",
    "markets_short_sale_report": "today",
    "markets_breakdown": "today",
    "edinet_major_shareholders": "today",
    "edinet_cross_shareholdings": "today",
    "edinet_large_volume_shareholders": "today",
}

# Single-day-param override key (default is "date"). Pinned from live API
# error messages: e.g. ``markets_short_sale_report`` rejects ``date=`` and
# only accepts ``code``/``disc_date``/``calc_date``.
DAYPARAM_EXPECTED = {
    "markets_short_sale_report": "disc_date",
}


def test_typescript_datemode_contract():
    """Every TS entry has the dateMode that matches the J-Quants V2 API shape.

    See DATEMODE_EXPECTED docstring for the failure-mode each entry guards.
    """
    entries = _contract_entries()
    for did, expected_mode in DATEMODE_EXPECTED.items():
        assert did in entries, f"{did} missing from shared contract"
        actual_mode = entries[did].get("date_mode")
        assert actual_mode == expected_mode, (
            f"{did}: expected dateMode={expected_mode!r} "
            f"but the shared contract has {actual_mode!r} — bare from/to is rejected "
            f"by this endpoint without a code filter"
        )


def test_typescript_dayparam_contract():
    """Endpoints whose single-day key is not ``date`` must declare dayParam."""
    entries = _contract_entries()
    for did, expected_key in DAYPARAM_EXPECTED.items():
        assert did in entries, f"{did} missing from shared contract"
        actual = entries[did].get("day_param")
        assert actual == expected_key, (
            f"{did}: expected dayParam={expected_key!r} "
            f"but the shared contract has {actual!r}"
        )


def test_datemode_contract_covers_all_premium_core():
    """The contract above must enumerate every Premium core dataset.

    New datasets added to PREMIUM_CORE_DATASETS must declare their dateMode
    here, otherwise the cron job will silently default to the wrong shape.
    """
    missing = set(PREMIUM_CORE_DATASETS) - set(DATEMODE_EXPECTED)
    assert not missing, (
        f"dateMode contract missing for: {sorted(missing)}; add each to "
        f"DATEMODE_EXPECTED with a justification comment"
    )


def test_assert_catalog_coverage_still_ok():
    assert_catalog_coverage()
