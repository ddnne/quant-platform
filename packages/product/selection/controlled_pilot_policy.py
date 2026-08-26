"""Digest-checked cross-runtime ControlledPilotPolicy source of truth."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qp_paths import repo_root


CONTROLLED_PILOT_POLICY_ID = "controlled-pilot-policy/v1"
CONTROLLED_PILOT_POLICY_SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"
CONTROLLED_PILOT_POLICY_DIGEST = (
    "sha256:60fc8438f7dd4914c9fec99ae53476b9a514a80d0411b7ab07dc7e9963d5f319"
)
CONTROLLED_PILOT_POLICY_RAW_DIGEST = (
    "sha256:4bf8d3a54e33776445918775b9ea1a33270098c72226f0af9fb695412ef801fc"
)
CONTROLLED_PILOT_POLICY_REL = (
    Path("specs") / "policy" / "controlled_pilot_policy.json"
)
_POLICY_FIELDS = frozenset(
    {
        "$schema",
        "policy_id",
        "policy_digest",
        "plans_exactly",
        "max_parallel_experiments",
        "max_generations",
        "max_model_calls",
        "max_input_tokens",
        "max_output_tokens",
        "max_cached_tokens",
        "max_paper_runs",
        "max_cost_usd",
        "lease_ttl_seconds",
        "automatic_promotion",
    }
)


class ControlledPilotPolicyError(ValueError):
    """Raised when the controlled-pilot policy is malformed or has drifted."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ControlledPilotPolicyError(
                f"controlled pilot policy contains duplicate key: {key}"
            )
        document[key] = value
    return document


def _reject_nonfinite(value: str) -> Any:
    raise ControlledPilotPolicyError(
        f"controlled pilot policy contains non-finite number: {value}"
    )


