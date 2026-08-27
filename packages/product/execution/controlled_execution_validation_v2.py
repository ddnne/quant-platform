"""Independent WebAuthn handoff and bounded exact-four output validation."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from execution.exact_four_binding import load_exact_four_execution_binding
from execution.exact_four_codec import (
    ExactFourAuthorityContractError,
    _canonical_bytes,
    _parsed_timestamp,
    _strict_json_loads,
    canonical_authority_digest,
)
from execution.exact_four_trader_v2 import (
    _decode_canonical_base64url,
    _require_content_digest,
    _validate_webauthn_bytes,
    derive_exact_four_trader_one_use_key_v2,
    parse_and_validate_unverified_exact_four_trader_approval_subject_v2,
)
from execution.exact_four_results import (
    AggregateSelectionEvidenceV2,
    ExactFourPilotResultManifestV2,
    KnowledgeArtifactEvidenceV2,
    PaperResultEvidenceV2,
    RiskResultEvidenceV2,
    _evidence_from_document,
    load_exact_four_result_schema,
)
from execution.trader_webauthn_authority_v2 import (
    TRADER_ASSERTION_FORMAT,
    TRADER_CHALLENGE_FORMAT,
    TRADER_COMMITTED_HANDOFF_FORMAT,
    TRADER_LEDGER_BACKEND,
    TRADER_LEDGER_EVENT_FORMAT,
)
from execution.controlled_execution_types_v2 import (
    ControlledExecutionWriterV2Error,
    _VerifiedBoundedExecutionOutputV2,
    _VERIFIED_EXECUTOR_OUTPUT_TOKEN,
)


CONTROLLED_WRITER_MANIFEST_FORMAT = "controlled-exact-four-artifact-manifest/v2"
CONTROLLED_WRITER_ARTIFACT_FORMAT = "controlled-exact-four-artifact/v2"
CONTROLLED_WRITER_EVENT_FORMAT = "controlled-execution-authority-event/v2"
CONTROLLED_WRITER_ISSUER = "ControlledExactFourExecutionWriter/v2"
CONTROLLED_TRADER_HANDOFF_OPERATION = (
    "controlled_execution:consume_trader_handoff"
)
CONTROLLED_TRADER_HANDOFF_PURPOSE = "exact_four_one_shot_execution"
CONTROLLED_WRITER_LIVE_STATE = (
    "PENDING_PROTECTED_CONTROLLED_EXECUTION_PRINCIPAL_KEY_STORE_AND_TRADER_PEER"
)
CONTROLLED_WRITER_ARTIFACT_TYPES = (
    "Paper",
    "Risk",
    "Selection",
    "Knowledge",
)
CONTROLLED_EXECUTION_ACTIVATION_PATH = Path(
    "/etc/quant-platform/authorities/controlled_execution/activation.json"
)

_MAX_FRAME_BYTES = 1024 * 1024
_MAX_HANDOFF_BYTES = 1024 * 1024
_MAX_CLOCK_SKEW = timedelta(seconds=5)
_REQUEST_FIELDS = frozenset(
    {"format", "request_id", "operation", "purpose", "payload"}
)
_CHALLENGE_FIELDS = frozenset(
    {
        "format",
        "environment",
        "status",
        "challenge_id",
        "challenge_base64url",
        "approval_subject_id",
        "rp_policy_generation",
        "rp_policy_digest",
        "rp_id",
        "origin",
        "user_presence_required",
        "user_verification_required",
        "issued_at",
        "expires_at",
        "one_use_key",
        "challenge_digest",
    }
)
_ASSERTION_FIELDS = frozenset(
    {
        "format",
        "environment",
        "status",
        "challenge_id",
        "challenge_digest",
        "approval_subject_id",
        "rp_policy_generation",
        "rp_policy_digest",
        "credential_id_base64url",
        "authenticator_data_base64url",
        "client_data_json_base64url",
        "signature_base64url",
        "rp_id",
        "origin",
        "user_present",
        "user_verified",
        "sign_count",
        "asserted_at",
        "one_use_key",
        "assertion_digest",
    }
)
_CREDENTIAL_EVIDENCE_FIELDS = frozenset(
    {
        "format",
        "environment",
        "credential_id_base64url",
        "credential_public_key_digest",
        "credential_algorithm",
        "key_backend",
        "credential_registry_generation",
        "credential_registry_digest",
        "rp_policy_digest",
        "counter_mode",
    }
)
_TRADER_EVENT_FIELDS = frozenset(
    {
        "format",
        "environment",
        "ledger_backend_id",
        "sequence",
        "event_id",
        "prior_event_digest",
        "request_digest",
        "approval_subject_id",
        "challenge_id",
        "challenge_digest",
        "assertion_digest",
        "one_use_key",
        "one_use_prior_status",
        "one_use_result_status",
        "one_use_cas_status",
        "credential_id_base64url",
        "credential_registry_generation",
        "credential_registry_digest",
        "counter_mode",
        "prior_sign_count",
        "asserted_sign_count",
        "result_sign_count",
        "counter_cas_status",
        "transaction_status",
        "committed_at",
        "automatic_promotion",
        "mass_research_enabled",
        "live_trading_enabled",
        "event_digest",
    }
)
_HANDOFF_FIELDS = frozenset(
    {
        "format",
        "environment",
        "handoff_status",
        "ready_authority_response_digest",
        "approval_subject_id",
        "approval_subject",
        "challenge_evidence",
        "assertion_evidence",
        "credential_registry_evidence",
        "one_use_counter_event",
        "issued_at",
        "expires_at",
        "automatic_promotion",
        "mass_research_enabled",
        "live_trading_enabled",
        "handoff_id",
    }
)


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _require_digest(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ControlledExecutionWriterV2Error(
            f"{label} must be a canonical sha256 digest"
        )
    return value


def _require_uuid4(value: Any, label: str) -> str:
    if type(value) is not str:
        raise ControlledExecutionWriterV2Error(f"{label} must be canonical UUID4")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ControlledExecutionWriterV2Error(
            f"{label} must be canonical UUID4"
        ) from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ControlledExecutionWriterV2Error(f"{label} must be canonical UUID4")
    return value


def _require_bytes(value: Any, label: str) -> bytes:
    if type(value) is not bytes or not value:
        raise ControlledExecutionWriterV2Error(
            f"{label} must be exact non-empty bytes"
        )
    return value


def _aware_utc(clock: Callable[[], datetime], label: str) -> datetime:
    value = clock()
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ControlledExecutionWriterV2Error(
            f"{label} must return an exact aware datetime"
        )
    return value.astimezone(timezone.utc)


class ControlledExecutionEvidenceValidatorV2:
    """Validation mixin with no persistence or transport responsibilities."""

    def _verify_handoff(
        self,
        handoff_bytes: bytes,
        *,
        expected_handoff_id: str,
    ) -> dict[str, Any]:
        document = _strict_json_loads(
            handoff_bytes,
            label="committed exact-four Trader handoff",
        )
        if set(document) != set(_HANDOFF_FIELDS):
            raise ControlledExecutionWriterV2Error(
                "Trader committed handoff fields are not closed"
            )
        body = dict(document)
        declared_handoff_id = body.pop("handoff_id", None)
        if (
            document.get("format") != TRADER_COMMITTED_HANDOFF_FORMAT
            or document.get("environment") != self.environment
            or document.get("handoff_status") != "COMMITTED"
            or declared_handoff_id != expected_handoff_id
            or declared_handoff_id != canonical_authority_digest(body)
            or document.get("automatic_promotion") is not False
            or document.get("mass_research_enabled") is not False
            or document.get("live_trading_enabled") is not False
        ):
            raise ControlledExecutionWriterV2Error(
                "Trader committed handoff identity or policy is invalid"
            )
        _require_digest(
            document["ready_authority_response_digest"],
            "READY authority response digest",
        )

        subject_document = document["approval_subject"]
        if type(subject_document) is not dict:
            raise ControlledExecutionWriterV2Error(
                "Trader approval subject must be an exact object"
            )
        subject = parse_and_validate_unverified_exact_four_trader_approval_subject_v2(
            _canonical_bytes(subject_document)
        )
        if (
            document["approval_subject_id"] != subject.approval_subject_id
            or subject_document != subject.to_dict()
            or subject.environment != self.environment
        ):
            raise ControlledExecutionWriterV2Error(
                "Trader handoff approval subject content id is invalid"
            )

        challenge = document["challenge_evidence"]
        assertion = document["assertion_evidence"]
        credential_evidence = document["credential_registry_evidence"]
        event = document["one_use_counter_event"]
        if (
            type(challenge) is not dict
            or set(challenge) != set(_CHALLENGE_FIELDS)
            or type(assertion) is not dict
            or set(assertion) != set(_ASSERTION_FIELDS)
            or type(credential_evidence) is not dict
            or set(credential_evidence) != set(_CREDENTIAL_EVIDENCE_FIELDS)
            or type(event) is not dict
            or set(event) != set(_TRADER_EVENT_FIELDS)
        ):
            raise ControlledExecutionWriterV2Error(
                "Trader handoff nested evidence fields are not closed"
            )
        challenge_digest = _require_content_digest(
            challenge,
            digest_field="challenge_digest",
            label="Controlled-reverified WebAuthn challenge",
        )
        assertion_digest = _require_content_digest(
            assertion,
            digest_field="assertion_digest",
            label="Controlled-reverified WebAuthn assertion",
        )
        event_digest = _require_content_digest(
            event,
            digest_field="event_digest",
            label="Controlled-reverified Trader event",
        )
        if (
            challenge["format"] != TRADER_CHALLENGE_FORMAT
            or challenge["status"] != "ISSUED"
            or challenge["environment"] != self.environment
            or challenge["approval_subject_id"] != subject.approval_subject_id
            or challenge["user_presence_required"] is not True
            or challenge["user_verification_required"] is not True
        ):
            raise ControlledExecutionWriterV2Error(
                "Controlled-reverified WebAuthn challenge identity is invalid"
            )
        challenge_body = dict(challenge)
        challenge_body.pop("challenge_digest")
        one_use_key = challenge_body.pop("one_use_key")
        if one_use_key != derive_exact_four_trader_one_use_key_v2(challenge_body):
            raise ControlledExecutionWriterV2Error(
                "Controlled-reverified challenge one-use key is invalid"
            )

        rp = self._rps.require(self.environment)
        if (
            challenge["rp_policy_generation"] != rp.policy_generation
            or challenge["rp_policy_digest"] != rp.policy_digest
            or challenge["rp_id"] != rp.rp_id
            or challenge["origin"] != rp.origin
        ):
            raise ControlledExecutionWriterV2Error(
                "Trader challenge is not bound to Controlled's governed RP registry"
            )
        if assertion["format"] != TRADER_ASSERTION_FORMAT or assertion[
            "status"
        ] != "VERIFIED":
            raise ControlledExecutionWriterV2Error(
                "Controlled-reverified WebAuthn assertion identity is invalid"
            )
        for field in (
            "environment",
            "challenge_id",
            "approval_subject_id",
            "rp_policy_generation",
            "rp_policy_digest",
            "rp_id",
            "origin",
            "one_use_key",
        ):
            if assertion[field] != challenge[field]:
                raise ControlledExecutionWriterV2Error(
                    f"Controlled-reverified assertion {field} is not challenge-bound"
                )
        if assertion["challenge_digest"] != challenge_digest:
            raise ControlledExecutionWriterV2Error(
                "Controlled-reverified assertion challenge digest mismatch"
            )
        _validate_webauthn_bytes(challenge, assertion)

        credential = self._credentials.require(
            self.environment,
            assertion["credential_id_base64url"],
        )
        if (
            credential_evidence["format"]
            != "exact-four-trader-credential-evidence/v2"
            or credential_evidence["environment"] != self.environment
            or credential_evidence["credential_id_base64url"]
            != credential.credential_id_base64url
            or credential_evidence["credential_public_key_digest"]
            != credential.public_key_digest
            or credential_evidence["credential_algorithm"] != credential.algorithm
            or credential_evidence["key_backend"] != credential.key_backend
            or credential_evidence["credential_registry_generation"]
            != self._credentials.generation
            or credential_evidence["credential_registry_digest"]
            != self._credentials.registry_digest
            or credential_evidence["rp_policy_digest"] != credential.rp_policy_digest
            or credential_evidence["counter_mode"] != credential.counter_mode
        ):
            raise ControlledExecutionWriterV2Error(
                "Trader credential evidence is not bound to Controlled's public registry"
            )
        authenticator_data = _decode_canonical_base64url(
            assertion["authenticator_data_base64url"],
            label="Controlled authenticatorData",
            minimum_bytes=37,
            maximum_bytes=4096,
        )
        client_data = _decode_canonical_base64url(
            assertion["client_data_json_base64url"],
            label="Controlled clientDataJSON",
            minimum_bytes=32,
            maximum_bytes=8192,
        )
        signature = _decode_canonical_base64url(
            assertion["signature_base64url"],
            label="Controlled WebAuthn signature",
            minimum_bytes=32,
            maximum_bytes=1024,
        )
        try:
            credential.public_key.verify(
                signature,
                authenticator_data + hashlib.sha256(client_data).digest(),
                ec.ECDSA(hashes.SHA256()),
            )
        except (InvalidSignature, ValueError) as exc:
            raise ControlledExecutionWriterV2Error(
                "Controlled WebAuthn ES256 signature revalidation failed"
            ) from exc

        request_body = {
            "format": "exact-four-trader-authority-request/v2",
            "environment": self.environment,
            "approval_subject_id": subject.approval_subject_id,
            "ready_authority_response_digest": document[
                "ready_authority_response_digest"
            ],
            "challenge_digest": challenge_digest,
            "assertion_digest": assertion_digest,
            "credential_registry_digest": self._credentials.registry_digest,
            "credential_public_key_digest": credential.public_key_digest,
        }
        expected_request_digest = canonical_authority_digest(request_body)
        sequence = event["sequence"]
        prior_event_digest = event["prior_event_digest"]
        if (
            event["format"] != TRADER_LEDGER_EVENT_FORMAT
            or event["environment"] != self.environment
            or event["ledger_backend_id"] != TRADER_LEDGER_BACKEND
            or type(sequence) is not int
            or sequence < 1
            or (sequence == 1 and prior_event_digest is not None)
            or (
                sequence > 1
                and _require_digest(prior_event_digest, "prior Trader event digest")
                != prior_event_digest
            )
            or event["request_digest"] != expected_request_digest
            or event["approval_subject_id"] != subject.approval_subject_id
            or event["challenge_id"] != challenge["challenge_id"]
            or event["challenge_digest"] != challenge_digest
            or event["assertion_digest"] != assertion_digest
            or event["one_use_key"] != challenge["one_use_key"]
            or event["one_use_prior_status"] != "AVAILABLE"
            or event["one_use_result_status"] != "CONSUMED"
            or event["one_use_cas_status"] != "APPLIED"
            or event["credential_id_base64url"]
            != credential.credential_id_base64url
            or event["credential_registry_generation"]
            != self._credentials.generation
            or event["credential_registry_digest"]
            != self._credentials.registry_digest
            or event["counter_mode"] != credential.counter_mode
            or event["asserted_sign_count"] != assertion["sign_count"]
            or event["result_sign_count"] != assertion["sign_count"]
            or event["transaction_status"] != "COMMITTED"
            or event["automatic_promotion"] is not False
            or event["mass_research_enabled"] is not False
            or event["live_trading_enabled"] is not False
        ):
            raise ControlledExecutionWriterV2Error(
                "Controlled-reverified Trader one-use/counter event is invalid"
            )
        _require_uuid4(event["event_id"], "Trader event_id")
        prior_count = event["prior_sign_count"]
        asserted_count = event["asserted_sign_count"]
        if (
            type(prior_count) is not int
            or prior_count < 0
            or type(asserted_count) is not int
            or asserted_count < 0
            or (
                credential.counter_mode == "COUNTING"
                and (
                    asserted_count <= prior_count
                    or event["counter_cas_status"] != "APPLIED"
                )
            )
            or (
                credential.counter_mode == "COUNTERLESS"
                and (
                    prior_count != 0
                    or asserted_count != 0
                    or event["counter_cas_status"] != "NOT_APPLICABLE"
                )
            )
        ):
            raise ControlledExecutionWriterV2Error(
                "Controlled-reverified WebAuthn counter transition is invalid"
            )

        now = _aware_utc(self._clock, "Controlled authority clock")
        challenge_issued = _parsed_timestamp(
            challenge["issued_at"], "Controlled challenge issued_at"
        ).astimezone(timezone.utc)
        challenge_expires = _parsed_timestamp(
            challenge["expires_at"], "Controlled challenge expires_at"
        ).astimezone(timezone.utc)
        asserted_at = _parsed_timestamp(
            assertion["asserted_at"], "Controlled assertion asserted_at"
        ).astimezone(timezone.utc)
        committed_at = _parsed_timestamp(
            event["committed_at"], "Controlled Trader event committed_at"
        ).astimezone(timezone.utc)
        handoff_issued = _parsed_timestamp(
            document["issued_at"], "Controlled handoff issued_at"
        ).astimezone(timezone.utc)
        handoff_expires = _parsed_timestamp(
            document["expires_at"], "Controlled handoff expires_at"
        ).astimezone(timezone.utc)
        ready_issued = _parsed_timestamp(
            subject.ready_issued_at, "Controlled READY issued_at"
        ).astimezone(timezone.utc)
        ready_expires = _parsed_timestamp(
            subject.ready_expires_at, "Controlled READY expires_at"
        ).astimezone(timezone.utc)
        credential_effective = _parsed_timestamp(
            credential.effective_at, "Controlled credential effective_at"
        ).astimezone(timezone.utc)
        rp_effective = _parsed_timestamp(
            rp.effective_at, "Controlled RP effective_at"
        ).astimezone(timezone.utc)
        if not (
            ready_issued <= challenge_issued
            and credential_effective <= asserted_at
            and rp_effective <= asserted_at
            and challenge_issued <= asserted_at <= committed_at + _MAX_CLOCK_SKEW
            and committed_at == handoff_issued
            and handoff_expires == challenge_expires
            and challenge_expires <= ready_expires
            and committed_at <= now + _MAX_CLOCK_SKEW
            and now < handoff_expires
        ):
            raise ControlledExecutionWriterV2Error(
                "Controlled-reverified Trader handoff is outside its authority window"
            )
        document["_controlled_event_digest"] = event_digest
        return document

    @staticmethod
    def _content_digest(content: bytes) -> str:
        return _sha256_bytes(content)

    def _execution_context(
        self,
        handoff: Mapping[str, Any],
        *,
        canonical_handoff: bytes,
    ) -> dict[str, Any]:
        binding = load_exact_four_execution_binding()
        request_id = canonical_authority_digest(
            {
                "format": "controlled-exact-four-execution-request/v2",
                "environment": self.environment,
                "handoff_id": handoff["handoff_id"],
                "approval_subject_id": handoff["approval_subject_id"],
                "exact_four_binding_digest": binding.binding_digest,
            }
        )
        lease_id = canonical_authority_digest(
            {
                "format": "controlled-exact-four-execution-lease/v2",
                "environment": self.environment,
                "handoff_id": handoff["handoff_id"],
                "one_use_key": handoff["challenge_evidence"]["one_use_key"],
            }
        )
        idempotency_key = canonical_authority_digest(
            {
                "format": "controlled-exact-four-execution-idempotency/v2",
                "environment": self.environment,
                "lease_id": lease_id,
            }
        )
        subject = handoff["approval_subject"]
        return {
            "format": "bounded-controlled-pilot-execution-context/v2",
            "environment": self.environment,
            "pilot_run_id": subject["pilot_run_id"],
            "ready_environment": subject["environment"],
            "ready_authority_instance_id": subject[
                "ready_authority_instance_id"
            ],
            "ready_authority_resource_digest": subject[
                "ready_authority_resource_digest"
            ],
            "readiness_attestation_id": subject["readiness_attestation_id"],
            "trader_authorization_id": handoff["handoff_id"],
            "trader_handoff_digest": _sha256_bytes(canonical_handoff),
            "execution_request_id": request_id,
            "lease_id": lease_id,
            "idempotency_key": idempotency_key,
            "exact_four_binding_digest": binding.binding_digest,
            "controlled_pilot_policy_digest": binding.policy.policy_digest,
            "budget_scope_digest": binding.budget_scope_digest,
            "plan_set_digest": binding.plan_set_digest,
            "dependency_closure_set_digest": (
                binding.dependency_closure_set_digest
            ),
            "profile_set_digest": binding.profile_set_digest,
            "required_dataset_membership_digest": (
                binding.required_dataset_membership_digest
            ),
            "snapshot_id": subject["snapshot_id"],
            "ready_manifest_digest": subject["ready_manifest_digest"],
            "immutable_snapshot_digest": subject["immutable_snapshot_digest"],
            "execution_issued_at": handoff["issued_at"],
            "execution_expires_at": handoff["expires_at"],
            "plan_bindings": [item.to_dict() for item in binding.plan_bindings],
            "automatic_promotion": False,
            "mass_research_enabled": False,
            "live_trading_enabled": False,
        }

    def _verify_executor_output(
        self,
        raw: Mapping[str, Any],
        *,
        context: Mapping[str, Any],
    ) -> _VerifiedBoundedExecutionOutputV2:
        if type(raw) is not dict or set(raw) != {"manifest", "contents"}:
            raise ControlledExecutionWriterV2Error(
                "bounded executor output fields are not closed"
            )
        manifest_raw = raw["manifest"]
        contents_raw = raw["contents"]
        if type(manifest_raw) is not bytes or type(contents_raw) is not dict:
            raise ControlledExecutionWriterV2Error(
                "bounded executor manifest and content container types are invalid"
            )
        manifest_document = _strict_json_loads(
            manifest_raw,
            label="bounded exact-four result manifest",
        )
        try:
            from jsonschema import Draft202012Validator, FormatChecker

            errors = sorted(
                Draft202012Validator(
                    load_exact_four_result_schema(),
                    format_checker=FormatChecker(),
                ).iter_errors(manifest_document),
                key=lambda item: tuple(str(part) for part in item.path),
            )
        except ExactFourAuthorityContractError:
            raise
        except Exception as exc:
            raise ControlledExecutionWriterV2Error(
                "cannot validate bounded exact-four result schema"
            ) from exc
        if errors:
            raise ControlledExecutionWriterV2Error(
                "bounded executor result violates the canonical exact-four schema"
            )
        body = dict(manifest_document)
        declared_manifest_id = body.pop("manifest_id", None)
        paper_rows = body.pop("paper_results", None)
        risk_rows = body.pop("risk_results", None)
        selection_row = body.pop("aggregate_selection", None)
        knowledge_row = body.pop("knowledge_artifact", None)
        if type(paper_rows) is not list or type(risk_rows) is not list:
            raise ControlledExecutionWriterV2Error(
                "bounded result Paper/Risk evidence must be exact arrays"
            )
        try:
            papers = tuple(
                _evidence_from_document(PaperResultEvidenceV2, item)
                for item in paper_rows
            )
            risks = tuple(
                _evidence_from_document(RiskResultEvidenceV2, item)
                for item in risk_rows
            )
            selection = _evidence_from_document(
                AggregateSelectionEvidenceV2, selection_row
            )
            knowledge = _evidence_from_document(
                KnowledgeArtifactEvidenceV2, knowledge_row
            )
            manifest = ExactFourPilotResultManifestV2(
                paper_results=papers,
                risk_results=risks,
                aggregate_selection=selection,
                knowledge_artifact=knowledge,
                **body,
            )
        except (ExactFourAuthorityContractError, TypeError) as exc:
            raise ControlledExecutionWriterV2Error(
                "bounded executor result evidence is not canonical exact-four"
            ) from exc
        if (
            declared_manifest_id != manifest.manifest_id
            or manifest_document != manifest.to_dict()
        ):
            raise ControlledExecutionWriterV2Error(
                "bounded result manifest content id is invalid"
            )
        expected_fields = (
            "pilot_run_id",
            "readiness_attestation_id",
            "trader_authorization_id",
            "execution_request_id",
            "lease_id",
            "idempotency_key",
            "exact_four_binding_digest",
            "controlled_pilot_policy_digest",
            "budget_scope_digest",
            "plan_set_digest",
            "dependency_closure_set_digest",
            "profile_set_digest",
            "required_dataset_membership_digest",
            "snapshot_id",
            "ready_manifest_digest",
            "immutable_snapshot_digest",
            "execution_issued_at",
            "execution_expires_at",
        )
        if any(
            getattr(manifest, field) != context[field] for field in expected_fields
        ):
            raise ControlledExecutionWriterV2Error(
                "bounded result does not bind plan/profile/closure/snapshot/Trader chain"
            )
        completed = _parsed_timestamp(
            manifest.completed_at, "bounded execution completed_at"
        ).astimezone(timezone.utc)
        if completed > _aware_utc(self._clock, "bounded result clock") + _MAX_CLOCK_SKEW:
            raise ControlledExecutionWriterV2Error(
                "bounded result completion is in the future"
            )
        expected_keys = {
            *(f"Paper:{ordinal}" for ordinal in range(1, 5)),
            *(f"Risk:{ordinal}" for ordinal in range(1, 5)),
            "Selection:0",
            "Knowledge:0",
        }
        if set(contents_raw) != expected_keys:
            raise ControlledExecutionWriterV2Error(
                "bounded executor must return exact four/four/one/one contents"
            )
        contents: dict[str, bytes] = {}
        for key, value in contents_raw.items():
            contents[key] = _require_bytes(value, f"bounded executor {key}")
        if len(set(contents.values())) != 10:
            raise ControlledExecutionWriterV2Error(
                "bounded executor artifact contents must be non-duplicated"
            )
        for paper, risk in zip(papers, risks, strict=True):
            paper_digest = _sha256_bytes(contents[f"Paper:{paper.ordinal}"])
            risk_digest = _sha256_bytes(contents[f"Risk:{risk.ordinal}"])
            if (
                paper.paper_result_id != paper_digest
                or paper.paper_artifact_digest != paper_digest
                or risk.risk_result_id != risk_digest
                or risk.risk_artifact_digest != risk_digest
            ):
                raise ControlledExecutionWriterV2Error(
                    "bounded Paper/Risk content digest does not match its evidence"
                )
        selection_digest = _sha256_bytes(contents["Selection:0"])
        knowledge_digest = _sha256_bytes(contents["Knowledge:0"])
        if (
            selection.selection_result_id != selection_digest
            or selection.selection_artifact_digest != selection_digest
            or knowledge.knowledge_artifact_id != knowledge_digest
            or knowledge.knowledge_artifact_digest != knowledge_digest
        ):
            raise ControlledExecutionWriterV2Error(
                "bounded Selection/Knowledge content digest does not match evidence"
            )
        return _VerifiedBoundedExecutionOutputV2(
            manifest,
            contents,
            _token=_VERIFIED_EXECUTOR_OUTPUT_TOKEN,
        )


__all__ = ["ControlledExecutionEvidenceValidatorV2"]
