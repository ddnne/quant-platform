"""Thin dataset fetch wrappers over :class:`JQuantsClient`.

The generic :meth:`JQuantsClient.fetch_dataset` already covers the whole
catalog; this module provides a few readable aliases plus a single
:func:`fetch` entry point so call sites read as ``fetch(client, "fins_dividend",
code="8697")`` rather than carrying the client method name around. It also
normalizes ``from_date``/``to_date`` aliases the same way the client does.
"""

from __future__ import annotations

from typing import Any

from . import catalog
from .client import JQuantsClient


def fetch(client: JQuantsClient, dataset_id: str, **params: Any) -> list[dict]:
    """Fetch any catalog dataset by id (delegates to the client)."""
    return client.fetch_dataset(dataset_id, **params)


def available_datasets(group: str | None = None) -> list[str]:
    """All catalog dataset ids, optionally filtered by group."""
    return catalog.list_datasets(group)


# Readable aliases for the most common series — each is just fetch() with a
# fixed dataset id. Keep this list small; reach for fetch(client, <id>) for
# anything not listed here.
def equities_master(client: JQuantsClient, **p: Any) -> list[dict]:
    return fetch(client, "equities_master", **p)


def equities_bars_daily(client: JQuantsClient, **p: Any) -> list[dict]:
    return fetch(client, "equities_bars_daily", **p)


def fins_dividend(client: JQuantsClient, **p: Any) -> list[dict]:
    return fetch(client, "fins_dividend", **p)


def markets_calendar(client: JQuantsClient, **p: Any) -> list[dict]:
    return fetch(client, "markets_calendar", **p)
