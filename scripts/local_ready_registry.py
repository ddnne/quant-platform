"""Compatibility names for the canonical verify-only READY registry.

No independent schema, pins or local minting authority live in this module.
"""

from paper_runtime.readiness_attestation import (
    ReadyAttestationVerificationError as LocalReadyRegistryError,
    derive_ready_authority_resource_digest as _derive_ready_authority_resource_digest,
    load_pinned_readiness_public_keys as load_scoped_ready_public_keys,
    ready_authority_instance_id,
)


def derive_ready_authority_resource_digest(
    *,
    environment: str,
    snapshot_id: str,
    immutable_db_digest: str,
    ready_manifest_digest: str,
    signed_projection_document_digest: str,
) -> str:
    return _derive_ready_authority_resource_digest(
        environment=environment,
        authority_instance_id=ready_authority_instance_id(environment),
        snapshot_id=snapshot_id,
        immutable_db_digest=immutable_db_digest,
        ready_manifest_digest=ready_manifest_digest,
        signed_projection_document_digest=signed_projection_document_digest,
    )


__all__ = [
    "LocalReadyRegistryError",
    "derive_ready_authority_resource_digest",
    "load_scoped_ready_public_keys",
    "ready_authority_instance_id",
]
