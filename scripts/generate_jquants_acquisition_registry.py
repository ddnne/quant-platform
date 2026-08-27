#!/usr/bin/env python3
"""Generate the build-isolated J-Quants acquisition target registry."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DATASETS = ROOT / "packages/data_plane/data_contracts/canonical_datasets.json"
PREMIUM_CONTRACT = ROOT / "packages/data_plane/data_contracts/jquants_premium_core.json"
COLLECTION_COVERAGE = ROOT / "packages/data_plane/data_contracts/collection_coverage.json"
SOURCE_CAPABILITY_DIR = (
    ROOT / "packages/data_plane/data_contracts/source_capability_contracts"
)
JQUANTS_ACQUISITION_RPC_SCHEMA = (
    ROOT / "specs/authorities/jquants_acquisition_rpc.schema.json"
)
OUTPUT_JSON = (
    ROOT
    / "packages/data_plane/data_contracts/jquants_acquisition_target_registry.generated.json"
)
OUTPUT_TS = (
    ROOT
    / "platform/workers/ingestion-secrets/src/generated/jquants_acquisition_registry.ts"
)

_COVERAGE_REQUIRED = (
    "collection_scope", "history_target_start", "history_target_end_rule",
    "coverage_mode", "expected_frequency", "universe_rule",
    "raw_retention_required", "structured_reconciliation_required",
    "segment_granularity", "governance_tier",
)
_COVERAGE_OPTIONAL = (
    "policy_version", "history_mode", "required_domain_basis",
    "empty_success_policy", "not_historical_required_start",
    "earliest_official_availability", "official_mode",
    "vendor_data_provision_start", "vendor_history_policy",
    "vendor_data_provision_citation", "vendor_history_policy_citation",
)

_CLIENT_REVISION = "e38614ea3d66c4420597ff148c4848693692d6d9"
_CLIENT_ROOT = (
    "https://github.com/J-Quants/jquants-api-client-python/blob/"
    + _CLIENT_REVISION
)

# Query navigation is explicit. `cursor` on disclosure responses is a
# differential-feed marker and is never sent as historical pagination.
_ROUTES: dict[str, dict[str, Any]] = {
    "equities_bars_daily": {
        "mode": "calendar_month_sliced", "day_parameter": "date",
        "disposition": "TARGET_DATE_ROUTE_SELECTED",
        "evidence": [f"{_CLIENT_ROOT}/jquantsapi/apis/v2/equities.py",
                     f"{_CLIENT_ROOT}/jquantsapi/client_v2.py"],
        "pagination": True, "ignored_response_fields": [],
    },
    "equities_master": {
        "mode": "official_business_day_sliced", "day_parameter": "date",
        "disposition": "TARGET_OFFICIAL_CALENDAR_ROUTE_SELECTED",
        "evidence": [f"{_CLIENT_ROOT}/jquantsapi/apis/v2/equities.py",
                     f"{_CLIENT_ROOT}/jquantsapi/apis/v2/markets.py"],
        "pagination": True, "ignored_response_fields": [],
    },
    "fins_details": {
        "mode": "calendar_month_sliced", "day_parameter": "date",
        "disposition": "MATCHED",
        "evidence": [f"{_CLIENT_ROOT}/jquantsapi/apis/v2/fins.py"],
        "pagination": True, "ignored_response_fields": ["cursor"],
    },
    "fins_dividend": {
        "mode": "calendar_month_sliced", "day_parameter": "date",
        "disposition": "STALE_PREMIUM_PARAMS_OFFICIAL_DATE_OVERRIDE",
        "evidence": [f"{_CLIENT_ROOT}/jquantsapi/apis/v2/fins.py",
                     f"{_CLIENT_ROOT}/jquantsapi/client_v2.py"],
        "pagination": True, "ignored_response_fields": [],
    },
    "fins_earnings_date": {
        "mode": "calendar_month_sliced", "day_parameter": "date",
        "disposition": "STALE_PREMIUM_PARAMS_OFFICIAL_DATE_OVERRIDE",
        "evidence": [f"{_CLIENT_ROOT}/jquantsapi/apis/v2/fins.py",
                     f"{_CLIENT_ROOT}/jquantsapi/client_v2.py"],
        "pagination": True, "ignored_response_fields": [],
    },
    "fins_summary": {
        "mode": "calendar_month_sliced", "day_parameter": "date",
        "disposition": "MATCHED",
        "evidence": [f"{_CLIENT_ROOT}/jquantsapi/apis/v2/fins.py"],
        "pagination": True, "ignored_response_fields": ["cursor"],
    },
    "indices_bars_daily_topix": {
        "mode": "calendar_month_range", "day_parameter": None,
        "disposition": "MATCHED",
        "evidence": [f"{_CLIENT_ROOT}/jquantsapi/apis/v2/indices.py"],
        "pagination": True, "ignored_response_fields": [],
    },
    "markets_calendar": {
        "mode": "calendar_month_range", "day_parameter": None,
        "disposition": "MATCHED_WITH_OPTIONAL_FILTER_OMITTED",
        "evidence": [f"{_CLIENT_ROOT}/jquantsapi/apis/v2/markets.py"],
        "pagination": False, "ignored_response_fields": [],
    },
}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda item: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON value: {item}")
        ),
    )
    if type(value) is not dict:
        raise ValueError(f"contract must be an object: {path}")
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _rows_by_id(document: dict[str, Any], *, label: str) -> dict[str, dict[str, Any]]:
    rows = document.get("datasets")
    if type(rows) is not list:
        raise ValueError(f"{label}.datasets must be an array")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if type(row) is not dict or type(row.get("dataset_id")) is not str:
            raise ValueError(f"{label} contains an invalid dataset row")
        dataset_id = row["dataset_id"]
        if dataset_id in result:
            raise ValueError(f"{label} duplicate dataset: {dataset_id}")
        result[dataset_id] = row
    return result


def _query_resolution(dataset_id: str, capability: dict[str, Any]) -> dict[str, Any]:
    route = _ROUTES[dataset_id]
    supported = capability.get("supported_query_parameters")
    window = capability.get("collection_window")
    if type(supported) is not list or type(window) is not dict:
        raise ValueError(f"malformed SourceCapability query contract: {dataset_id}")
    if window.get("grain") != "calendar_month":
        raise ValueError(f"historical route is not calendar_month: {dataset_id}")
    if route["mode"] in {
        "calendar_month_sliced", "official_business_day_sliced"
    } and "date" not in supported:
        raise ValueError(f"daily route lacks date capability: {dataset_id}")
    if route["mode"] == "calendar_month_range" and not {"from", "to"} <= set(supported):
        raise ValueError(f"range route lacks bounds capability: {dataset_id}")
    if route["pagination"] and "pagination_key" not in supported:
        raise ValueError(f"route lacks explicit pagination capability: {dataset_id}")

    mismatches: list[dict[str, str]] = []
    if dataset_id == "markets_calendar":
        mismatches.append({
            "repository_parameter": "holidaydivision",
            "official_client_parameter": "hol_div",
            "disposition": "OMIT_OPTIONAL_FILTER",
            "evidence": f"{_CLIENT_ROOT}/jquantsapi/apis/v2/markets.py",
        })
    pagination = ([{"response_field": "pagination_key",
                    "query_parameter": "pagination_key"}]
                  if route["pagination"] else [])
    result = {
        "authority": "target-reviewed-route/v2",
        "coverage_segment_granularity": "calendar_month",
        "mode": route["mode"],
        "day_parameter": route["day_parameter"],
        "premium_parameter_disposition": route["disposition"],
        "pagination": pagination,
        "pagination_evidence": route["evidence"][0] if pagination else None,
        "allowed_ignored_response_fields": route["ignored_response_fields"],
        "official_client_evidence": route["evidence"],
        "omitted_optional_parameter_mismatches": mismatches,
    }
    if dataset_id == "equities_master":
        result["official_calendar_binding"] = {
            "authority": "target-and-receipt-independent-reproof/v1",
            "path": "/v2/markets/calendar",
            "ordered_parameters": ["from", "to"],
            "response_data_field": "data",
            "date_field": "Date",
            "holiday_division_field": "HolDiv",
            "tse_business_day_values": ["1", "2"],
            "complete_calendar_day_sequence_required": True,
            "cross_segment_resolution": "FORBIDDEN",
        }
    return result


def _closed_rpc_surface(schema: dict[str, Any]) -> dict[str, list[str]]:
    """Freeze the reviewed wire inventories into the package-owned registry.

    The receipt runtime is distributed without the repository-level ``specs``
    tree.  These inventories are therefore generated from the reviewed schema,
    covered by both the schema digest and the registry self-digest, and shipped
    beside the Python package and Worker target.
    """
    definitions = schema.get("$defs")
    if type(definitions) is not dict:
        raise ValueError("J-Quants acquisition RPC schema definitions are missing")
    result: dict[str, list[str]] = {}
    for definition_name, output_name, expected_count in (
        ("request", "request_fields", 14),
        ("response_metadata", "response_metadata_fields", 34),
        ("response_headers", "response_header_fields", 37),
    ):
        definition = definitions.get(definition_name)
        if type(definition) is not dict:
            raise ValueError(
                f"J-Quants acquisition RPC schema lacks {definition_name}"
            )
        required = definition.get("required")
        properties = definition.get("properties")
        if (
            type(required) is not list
            or not all(type(item) is str for item in required)
            or len(required) != len(set(required))
            or type(properties) is not dict
            or set(required) != set(properties)
            or definition.get("additionalProperties") is not False
            or len(required) != expected_count
        ):
            raise ValueError(
                f"J-Quants acquisition RPC {definition_name} is not the closed reviewed surface"
            )
        result[output_name] = list(required)
    return result


def build_registry() -> dict[str, Any]:
    canonical = _rows_by_id(_load(CANONICAL_DATASETS), label="canonical registry")
    premium = _rows_by_id(_load(PREMIUM_CONTRACT), label="Premium contract")
    coverage_document = _load(COLLECTION_COVERAGE)
    defaults = coverage_document.get("defaults")
    coverage_rows = coverage_document.get("datasets")
    root_version = coverage_document.get("policy_version")
    if type(defaults) is not dict or type(coverage_rows) is not dict or type(root_version) is not str:
        raise ValueError("collection Coverage contract is malformed")
    capabilities: dict[str, dict[str, Any]] = {}
    for path in sorted(SOURCE_CAPABILITY_DIR.glob("*.json")):
        row = _load(path)
        dataset_id = row.get("dataset_id")
        if type(dataset_id) is not str or dataset_id in capabilities:
            raise ValueError(f"invalid/duplicate SourceCapability: {path}")
        capabilities[dataset_id] = row

    rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    for dataset_id in sorted(set(canonical) & set(premium) & set(capabilities)):
        meta, contract, capability = canonical[dataset_id], premium[dataset_id], capabilities[dataset_id]
        if (meta.get("enabled") is not True or
                meta.get("governance_tier") != "governed" or
                meta.get("source") != "jquants_premium_core" or
                capability.get("source") != "jquants_premium_core" or
                capability.get("policy_version") != "source-capability/v3"):
            continue
        if contract.get("path") != capability.get("upstream_locator"):
            raise ValueError(f"locator drift: {dataset_id}")
        if (meta.get("contracts") or {}).get("primary") != "jquants_premium_core":
            raise ValueError(f"primary contract drift: {dataset_id}")
        if capability.get("tip_only_operational") is True:
            exclusions.append({
                "dataset_id": dataset_id, "status": "PENDING",
                "reason": "tip snapshot requires target-owned verified JPX business-calendar and cutoff capability; weekday approximation forbidden",
            })
            continue
        if dataset_id == "equities_master":
            exclusions.append({
                "dataset_id": dataset_id,
                "status": "PENDING",
                "reason": (
                    "official-calendar-bound target route is implemented but "
                    "activation awaits a governed Receipt acquisition capability "
                    "that independently persists opaque calendar reproof bytes"
                ),
            })
        if dataset_id not in _ROUTES:
            continue

        override = coverage_rows.get(dataset_id)
        if type(override) is not dict:
            raise ValueError(f"Coverage policy missing: {dataset_id}")
        effective = {**defaults, "policy_version": root_version, **override}
        coverage = {"dataset_id": dataset_id}
        for name in _COVERAGE_REQUIRED:
            if name not in effective:
                raise ValueError(f"Coverage policy {dataset_id} missing {name}")
            coverage[name] = effective[name]
        for name in _COVERAGE_OPTIONAL:
            coverage[name] = effective.get(name)
        rows.append({
            "canonical_dataset": meta,
            "coverage_policy": coverage,
            "premium_contract": contract,
            "query_resolution": _query_resolution(dataset_id, capability),
            "source_capability": capability,
        })

    if sorted(row["canonical_dataset"]["dataset_id"] for row in rows) != sorted(_ROUTES):
        raise ValueError("reviewed route inventory is incomplete")
    expected_exclusions = {
        "equities_bars_daily_am", "equities_earnings_calendar", "equities_master"
    }
    actual_exclusions = [row["dataset_id"] for row in exclusions]
    if len(actual_exclusions) != len(set(actual_exclusions)) or set(actual_exclusions) != expected_exclusions:
        raise ValueError("reviewed PENDING exclusion inventory is incomplete")
    rpc_schema = _load(JQUANTS_ACQUISITION_RPC_SCHEMA)
    body: dict[str, Any] = {
        "schema_version": "jquants-acquisition-target-registry/v2",
        "official_origin": "https://api.jquants.com",
        "maximum_redirects": 0,
        "maximum_page_bytes": 16 * 1024 * 1024,
        "maximum_segment_pages": 8192,
        "maximum_provider_pages_per_slice": 256,
        "continuation_ttl_seconds": 21600,
        "canonicalization": "RFC8259_UTF8_SORTED_KEYS_NO_WHITESPACE",
        "sources": {
            "canonical_dataset_registry": str(CANONICAL_DATASETS.relative_to(ROOT)),
            "premium_contract": str(PREMIUM_CONTRACT.relative_to(ROOT)),
            "collection_coverage": str(COLLECTION_COVERAGE.relative_to(ROOT)),
            "source_capability_directory": str(SOURCE_CAPABILITY_DIR.relative_to(ROOT)),
            "jquants_acquisition_rpc_schema": str(
                JQUANTS_ACQUISITION_RPC_SCHEMA.relative_to(ROOT)
            ),
            "jquants_acquisition_rpc_schema_digest": _digest(
                rpc_schema
            ),
            "official_client_revision": _CLIENT_REVISION,
        },
        "rpc_surface": _closed_rpc_surface(rpc_schema),
        "datasets": rows,
        "excluded_datasets": exclusions,
    }
    return {**body, "registry_digest": _digest(body)}


def _render_json(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _render_typescript() -> str:
    return (
        "// Generated by scripts/generate_jquants_acquisition_registry.py.\n"
        "// Do not edit by hand.\n"
        "import registry from \"../../../../../packages/data_plane/data_contracts/"
        "jquants_acquisition_target_registry.generated.json\";\n"
        "export default registry;\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    registry = build_registry()
    rendered_json = _render_json(registry)
    rendered_typescript = _render_typescript()
    if args.write:
        for output, rendered in (
            (OUTPUT_JSON, rendered_json),
            (OUTPUT_TS, rendered_typescript),
        ):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered, encoding="utf-8")
            print(output.relative_to(ROOT))
        return 0
    for output, rendered in (
        (OUTPUT_JSON, rendered_json),
        (OUTPUT_TS, rendered_typescript),
    ):
        if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            print(
                "J-Quants acquisition registry drift; review and run "
                "scripts/generate_jquants_acquisition_registry.py --write"
            )
            return 1
    print("J-Quants acquisition registry: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
