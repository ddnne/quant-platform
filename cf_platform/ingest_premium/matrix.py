"""Phase 3.5 — Validation matrix catalog (data-only).

This module is the **canonical Python mirror** of
``docs/phase35_validation_matrix.md``. It enumerates every check id referred
to in that document (C1–C12, M1–M4, B1–B7, A1–A3, K1–K3, E1–E3, F1–F5,
I1–I3, D1–D4, S1–S4, N1–N4, X1–X5), records the execution tier each id
belongs to (``daily`` or ``weekly``), and exposes lookup helpers used by both
the coverage runner (:mod:`cf_platform.ingest_premium.coverage`) and tests.

Pure data — no I/O. The runners that actually execute checks live in
:mod:`cf_platform.ingest_premium.coverage`.

Adding a new id? Add it here AND to the doc table — the catalog completeness
test (``tests/test_phase35_coverage_matrix.py``) parses the markdown to keep
the two in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Category codes from the doc legend (H/G/U/P/X).
Category = Literal["H", "G", "U", "P", "X"]
Tier = Literal["daily", "weekly"]


@dataclass(frozen=True)
class CheckDef:
    """One catalog row in the validation matrix.

    ``applies_to`` lists the dataset ids the check is meaningful for. An
    empty tuple means "cross-cutting" (one global result rather than
    per-dataset). The runner uses this to know whether to fan out.
    """

    id: str
    title: str
    category: Category
    tier: Tier
    applies_to: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Common checks (C1–C12) — apply to every Premium core dataset.
# ---------------------------------------------------------------------------
# The 23 Premium-core datasets (mirrors ingestion.jquants.catalog's
# PREMIUM_CORE_DATASETS). Hard-coded here so importing this module never
# transitively imports the catalog (kept self-contained for tests).
_PREMIUM_CORE: tuple[str, ...] = (
    "equities_master",
    "equities_bars_daily",
    "equities_bars_daily_am",
    "fins_summary",
    "fins_details",
    "fins_dividend",
    "fins_earnings_date",
    "equities_earnings_calendar",
    "markets_calendar",
    "equities_investor_types",
    "indices_bars_daily_topix",
    "indices_bars_daily",
    "derivatives_bars_daily_options_225",
    "derivatives_bars_daily_futures",
    "derivatives_bars_daily_options",
    "markets_margin_interest",
    "markets_margin_alert",
    "markets_short_ratio",
    "markets_short_sale_report",
    "markets_breakdown",
    "edinet_major_shareholders",
    "edinet_cross_shareholdings",
    "edinet_large_volume_shareholders",
)


_COMMON: tuple[CheckDef, ...] = (
    CheckDef("C1",  "Job exists",            "P", "daily",   _PREMIUM_CORE),
    CheckDef("C2",  "Last run outcome",      "P", "daily",   _PREMIUM_CORE),
    CheckDef("C3",  "Row count",             "P", "daily",   _PREMIUM_CORE),
    CheckDef("C4",  "event_time min/max",    "H", "daily",   _PREMIUM_CORE),
    CheckDef("C5",  "available_at coverage", "P", "daily",   _PREMIUM_CORE),
    CheckDef("C6",  "Lag vs official start", "H", "weekly",  _PREMIUM_CORE),
    CheckDef("C7",  "Expected years fill",   "H", "weekly",  _PREMIUM_CORE),
    CheckDef("C8",  "Freshness",             "P", "daily",   _PREMIUM_CORE),
    CheckDef("C9",  "Incremental continuity","G", "weekly",  _PREMIUM_CORE),
    CheckDef("C10", "Idempotency",           "P", "weekly",  _PREMIUM_CORE),
    CheckDef("C11", "Raw present",           "P", "weekly",  _PREMIUM_CORE),
    CheckDef("C12", "No addon leak",         "X", "daily",   ()),  # global
)


# ---------------------------------------------------------------------------
# Series-specific checks
# ---------------------------------------------------------------------------
_MASTER: tuple[CheckDef, ...] = (
    CheckDef("M1", "Issuer count order",          "U", "weekly", ("equities_master",)),
    CheckDef("M2", "Multi-day snapshots",         "U", "weekly", ("equities_master",)),
    CheckDef("M3", "Key codes present",           "U", "weekly", ("equities_master",)),
    CheckDef("M4", "Listings/delistings observed","U", "weekly", ("equities_master",)),
)

_BARS: tuple[CheckDef, ...] = (
    CheckDef("B1", "Year span near Premium",      "H", "weekly", ("equities_bars_daily",)),
    CheckDef("B2", "Universe coverage vs master", "U", "daily",  ("equities_bars_daily",)),
    CheckDef("B3", "Concentration top-N",         "U", "weekly", ("equities_bars_daily",)),
    CheckDef("B4", "Calendar gaps",               "G", "daily",  ("equities_bars_daily",)),
    CheckDef("B5", "Per-issuer missing rate",     "G", "weekly", ("equities_bars_daily",)),
    CheckDef("B6", "OHLC null/zero anomaly",      "P", "weekly", ("equities_bars_daily",)),
    CheckDef("B7", "Adjustment field consistency","P", "weekly", ("equities_bars_daily",)),
)

_AM: tuple[CheckDef, ...] = (
    CheckDef("A1", "Recent-only score",           "H", "weekly", ("equities_bars_daily_am",)),
    CheckDef("A2", "Sample join vs full bars",    "X", "weekly", ("equities_bars_daily_am",)),
    CheckDef("A3", "Issuer count not tiny",       "U", "weekly", ("equities_bars_daily_am",)),
)

_CAL: tuple[CheckDef, ...] = (
    CheckDef("K1", "Year span",                   "H", "weekly", ("markets_calendar",)),
    CheckDef("K2", "Holiday flag completeness",   "P", "weekly", ("markets_calendar",)),
    CheckDef("K3", "Bar gaps ⊆ non-trading days", "G", "daily",  ("markets_calendar",)),
)

_EARN: tuple[CheckDef, ...] = (
    CheckDef("E1", "Period coverage",             "H", "weekly",
             ("equities_earnings_calendar", "fins_earnings_date")),
    CheckDef("E2", "Recent-only schedule match",  "H", "weekly",
             ("equities_earnings_calendar", "fins_earnings_date")),
    CheckDef("E3", "Major-code miss rate",        "U", "weekly",
             ("equities_earnings_calendar", "fins_earnings_date")),
)

_FINS: tuple[CheckDef, ...] = (
    CheckDef("F1", "Year span vs start",          "H", "weekly",
             ("fins_summary", "fins_details", "fins_dividend")),
    CheckDef("F2", "Issuer coverage vs master",   "U", "weekly",
             ("fins_summary", "fins_details", "fins_dividend")),
    CheckDef("F3", "Period jumps (holes)",        "G", "weekly",
             ("fins_summary", "fins_details", "fins_dividend")),
    CheckDef("F4", "Dividend record/pay order",   "P", "weekly", ("fins_dividend",)),
    CheckDef("F5", "details ⊇ summary sample",    "X", "weekly",
             ("fins_summary", "fins_details")),
)

_IDX: tuple[CheckDef, ...] = (
    CheckDef("I1", "Year span",                   "H", "weekly",
             ("indices_bars_daily", "indices_bars_daily_topix")),
    CheckDef("I2", "Required index continuity",   "G", "weekly",
             ("indices_bars_daily", "indices_bars_daily_topix")),
    CheckDef("I3", "Not empty / not tiny",        "P", "weekly",
             ("indices_bars_daily", "indices_bars_daily_topix")),
)

_DERIV: tuple[CheckDef, ...] = (
    CheckDef("D1", "Year span",                   "H", "weekly",
             ("derivatives_bars_daily_options_225",
              "derivatives_bars_daily_futures",
              "derivatives_bars_daily_options")),
    CheckDef("D2", "Contract cardinality",        "U", "weekly",
             ("derivatives_bars_daily_options_225",
              "derivatives_bars_daily_futures",
              "derivatives_bars_daily_options")),
    CheckDef("D3", "Trading-day gaps",            "G", "weekly",
             ("derivatives_bars_daily_options_225",
              "derivatives_bars_daily_futures",
              "derivatives_bars_daily_options")),
    CheckDef("D4", "Post-expiry holes",           "G", "weekly",
             ("derivatives_bars_daily_options_225",
              "derivatives_bars_daily_futures",
              "derivatives_bars_daily_options")),
)

_STATS: tuple[CheckDef, ...] = (
    CheckDef("S1", "Year span per series",        "H", "weekly",
             ("equities_investor_types",
              "markets_margin_interest", "markets_margin_alert",
              "markets_short_ratio", "markets_short_sale_report",
              "markets_breakdown")),
    CheckDef("S2", "Cadence matches spec",        "P", "weekly",
             ("equities_investor_types",
              "markets_margin_interest", "markets_margin_alert",
              "markets_short_ratio", "markets_short_sale_report",
              "markets_breakdown")),
    CheckDef("S3", "Key cardinality",             "U", "weekly",
             ("equities_investor_types",
              "markets_margin_interest", "markets_margin_alert",
              "markets_short_ratio", "markets_short_sale_report",
              "markets_breakdown")),
    CheckDef("S4", "Freshness lag",               "P", "weekly",
             ("equities_investor_types",
              "markets_margin_interest", "markets_margin_alert",
              "markets_short_ratio", "markets_short_sale_report",
              "markets_breakdown")),
)

_EDINET: tuple[CheckDef, ...] = (
    CheckDef("N1", "Year span vs start",          "H", "weekly",
             ("edinet_major_shareholders",
              "edinet_cross_shareholdings",
              "edinet_large_volume_shareholders")),
    CheckDef("N2", "Issuer coverage (hundreds)",  "U", "weekly",
             ("edinet_major_shareholders",
              "edinet_cross_shareholdings",
              "edinet_large_volume_shareholders")),
    CheckDef("N3", "Filing date vs available_at", "P", "weekly",
             ("edinet_major_shareholders",
              "edinet_cross_shareholdings",
              "edinet_large_volume_shareholders")),
    CheckDef("N4", "Sample issuer time series",   "G", "weekly",
             ("edinet_major_shareholders",
              "edinet_cross_shareholdings",
              "edinet_large_volume_shareholders")),
)


# ---------------------------------------------------------------------------
# Cross-dataset checks (X1–X5)
# ---------------------------------------------------------------------------
_CROSS: tuple[CheckDef, ...] = (
    CheckDef("X1", "Master vs bar issuer count",  "X", "weekly", ()),
    CheckDef("X2", "Bar dates ⊆ calendar",        "X", "weekly", ()),
    CheckDef("X3", "PIT fixed as_of no leak",      "X", "weekly", ()),
    CheckDef("X4", "SQLite rows vs validation",   "X", "daily",  ()),
    CheckDef("X5", "Backfill moves min forward",  "H", "weekly", ()),
)


# All checks, in stable doc order.  C → M → B → A → K → E → F → I → D → S → N → X.
CHECKS: tuple[CheckDef, ...] = (
    _COMMON + _MASTER + _BARS + _AM + _CAL + _EARN + _FINS
    + _IDX + _DERIV + _STATS + _EDINET + _CROSS
)

# Tier membership — exactly the daily/weekly split documented in the matrix.
DAILY_IDS: frozenset[str] = frozenset(
    c.id for c in CHECKS if c.tier == "daily"
)
WEEKLY_IDS: frozenset[str] = frozenset(
    c.id for c in CHECKS if c.tier == "weekly"
)


def list_checks(tier: Tier | None = None) -> tuple[CheckDef, ...]:
    """Return checks, optionally filtered by tier.

    Stable order (the doc order above) regardless of filter. Pass
    ``tier="daily"`` to get just the daily set the runner executes nightly.
    """
    if tier is None:
        return CHECKS
    if tier not in ("daily", "weekly"):
        raise ValueError(f"tier must be 'daily' or 'weekly', got {tier!r}")
    return tuple(c for c in CHECKS if c.tier == tier)


def get_check(check_id: str) -> CheckDef:
    """Lookup by id. Raises ``KeyError`` if unknown.

    Used by the runner to resolve per-check metadata (title, applies_to)
    when emitting ``CheckResult`` rows.
    """
    for c in CHECKS:
        if c.id == check_id:
            return c
    raise KeyError(f"unknown validation check id: {check_id!r}")


def premium_core_datasets() -> tuple[str, ...]:
    """The 23 Premium-core dataset ids this matrix applies to.

    Mirrors ``ingestion.jquants.catalog.PREMIUM_CORE_DATASETS`` (kept
    inlined here so :mod:`cf_platform.ingest_premium.matrix` has no
    dependency on the ingestion package — it's pure data).
    """
    return _PREMIUM_CORE
