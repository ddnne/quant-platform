"""Content-addressed, unsigned Ops Projection authority candidates.

This module deliberately contains no signing or publication capability.  A
candidate is the immutable output of rendering one authenticated SQLite read
snapshot.  C4 remains PENDING until a separately provisioned authority can
verify, sign, append, and activate one of these documents.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from types import MappingProxyType
from typing import Any, Mapping


UNSIGNED_CANDIDATE_SCHEMA = "ops-projection-unsigned-candidate/v1"
UNSIGNED_CANDIDATE_IDENTITY_SCHEMA = (
    "ops-projection-unsigned-candidate-identity/v1"
)


class OpsProjectionCandidateError(RuntimeError):
    """The renderer did not produce one exact, content-addressed candidate."""


def _copy_exact_json(value: Any, *, field: str) -> Any:
    if type(value) is dict:
        copied: dict[str, Any] = {}
        for key, item in dict.items(value):
            if type(key) is not str or key in copied:
                raise OpsProjectionCandidateError(
                    f"{field} keys must be unique exact strings"
                )
            copied[key] = _copy_exact_json(item, field=f"{field}.{key}")
        return copied
    if type(value) is list:
        return [
            _copy_exact_json(item, field=f"{field}[{index}]")
            for index, item in enumerate(value)
        ]
    if type(value) in {str, int, bool, type(None)}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise OpsProjectionCandidateError(
        f"{field} must contain only exact finite JSON built-in values"
    )


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    copied = _copy_exact_json(value, field="Ops Projection candidate")
    assert type(copied) is dict
    return json.dumps(
        copied,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _deep_immutable(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType(
            {key: _deep_immutable(item) for key, item in value.items()}
        )
    if type(value) is list:
        return tuple(_deep_immutable(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class UnsignedOpsProjectionCandidate:
    """One immutable candidate plus its independently addressable identity."""

    candidate_bytes: bytes
    candidate_digest: str
    identity_bytes: bytes
    identity_digest: str
    identity: Mapping[str, Any]

    def __post_init__(self) -> None:
        if _sha256_bytes(self.candidate_bytes) != self.candidate_digest:
            raise OpsProjectionCandidateError("candidate digest mismatch")
        if _sha256_bytes(self.identity_bytes) != self.identity_digest:
            raise OpsProjectionCandidateError("candidate identity digest mismatch")


def _freeze_unsigned_projection_candidate(
    document: dict[str, Any],
    identity_fields: dict[str, Any],
) -> UnsignedOpsProjectionCandidate:
    """Freeze the canonical renderer's already-derived private documents.

    This private serializer is not an authority entrypoint.  In particular it
    has no API for a caller envelope, count, digest, cursor, signer, or path.
    """

    if type(document) is not dict or set(document) != {
        "schema_version",
        "authority_status",
        "sync_identity",
        "sync_identity_digest",
        "projection",
    }:
        raise OpsProjectionCandidateError("candidate document fields are not closed")
    if (
        document.get("schema_version") != UNSIGNED_CANDIDATE_SCHEMA
        or document.get("authority_status") != "PENDING"
    ):
        raise OpsProjectionCandidateError("candidate authority status is invalid")
    expected_identity_fields = {
        "sync_identity_digest",
        "generation_id",
        "source_db_digest",
        "content_digest",
        "producer_commit_sha",
        "contract_digest",
        "registry_digest",
        "source_cursor",
        "export_cursor",
        "applied_cursor",
    }
    if type(identity_fields) is not dict or set(identity_fields) != expected_identity_fields:
        raise OpsProjectionCandidateError("candidate identity fields are not derived")
    sync_identity = document.get("sync_identity")
    if type(sync_identity) is not dict:
        raise OpsProjectionCandidateError("candidate sync identity is invalid")
    sync_identity_digest = _sha256_bytes(_canonical_json_bytes(sync_identity))
    if (
        document.get("sync_identity_digest") != sync_identity_digest
        or identity_fields.get("sync_identity_digest") != sync_identity_digest
    ):
        raise OpsProjectionCandidateError("candidate sync identity digest mismatch")
    projection = document.get("projection")
    expected_projection_fields = {
        "sql",
        "generation_id",
        "source_db_digest",
        "content_digest",
        "producer_commit_sha",
        "contract_digest",
        "registry_digest",
        "source_cursor",
        "export_cursor",
        "applied_cursor",
        "metadata",
        "envelope",
        "row_counts",
        "complete_coverage_segments",
        "activation_included",
    }
    if type(projection) is not dict or set(projection) != expected_projection_fields:
        raise OpsProjectionCandidateError("candidate projection fields are not closed")
    for field in expected_identity_fields - {"sync_identity_digest"}:
        if projection.get(field) != identity_fields.get(field):
            raise OpsProjectionCandidateError(
                f"candidate projection identity mismatch: {field}"
            )
    candidate_bytes = _canonical_json_bytes(document)
    candidate_digest = _sha256_bytes(candidate_bytes)
    identity_document = {
        "schema_version": UNSIGNED_CANDIDATE_IDENTITY_SCHEMA,
        "candidate_digest": candidate_digest,
        **identity_fields,
    }
    identity_bytes = _canonical_json_bytes(identity_document)
    immutable_identity = _deep_immutable(identity_document)
    assert isinstance(immutable_identity, Mapping)
    return UnsignedOpsProjectionCandidate(
        candidate_bytes=candidate_bytes,
        candidate_digest=candidate_digest,
        identity_bytes=identity_bytes,
        identity_digest=_sha256_bytes(identity_bytes),
        identity=immutable_identity,
    )


__all__ = [
    "OpsProjectionCandidateError",
    "UNSIGNED_CANDIDATE_IDENTITY_SCHEMA",
    "UNSIGNED_CANDIDATE_SCHEMA",
    "UnsignedOpsProjectionCandidate",
]
