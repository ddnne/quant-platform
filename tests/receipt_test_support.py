"""Test-only signed receipt fixture builder.

Production deliberately exposes neither an evidence constructor nor a signing
authority.  Tests which exercise downstream receipt verification still need a
way to construct adversarial envelopes, so that power lives under ``tests``
and requires an explicitly injected ephemeral test key.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from weakref import WeakSet

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from data_contracts import coverage_contract_for
from storage.coverage_ledger import CollectionReceipt, RequiredCoverageSegment
from storage.receipt_crypto import (
    ReceiptSigningKey,
    build_signed_digest_fields,
    canonical_evidence_digest,
    partition_extra_digests,
)


_TEST_EVIDENCE_SEAL = object()
_TEST_EVIDENCE: WeakSet[Any] = WeakSet()


def generate_test_receipt_keypair(
    *, key_id: str = "test-receipt-v1"
) -> tuple[bytes, bytes, str]:
    """Create ephemeral key material strictly inside the test tree."""
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_pem, public_raw, key_id


def write_test_receipt_registry(
    path: Path, *, key_id: str, public_raw: bytes
) -> Path:
    """Write one ephemeral verifier registry for adversarial tests."""
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "purpose": "receipt_verification",
                "keys": [
                    {
                        "key_id": key_id,
                        "public_key_b64": base64.b64encode(public_raw).decode("ascii"),
                        "algorithm": "Ed25519",
                        "status": "active",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def configure_test_receipt_authority(
    *,
    tmp_path: Path,
    monkeypatch: Any,
    key_id: str = "test-receipt-v1",
) -> SimpleNamespace:
    """Pin one ephemeral registry/key pair for a pytest process scope.

    Production loaders remain argument-free. Tests replace the committed path
    in-process but do not configure production private-key discovery globally.
    Tests that need signing authority use ``open_test_receipt_service``.
    """
    import storage.receipt_crypto as crypto

    private_pem, public_raw, resolved_key_id = generate_test_receipt_keypair(
        key_id=key_id
    )
    registry_path = write_test_receipt_registry(
        tmp_path / "receipt_verify_public_keys.json",
        key_id=resolved_key_id,
        public_raw=public_raw,
    )
    monkeypatch.setattr(crypto, "_PINNED_VERIFY_KEYS_PATH", registry_path)
    crypto._load_verify_key_file.cache_clear()
    monkeypatch.delenv("QUANT_RECEIPT_SIGNING_KEY_PEM", raising=False)
    monkeypatch.delenv("QUANT_RECEIPT_VERIFY_KEYS", raising=False)
    monkeypatch.delenv("QUANT_RECEIPT_KEY_ID", raising=False)
    private = serialization.load_pem_private_key(private_pem, password=None)
    assert isinstance(private, Ed25519PrivateKey)
    return SimpleNamespace(
        path=registry_path,
        key_id=resolved_key_id,
        private_pem=private_pem,
        public_raw=public_raw,
        signing_key=ReceiptSigningKey(key_id=resolved_key_id, _private=private),
    )


def open_test_receipt_service(
    *,
    signing_key: ReceiptSigningKey,
    clock: Any | None = None,
) -> Any:
    """Construct/register governed service authority only for unit tests."""
    import ingestion.runtime_authority as runtime

    service = runtime._GovernedReceiptService(
        _seal=runtime._SERVICE_SEAL,
        _signing_key=signing_key,
        _clock=clock or runtime._utc_now,
        _authority_id=object(),
    )
    with runtime._CAPABILITY_REGISTRY_LOCK:
        runtime._GOVERNED_SERVICES.add(service)
    return service


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, eq=False)
class TestReconciledEvidence:
    _seal: object
    required: RequiredCoverageSegment
    claims: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self._seal is not _TEST_EVIDENCE_SEAL:
            raise TypeError("test evidence is opaque")

    @property
    def extra_digests(self) -> Mapping[str, Any]:
        value = self.claims["extra_digests"]
        assert isinstance(value, Mapping)
        return value


TestReconciledEvidence.__test__ = False


@dataclass(frozen=True)
class TestSignedReceiptAuthority:
    """Ephemeral fixture authority; never imported by production code."""

    signing_key: ReceiptSigningKey

    def issue(self, evidence: TestReconciledEvidence) -> CollectionReceipt:
        if not isinstance(evidence, TestReconciledEvidence) or evidence not in _TEST_EVIDENCE:
            raise TypeError("test evidence is not fixture-minted")
        claims = _thaw(evidence.claims)
        signed = build_signed_digest_fields(
            signing_key=self.signing_key,
            closure_claims=claims,
        )
        required = evidence.required
        return CollectionReceipt(
            source=required.source,
            dataset=required.dataset,
            segment_id=required.segment_id,
            segment_start=required.segment_start,
            segment_end=required.segment_end,
            expected_scope=_thaw(required.expected_scope),
            expected_items=required.expected_items,
            observed_items=int(claims["observed_items"]),
            raw_page_count=int(claims["raw_page_count"]),
            raw_row_count=int(claims["raw_count"]),
            structured_row_count=int(claims["structured_count"]),
            pagination_exhausted=bool(claims["pagination_exhausted"]),
            digests=MappingProxyType(dict(signed)),
            run_id=int(claims["run_id"]),
            status=str(claims["status"]),
            error=None,
            checked_at=str(claims["checked_at"]),
        )


def reconcile_test_evidence(
    *,
    required: RequiredCoverageSegment,
    run_id: int,
    raw_pages: Sequence[bytes],
    raw_records: Sequence[Any],
    structured_records: Sequence[Mapping[str, Any]],
    checked_at: str,
    source_request: Mapping[str, Any] | None = None,
    extra_evidence: Mapping[str, Any] | None = None,
) -> TestReconciledEvidence:
    """Build closed claims strictly for verifier/policy unit tests."""
    pages = tuple(bytes(page) for page in raw_pages)
    raw_rows = tuple(raw_records)
    structured_rows = tuple(dict(row) for row in structured_records)
    if not pages:
        raise ValueError("test receipt requires at least one raw page")
    if not raw_rows:
        raise ValueError("zero-row SUCCESS is not trusted")
    extras = partition_extra_digests(extra_evidence)
    manifest = [
        {
            "index": index,
            "digest": canonical_evidence_digest(page),
            "size": len(page),
        }
        for index, page in enumerate(pages)
    ]
    raw_digest = (
        manifest[0]["digest"]
        if len(manifest) == 1
        else canonical_evidence_digest({"pages": manifest})
    )
    policy = coverage_contract_for(required.dataset)
    scope = {
        "coverage_policy_version": policy.policy_version,
        "source": required.source,
        "dataset": required.dataset,
        "segment_id": required.segment_id,
        "segment_start": required.segment_start,
        "segment_end": required.segment_end,
        "expected_scope": dict(required.expected_scope),
        "expected_items": required.expected_items,
    }
    unit = str(required.expected_scope.get("expected_item_unit") or "")
    observed = int(bool(raw_rows)) if unit in {
        "source_query",
        "official_archive_file",
        "official_archive_index",
        "official_full_timeseries_file",
        "official_correction_artifact",
    } else len(raw_rows)
    claims = {
        **scope,
        "observed_items": observed,
        "raw_page_count": len(pages),
        "raw_count": len(raw_rows),
        "structured_count": len(structured_rows),
        "status": "SUCCESS",
        "error": None,
        "pagination_exhausted": True,
        "discovery_exhausted": True,
        "source_request_digest": canonical_evidence_digest(
            dict(source_request or scope)
        ),
        "raw_manifest_digest": canonical_evidence_digest({"pages": manifest}),
        "raw_digest": raw_digest,
        "structured_digest": canonical_evidence_digest(list(structured_rows)),
        "structured_generation": int(run_id),
        "scope_digest": canonical_evidence_digest(scope),
        "run_id": int(run_id),
        "checked_at": checked_at,
        "extra_digests": extras,
    }
    claims["observation_digest"] = canonical_evidence_digest(claims)
    frozen_required = RequiredCoverageSegment(
        source=required.source,
        dataset=required.dataset,
        segment_id=required.segment_id,
        segment_start=required.segment_start,
        segment_end=required.segment_end,
        expected_scope=_freeze(required.expected_scope),
        expected_items=required.expected_items,
    )
    evidence = TestReconciledEvidence(
        _seal=_TEST_EVIDENCE_SEAL,
        required=frozen_required,
        claims=_freeze(claims),
    )
    _TEST_EVIDENCE.add(evidence)
    return evidence


# Old names are aliases only inside the test tree, keeping fixture diffs small.
_SignedReceiptAuthority = TestSignedReceiptAuthority
_reconcile_collection_evidence = reconcile_test_evidence
