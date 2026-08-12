"""PIT Data API error types.

The PIT API is **read-only** and requires an ``as_of`` on every call. These
errors surface contract violations explicitly instead of leaking
``TypeError`` / ``sqlite3`` noise to callers. All inherit from
:class:`PitError`, so callers can catch the whole family with one ``except``.
"""

from __future__ import annotations


class PitError(Exception):
    """Base class for every PIT Data API error."""


class AsOfRequired(PitError):
    """Raised when a PIT read is attempted without a required ``as_of``.

    ``as_of`` is mandatory on every public ``get_*`` call — there is **no**
    "latest" fallback. A missing ``as_of`` is a look-ahead footgun, so the API
    refuses to guess. Pass an explicit Asia/Tokyo instant
    (e.g. ``"2025-04-01T00:00:00+09:00"``).
    """


class InvalidAsOf(PitError):
    """Raised when ``as_of`` cannot be parsed into an Asia/Tokyo instant."""


class InvalidDataset(PitError):
    """Raised when a required ``dataset`` selector is missing or empty.

    Only relevant for the generic ``jquants_records`` table, which is
    partitioned by ``dataset``. Unknown (non-empty) dataset ids are **not**
    rejected — they simply yield an empty result, since the table is a
    catch-all for future catalog entries.
    """


class DatabaseNotFound(PitError):
    """Raised when the structured SQLite DB does not exist at the resolved path.

    A missing DB is a setup error (run ingestion first), not an empty result —
    returning ``[]`` here would silently masquerade as "no data as of then".
    """


class SnapshotNotReady(PitError):
    """Raised when a managed database is not a committed READY generation."""
