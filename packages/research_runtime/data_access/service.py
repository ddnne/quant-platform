"""Shared read-domain service for Ops-current and Research-READY clients.

The two planes deliberately have different consistency contracts:

* ``OpsCurrentReadService`` reads the mutable local control database. Its
  results are operational observations and are never research facts.
* ``ResearchReadyReadService`` composes :class:`QuantDataAccess`, preserving
  its READY-only, PIT-bounded behavior.

Only named domain operations cross this boundary. Callers cannot provide SQL,
filesystem paths, storage handles, URLs, or mutation instructions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ops.current_read import (
    DEFAULT_OPS_DB,
    OPS_CURRENT_METHODS,
    OpsCurrentReadService,
    _plane,
)

from .adapter import QuantDataAccess


RESEARCH_READY_METHODS = frozenset({
    "list_datasets",
    "describe_dataset",
    "coverage_summary",
    "dataset_coverage",
    "coverage_gaps",
    "latest_ready_snapshot",
    "describe_snapshot",
    "diff_snapshots",
    "quality_summary",
    "quality_failures",
    "query_dataset",
    "get_series",
    "compute_feature",
    "compute_features",
    "raw_manifest",
    "trace_provenance",
})


class ResearchReadyReadService:
    """Immutable research interface backed only by published READY data."""

    plane = "research_ready"
    mutable = False

    def __init__(self, access: QuantDataAccess) -> None:
        self.access = access

    def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        if name not in RESEARCH_READY_METHODS:
            raise KeyError(f"unknown Research READY read: {name!r}")
        method = getattr(self.access, name)
        value = method(**dict(arguments or {}))
        return _plane(value, name=self.plane, mutable=self.mutable)

    def latest_ready_snapshot(self) -> dict[str, Any]:
        return self.call_tool("latest_ready_snapshot")

    def snapshot_quality(self, snapshot_id: str | None = None) -> dict[str, Any]:
        arguments = {"snapshot_id": snapshot_id} if snapshot_id is not None else {}
        return self.call_tool("quality_summary", arguments)


class QuantReadDomainService:
    """Shared dispatcher with explicit current and immutable interfaces."""

    def __init__(
        self,
        research_access: QuantDataAccess | None = None,
        *,
        ops_db_path: str | Path = DEFAULT_OPS_DB,
    ) -> None:
        self.research_ready = ResearchReadyReadService(
            research_access or QuantDataAccess()
        )
        self.ops_current = OpsCurrentReadService(ops_db_path)

    def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        # The local/dev MCP combines both planes. Coverage without a snapshot
        # is explicitly current; READY coverage remains available through the
        # research_ready Python interface and coverage_summary.
        if name in OPS_CURRENT_METHODS:
            return self.ops_current.call_tool(name, arguments)
        if name == "latest_ready_snapshot":
            return self.research_ready.latest_ready_snapshot()
        if name == "snapshot_quality":
            values = dict(arguments or {})
            return self.research_ready.snapshot_quality(values.get("snapshot_id"))
        return self.research_ready.call_tool(name, arguments)


__all__ = [
    "DEFAULT_OPS_DB",
    "OPS_CURRENT_METHODS",
    "RESEARCH_READY_METHODS",
    "OpsCurrentReadService",
    "QuantReadDomainService",
    "ResearchReadyReadService",
]
