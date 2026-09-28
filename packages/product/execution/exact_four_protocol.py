"""Digest-pinned schema loaders for the authority-free protocol."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from execution.exact_four_codec import (
    ExactFourAuthorityContractError,
    _strict_json_loads,
    canonical_authority_digest,
)
from qp_paths import repo_root
from selection.controlled_pilot_policy import CONTROLLED_PILOT_POLICY_SCHEMA_URI


EXACT_FOUR_AUTHORITY_SCHEMA_REL = (
    Path("specs") / "ready" / "exact_four_authority_protocol.schema.json"
)
PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_DIGEST = (
    "sha256:4d31fe5d60697dfe5cc923387e0fb49aebd06f7e1b5adc5fe480fd3084462f48"
)
PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_RAW_DIGEST = (
    "sha256:0a08f6dd8a1cf70837d08b68b32a1e2cd16444dd64528b94e03e3f9c18851bf3"
)
EXACT_FOUR_RESULT_SCHEMA_REL = (
    Path("specs") / "ready" / "exact_four_result_manifest.schema.json"
)
PINNED_EXACT_FOUR_RESULT_SCHEMA_DIGEST = (
    "sha256:1eec4b2f5c3adc7aa5673e3f2b755a20bf3c870b1f9329f3fe2f0f046705128d"
)
PINNED_EXACT_FOUR_RESULT_SCHEMA_RAW_DIGEST = (
    "sha256:3d60bb3cd7ad12307151de4dc1c73fe83036c6237df902bbe0aea30468e12f4c"
)


def authority_schema_path() -> Path:
    return repo_root() / EXACT_FOUR_AUTHORITY_SCHEMA_REL


def load_exact_four_authority_schema() -> dict[str, Any]:
    try:
        raw = authority_schema_path().read_bytes()
        value = _strict_json_loads(raw, label="exact-four authority protocol schema")
    except (OSError, ExactFourAuthorityContractError) as exc:
        raise ExactFourAuthorityContractError(
            "cannot load exact-four authority protocol schema"
        ) from exc
    raw_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if raw_digest != PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_RAW_DIGEST:
        raise ExactFourAuthorityContractError(
            "pinned exact-four authority protocol schema raw digest mismatch"
        )
    if type(value) is not dict:
        raise ExactFourAuthorityContractError(
            "exact-four authority protocol schema must be an object"
        )
    if set(value) != {"$schema", "$id", "title", "oneOf", "$defs"} or (
        value.get("$schema") != CONTROLLED_PILOT_POLICY_SCHEMA_URI
        or value.get("$id")
        != "https://quant-platform.local/specs/ready/"
        "exact_four_authority_protocol.schema.json"
        or value.get("title")
        != "Exact-four controlled-pilot v2 authority protocol"
    ):
        raise ExactFourAuthorityContractError(
            "exact-four authority protocol schema identity is not closed"
        )
    if canonical_authority_digest(value) != PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_DIGEST:
        raise ExactFourAuthorityContractError(
            "pinned exact-four authority protocol schema digest mismatch"
        )
    try:
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(value)
    except Exception as exc:
        raise ExactFourAuthorityContractError(
            "exact-four authority protocol schema is invalid"
        ) from exc
    return value


def exact_four_result_schema_path() -> Path:
    return repo_root() / EXACT_FOUR_RESULT_SCHEMA_REL


def load_exact_four_result_schema() -> dict[str, Any]:
    path = exact_four_result_schema_path()
    try:
        raw = path.read_bytes()
        value = _strict_json_loads(raw, label="exact-four result manifest schema")
    except (OSError, ExactFourAuthorityContractError) as exc:
        raise ExactFourAuthorityContractError(
            "cannot load exact-four result manifest schema"
        ) from exc
    raw_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if raw_digest != PINNED_EXACT_FOUR_RESULT_SCHEMA_RAW_DIGEST:
        raise ExactFourAuthorityContractError(
            "pinned exact-four result manifest schema raw digest mismatch"
        )
    if (
        type(value) is not dict
        or value.get("$schema") != CONTROLLED_PILOT_POLICY_SCHEMA_URI
        or value.get("$id")
        != "https://quant-platform.local/specs/ready/"
        "exact_four_result_manifest.schema.json"
        or value.get("title")
        != "Exact-four controlled-pilot v2 result manifest"
        or canonical_authority_digest(value)
        != PINNED_EXACT_FOUR_RESULT_SCHEMA_DIGEST
    ):
        raise ExactFourAuthorityContractError(
            "pinned exact-four result manifest schema identity or digest mismatch"
        )
    try:
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(value)
    except Exception as exc:
        raise ExactFourAuthorityContractError(
            "exact-four result manifest schema is invalid"
        ) from exc
    return value


__all__ = [
    "PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_DIGEST",
    "PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_RAW_DIGEST",
    "PINNED_EXACT_FOUR_RESULT_SCHEMA_DIGEST",
    "PINNED_EXACT_FOUR_RESULT_SCHEMA_RAW_DIGEST",
    "authority_schema_path",
    "exact_four_result_schema_path",
    "load_exact_four_authority_schema",
    "load_exact_four_result_schema",
]
