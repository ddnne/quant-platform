"""Phase 3.5 — Premium core closed-loop dataset set.

Asserts:
* `PREMIUM_CORE_DATASETS` is the canonical required set from the handoff.
* No addon id is in the required set.
* The TypeScript mirror (catalog.ts) agrees with the Python list.
"""

from __future__ import annotations

import re
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

CATALOG_TS = Path(__file__).resolve().parents[1] / (
    "platform/workers/ingestion-premium/src/catalog.ts"
)


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


def test_typescript_catalog_matches_python():
    """catalog.ts must mirror the Python list exactly."""
    assert CATALOG_TS.exists(), f"missing {CATALOG_TS}"
    text = CATALOG_TS.read_text(encoding="utf-8")
    # Pull out the id: "..." tokens that appear in PREMIUM_CORE_DATASETS.
    # The TS file lists each entry as `{ id: "X", path: "/v2/...", ... }`.
    ts_ids = set(re.findall(r'id:\s*"([^"]+)"', text))
    # The interface field also matches "id"; the actual dataset ids are the
    # 23 known names. Sanity-check we found at least all of them.
    missing = set(PREMIUM_CORE_DATASETS) - ts_ids
    extra = ts_ids - set(PREMIUM_CORE_DATASETS)
    assert not missing, f"TS catalog.ts missing ids: {missing}"
    assert not extra, f"TS catalog.ts has extra ids: {extra}"


def test_typescript_paths_match_python():
    """Each TS entry's path agrees with the Python catalog."""
    text = CATALOG_TS.read_text(encoding="utf-8")
    # Parse `{ id: "X", path: "/v2/Y", ... }` pairs line-by-line.
    pairs = re.findall(r'id:\s*"([^"]+)"[^{\n]*?path:\s*"([^"]+)"', text)
    parsed = {pid: path for pid, path in pairs}
    for did in PREMIUM_CORE_DATASETS:
        assert parsed.get(did) == DATASETS[did]["path"], (
            f"path mismatch for {did}: ts={parsed.get(did)!r} "
            f"py={DATASETS[did]['path']!r}"
        )


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
    "equities_earnings_calendar": "range",
    "markets_calendar": "range",
    "equities_investor_types": "range",
    "indices_bars_daily_topix": "range",
    # Everything else in the Premium core set is single-day market-wide.
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


def _parse_ts_entries(text: str) -> dict[str, dict[str, str]]:
    """Parse each `{ id: "..", ... }` line into {id: {field: value, ...}}.

    Only single-line entries are supported — the catalog deliberately keeps
    one dataset per line for grep-ability and to make this regex robust.
    """
    entries: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        m_id = re.search(r'id:\s*"([^"]+)"', line)
        if not m_id or line.strip().startswith("//"):
            continue
        fields: dict[str, str] = {}
        for field in ("path", "bulk", "dateMode", "dayParam"):
            m = re.search(rf'{field}:\s*"([^"]+)"', line)
            if m:
                fields[field] = m.group(1)
        entries[m_id.group(1)] = fields
    return entries


def test_typescript_datemode_contract():
    """Every TS entry has the dateMode that matches the J-Quants V2 API shape.

    See DATEMODE_EXPECTED docstring for the failure-mode each entry guards.
    """
    text = CATALOG_TS.read_text(encoding="utf-8")
    entries = _parse_ts_entries(text)
    for did, expected_mode in DATEMODE_EXPECTED.items():
        assert did in entries, f"{did} missing from catalog.ts"
        actual_mode = entries[did].get("dateMode")
        assert actual_mode == expected_mode, (
            f"{did}: expected dateMode={expected_mode!r} "
            f"but catalog.ts has {actual_mode!r} — bare from/to is rejected "
            f"by this endpoint without a code filter"
        )


def test_typescript_dayparam_contract():
    """Endpoints whose single-day key is not ``date`` must declare dayParam."""
    text = CATALOG_TS.read_text(encoding="utf-8")
    entries = _parse_ts_entries(text)
    for did, expected_key in DAYPARAM_EXPECTED.items():
        assert did in entries, f"{did} missing from catalog.ts"
        actual = entries[did].get("dayParam")
        assert actual == expected_key, (
            f"{did}: expected dayParam={expected_key!r} "
            f"but catalog.ts has {actual!r}"
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
