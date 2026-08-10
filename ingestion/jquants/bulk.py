"""Bulk / CSV transport helpers for J-Quants.

For heavy history the official API offers bulk endpoints (``/v2/bulk/...``)
that return large date ranges in fewer round-trips. Phase 1 fetches via the
paginated REST client by default; this module documents where a bulk path
exists so a later phase can prefer it without re-deriving the mapping.

``bulk_path_for(dataset_id)`` returns the canonical bulk path when one is
known, else ``None`` (caller falls back to paginated API). EDINET series have
no bulk surface — they always paginate.

Confirmed bulk paths are kept conservative; speculative ones are omitted
rather than guessed (a wrong bulk URL would only surface as a 404 at fetch
time, but we prefer to be explicit).
"""

from __future__ import annotations

from typing import Optional

from . import catalog

# Known official bulk endpoints keyed by dataset id. Add only paths confirmed
# against the J-Quants spec (see docs/data_sources.md verified date).
_BULK_PATHS: dict[str, str] = {
    "equities_bars_daily": "/v2/bulk/equities/bars/daily",
    "equities_bars_minute": "/v2/bulk/equities/bars/minute",
}


def bulk_path_for(dataset_id: str) -> Optional[str]:
    """Canonical bulk path for ``dataset_id``, or ``None`` if none is known.

    For ``td_bulk`` the dataset path *is* the bulk surface, so we return it
    directly. Returns ``None`` for the EDINET series (no bulk) and for any
    dataset whose bulk path is unconfirmed.
    """
    entry = catalog.get(dataset_id)
    if dataset_id == "td_bulk":
        return entry["path"]
    return _BULK_PATHS.get(dataset_id)


def prefers_bulk(dataset_id: str) -> bool:
    """Whether the catalog marks this dataset as bulk-preferred."""
    return catalog.get(dataset_id).get("bulk") == "bulk"
