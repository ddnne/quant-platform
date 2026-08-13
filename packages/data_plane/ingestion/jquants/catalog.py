"""J-Quants API V2 catalog.

Premium-core metadata is loaded from ``data_contracts/``.  The Worker imports
that same JSON document, so paths, date modes, natural keys, and PIT policies
have one authority.  Add-on datasets remain catalogued here because the F0
contract covers the Premium 23 only.
"""

from __future__ import annotations

from typing import Any

from data_contracts.loader import all_contracts

BASE = "https://api.jquants.com"
# Premium ~500 req/min → 0.12 s floor (500/min). Near-ceiling; 429 recovers via short backoff.
PREMIUM_MIN_INTERVAL = 0.12


def _premium_entries() -> dict[str, dict[str, Any]]:
    return {c.dataset_id: c.as_catalog_entry() for c in all_contracts()}


_ADDON_DATASETS: dict[str, dict[str, Any]] = {
    "equities_bars_minute": {
        "path": "/v2/equities/bars/minute",
        "group": "addon",
        "bulk": "bulk",
        "params": ["code", "from", "to"],
        # DateTime (bulk) and Date+Time (REST) are folded to one minute key by
        # normalize._natural_key so switching transports remains idempotent.
        "key": ["Code", "Date", "DateTime", "Time"],
    },
    "equities_trades": {
        "path": "/v2/equities/trades",
        "group": "addon",
        "bulk": "bulk",
        "params": ["code", "date", "from", "to"],
        "key": ["Code", "Date", "DateTime"],
        "_note": "Tick add-on; official path/CSV surface remains provisional.",
    },
    "td_list": {
        "path": "/v2/td/list",
        "group": "addon",
        "bulk": "api",
        "params": ["date"],
        "key": ["DiscDate", "DiscNo"],
    },
    "td_files": {
        "path": "/v2/td/files",
        "group": "addon",
        "bulk": "api",
        "params": ["date"],
        "key": ["DiscDate", "DiscNo"],
    },
    "td_bulk": {
        "path": "/v2/td/bulk",
        "group": "addon",
        "bulk": "bulk",
        "params": ["date"],
        "key": ["DiscDate", "DiscNo"],
        "_note": "TDnet bulk add-on; official path remains provisional.",
    },
}

DATASETS: dict[str, dict[str, Any]] = {**_premium_entries(), **_ADDON_DATASETS}


def list_datasets(group: str | None = None) -> list[str]:
    """All dataset ids, optionally filtered by ``group``."""
    if group is None:
        return list(DATASETS)
    return [dataset_id for dataset_id, entry in DATASETS.items() if entry["group"] == group]


def get(dataset_id: str) -> dict[str, Any]:
    try:
        return DATASETS[dataset_id]
    except KeyError as exc:
        raise KeyError(f"unknown jquants dataset: {dataset_id!r}") from exc


def path_of(dataset_id: str) -> str:
    return get(dataset_id)["path"]


PREMIUM_CORE_DATASETS: tuple[str, ...] = tuple(c.dataset_id for c in all_contracts())


def is_premium_core(dataset_id: str) -> bool:
    return dataset_id in PREMIUM_CORE_DATASETS


def assert_catalog_coverage() -> None:
    for dataset_id, entry in DATASETS.items():
        path = entry.get("path", "")
        if not isinstance(path, str) or not path.startswith("/v2/") or len(path) <= 4:
            raise ValueError(
                f"catalog entry {dataset_id!r} has no usable /v2/ path: {path!r}"
            )


__all__ = [
    "BASE",
    "DATASETS",
    "PREMIUM_CORE_DATASETS",
    "PREMIUM_MIN_INTERVAL",
    "assert_catalog_coverage",
    "get",
    "is_premium_core",
    "list_datasets",
    "path_of",
]
