from __future__ import annotations

import base64
import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

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
