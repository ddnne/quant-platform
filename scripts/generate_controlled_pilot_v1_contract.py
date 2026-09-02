#!/usr/bin/env python3
"""Compile the checked-in controlled_pilot_v1 Worker/Container contract.

Source of truth is the Python exact-four compiler (canonical plans +
``exact_four_binding``). TypeScript must import the generated JSON; do not
hand-pin those values in Worker source.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
from _bootstrap import ensure_repo_root

ROOT = ensure_repo_root()

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from execution.exact_four_binding import controlled_pilot_v1_contract
from data_contracts.coverage import coverage_policy_binding
from ops.projection_signing import (
    PINNED_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST,
    PINNED_OPS_PROJECTION_REGISTRY_BODY_DIGEST,
    PINNED_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST,
    PINNED_OPS_PROJECTION_REGISTRY_GENERATION,
    PINNED_STAGING_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST,
    PINNED_STAGING_OPS_PROJECTION_REGISTRY_BODY_DIGEST,
    PINNED_STAGING_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST,
    PINNED_STAGING_OPS_PROJECTION_REGISTRY_GENERATION,
)
from ops.trust_domain import d1_resource_identity
from paper_runtime.readiness_attestation import (
    CONTROLLED_READY_ENVELOPE_FORMAT,
    derive_ready_authority_resource_digest,
    ready_authority_instance_id,
)
from paper_runtime.canonical_json import canonical_json_digest
from research.universe_contract import ResolvedUniverseMembership

CONTRACT_REL = Path("specs") / "ready" / "controlled_pilot_v1.generated.json"
PLAN_SCHEMA_REL = Path("specs") / "experiment_plans" / "schema.json"
REGISTRY_RAW_TS_REL = (
    Path("platform")
    / "workers"
    / "research-mass-eval"
    / "src"
    / "controlled_pilot_registry_raw.generated.ts"
)
REGISTRY_FILES = (
    ("READY_PRODUCTION", Path("specs") / "ready" / "readiness_verify_public_keys.json"),
    ("READY_STAGING", Path("specs") / "ready" / "readiness_verify_public_keys.staging.json"),
    ("TRADER_PRODUCTION", Path("specs") / "trader_authorization" / "public_keys.json"),
    ("TRADER_STAGING", Path("specs") / "trader_authorization" / "public_keys.staging.json"),
    ("OPS_PROJECTION_PRODUCTION", Path("specs") / "ops_projection" / "verify_public_keys.json"),
    ("OPS_PROJECTION_STAGING", Path("specs") / "ops_projection" / "verify_public_keys.staging.json"),
)
FIXTURE_DIR = Path("specs") / "ready"
READY_FIXTURE_REL = FIXTURE_DIR / "controlled_pilot_ready.generated.json"
TRADER_FIXTURE_REL = FIXTURE_DIR / "controlled_pilot_trader_batch.generated.json"
KEYS_FIXTURE_REL = FIXTURE_DIR / "controlled_pilot_verify_keys.generated.json"
ARTIFACTS_FIXTURE_REL = (
    FIXTURE_DIR / "controlled_pilot_container_artifacts.generated.json"
)

# Deterministic fixture-only key. Not an ACTIVE production registry row.
_FIXTURE_SEED = b"controlled-pilot-v1-fixture-ed25519-seed-v1"
ISSUED_AT = "2026-09-02T12:00:00+00:00"
VERIFIER_NOW = "2026-09-02T12:00:30+00:00"
TTL_SECONDS = 3600


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _fixture_private_key() -> Ed25519PrivateKey:
    material = hashlib.sha256(_FIXTURE_SEED).digest()
    return Ed25519PrivateKey.from_private_bytes(material)


def _sign(private_key: Ed25519PrivateKey, body: dict[str, Any]) -> str:
    signature = private_key.sign(_canonical_bytes(body))
    return "ed25519:" + base64.b64encode(signature).decode("ascii")


def render_contract() -> bytes:
    document = controlled_pilot_v1_contract()
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True).encode(
        "utf-8"
    ) + b"\n"


def _fixture_universe(contract: dict[str, Any]) -> ResolvedUniverseMembership:
    period_start = str(contract["plans"][0]["period_start"])
    period_end = str(contract["plans"][0]["period_end"])
    membership = ResolvedUniverseMembership(
        period_start=period_start,
        period_end=period_end,
        decision_memberships=((period_start, ("7203",)),),
    )
    return membership


def render_fixtures() -> dict[str, bytes]:
    contract = controlled_pilot_v1_contract()
    private_key = _fixture_private_key()
    public_b64 = base64.b64encode(private_key.public_key().public_bytes_raw()).decode(
        "ascii"
    )
    key_id = "controlled-pilot-fixture-v1"
    environment = "staging"
    logical = "sha256:" + hashlib.sha256(b"controlled-pilot-logical-snapshot").hexdigest()
    physical = "sha256:" + hashlib.sha256(b"controlled-pilot-physical-sqlite").hexdigest()
    physical_key = (
        "research/controlled_pilot/v1/snapshots/sha256="
        + physical[len("sha256:") :]
        + ".sqlite"
    )
    universe = _fixture_universe(contract)
    issued = datetime.fromisoformat(ISSUED_AT)
    expires = issued + timedelta(seconds=TTL_SECONDS)
    proof = _digest({"fixture": "controlled-pilot-proof", "logical": logical})
    scope_entries = [
        {
            "dataset_id": dataset_id,
            "natural_key_count": 1,
            "natural_key_digest": proof,
            "receipt_digests": [proof],
            "receipt_set_digest": _digest([proof]),
            "product_artifact_digests": [proof],
            "product_artifact_set_digest": _digest([proof]),
        }
        for dataset_id in contract["dataset_ids"]
    ]
    scope_body = {
        "format": "pit-dependency-scope-proof/v1",
        "status": "PASS",
        "profile_digest": contract["profile_digest"],
        "plan_set_digest": contract["plan_set_digest"],
        "dependency_closure_digest": contract["dependency_closure_digest"],
        "universe_rule_digest": contract["universe_rule_digest"],
        "resolved_universe_digest": universe.resolved_membership_digest,
        "universe_daily_summary": [],
        "period_start": contract["plans"][0]["period_start"],
        "period_end": contract["plans"][0]["period_end"],
        "lookback_trading_days": 1,
        "physical_db_digest": physical,
        "entries": scope_entries,
        "product_materialization_digest": _digest(
            [
                {
                    "dataset_id": entry["dataset_id"],
                    "product_artifact_digests": entry["product_artifact_digests"],
                }
                for entry in scope_entries
            ]
        ),
    }
    dependency_scope = {**scope_body, "proof_digest": _digest(scope_body)}
    observed_through = "2026-09-02T21:00:00+09:00"
    membership_digest = str(contract["dataset_membership_digest"])
    manifest_body = {
        "format": "ready-manifest/v1",
        "identity": contract["identity"],
        "snapshot_id": logical,
        "publication_scope": "PILOT",
        "profile_id": contract["profile_id"],
        "profile_version": contract["profile_version"],
        "profile_digest": contract["profile_digest"],
        "plan_ids": list(contract["plan_ids"]),
        "plan_set_digest": contract["plan_set_digest"],
        "dependency_closure_digest": contract["dependency_closure_digest"],
        "universe_rule_digest": contract["universe_rule_digest"],
        "resolved_universe_digest": universe.resolved_membership_digest,
        "dataset_ids": list(contract["dataset_ids"]),
        "dataset_membership_digest": membership_digest,
        "coverage_policy_version": contract["coverage_policy_version"],
        "coverage_policy_digest": contract["coverage_policy_digest"],
        "coverage_proof_digest": proof,
        "raw_proof_digest": proof,
        "receipt_proof_digest": proof,
        "validation_proof_digest": proof,
        "b0_proof_digest": proof,
        "b4_proof_digest": proof,
        "source_generation": "g1",
        "applied_sync_generation": "g1",
        "export_cursor": "g1",
        "applied_cursor": "g1",
        "pit_contract_digests": {
            "pit_api": proof,
            "dependency_scope": dependency_scope["proof_digest"],
        },
        "feature_generation": proof,
        "catalog_generation": proof,
        "created_at": ISSUED_AT,
        "published_at": ISSUED_AT,
        "fill_contract_digest": contract["fill_contract_digest"],
        "observed_through": observed_through,
    }
    manifest = {
        **manifest_body,
        "manifest_digest": _digest(manifest_body),
    }
    signed_projection_document = {
        "fixture": "signed-ops-projection-placeholder",
        "environment": environment,
    }
    signed_projection = _digest(signed_projection_document)
    authority_digest = derive_ready_authority_resource_digest(
        environment=environment,
        authority_instance_id=ready_authority_instance_id(environment),
        snapshot_id=logical,
        immutable_db_digest=physical,
        ready_manifest_digest=manifest["manifest_digest"],
        signed_projection_document_digest=signed_projection,
    )
    attestation_id = f"ready-{authority_digest.removeprefix('sha256:')}"
    attestation_body = {
        "format": "verified-readiness-attestation/v1",
        "attestation_id": attestation_id,
        "environment": environment,
        "authority_instance_id": ready_authority_instance_id(environment),
        "authority_resource_digest": authority_digest,
        "signed_projection_document_digest": signed_projection,
        "readiness_scope": "PILOT",
        "identity": contract["identity"],
        "snapshot_id": logical,
        "profile_id": contract["profile_id"],
        "profile_version": contract["profile_version"],
        "profile_digest": contract["profile_digest"],
        "plan_ids": list(contract["plan_ids"]),
        "plan_set_digest": contract["plan_set_digest"],
        "dependency_closure_digest": contract["dependency_closure_digest"],
        "universe_rule_digest": contract["universe_rule_digest"],
        "resolved_universe_digest": universe.resolved_membership_digest,
        "dataset_ids": list(contract["dataset_ids"]),
        "ready_state": "READY",
        "ready_manifest_digest": manifest["manifest_digest"],
        "immutable_db_digest": physical,
        "coverage_policy_version": contract["coverage_policy_version"],
        "coverage_policy_digest": contract["coverage_policy_digest"],
        "coverage_proof_digest": proof,
        "governed_membership_digest": membership_digest,
        "raw_proof_digest": proof,
        "receipt_proof_digest": proof,
        "validation_proof_digest": proof,
        "b0_quality_proof_digest": proof,
        "b4_quality_proof_digest": proof,
        "source_generation": "g1",
        "export_cursor": "g1",
        "applied_cursor": "g1",
        "verified_at": ISSUED_AT,
        "expires_at": expires.isoformat(),
        "evidence_digest": _digest(
            {"manifest": manifest, "immutable_db_digest": physical}
        ),
        "key_id": key_id,
        "issuer": "ReadyPublicationService/v3",
        "fill_contract_digest": contract["fill_contract_digest"],
    }
    attestation = {
        **attestation_body,
        "signature": _sign(private_key, attestation_body),
    }
    envelope = {
        "format": CONTROLLED_READY_ENVELOPE_FORMAT,
        "identity": contract["identity"],
        "environment": environment,
        "attestation": attestation,
        "ready_manifest": manifest,
        "dependency_scope_evidence": dependency_scope,
        "signed_projection_document": signed_projection_document,
        "controlled_session_scope": {
            "format": "controlled-session-scope/v1",
            "dependency_scope_proof_digest": dependency_scope["proof_digest"],
            "physical_db_digest": physical,
            "observed_through": observed_through,
            "entries": [
                {
                    "dataset_id": entry["dataset_id"],
                    "natural_key_count": entry["natural_key_count"],
                    "natural_key_digest": entry["natural_key_digest"],
                    "product_artifact_digests": entry[
                        "product_artifact_digests"
                    ],
                    "product_artifact_set_digest": entry[
                        "product_artifact_set_digest"
                    ],
                }
                for entry in scope_entries
            ],
        },
        "physical": {"key": physical_key, "digest": physical, "size": 32},
    }
    request = {
        "idempotency_key": "controlled-job-1",
        "ready_attestation_id": attestation_id,
        "snapshot_id": logical,
    }
    request_digest = _digest(
        {
            "identity": contract["identity"],
            "idempotency_key": request["idempotency_key"],
            "ready_attestation_id": request["ready_attestation_id"],
            "snapshot_id": request["snapshot_id"],
        }
    )
    rows = [
        {
            "ordinal": plan["ordinal"],
            "plan_id": plan["plan_id"],
            "plan_binding_digest": plan["plan_binding_digest"],
            "strategy_spec_id": plan["strategy_spec_id"],
            "strategy_spec_version": plan["strategy_spec_version"],
            "strategy_spec_hash": plan["strategy_spec_hash"],
        }
        for plan in contract["plans"]
    ]
    trader_body = {
        "format": "controlled-pilot-trader-authorization-batch/v2",
        "schema_version": 2,
        "purpose": "controlled_trader_authorization_verification",
        "algorithm": "Ed25519",
        "identity": contract["identity"],
        "environment": environment,
        "authority_instance_id": f"trader-authority/{environment}/v1",
        "request_digest": request_digest,
        "idempotency_key": request["idempotency_key"],
        "ready_attestation_id": attestation_id,
        "ready_manifest_digest": manifest["manifest_digest"],
        "snapshot_id": logical,
        "immutable_db_digest": physical,
        "snapshot_key": physical_key,
        "snapshot_size": 32,
        "profile_digest": contract["profile_digest"],
        "dependency_closure_digest": contract["dependency_closure_digest"],
        "exact_four_binding_digest": contract["exact_four_binding_digest"],
        "policy_digest": contract["policy_digest"],
        "budget_scope_digest": contract["budget_scope_digest"],
        "execution_limit_set_digest": contract["execution_limit_set_digest"],
        "resolved_universe_digest": universe.resolved_membership_digest,
        "fill_contract_digest": contract["fill_contract_digest"],
        "rows": rows,
        "issued_at": ISSUED_AT,
        "expires_at": expires.isoformat(),
        "key_id": key_id,
        "issuer": "ControlledTraderAuthorizationService/v1",
    }
    trader = {**trader_body, "signature": _sign(private_key, trader_body)}
    authorization_digest = canonical_json_digest(trader)
    keys = {
        "key_id": key_id,
        "algorithm": "Ed25519",
        "public_key_b64": public_b64,
        "issued_at": ISSUED_AT,
        "verifier_now": VERIFIER_NOW,
        "ttl_seconds": TTL_SECONDS,
        "logical_snapshot_id": logical,
        "physical_snapshot_id": physical,
        "request": request,
        "request_digest": request_digest,
        "resolved_universe_digest": universe.resolved_membership_digest,
    }
    papers: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    for plan in contract["plans"]:
        ordinal = int(plan["ordinal"])
        paper = {
            "ordinal": ordinal,
            "plan_id": plan["plan_id"],
            "plan_binding_digest": plan["plan_binding_digest"],
            "identity": contract["identity"],
            "kind": "paper",
            "automatic_promotion": False,
            "live_orders_enabled": False,
            "mass": False,
            "snapshot_id": logical,
            "immutable_db_digest": physical,
            "snapshot_key": physical_key,
            "snapshot_size": 32,
            "authorization_digest": authorization_digest,
            "ready_attestation_id": attestation_id,
            "fill_contract_digest": contract["fill_contract_digest"],
            "execution_mode": "am_signal_pm_close",
            "price_basis": "RAW",
            "lifecycle": "Paper",
            "feature_refs": [],
            "metrics": {
                "total_return_post_cost": 0.0,
                "max_drawdown": -0.0,
            },
            "n_equity_points": 10,
            "n_trades": 0,
            "experiment_id": f"fixture-experiment-{ordinal}",
            "run_id": f"fixture-experiment-{ordinal}",
            "strategy_spec_id": plan["strategy_spec_id"],
            "strategy_spec_version": plan["strategy_spec_version"],
            "strategy_spec_hash": plan["strategy_spec_hash"],
            "profile_digest": contract["profile_digest"],
            "plan_set_digest": contract["plan_set_digest"],
            "dependency_closure_digest": contract["dependency_closure_digest"],
            "exact_four_binding_digest": contract["exact_four_binding_digest"],
            "resolved_universe_digest": universe.resolved_membership_digest,
            "max_gross_weight_ppm": plan["max_gross_weight_ppm"],
            "requested_gross_weight": 0.0,
            "realized_gross_weight": 0.0,
            "reproducibility": {
                "data_snapshot_id": logical,
                "feature_versions": {},
                "feature_definition_hashes": {},
                "strategy_definition_hash": plan["strategy_spec_hash"],
                "execution_mode": "am_signal_pm_close",
            },
        }
        paper["semantic_digest"] = canonical_json_digest(paper)
        papers.append(paper)
        risk = {
            "ordinal": ordinal,
            "plan_id": plan["plan_id"],
            "plan_binding_digest": plan["plan_binding_digest"],
            "strategy_spec_id": plan["strategy_spec_id"],
            "strategy_spec_version": plan["strategy_spec_version"],
            "strategy_spec_hash": plan["strategy_spec_hash"],
            "identity": contract["identity"],
            "kind": "risk",
            "automatic_promotion": False,
            "live_orders_enabled": False,
            "mass": False,
            "snapshot_id": logical,
            "immutable_db_digest": physical,
            "snapshot_key": physical_key,
            "snapshot_size": 32,
            "authorization_digest": authorization_digest,
            "ready_attestation_id": attestation_id,
            "fill_contract_digest": contract["fill_contract_digest"],
            "profile_digest": contract["profile_digest"],
            "plan_set_digest": contract["plan_set_digest"],
            "dependency_closure_digest": contract["dependency_closure_digest"],
            "exact_four_binding_digest": contract["exact_four_binding_digest"],
            "paper_semantic_digest": paper["semantic_digest"],
            "status": "pass",
            "audit_id": f"fixture-audit-{ordinal}",
            "experiment_id": f"fixture-experiment-{ordinal}",
            "run_id": f"fixture-experiment-{ordinal}",
            "checks": {
                "paper_result_has_experiment_id": True,
                "paper_result_has_snapshot": True,
                "paper_result_identity_matches": True,
                "max_drawdown_within_limit": True,
            },
            "findings": [],
            "metrics": {
                "max_drawdown": 0.0,
                "max_drawdown_limit": 0.35,
                "num_trades": 0,
            },
        }
        risk["semantic_digest"] = canonical_json_digest(risk)
        risks.append(risk)
    paper_semantic_digests = [row["semantic_digest"] for row in papers]
    risk_semantic_digests = [row["semantic_digest"] for row in risks]
    semantic_child_set_digest = canonical_json_digest(
        {
            "paper_semantic_digests": paper_semantic_digests,
            "risk_semantic_digests": risk_semantic_digests,
        }
    )
    selection = {
        "identity": contract["identity"],
        "kind": "selection",
        "decision": "HOLD",
        "automatic_promotion": False,
        "live_orders_enabled": False,
        "mass": False,
        "fill_contract_digest": contract["fill_contract_digest"],
        "paper_semantic_digests": paper_semantic_digests,
        "risk_semantic_digests": risk_semantic_digests,
        "semantic_child_set_digest": semantic_child_set_digest,
        "snapshot_id": logical,
        "immutable_db_digest": physical,
        "snapshot_key": physical_key,
        "snapshot_size": 32,
        "authorization_digest": authorization_digest,
        "ready_attestation_id": attestation_id,
        "rule": "deterministic_hold_pending_human_approval",
        "selected": [row["plan_id"] for row in papers],
        "rejected": [],
        "decisions": [
            {
                "decision": "HOLD",
                "reason_codes": ["PENDING_HUMAN_APPROVAL"],
                "subject_id": row["plan_id"],
                "evidence": {"automatic_promotion": False},
            }
            for row in papers
        ],
        "profile_digest": contract["profile_digest"],
        "plan_set_digest": contract["plan_set_digest"],
        "dependency_closure_digest": contract["dependency_closure_digest"],
        "exact_four_binding_digest": contract["exact_four_binding_digest"],
        "resolved_universe_digest": universe.resolved_membership_digest,
    }
    selection["semantic_digest"] = canonical_json_digest(selection)
    knowledge_body = {
        "identity": contract["identity"],
        "kind": "knowledge",
        "automatic_promotion": False,
        "live_orders_enabled": False,
        "mass": False,
        "snapshot_id": logical,
        "immutable_db_digest": physical,
        "selection_decision": "HOLD",
        "fill_contract_digest": contract["fill_contract_digest"],
        "selection_semantic_digest": selection["semantic_digest"],
        "semantic_child_set_digest": semantic_child_set_digest,
        "artifact_type": "controlled_pilot_knowledge",
        "schema_version": "controlled-pilot-knowledge/v1",
        "producer_role": "knowledge",
        "profile_digest": contract["profile_digest"],
        "plan_set_digest": contract["plan_set_digest"],
        "dependency_closure_digest": contract["dependency_closure_digest"],
        "exact_four_binding_digest": contract["exact_four_binding_digest"],
        "snapshot_key": physical_key,
        "snapshot_size": 32,
        "authorization_digest": authorization_digest,
        "n_papers": 4,
        "n_selected": 4,
        "payload": {
            "identity": contract["identity"],
            "snapshot_id": logical,
            "selection_decision": "HOLD",
            "paper_experiment_ids": [row["experiment_id"] for row in papers],
            "risk_audit_ids": [row["audit_id"] for row in risks],
            "fill_contract_digest": contract["fill_contract_digest"],
            "semantic_child_set_digest": semantic_child_set_digest,
            "selection_semantic_digest": selection["semantic_digest"],
        },
    }
    knowledge_digest = canonical_json_digest(knowledge_body)
    artifacts = {
        "ok": True,
        "identity": contract["identity"],
        "ephemeral_cleaned": True,
        "papers": papers,
        "risks": risks,
        "selection": selection,
        "knowledge": {
            **knowledge_body,
            "artifact_id": knowledge_digest,
            "digest": knowledge_digest,
            "semantic_digest": knowledge_digest,
        },
    }
    def encode(value: Any) -> bytes:
        return json.dumps(
            value, indent=2, sort_keys=True, ensure_ascii=True
        ).encode("utf-8") + b"\n"

    return {
        str(READY_FIXTURE_REL): encode(envelope),
        str(TRADER_FIXTURE_REL): encode(trader),
        str(KEYS_FIXTURE_REL): encode(keys),
        str(ARTIFACTS_FIXTURE_REL): encode(artifacts),
    }


def render_registry_raw_ts() -> bytes:
    lines = [
        "/** AUTO-GENERATED from specs registry file bytes. DO NOT HAND-EDIT.",
        " * Regenerate: python scripts/generate_controlled_pilot_v1_contract.py",
        " */",
        "",
    ]
    for name, rel in REGISTRY_FILES:
        raw = (ROOT / rel).read_bytes()
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        ints = ",".join(str(b) for b in raw)
        lines.append(f"export const {name}_RAW = Uint8Array.from([{ints}]);")
        lines.append(f'export const {name}_RAW_DIGEST = {json.dumps(digest)} as const;')
        lines.append(f"export const {name}_RAW_SIZE = {len(raw)} as const;")
        lines.append("")
    ops_pins = {
        "production": {
            "generation": PINNED_OPS_PROJECTION_REGISTRY_GENERATION,
            "prior_registry_digest": PINNED_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST,
            "body_digest": PINNED_OPS_PROJECTION_REGISTRY_BODY_DIGEST,
            "document_digest": PINNED_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST,
        },
        "staging": {
            "generation": PINNED_STAGING_OPS_PROJECTION_REGISTRY_GENERATION,
            "prior_registry_digest": PINNED_STAGING_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST,
            "body_digest": PINNED_STAGING_OPS_PROJECTION_REGISTRY_BODY_DIGEST,
            "document_digest": PINNED_STAGING_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST,
        },
    }
    lines.append(
        "export const OPS_PROJECTION_REGISTRY_PINS = "
        + json.dumps(ops_pins, sort_keys=True, separators=(",", ":"))
        + " as const;"
    )
    lines.append("")
    controlled_contract = controlled_pilot_v1_contract()
    coverage_rows = {
        str(dataset_id): dict(coverage_policy_binding(str(dataset_id)))
        for dataset_id in controlled_contract["dataset_ids"]
    }
    lines.append(
        "export const CONTROLLED_COVERAGE_POLICY_ROWS = "
        + json.dumps(coverage_rows, sort_keys=True, separators=(",", ":"))
        + " as const;"
    )
    lines.append("")
    d1_identities = {
        environment: dict(d1_resource_identity(environment))
        for environment in ("production", "staging")
    }
    lines.append(
        "export const OPS_PROJECTION_D1_IDENTITIES = "
        + json.dumps(d1_identities, sort_keys=True, separators=(",", ":"))
        + " as const;"
    )
    lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")


def plan_schema_matches_fill_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    path = ROOT / PLAN_SCHEMA_REL
    schema = json.loads(path.read_text(encoding="utf-8"))
    props = (
        schema.get("properties", {})
        .get("fill_contract", {})
        .get("properties", {})
    )
    fill = contract.get("fill_contract")
    if not isinstance(fill, dict) or not isinstance(props, dict):
        return ["experiment plan schema fill_contract is missing"]
    for key, value in fill.items():
        if props.get(key, {}).get("const") != value:
            errors.append(f"schema fill_contract.{key} drifted from controlled_pilot_v1")
    if fill.get("signal_price_dataset") != "equities_bars_daily_am":
        errors.append("schema/contract signal_price_dataset is not equities_bars_daily_am")
    return errors


def write_artifacts(*, check: bool) -> int:
    expected = {
        str(CONTRACT_REL): render_contract(),
        str(REGISTRY_RAW_TS_REL): render_registry_raw_ts(),
        **render_fixtures(),
    }
    errors: list[str] = []
    for rel, payload in expected.items():
        path = ROOT / rel
        if check:
            try:
                observed = path.read_bytes()
            except OSError:
                errors.append(f"missing {rel}")
                continue
            if observed != payload:
                errors.append(f"drift {rel}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    schema_errors = plan_schema_matches_fill_contract(controlled_pilot_v1_contract())
    errors.extend(schema_errors)
    if check and errors:
        print("FAIL controlled_pilot_v1 generated artifacts:", file=sys.stderr)
        for item in errors:
            print(f" - {item}", file=sys.stderr)
        print(
            "Regenerate: python scripts/generate_controlled_pilot_v1_contract.py",
            file=sys.stderr,
        )
        return 1
    if check:
        print("OK controlled_pilot_v1 contract and Python-signed fixtures")
        return 0
    for rel in expected:
        print(f"wrote {rel}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail closed unless generated artifacts match the compiler",
    )
    args = parser.parse_args()
    return write_artifacts(check=bool(args.check))


if __name__ == "__main__":
    raise SystemExit(main())
