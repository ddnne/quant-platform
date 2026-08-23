"""Dependency-free MCP façade for :mod:`data_access`.

The core registry is importable and testable without an MCP SDK. The stdio
entry point implements the small JSON-RPC surface needed by MCP clients:
``initialize``, ``tools/list``, and ``tools/call``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from data_access import QuantDataAccess, QuantDataConfig, QuantReadDomainService


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def _object(
    properties: Mapping[str, Any] | None = None,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties or {}),
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


_STRING = {"type": "string"}
_SNAPSHOT = {"snapshot_id": _STRING}
_PAGING = {
    "page_size": {"type": "integer", "minimum": 1, "maximum": 1000},
    "page_token": _STRING,
}

RESEARCH_TOOLS: tuple[Tool, ...] = (
    Tool("list_datasets", "List allowlisted canonical datasets.", _object()),
    Tool("describe_dataset", "Describe one canonical dataset and collection policy.", _object({"dataset": _STRING}, ("dataset",))),
    Tool("coverage_summary", "Summarize the persistent coverage ledger for a READY snapshot.", _object(_SNAPSHOT)),
    Tool("dataset_coverage", "Read one dataset's coverage-ledger row.", _object({"dataset": _STRING, **_SNAPSHOT}, ("dataset",))),
    Tool("coverage_gaps", "List incomplete, stale, unknown, or failed coverage rows.", _object(_SNAPSHOT)),
    Tool("latest_ready_snapshot", "Describe the latest verified READY snapshot.", _object()),
    Tool("describe_snapshot", "Describe a verified READY snapshot by content id.", _object({"snapshot_id": _STRING}, ("snapshot_id",))),
    Tool("diff_snapshots", "Diff watermarks and change sequence between READY snapshots.", _object({"from_snapshot_id": _STRING, "to_snapshot_id": _STRING}, ("from_snapshot_id", "to_snapshot_id"))),
    Tool("quality_summary", "Read snapshot publication-gate quality summary.", _object(_SNAPSHOT)),
    Tool("quality_failures", "Read publication-gate failures for a READY snapshot.", _object(_SNAPSHOT)),
    Tool(
        "query_dataset",
        "PIT query with mandatory as_of, READY-only source, bounded dates and pagination.",
        _object({
            "dataset": _STRING,
            "as_of": _STRING,
            "snapshot_id": _STRING,
            "code": _STRING,
            "start": {"type": "string", "format": "date"},
            "end": {"type": "string", "format": "date"},
            **_PAGING,
        }, ("dataset", "as_of")),
    ),
    Tool(
        "get_series",
        "Return one field as a PIT time series from an allowlisted dataset.",
        _object({
            "dataset": _STRING,
            "as_of": _STRING,
            "code": _STRING,
            "value_field": _STRING,
            "snapshot_id": _STRING,
            "start": {"type": "string", "format": "date"},
            "end": {"type": "string", "format": "date"},
            **_PAGING,
        }, ("dataset", "as_of", "code", "value_field")),
    ),
    Tool(
        "compute_feature",
        "Compute an approved, exactly versioned feature on a READY snapshot.",
        _object({
            "feature_id": _STRING,
            "version": _STRING,
            "as_of": _STRING,
            "params": {"type": "object"},
            "snapshot_id": _STRING,
        }, ("feature_id", "version", "as_of", "params")),
    ),
    Tool(
        "compute_features",
        "Compute up to 50 approved, exactly versioned feature calls.",
        _object({
            "features": {
                "type": "array",
                "minItems": 1,
                "maxItems": 50,
                "items": _object({"id": _STRING, "version": _STRING, "params": {"type": "object"}}, ("id", "version")),
            },
            "as_of": _STRING,
            "snapshot_id": _STRING,
        }, ("features", "as_of")),
    ),
    Tool("raw_manifest", "Return only the governed raw manifest for one dataset; no R2 browse.", _object({"dataset": _STRING, **_SNAPSHOT}, ("dataset",))),
    Tool(
        "trace_provenance",
        "Trace one natural key to PIT timestamps, snapshot, and governed raw manifest.",
        _object({"dataset": _STRING, "natural_key": _STRING, "as_of": _STRING, "snapshot_id": _STRING}, ("dataset", "natural_key", "as_of")),
    ),
)

OPS_TOOLS: tuple[Tool, ...] = (
    Tool("ops_status", "Read mutable current ingestion control-plane status.", _object()),
    Tool("ingestion_last_run", "Read the latest current ingestion run.", _object()),
    Tool(
        "dataset_coverage",
        "Read one dataset's current Coverage projection (policy_version as stored on the generation).",
        _object({"dataset": _STRING}, ("dataset",)),
    ),
    Tool(
        "coverage_gaps",
        "List current governed datasets whose Coverage projection (policy_version as stored on the generation) is not COMPLETE.",
        _object(),
    ),
    Tool(
        "coverage_segments",
        "Read bounded current Coverage projection (policy_version as stored on the generation) segment evidence.",
        _object({
            "dataset": _STRING,
            "status": {
                "type": "string",
                "enum": ["COMPLETE", "PARTIAL", "FAILED", "UNKNOWN", "STALE"],
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        }),
    ),
    Tool(
        "backfill_status",
        "Count current required, complete, and remaining segments.",
        _object({"dataset": _STRING}),
    ),
    Tool("validation_summary", "Read the latest current validation verdicts.", _object()),
    Tool("b0_status", "Read the current recorded B0 gate verdict.", _object()),
    Tool(
        "latest_ready_snapshot",
        "Describe the latest immutable published READY generation.",
        _object(),
    ),
    Tool(
        "snapshot_quality",
        "Read quality evidence attached to an immutable READY generation.",
        _object(_SNAPSHOT),
    ),
    Tool(
        "raw_retention_status",
        "Read current raw-retention attestations linked to ingestion runs.",
        _object({"dataset": _STRING}),
    ),
    Tool("sync_status", "Read current sync watermarks and change sequence.", _object()),
    Tool(
        "storage_plane_status",
        "D1 light-path / hot-window / surplus-stage proof for CF-native P0. Counts only.",
        _object(),
    ),
)

_OPS_BY_NAME = {tool.name: tool for tool in OPS_TOOLS}
TOOLS: tuple[Tool, ...] = tuple(
    _OPS_BY_NAME.get(tool.name, tool) for tool in RESEARCH_TOOLS
) + tuple(tool for tool in OPS_TOOLS if tool.name not in {
    candidate.name for candidate in RESEARCH_TOOLS
})


class QuantDataMCPServer:
    def __init__(
        self,
        access: QuantDataAccess | None = None,
        *,
        service: QuantReadDomainService | None = None,
        ops_db_path: str | Path = "data/structured/ingestion.sqlite",
    ) -> None:
        if access is not None and service is not None:
            raise ValueError("pass access or service, not both")
        self.service = service or QuantReadDomainService(
            access, ops_db_path=ops_db_path
        )
        self._tools = {tool.name: tool for tool in TOOLS}

    def list_tools(self) -> list[dict[str, Any]]:
        return [tool.to_dict() for tool in TOOLS]

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> Any:
        if name not in self._tools:
            raise KeyError(f"unknown Quant Data Access tool: {name!r}")
        return self.service.call_tool(name, arguments)


def create_server(
    *,
    snapshot_dir: str | Path = "data/research_snapshots",
    ops_db_path: str | Path = "data/structured/ingestion.sqlite",
) -> QuantDataMCPServer:
    return QuantDataMCPServer(
        QuantDataAccess(QuantDataConfig(snapshot_dir=Path(snapshot_dir))),
        ops_db_path=ops_db_path,
    )


def _response(request_id: Any, result: Any = None, error: Exception | None = None) -> dict[str, Any]:
    if error is not None:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": str(error)},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _serve_stdio(server: QuantDataMCPServer) -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        request: dict[str, Any] = {}
        try:
            request = json.loads(line)
            method = request.get("method")
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "quant-data-access", "version": "0.1.0"},
                }
            elif method == "tools/list":
                result = {"tools": server.list_tools()}
            elif method == "tools/call":
                params = request.get("params") or {}
                value = server.call_tool(params["name"], params.get("arguments"))
                result = {
                    "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, sort_keys=True)}],
                    "isError": False,
                }
            elif method == "notifications/initialized":
                continue
            else:
                raise KeyError(f"unsupported method: {method!r}")
            print(json.dumps(_response(request.get("id"), result), separators=(",", ":")), flush=True)
        except Exception as exc:
            print(json.dumps(_response(request.get("id"), error=exc), separators=(",", ":")), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Quant Data Access MCP")
    parser.add_argument("--snapshot-dir", default="data/research_snapshots")
    parser.add_argument("--ops-db", default="data/structured/ingestion.sqlite")
    parser.add_argument("--list-tools", action="store_true")
    args = parser.parse_args(argv)
    server = create_server(snapshot_dir=args.snapshot_dir, ops_db_path=args.ops_db)
    if args.list_tools:
        print(json.dumps({"tools": server.list_tools()}, sort_keys=True))
        return 0
    return _serve_stdio(server)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "OPS_TOOLS",
    "RESEARCH_TOOLS",
    "TOOLS",
    "QuantDataMCPServer",
    "create_server",
    "main",
]
