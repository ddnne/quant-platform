"""No receipt-minting API lives in the storage plane.

The ingestion runtime may derive a one-shot reconciled evidence handle only
after replaying immutable acquisition evidence and rereading the exact
structured segment.  A separately provisioned authority must consume that
handle and return a signed document; no such production authority is currently
available in-process.  Keeping this compatibility module empty makes old
imports fail closed while historical receipt rows remain auditable.
"""

from __future__ import annotations

__all__: list[str] = []