def canonical_policy_digest(value: Any) -> str:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ControlledPilotPolicyError(
            "controlled pilot policy is not canonical JSON"
        ) from exc
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ControlledPilotPolicyError(f"{label} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class ControlledPilotPolicyPin:
    """Self-verifying policy data.  This value carries no run authority."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("ControlledPilotPolicyPin is final")

    schema_uri: str
    policy_id: str
    policy_digest: str
    plans_exactly: int
    max_parallel_experiments: int
    max_generations: int
    max_model_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_cached_tokens: int
    max_paper_runs: int
    max_cost_usd: int
    lease_ttl_seconds: int
    automatic_promotion: bool

    def __post_init__(self) -> None:
        if type(self.schema_uri) is not str or (
            self.schema_uri != CONTROLLED_PILOT_POLICY_SCHEMA_URI
        ):
            raise ControlledPilotPolicyError(
                "controlled pilot policy schema uri is not canonical"
            )
        if type(self.policy_id) is not str or (
            self.policy_id != CONTROLLED_PILOT_POLICY_ID
        ):
            raise ControlledPilotPolicyError(
                "controlled pilot policy id is not canonical"
            )
        if type(self.policy_digest) is not str or (
            self.policy_digest != CONTROLLED_PILOT_POLICY_DIGEST
        ):
            raise ControlledPilotPolicyError(
                "controlled pilot policy digest is not pinned"
            )
        if type(self.plans_exactly) is not int or self.plans_exactly != 4:
            raise ControlledPilotPolicyError(
                "controlled pilot policy requires exactly four plans"
            )
        for name in (
            "max_parallel_experiments",
            "max_generations",
            "max_model_calls",
            "max_input_tokens",
            "max_output_tokens",
            "max_cached_tokens",
            "max_paper_runs",
            "max_cost_usd",
            "lease_ttl_seconds",
        ):
            _positive_int(getattr(self, name), name)
        if self.max_generations != 1:
            raise ControlledPilotPolicyError("generation two is disabled")
        if type(self.automatic_promotion) is not bool or self.automatic_promotion:
            raise ControlledPilotPolicyError("automatic promotion is disabled")
        if canonical_policy_digest(self.to_digest_body()) != self.policy_digest:
            raise ControlledPilotPolicyError(
                "controlled pilot policy values do not match its declared digest"
            )

    def to_digest_body(self) -> dict[str, Any]:
        """Closed policy body hashed without the self-referential digest field."""
        return {
            "$schema": self.schema_uri,
            "policy_id": self.policy_id,
            "plans_exactly": self.plans_exactly,
            "max_parallel_experiments": self.max_parallel_experiments,
            "max_generations": self.max_generations,
            "max_model_calls": self.max_model_calls,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_cached_tokens": self.max_cached_tokens,
            "max_paper_runs": self.max_paper_runs,
            "max_cost_usd": self.max_cost_usd,
            "lease_ttl_seconds": self.lease_ttl_seconds,
            "automatic_promotion": self.automatic_promotion,
        }

    @property
    def budget_scope_digest(self) -> str:
        return canonical_policy_digest(
            {
                "policy_id": self.policy_id,
                "policy_digest": self.policy_digest,
                "plans_exactly": self.plans_exactly,
                "max_parallel_experiments": self.max_parallel_experiments,
                "max_generations": self.max_generations,
                "max_model_calls": self.max_model_calls,
                "max_input_tokens": self.max_input_tokens,
                "max_output_tokens": self.max_output_tokens,
                "max_cached_tokens": self.max_cached_tokens,
                "max_paper_runs": self.max_paper_runs,
                "max_cost_usd": self.max_cost_usd,
                "lease_ttl_seconds": self.lease_ttl_seconds,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "policy_digest": self.policy_digest,
            "plans_exactly": self.plans_exactly,
            "max_parallel_experiments": self.max_parallel_experiments,
            "max_generations": self.max_generations,
            "max_model_calls": self.max_model_calls,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_cached_tokens": self.max_cached_tokens,
            "max_paper_runs": self.max_paper_runs,
            "max_cost_usd": self.max_cost_usd,
            "lease_ttl_seconds": self.lease_ttl_seconds,
            "automatic_promotion": self.automatic_promotion,
        }


def load_controlled_pilot_policy(
    *, root: Path | None = None
) -> ControlledPilotPolicyPin:
    """Load the policy SoT and fail if any field or declared digest drifted."""
    path = (root or repo_root()) / CONTROLLED_PILOT_POLICY_REL
    try:
        raw = path.read_bytes()
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControlledPilotPolicyError(
            "cannot load controlled pilot policy"
        ) from exc
    raw_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if raw_digest != CONTROLLED_PILOT_POLICY_RAW_DIGEST:
        raise ControlledPilotPolicyError(
            "controlled pilot policy raw digest is not code-pinned"
        )
    if type(document) is not dict or set(document) != _POLICY_FIELDS:
        raise ControlledPilotPolicyError(
            "controlled pilot policy fields are not closed"
        )
    declared_digest = document.get("policy_digest")
    if type(declared_digest) is not str:
        raise ControlledPilotPolicyError("policy_digest must be a string")
    digest_body = dict(document)
    digest_body.pop("policy_digest")
    if canonical_policy_digest(digest_body) != declared_digest:
        raise ControlledPilotPolicyError(
            "controlled pilot policy digest mismatch"
        )
    return ControlledPilotPolicyPin(
        schema_uri=document["$schema"],
        policy_id=document["policy_id"],
        policy_digest=declared_digest,
        plans_exactly=document["plans_exactly"],
        max_parallel_experiments=document["max_parallel_experiments"],
        max_generations=document["max_generations"],
        max_model_calls=document["max_model_calls"],
        max_input_tokens=document["max_input_tokens"],
        max_output_tokens=document["max_output_tokens"],
        max_cached_tokens=document["max_cached_tokens"],
        max_paper_runs=document["max_paper_runs"],
        max_cost_usd=document["max_cost_usd"],
        lease_ttl_seconds=document["lease_ttl_seconds"],
        automatic_promotion=document["automatic_promotion"],
    )


__all__ = [
    "CONTROLLED_PILOT_POLICY_DIGEST",
    "CONTROLLED_PILOT_POLICY_ID",
    "CONTROLLED_PILOT_POLICY_RAW_DIGEST",
    "ControlledPilotPolicyError",
    "ControlledPilotPolicyPin",
    "canonical_policy_digest",
    "load_controlled_pilot_policy",
]
