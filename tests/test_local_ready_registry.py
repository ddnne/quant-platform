from __future__ import annotations

import base64
import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from paper_runtime import readiness_attestation as runtime_readiness
from research import readiness as product_readiness

from scripts import local_ready_registry as registry


def _digest(document: object) -> str:
    raw = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def test_staging_ready_key_cannot_enter_production_scope(tmp_path, monkeypatch):
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(
        private.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    staging = {
        "schema_version": 2,
        "purpose": "readiness_attestation_verification",
        "environment": "staging",
        "authority_instance_id": "ready-authority/staging/v1",
        "keys": [
            {
                "key_id": "ready-staging-v1",
                "algorithm": "Ed25519",
                "public_key_b64": public,
                "status": "active",
            }
        ],
    }
    production = {
        "schema_version": 2,
        "purpose": "readiness_attestation_verification",
        "environment": "production",
        "authority_instance_id": "ready-authority/production/v1",
        "keys": [],
    }
    staging_path = tmp_path / "staging.json"
    production_path = tmp_path / "production.json"
    staging_path.write_text(json.dumps(staging), encoding="utf-8")
    production_path.write_text(json.dumps(production), encoding="utf-8")
    monkeypatch.setattr(
        registry,
        "_REGISTRIES",
        {
            "staging": (staging_path, _digest(staging)),
            "production": (production_path, _digest(production)),
        },
    )

    staged = registry.load_scoped_ready_public_keys(
        expected_environment="staging"
    )
    production_keys = registry.load_scoped_ready_public_keys(
        expected_environment="production"
    )
    assert (
        "staging",
        "ready-authority/staging/v1",
        "ready-staging-v1",
    ) in staged
    assert production_keys == {}


def test_ready_authority_resource_digest_has_one_canonical_implementation():
    values = {
        "snapshot_id": "sha256:" + "11" * 32,
        "immutable_db_digest": "sha256:" + "22" * 32,
        "ready_manifest_digest": "sha256:" + "33" * 32,
        "signed_projection_document_digest": "sha256:" + "44" * 32,
    }
    for environment in ("staging", "production"):
        instance = runtime_readiness.ready_authority_instance_id(environment)
        expected = runtime_readiness.derive_ready_authority_resource_digest(
            environment=environment,
            authority_instance_id=instance,
            **values,
        )
        assert product_readiness.ready_authority_instance_id(environment) == instance
        assert registry.ready_authority_instance_id(environment) == instance
        assert (
            product_readiness.derive_ready_authority_resource_digest(
                environment=environment,
                authority_instance_id=instance,
                **values,
            )
            == expected
        )
        assert (
            registry.derive_ready_authority_resource_digest(
                environment=environment,
                **values,
            )
            == expected
        )
