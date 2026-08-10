"""J-Quants API V2 dataset catalog — Premium core + add-ons.

Single source of truth for every dataset we can fetch. Each entry carries:

* ``path``     — the ``/v2/...`` REST path (must start with ``/v2/``);
* ``group``    — ``core`` (Premium), ``addon`` (minute/tick/TDnet), or ``edinet``;
* ``bulk``     — preferred fetch mode: ``"api"`` (paginated REST) or ``"bulk"``
  (official bulk/CSV endpoint, when one exists);
* ``params``   — a hint of the common request params for documentation /
  normalization (not enforced);
* ``key``      — the identity field(s) used to build a natural key for the
  generic ``jquants_records`` table (best-effort; the normalizer falls back to
  a row hash when none match).

No endpoint is left as a stub: every id here is fetchable through
:meth:`ingestion.jquants.client.JQuantsClient.fetch_dataset`. The coverage
test in ``tests/test_jquants_catalog.py`` fails if any entry lacks a usable
``/v2/`` path.

Paths reflect the J-Quants API V2 spec (Premium + minute/TDnet add-ons); see
``docs/data_sources.md`` for the verified date and
https://jpx-jquants.com/en/spec/data-spec for the canonical reference. A few
add-on paths are marked ``_note`` where the official bulk/tick surface is
still being confirmed — they remain callable through the same client; only
their *preferred* transport is provisional.
"""

from __future__ import annotations

from typing import Any

BASE = "https://api.jquants.com"

# Premium-safe request spacing. Premium allows 500 req/min (8.33 rps); we cap
# at ~8 rps (0.125 s, 480/min) for headroom. Overridable per-client.
PREMIUM_MIN_INTERVAL = 0.125

