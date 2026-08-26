"""Tests-only live JQUANTS_ACQUISITION capture fixtures.

Production intentionally has no equivalent capture constructor until the
separate Receipt Worker and Service Binding are provisioned.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ingestion.jquants import acquisition_collection as acquisition
from storage.coverage_ledger import RequiredCoverageSegment
from storage.receipt_crypto import canonical_evidence_digest


def _digest(value: Any) -> str:
    return canonical_evidence_digest(value)


def _token(index: int) -> str:
    payload = json.dumps(
        {"page": index}, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = base64.urlsafe_b64encode(bytes([index % 251]) * 32).decode(
        "ascii"
    ).rstrip("=")
    return f"jqa2.{encoded}.{signature}"


def _metadata_headers(metadata: Mapping[str, Any]) -> dict[str, str]:
    def value(item: Any) -> str:
        return "NONE" if item is None else str(item)

    headers = {
        "cache-control": "no-store",
        "content-type": str(metadata["content_type"]),
        "x-content-type-options": "nosniff",
        "x-quant-acquisition-acquisition-expires-at": value(
            metadata["acquisition_expires_at"]
        ),
        "x-quant-acquisition-acquisition-id": value(metadata["acquisition_id"]),
        "x-quant-acquisition-acquisition-issued-at": value(
            metadata["acquisition_issued_at"]
        ),
        "x-quant-acquisition-body-digest": str(metadata["body_digest"]),
        "x-quant-acquisition-body-kind": str(metadata["body_kind"]),
        "x-quant-acquisition-chain-digest": value(metadata["chain_digest"]),
        "x-quant-acquisition-continuation": value(metadata["continuation_token"]),
        "x-quant-acquisition-coverage-policy-digest": value(
            metadata["coverage_policy_digest"]
        ),
        "x-quant-acquisition-cursor-key-id": value(metadata["cursor_key_id"]),
        "x-quant-acquisition-dataset": value(metadata["dataset_id"]),
        "x-quant-acquisition-dataset-contract-digest": value(
            metadata["dataset_contract_digest"]
        ),
        "x-quant-acquisition-environment": value(metadata["environment"]),
        "x-quant-acquisition-evidence-state": str(metadata["evidence_state"]),
        "x-quant-acquisition-metadata-digest": _digest(dict(metadata)),
        "x-quant-acquisition-page-ordinal": value(metadata["page_ordinal"]),
        "x-quant-acquisition-pagination-state": str(metadata["pagination_state"]),
        "x-quant-acquisition-previous-chain-digest": value(
            metadata["previous_chain_digest"]
        ),
        "x-quant-acquisition-previous-request-digest": value(
            metadata["previous_request_digest"]
        ),
        "x-quant-acquisition-provider-page-ordinal": value(
            metadata["provider_page_ordinal"]
        ),
        "x-quant-acquisition-provider-pagination-state": str(
            metadata["provider_pagination_state"]
        ),
        "x-quant-acquisition-query-contract-digest": value(
            metadata["query_contract_digest"]
        ),
        "x-quant-acquisition-query-digest": value(metadata["query_digest"]),
        "x-quant-acquisition-redirect-count": str(metadata["redirect_count"]),
        "x-quant-acquisition-registry-digest": value(
            metadata["target_registry_digest"]
        ),
        "x-quant-acquisition-request-digest": value(metadata["request_digest"]),
        "x-quant-acquisition-request-identity-digest": value(
            metadata["request_identity_digest"]
        ),
        "x-quant-acquisition-schema": "jquants-acquisition-rpc-response/v2",
        "x-quant-acquisition-segment": value(metadata["segment_id"]),
        "x-quant-acquisition-segment-end": value(metadata["segment_end"]),
        "x-quant-acquisition-segment-start": value(metadata["segment_start"]),
        "x-quant-acquisition-slice-date": value(metadata["slice_date"]),
        "x-quant-acquisition-slice-ordinal": value(metadata["slice_ordinal"]),
        "x-quant-acquisition-source-capability-digest": value(
            metadata["source_capability_digest"]
        ),
        "x-quant-acquisition-upstream-status": value(
            metadata["upstream_http_status"]
        ),
    }
    assert set(headers) == set(acquisition._rpc_surface().header_names)
    return headers


@dataclass(frozen=True)
class TestLiveAcquisition:
    capture: Any
    manifest_path: Path
    raw_paths: tuple[Path, ...]
    document: Mapping[str, Any]


TestLiveAcquisition.__test__ = False


def build_live_acquisition(
    *,
    tmp_path: Path,
    service: Any,
    required: RequiredCoverageSegment,
    raw_pages: Sequence[bytes] | None = None,
    page_slices: Sequence[str | None] | None = None,
    provider_states: Sequence[str] | None = None,
    issued_at: str = "2026-08-11T00:00:00.000Z",
    expires_at: str = "2026-08-11T06:00:00.000Z",
    mutate_document: Callable[[dict[str, Any]], None] | None = None,
) -> TestLiveAcquisition:
    """Persist target-shaped pages and mint a tests-only live capability."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    registry = acquisition._target_registry()
    route = registry.routes[required.dataset]
    request = {
        "schema_version": "jquants-acquisition-rpc-request/v2",
        "environment": "production",
        "operation": "fetch_governed_page",
        "dataset_id": required.dataset,
        "segment_id": required.segment_id,
        "segment_start": required.segment_start,
        "segment_end": required.segment_end,
        "acquisition_nonce": "1" * 64,
        "source_capability_digest": route.source_capability_digest,
        "dataset_contract_digest": route.dataset_contract_digest,
        "coverage_policy_digest": route.coverage_policy_digest,
        "query_contract_digest": route.query_contract_digest,
        "target_registry_digest": registry.digest,
        "continuation_token": None,
    }
    identity = {key: value for key, value in request.items() if key != "continuation_token"}
    request_identity_digest = _digest(identity)
    acquisition_id = "hmac-sha256:" + "2" * 64
    cursor_key_id = "hmac-sha256:" + "3" * 64
    previous_chain = _digest(
        {
            "schema_version": "jquants-acquisition-chain-genesis/v2",
            "acquisition_id": acquisition_id,
            "request_identity_digest": request_identity_digest,
            "cursor_key_id": cursor_key_id,
            "acquisition_issued_at": issued_at,
            "acquisition_expires_at": expires_at,
        }
    )
    start = date.fromisoformat(required.segment_start)
    end = date.fromisoformat(required.segment_end)
    bodies = list(raw_pages or ())
    if page_slices is not None:
        page_dates = [
            None if item is None else date.fromisoformat(item)
            for item in page_slices
        ]
    elif route.mode == "calendar_month_sliced":
        page_dates: list[date | None] = []
        cursor = start
        while cursor <= end:
            page_dates.append(cursor)
            cursor += timedelta(days=1)
    else:
        page_dates = [None] * max(1, len(bodies))
    if not bodies:
        bodies = [b'{"data":[]}'] * len(page_dates)
    if len(bodies) != len(page_dates):
        raise ValueError("raw_pages must enumerate the exact target slice sequence")
    if provider_states is not None and len(provider_states) != len(page_dates):
        raise ValueError("provider_states must enumerate every fixture page")

    pages: list[dict[str, Any]] = []
    prior_request_digest: str | None = None
    current_request = dict(request)
    raw_paths: list[Path] = []
    prior_provider_cursor: str | None = None
    prior_slice_day: date | None = None
    prior_provider_ordinal = -1
    for index, (slice_day, raw) in enumerate(zip(page_dates, bodies, strict=True)):
        request_digest = _digest(current_request)
        terminal = index == len(page_dates) - 1
        provider_state = (
            provider_states[index]
            if provider_states is not None
            else (
                "EXHAUSTED"
                if terminal or route.mode == "calendar_month_sliced"
                else "CONTINUATION"
            )
        )
        if provider_state not in {"CONTINUATION", "EXHAUSTED"}:
            raise ValueError("provider state fixture is invalid")
        provider_page_ordinal = (
            index
            if route.mode == "calendar_month_range"
            else (
                prior_provider_ordinal + 1
                if slice_day == prior_slice_day and index > 0
                else 0
            )
        )
        ordered_query = (
            [["from", required.segment_start], ["to", required.segment_end]]
            if route.mode == "calendar_month_range"
            else [["date", slice_day.isoformat() if slice_day is not None else None]]
        )
        if provider_page_ordinal > 0:
            if prior_provider_cursor is None:
                raise ValueError("range continuation fixture requires a prior cursor")
            ordered_query.append(["pagination_key", prior_provider_cursor])
        segment_state = "EXHAUSTED" if terminal else "CONTINUATION"
        continuation = None if terminal else _token(index + 1)
        body_digest = _digest(raw)
        metadata = {
            "schema_version": "jquants-acquisition-rpc-response-metadata/v2",
            "evidence_state": "RAW_PAGE",
            "environment": "production",
            "dataset_id": required.dataset,
            "segment_id": required.segment_id,
            "segment_start": required.segment_start,
            "segment_end": required.segment_end,
            "request_digest": request_digest,
            "request_identity_digest": request_identity_digest,
            "previous_request_digest": prior_request_digest,
            "acquisition_id": acquisition_id,
            "acquisition_issued_at": issued_at,
            "acquisition_expires_at": expires_at,
            "target_registry_digest": registry.digest,
            "source_capability_digest": route.source_capability_digest,
            "dataset_contract_digest": route.dataset_contract_digest,
            "coverage_policy_digest": route.coverage_policy_digest,
            "query_contract_digest": route.query_contract_digest,
            "cursor_key_id": cursor_key_id,
            "slice_date": None if slice_day is None else slice_day.isoformat(),
            "query_digest": _digest(
                {
                    "schema_version": "jquants-acquisition-query/v2",
                    "path": route.path,
                    "ordered_query": ordered_query,
                }
            ),
            "page_ordinal": index,
            "slice_ordinal": 0 if slice_day is None else (slice_day - start).days,
            "provider_page_ordinal": provider_page_ordinal,
            "provider_pagination_state": provider_state,
            "upstream_http_status": 200,
            "body_digest": body_digest,
            "body_kind": "UPSTREAM_EXACT_BYTES",
            "pagination_state": segment_state,
            "continuation_token": continuation,
            "content_type": "application/json",
            "redirect_count": 0,
            "previous_chain_digest": previous_chain,
            "chain_digest": None,
        }
        link = {
            "schema_version": "jquants-acquisition-chain-link/v2",
            "acquisition_id": acquisition_id,
            "cursor_key_id": cursor_key_id,
            "acquisition_issued_at": issued_at,
            "acquisition_expires_at": expires_at,
            "request_digest": request_digest,
            "request_identity_digest": request_identity_digest,
            "previous_request_digest": prior_request_digest,
            "previous_chain_digest": previous_chain,
            "page_ordinal": index,
            "slice_date": metadata["slice_date"],
            "slice_ordinal": metadata["slice_ordinal"],
            "provider_page_ordinal": metadata["provider_page_ordinal"],
            "query_digest": metadata["query_digest"],
            "body_digest": body_digest,
            "upstream_http_status": 200,
            "evidence_state": "RAW_PAGE",
            "provider_pagination_state": provider_state,
            "pagination_state": segment_state,
        }
        metadata["chain_digest"] = _digest(link)
        raw_path = (tmp_path / f"page-{index:04d}.json").resolve()
        raw_path.write_bytes(raw)
        raw_path.chmod(0o444)
        raw_paths.append(raw_path)
        pages.append(
            {
                "raw_path": str(raw_path),
                "raw_size": len(raw),
                "raw_digest": body_digest,
                "response_status": 200,
                "headers": _metadata_headers(metadata),
                "metadata": metadata,
            }
        )
        previous_chain = str(metadata["chain_digest"])
        prior_request_digest = request_digest
        current_request = dict(request)
        current_request["continuation_token"] = continuation
        if provider_state == "CONTINUATION":
            try:
                next_cursor = json.loads(raw)["pagination_key"]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    "continuing range fixture requires raw pagination_key"
                ) from exc
            if not isinstance(next_cursor, str) or not next_cursor:
                raise ValueError(
                    "continuing range fixture requires non-empty pagination_key"
                )
            prior_provider_cursor = next_cursor
        else:
            prior_provider_cursor = None
        prior_slice_day = slice_day
        prior_provider_ordinal = provider_page_ordinal

    document: dict[str, Any] = {
        "schema_version": "jquants-acquisition-collection/v2",
        "capture_mode": "LIVE_SERVICE_BINDING_RESPONSE",
        "initial_request": request,
        "pages": pages,
    }
    if mutate_document is not None:
        mutate_document(document)
    document["collection_digest"] = _digest(document)
    manifest_path = (tmp_path / "acquisition-collection.json").resolve()
    manifest_path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    manifest_path.chmod(0o444)
    capture = acquisition._LiveJQuantsAcquisitionCapture(
        _seal=acquisition._LIVE_CAPTURE_SEAL
    )
    with acquisition._CAPABILITY_LOCK:
        acquisition._LIVE_CAPTURES[capture] = {
            "authority_id": service._authority_id,
            "manifest_path": manifest_path,
            "manifest_size": manifest_path.stat().st_size,
            "manifest_digest": _digest(manifest_path.read_bytes()),
            "consumed": False,
        }
    return TestLiveAcquisition(
        capture=capture,
        manifest_path=manifest_path,
        raw_paths=tuple(raw_paths),
        document=document,
    )


def verify_live_acquisition(
    fixture: TestLiveAcquisition,
    *,
    service: Any,
    required: RequiredCoverageSegment,
) -> Any:
    return service.verify_live_jquants_collection(
        capture=fixture.capture,
        required=required,
    )


__all__ = ["TestLiveAcquisition", "build_live_acquisition", "verify_live_acquisition"]
