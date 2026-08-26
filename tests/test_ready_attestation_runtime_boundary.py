"""Behavioral invariants for the lower-plane READY verifier boundary."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import paper_runtime.readiness_attestation as runtime_attestation
from research.ready_manifest import (
    VerifiedPilotReadyPublication,
    build_ready_manifest,
    load_exact_four_pilot_ready_binding,
    publish_exact_four_pilot_ready_snapshot,
)
from research.readiness import (
    ReadyPublicationAuthorityPending,
    load_verified_pilot_readiness,
)
from research.universe_contract import EXACT_FOUR_UNIVERSE_RULE_DIGEST
from selection.budget_ledger import MassResearchDisabledError
from tests.readiness_test_support import (
    _TestReadinessSigner,
    make_readiness_signer,
    mint_pilot_readiness,
)


class _HostileEvidence(Mapping[str, object]):
    """Caller mapping that explodes if a pending issuer inspects it."""

    def __getitem__(self, key: str) -> object:
        raise AssertionError(f"unprovisioned issuer inspected {key}")

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("unprovisioned issuer iterated caller evidence")

    def __len__(self) -> int:
        raise AssertionError("unprovisioned issuer measured caller evidence")


def _signed_sidecar(
    tmp_path: Path,
    *,
    verified_at: datetime,
    published_at: datetime,
    ttl_seconds: int,
) -> tuple[Path, dict[str, object], str, _TestReadinessSigner]:
    binding = load_exact_four_pilot_ready_binding()
    digest = "sha256:" + ("ab" * 32)
    manifest = build_ready_manifest(
        snapshot_id=digest,
        publication_scope="PILOT",
        profile_id=binding.profile_id,
        profile_version=binding.profile_version,
        profile_digest=binding.profile_digest,
        plan_ids=binding.plan_ids,
        plan_set_digest=binding.plan_set_digest,
        dependency_closure_digest=binding.closure_set_digest,
        universe_rule_digest=EXACT_FOUR_UNIVERSE_RULE_DIGEST,
        resolved_universe_digest=digest,
        dataset_ids=binding.required_datasets,
        coverage_proof_digest=digest,
        raw_proof_digest=digest,
        receipt_proof_digest=digest,
        validation_proof_digest=digest,
        b0_proof_digest=digest,
        b4_proof_digest=digest,
        source_generation="1",
        applied_sync_generation="1",
        export_cursor="1",
        applied_cursor="1",
        pit_contract_digests={"pit_api": digest, "dependency_scope": digest},
        feature_generation=digest,
        catalog_generation=digest,
        created_at=(published_at - timedelta(minutes=1)).isoformat(),
        published_at=published_at.isoformat(),
    )
    signer = make_readiness_signer(key_id="runtime-boundary-test")
    readiness = mint_pilot_readiness(
        manifest,
        publisher=signer,
        immutable_db_digest=digest,
        now=verified_at,
        ttl_seconds=ttl_seconds,
    )
    sidecar = tmp_path / "pilot.readiness.json"
    sidecar.write_text(json.dumps(readiness.to_dict()), encoding="utf-8")
    return sidecar, manifest.to_dict(), digest, signer


def test_runtime_exact_four_pins_match_the_canonical_compiler() -> None:
    binding = load_exact_four_pilot_ready_binding()
    assert runtime_attestation.EXACT_FOUR_PROFILE_ID == binding.profile_id
    assert runtime_attestation.EXACT_FOUR_PROFILE_VERSION == binding.profile_version
    assert runtime_attestation.EXACT_FOUR_PROFILE_DIGEST == binding.profile_digest
    assert runtime_attestation.EXACT_FOUR_PLAN_IDS == binding.plan_ids
    assert runtime_attestation.EXACT_FOUR_PLAN_SET_DIGEST == binding.plan_set_digest
    assert runtime_attestation.EXACT_FOUR_CLOSURE_DIGEST == binding.closure_set_digest
    assert runtime_attestation.EXACT_FOUR_DATASET_IDS == binding.required_datasets
    assert (
        runtime_attestation.EXACT_FOUR_UNIVERSE_RULE_DIGEST
        == EXACT_FOUR_UNIVERSE_RULE_DIGEST
    )


def test_caller_registry_replacement_cannot_self_root_runtime_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attacker_registry = tmp_path / "attacker-readiness-registry.json"
    attacker_registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "purpose": "readiness_attestation_verification",
                "keys": [
                    {
                        "key_id": "same-uid-attacker",
                        "algorithm": "Ed25519",
                        "public_key_b64": base64.b64encode(bytes(32)).decode("ascii"),
                        "status": "active",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_attestation,
        "_PINNED_READINESS_REGISTRY_PATH",
        attacker_registry,
    )
    with pytest.raises(
        runtime_attestation.ReadyAttestationVerificationError,
        match="digest mismatch",
    ):
        runtime_attestation.load_pinned_readiness_public_keys()


def test_pending_authority_does_not_inspect_or_mutate_caller_inputs(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "current.sqlite"
    staging.write_bytes(b"unchanged")
    snapshots = tmp_path / "snapshots"
    with pytest.raises(ReadyPublicationAuthorityPending, match="PENDING"):
        publish_exact_four_pilot_ready_snapshot(
            staging,
            snapshots,
            signed_projection_document=_HostileEvidence(),
        )
    assert staging.read_bytes() == b"unchanged"
    assert not snapshots.exists()


class _ExplodingPublicationInput:
    def __getattribute__(self, name: str) -> object:
        raise AssertionError(f"pending publication wrapper inspected {name}")


def test_pending_publication_result_cannot_be_caller_constructed(
    tmp_path: Path,
) -> None:
    hostile = _ExplodingPublicationInput()
    with pytest.raises(ReadyPublicationAuthorityPending, match="PENDING"):
        VerifiedPilotReadyPublication(
            snapshot=hostile,
            readiness=hostile,
            readiness_path=tmp_path / "attestation.json",
        )


def test_ready_json_rejects_duplicate_keys_and_nonfinite_constants(
    tmp_path: Path,
) -> None:
    clock = datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc)
    sidecar, _manifest, _digest, _signer = _signed_sidecar(
        tmp_path,
        verified_at=clock,
        published_at=clock - timedelta(minutes=1),
        ttl_seconds=3_600,
    )
    raw = sidecar.read_text(encoding="utf-8")
    duplicate = raw.replace(
        '"attestation_id":',
        '"attestation_id": "ignored-by-last-wins", "attestation_id":',
        1,
    ).encode("utf-8")
    with pytest.raises(
        runtime_attestation.ReadyAttestationVerificationError,
        match="duplicate key 'attestation_id'",
    ):
        runtime_attestation.decode_strict_ready_json(duplicate)

    sidecar.write_bytes(duplicate)
    with pytest.raises(MassResearchDisabledError, match="ambiguous or invalid"):
        load_verified_pilot_readiness(sidecar)

    with pytest.raises(
        runtime_attestation.ReadyAttestationVerificationError,
        match="non-finite constant 'NaN'",
    ):
        runtime_attestation.decode_strict_ready_json(
            b'{"outer":{"value":NaN}}'
        )


def test_runtime_verifier_has_no_caller_clock_and_accepts_bounded_ttl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc)
    sidecar, manifest, digest, signer = _signed_sidecar(
        tmp_path,
        verified_at=clock,
        published_at=clock - timedelta(minutes=1),
        ttl_seconds=runtime_attestation.MAX_READY_ATTESTATION_TTL_SECONDS,
    )
    monkeypatch.setattr(
        runtime_attestation,
        "_load_pinned_readiness_public_keys",
        signer.public_keys,
    )
    monkeypatch.setattr(runtime_attestation, "_now", lambda: clock)
    verified = runtime_attestation.verify_pinned_pilot_snapshot_attestation(
        sidecar.read_bytes(),
        snapshot_id=digest,
        ready_manifest=manifest,
        immutable_db_digest=digest,
    )
    assert verified["snapshot_id"] == digest
    with pytest.raises(TypeError, match="unexpected keyword argument 'now'"):
        runtime_attestation.verify_pinned_pilot_snapshot_attestation(
            sidecar.read_bytes(),
            snapshot_id=digest,
            ready_manifest=manifest,
            immutable_db_digest=digest,
            now=clock,
        )  # type: ignore[call-arg]


def test_runtime_verifier_rejects_unbounded_ttl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc)
    sidecar, manifest, digest, signer = _signed_sidecar(
        tmp_path,
        verified_at=clock,
        published_at=clock - timedelta(minutes=1),
        ttl_seconds=runtime_attestation.MAX_READY_ATTESTATION_TTL_SECONDS + 1,
    )
    monkeypatch.setattr(
        runtime_attestation,
        "_load_pinned_readiness_public_keys",
        signer.public_keys,
    )
    monkeypatch.setattr(runtime_attestation, "_now", lambda: clock)
    with pytest.raises(
        runtime_attestation.ReadyAttestationVerificationError,
        match="time-incoherent",
    ):
        runtime_attestation.verify_pinned_pilot_snapshot_attestation(
            sidecar.read_bytes(),
            snapshot_id=digest,
            ready_manifest=manifest,
            immutable_db_digest=digest,
        )


@pytest.mark.parametrize(
    ("published_offset", "verified_offset"),
    (
        (timedelta(minutes=1), timedelta()),
        (timedelta(), timedelta(minutes=6)),
    ),
)
def test_runtime_verifier_rejects_future_manifest_or_attestation_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    published_offset: timedelta,
    verified_offset: timedelta,
) -> None:
    clock = datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc)
    sidecar, manifest, digest, signer = _signed_sidecar(
        tmp_path,
        verified_at=clock + verified_offset,
        published_at=clock + published_offset,
        ttl_seconds=3_600,
    )
    monkeypatch.setattr(
        runtime_attestation,
        "_load_pinned_readiness_public_keys",
        signer.public_keys,
    )
    monkeypatch.setattr(runtime_attestation, "_now", lambda: clock)
    with pytest.raises(
        runtime_attestation.ReadyAttestationVerificationError,
        match="time-incoherent",
    ):
        runtime_attestation.verify_pinned_pilot_snapshot_attestation(
            sidecar.read_bytes(),
            snapshot_id=digest,
            ready_manifest=manifest,
            immutable_db_digest=digest,
        )
