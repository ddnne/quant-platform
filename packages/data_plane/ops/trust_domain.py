"""Closed environment and Cloudflare resource identities for local authorities."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping


ENVIRONMENTS = frozenset({"staging", "production"})

_D1_RESOURCES = {
    "staging": {
        "provider": "cloudflare",
        "kind": "d1",
        "name": "quant-ingest-staging",
        "database_id": "d448d1c6-27c8-4aeb-8702-3e7a8b6bf2bb",
        "authority_id": "cloudflare-d1:d448d1c6-27c8-4aeb-8702-3e7a8b6bf2bb",
    },
    "production": {
        "provider": "cloudflare",
        "kind": "d1",
        "name": "quant-ingest",
        "database_id": "be6fdcf8-40be-41fc-9535-7facd1fc2ffc",
        "authority_id": "cloudflare-d1:be6fdcf8-40be-41fc-9535-7facd1fc2ffc",
    },
}


def require_environment(value: object) -> str:
    if type(value) is not str or value not in ENVIRONMENTS:
        raise ValueError("authority environment must be staging or production")
    return value


def d1_resource_identity(environment: str) -> Mapping[str, str]:
    selected = require_environment(environment)
    return MappingProxyType(dict(_D1_RESOURCES[selected]))


def require_d1_resource_identity(
    value: object, *, expected_environment: str
) -> dict[str, str]:
    selected = require_environment(expected_environment)
    expected = dict(_D1_RESOURCES[selected])
    if type(value) not in {dict, MappingProxyType} or dict(value) != expected:
        raise ValueError("D1 resource identity crosses the expected trust domain")
    return dict(expected)


def projection_resource_identity(
    *, environment: str, source: Mapping[str, Any]
) -> dict[str, Any]:
    selected = require_environment(environment)
    d1 = require_d1_resource_identity(
        source.get("resource_identity"), expected_environment=selected
    )
    return {
        "environment": selected,
        "source_d1": d1,
        "source_audit_digest": source.get("audit_digest"),
        "source_export_digest": source.get("export_digest"),
        "source_change_seq": source.get("source_change_seq"),
    }


__all__ = [
    "ENVIRONMENTS",
    "d1_resource_identity",
    "projection_resource_identity",
    "require_d1_resource_identity",
    "require_environment",
]
