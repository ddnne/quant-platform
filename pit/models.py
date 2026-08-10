"""Result wrappers for the PIT Data API.

A :class:`PitResult` carries the matching rows **plus** provenance metadata:
the ``as_of`` actually applied, the source/table/dataset, the row count, and
the ``pit_api`` version. That metadata is enough to reproduce or audit any
read — researchers should log it alongside downstream computations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Bumped per Phase 2 handoff. Surface in every result's metadata so a consumer
# can tell which contract a given response obeys.
PIT_API_VERSION = "0.2.0"


@dataclass(frozen=True)
class PitResult:
    """A point-in-time read result: ``rows`` + provenance ``metadata``.

    ``rows`` are plain ``dict``\\s of column -> value. JSON payload columns
    (``raw_payload`` / ``payload``) are decoded into Python objects when the
    stored value is valid JSON (best-effort; on failure the original string is
    kept). The wrapper is iterable / sized over ``rows`` for convenience:

        result = get_equity_bars_daily(as_of="2025-04-01T00:00:00+09:00", code="8697")
        for row in result:          # iterate rows directly
            ...
        len(result)                 # == result.metadata["count"]
        bool(result)                # False when no rows matched

    ``metadata`` always includes ``as_of`` (normalized), ``table``, ``count``,
    and ``pit_api_version``; ``source`` and (for the generic table) ``dataset``
    are added where meaningful.
    """

    rows: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def count(self) -> int:
        """Number of matching rows (also in ``metadata["count"]``)."""
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __bool__(self) -> bool:
        return bool(self.rows)
