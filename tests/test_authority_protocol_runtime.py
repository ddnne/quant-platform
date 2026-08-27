"""Retirement invariants for the caller-owned frozen-mirror v2 protocol."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from scripts import authority_protocol_runtime as runtime

NOW = datetime(2026, 8, 26, 0, 0, 30, tzinfo=UTC)


def _legacy_request(*, caller: str = "ops_projection") -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "d1-frozen-mirror-request/v2",
        "request_id": "00000000-0000-4000-8000-000000000001",
        "environment": "production",
        "authenticated_caller": caller,
        "target_authority": "d1_sync",
        "target_operation": "frozen_mirror:readonly_handoff",
        "purpose": "ops_projection",
        "issued_at": "2026-08-26T00:00:00Z",
        "expires_at": "2026-08-26T00:01:00Z",
    }
    document["request_digest"] = runtime._digest(document)
    return document


@pytest.fixture(autouse=True)
def _fixed_authority_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "_trusted_now", lambda: NOW)


def test_ops_or_coverage_cannot_request_a_self_selected_mirror_handoff() -> None:
    for caller in ("ops_projection", "coverage_transition"):
        document = _legacy_request(caller=caller)
        if caller == "coverage_transition":
            document["purpose"] = "coverage_transition"
            document["request_digest"] = runtime._digest(
                {
                    key: value
                    for key, value in document.items()
                    if key != "request_digest"
                }
            )
        with pytest.raises(
            runtime.AuthorityProtocolError, match="not authorized by exact method ACL"
        ):
            runtime.inspect_frozen_mirror_request_candidate(
                json.dumps(document, sort_keys=True, separators=(",", ":")),
                transport_authenticated_caller=caller,
                expected_environment="production",
            )


def test_retired_request_still_rejects_transport_caller_spoofing_first() -> None:
    document = _legacy_request()
    with pytest.raises(runtime.AuthorityProtocolError, match="transport-authenticated"):
        runtime.inspect_frozen_mirror_request_candidate(
            json.dumps(document, sort_keys=True, separators=(",", ":")),
            transport_authenticated_caller="coverage_transition",
            expected_environment="production",
        )


def test_retired_runtime_codec_rejects_floats_and_duplicate_keys() -> None:
    with pytest.raises(runtime.AuthorityProtocolError, match="float is forbidden"):
        runtime._strict_json('{"value":1.5}', field="retired request")
    with pytest.raises(runtime.AuthorityProtocolError, match="duplicate"):
        runtime._strict_json(
            '{"value":1,"value":2}', field="retired request"
        )