DATASETS: dict[str, dict[str, Any]] = {
    # ------------------------------------------------------------------ core
    "equities_master": {
        "path": "/v2/equities/master",
        "group": "core",
        "bulk": "api",
        "params": ["code", "date"],
        "key": ["Code", "Date"],
    },
    "equities_bars_daily": {
        "path": "/v2/equities/bars/daily",
        "group": "core",
        "bulk": "bulk",
        "params": ["code", "date", "from", "to"],
        "key": ["Code", "Date"],
    },
    "equities_bars_daily_am": {
        "path": "/v2/equities/bars/daily/am",
        "group": "core",
        "bulk": "api",
        "params": ["code", "date"],
        "key": ["Code", "Date"],
    },
    "fins_summary": {
        "path": "/v2/fins/summary",
        "group": "core",
        "bulk": "api",
        "params": ["code", "date"],
        "key": ["Code", "DisclosedDate"],
        "_note": "OPTIONAL on some plans; raw-only when not normalizable.",
    },
    "fins_details": {
        "path": "/v2/fins/details",
        "group": "core",
        "bulk": "api",
        "params": ["code", "date"],
        "key": ["Code", "DisclosedDate"],
    },
    "fins_dividend": {
        "path": "/v2/fins/dividend",
        "group": "core",
        "bulk": "api",
        "params": ["code", "from", "to"],
        "key": ["Code", "AnnouncementDate"],
    },
    "fins_earnings_date": {
        "path": "/v2/fins/earnings-date",
        "group": "core",
        "bulk": "api",
        "params": ["code"],
        "key": ["Code", "Date"],
    },
    "equities_earnings_calendar": {
        "path": "/v2/equities/earnings-calendar",
        "group": "core",
        "bulk": "api",
        "params": ["from", "to", "date"],
        "key": ["Date", "Code"],
    },
    "markets_calendar": {
        "path": "/v2/markets/calendar",
        "group": "core",
        "bulk": "api",
        "params": ["from", "to", "holidaydivision"],
        "key": ["Date"],
    },
    "equities_investor_types": {
        "path": "/v2/equities/investor-types",
        "group": "core",
        "bulk": "api",
        "params": ["code", "from", "to"],
        "key": ["Date", "Code"],
    },
    "indices_bars_daily_topix": {
        "path": "/v2/indices/bars/daily/topix",
        "group": "core",
        "bulk": "api",
        "params": ["from", "to"],
        "key": ["Date"],
    },
    "indices_bars_daily": {
        "path": "/v2/indices/bars/daily",
        "group": "core",
        "bulk": "api",
        "params": ["code", "from", "to"],
        "key": ["Date", "Code"],
    },
    "derivatives_bars_daily_options_225": {
        "path": "/v2/derivatives/bars/daily/options/225",
        "group": "core",
        "bulk": "api",
        "params": ["from", "to"],
        "key": ["Date"],
    },
    "derivatives_bars_daily_futures": {
        "path": "/v2/derivatives/bars/daily/futures",
        "group": "core",
        "bulk": "api",
        "params": ["code", "from", "to"],
        "key": ["Date", "Code"],
    },
    "derivatives_bars_daily_options": {
        "path": "/v2/derivatives/bars/daily/options",
        "group": "core",
        "bulk": "api",
        "params": ["code", "from", "to"],
        "key": ["Date", "Code"],
    },
    "markets_margin_interest": {
        "path": "/v2/markets/margin-interest",
        "group": "core",
        "bulk": "api",
        "params": ["code", "date", "from", "to"],
        "key": ["Date", "Code"],
    },
    "markets_margin_alert": {
        "path": "/v2/markets/margin-alert",
        "group": "core",
        "bulk": "api",
        "params": ["code", "date", "from", "to"],
        "key": ["Date", "Code"],
    },
    "markets_short_ratio": {
        "path": "/v2/markets/short-ratio",
        "group": "core",
        "bulk": "api",
        "params": ["code", "date", "from", "to", "section"],
        "key": ["Date", "Code"],
    },
    "markets_short_sale_report": {
        "path": "/v2/markets/short-sale-report",
        "group": "core",
        "bulk": "api",
        "params": ["code", "date", "from", "to"],
        "key": ["Date", "Code"],
    },
    "markets_breakdown": {
        "path": "/v2/markets/breakdown",
        "group": "core",
        "bulk": "api",
        "params": ["code", "date", "from", "to"],
        "key": ["Date", "Code"],
    },
    # ----------------------------------------------------- EDINET (no bulk)
    "edinet_major_shareholders": {
        "path": "/v2/edinet/major-shareholders",
        "group": "edinet",
        "bulk": "api",
        "params": ["code", "date"],
        "key": ["Code", "DisclosedDate"],
    },
    "edinet_cross_shareholdings": {
        "path": "/v2/edinet/cross-shareholdings",
        "group": "edinet",
        "bulk": "api",
        "params": ["code", "date"],
        "key": ["Code", "DisclosedDate"],
    },
    "edinet_large_volume_shareholders": {
        "path": "/v2/edinet/large-volume-shareholders",
        "group": "edinet",
        "bulk": "api",
        "params": ["code", "date"],
        "key": ["Code", "DisclosedDate"],
    },
    # --------------------------------------------------------------- add-ons
    "equities_bars_minute": {
        "path": "/v2/equities/bars/minute",
        "group": "addon",
        "bulk": "bulk",
        "params": ["code", "from", "to"],
        "key": ["Code", "Date"],
    },
    "equities_trades": {
        "path": "/v2/equities/trades",
        "group": "addon",
        "bulk": "bulk",
        "params": ["code", "date", "from", "to"],
        "key": ["Code", "Date"],
        "_note": "Tick (trades) add-on; official path/CSV surface to confirm. "
                 "Callable via the generic client regardless.",
    },
    "td_list": {
        "path": "/v2/td/list",
        "group": "addon",
        "bulk": "api",
        "params": ["date"],
        "key": ["Date"],
    },
    "td_files": {
        "path": "/v2/td/files",
        "group": "addon",
        "bulk": "api",
        "params": ["date"],
        "key": ["Date"],
    },
    "td_bulk": {
        "path": "/v2/td/bulk",
        "group": "addon",
        "bulk": "bulk",
        "params": ["date"],
        "key": ["Date"],
        "_note": "TDnet bulk add-on; official path to confirm.",
    },
}


def list_datasets(group: str | None = None) -> list[str]:
    """All dataset ids, optionally filtered by ``group`` (core/addon/edinet)."""
    if group is None:
        return list(DATASETS.keys())
    return [k for k, v in DATASETS.items() if v.get("group") == group]


def get(dataset_id: str) -> dict[str, Any]:
    """Catalog entry for ``dataset_id`` — raises ``KeyError`` if unknown."""
    if dataset_id not in DATASETS:
        raise KeyError(f"unknown jquants dataset: {dataset_id!r}")
    return DATASETS[dataset_id]


def path_of(dataset_id: str) -> str:
    """The ``/v2/...`` REST path for ``dataset_id``."""
    return get(dataset_id)["path"]


def assert_catalog_coverage() -> None:
    """Fail fast (raise) if any catalog entry is missing a usable ``/v2/`` path.

    Called from the coverage test and importable so downstream tooling can
    assert completeness without re-implementing the check.
    """
    for did, entry in DATASETS.items():
        p = entry.get("path", "")
        if not isinstance(p, str) or not p.startswith("/v2/") or len(p) <= len("/v2/"):
            raise ValueError(
                f"catalog entry {did!r} has no usable /v2/ path: {p!r}"
            )
