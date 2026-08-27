#!/usr/bin/env python3
"""R10/R11 handlers for the isolated local AuthorityServer runtime.

The request plane never receives a reusable positive Trader capability.  The
Trader handler performs a two-phase WebAuthn ceremony, commits the assertion in
its authority-owned ledger, then passes the committed canonical handoff to the
kernel-authenticated Controlled service as one unlinked read-only descriptor.
The Controlled handler independently verifies and reserves that handoff before
using its server-constructed budget/snapshot/provider runtime.
"""

from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from execution.controlled_execution_writer_v2 import (
    CONTROLLED_TRADER_HANDOFF_OPERATION,
    CONTROLLED_TRADER_HANDOFF_PURPOSE,
    SQLiteControlledExecutionWriterV2,
    _open_server_bound_controlled_execution_runtime_v2,
    _open_server_bound_controlled_execution_writer_v2,
)
from execution.controlled_execution_runtime_v2 import ControlledExecutionRuntimeV2
from execution.controlled_execution_quiescence_v2 import (
    ControlledWriterLifecycleLeaseV2,
    require_held_controlled_writer_lifecycle_v2,
)
from execution.exact_four_codec import (
    ExactFourAuthorityContractError,
    _canonical_bytes,
    _strict_json_loads,
    canonical_authority_digest,
)
from execution.trader_webauthn_authority_v2 import (
    ExactFourTraderWebAuthnAuthorityV2,
    IssuedExactFourTraderChallengeV2,
    _load_live_activation_document,
    _open_server_bound_exact_four_trader_authority_v2,
    verify_ready_authority_response_v2,
)
from scripts.local_authority_service import (
    REQUEST_FORMAT,
    AuthorityRequestContext,
    LocalAuthorityError,
    call_controlled_execution_with_trader_handoff,
)


TRADER_AUTHORIZE_OPERATION = "trader:authorize_exact_four_batch_human_present"
TRADER_AUTHORIZE_PURPOSE = "exact_four_human_approval"
TRADER_PHASE_ISSUE_CHALLENGE = "ISSUE_CHALLENGE"
TRADER_PHASE_VERIFY_ASSERTION = "VERIFY_ASSERTION"

_TRADER_CALLER = "controlled_pilot_orchestrator"
_CONTROLLED_CALLER = "trader"
_ISSUE_FIELDS = {"phase", "ready_response_base64"}
_VERIFY_FIELDS = {
    "phase",
    "ready_response_base64",
    "challenge",
    "assertion_base64",
}


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _decode_canonical_base64(value: object, *, field: str) -> bytes:
    if type(value) is not str or not value:
        raise LocalAuthorityError(f"{field} must be non-empty base64 text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (TypeError, ValueError) as exc:
        raise LocalAuthorityError(f"{field} is invalid base64") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise LocalAuthorityError(f"{field} is not canonical base64")
    return decoded


def _require_server_context(
    context: AuthorityRequestContext,
    *,
    caller: str,
    operation: str,
    purpose: str,
    environment: str,
) -> None:
    if (
        type(context) is not AuthorityRequestContext
        or context.caller != caller
        or context.grant.caller != caller
        or context.grant.operation != operation
        or context.grant.purpose != purpose
        or context.grant.environment != environment
    ):
        raise LocalAuthorityError(
            "execution handler lacks the exact server-authenticated method context"
        )


def _require_context_request_digest(
    context: AuthorityRequestContext,
    payload: Mapping[str, Any],
) -> None:
    request = {
        "format": REQUEST_FORMAT,
        "request_id": context.request_id,
        "operation": context.grant.operation,
        "purpose": context.grant.purpose,
        "payload": dict(payload),
    }
    if canonical_authority_digest(request) != context.request_digest:
        raise LocalAuthorityError(
            "execution handler request differs from the authenticated frame"
        )


class TraderAuthorizeExactFourBatchHumanPresentV2:
    """Two-phase WebAuthn handler; only phase two can reach Controlled."""

    operation = TRADER_AUTHORIZE_OPERATION

    def __init__(
        self,
        *,
        authority: ExactFourTraderWebAuthnAuthorityV2,
        controlled_socket_path: str | Path,
        controlled_execution_uid: int,
    ) -> None:
        path = Path(controlled_socket_path)
        if (
            type(authority) is not ExactFourTraderWebAuthnAuthorityV2
            or not path.is_absolute()
            or type(controlled_execution_uid) is not int
            or controlled_execution_uid <= 0
            or authority._controlled_execution_uid != controlled_execution_uid
        ):
            raise LocalAuthorityError("Trader handler endpoint configuration is invalid")
        self.authority = authority
        self.controlled_socket_path = path
        self.controlled_execution_uid = controlled_execution_uid

    def __call__(
        self,
        context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
    ) -> Mapping[str, Any]:
        _require_server_context(
            context,
            caller=_TRADER_CALLER,
            operation=self.operation,
            purpose=TRADER_AUTHORIZE_PURPOSE,
            environment=self.authority.environment,
        )
        _require_context_request_digest(context, payload)
        if fds:
            raise LocalAuthorityError("Trader WebAuthn operation accepts no descriptor")
        phase = payload.get("phase")
        try:
            if phase == TRADER_PHASE_ISSUE_CHALLENGE:
                if set(payload) != _ISSUE_FIELDS:
                    raise LocalAuthorityError(
                        "Trader challenge payload fields are not closed"
                    )
                ready_raw = _decode_canonical_base64(
                    payload["ready_response_base64"],
                    field="READY response",
                )
                readiness = verify_ready_authority_response_v2(
                    ready_raw,
                    expected_environment=self.authority.environment,
                )
                challenge = self.authority.issue_challenge(readiness)
                return {
                    "status": "CHALLENGE_ISSUED",
                    "phase": TRADER_PHASE_ISSUE_CHALLENGE,
                    "challenge": challenge.to_dict(),
                    "ready_authority_response_digest": readiness.response_digest,
                    "human_presence_still_required": True,
                    "controlled_execution_started": False,
                }
            if phase != TRADER_PHASE_VERIFY_ASSERTION or set(payload) != _VERIFY_FIELDS:
                raise LocalAuthorityError(
                    "Trader WebAuthn phase or payload fields are invalid"
                )
            ready_raw = _decode_canonical_base64(
                payload["ready_response_base64"],
                field="READY response",
            )
            assertion_raw = _decode_canonical_base64(
                payload["assertion_base64"],
                field="WebAuthn assertion",
            )
            # Require the external ceremony to return the exact canonical
            # assertion bytes that the challenge/event digests bind.
            assertion_document = _strict_json_loads(
                assertion_raw,
                label="Trader WebAuthn assertion",
            )
            if _canonical_bytes(assertion_document) != assertion_raw:
                raise LocalAuthorityError(
                    "WebAuthn assertion bytes are not canonical JSON"
                )
            challenge_document = payload["challenge"]
            if type(challenge_document) is not dict:
                raise LocalAuthorityError("Trader challenge must be one exact object")
            readiness = verify_ready_authority_response_v2(
                ready_raw,
                expected_environment=self.authority.environment,
            )
            challenge = IssuedExactFourTraderChallengeV2.from_document(
                challenge_document
            )
            handoff = self.authority.authorize(
                readiness=readiness,
                challenge=challenge,
                assertion_raw=assertion_raw,
            )
            descriptor = self.authority.open_handoff_descriptor(handoff)
            try:
                controlled_request = {
                    "format": REQUEST_FORMAT,
                    "request_id": handoff.handoff_id,
                    "operation": CONTROLLED_TRADER_HANDOFF_OPERATION,
                    "purpose": CONTROLLED_TRADER_HANDOFF_PURPOSE,
                    "payload": {
                        "handoff_id": handoff.handoff_id,
                        "handoff_digest": _sha256_bytes(handoff.canonical_bytes),
                    },
                }
                controlled = dict(
                    call_controlled_execution_with_trader_handoff(
                        self.controlled_socket_path,
                        controlled_request,
                        expected_server_uid=self.controlled_execution_uid,
                        unlinked_read_only_fd=descriptor,
                    )
                )
            finally:
                os.close(descriptor)
            if (
                controlled.get("status") != "CONTROLLED_ARTIFACTS_COMMITTED"
                or controlled.get("handoff_id") != handoff.handoff_id
                or controlled.get("one_shot") is not True
                or controlled.get("automatic_promotion") is not False
                or controlled.get("mass_research_enabled") is not False
                or controlled.get("live_trading_enabled") is not False
            ):
                raise LocalAuthorityError(
                    "Controlled service returned an invalid commit acknowledgement"
                )
            return {
                "status": "CONTROLLED_EXECUTION_COMMITTED",
                "phase": TRADER_PHASE_VERIFY_ASSERTION,
                "handoff_id": handoff.handoff_id,
                "handoff_digest": _sha256_bytes(handoff.canonical_bytes),
                "controlled_result": controlled,
                "controlled_result_digest": canonical_authority_digest(controlled),
                "reusable_trader_capability_returned": False,
                "automatic_promotion": False,
                "mass_research_enabled": False,
                "live_trading_enabled": False,
            }
        except LocalAuthorityError:
            raise
        except (ExactFourAuthorityContractError, OSError) as exc:
            raise LocalAuthorityError("Trader WebAuthn operation rejected") from exc


class ControlledExecutionConsumeTraderHandoffV2:
    """AuthorityServer-only bridge into the one-call Controlled writer."""

    operation = CONTROLLED_TRADER_HANDOFF_OPERATION

    def __init__(
        self,
        *,
        writer: SQLiteControlledExecutionWriterV2,
        execution_runtime: ControlledExecutionRuntimeV2,
    ) -> None:
        if (
            type(writer) is not SQLiteControlledExecutionWriterV2
            or not (
                (
                    writer._test_mode is False
                    and type(execution_runtime) is ControlledExecutionRuntimeV2
                    and execution_runtime._production_bound is True
                )
                or (
                    writer._test_mode is True
                    and isinstance(
                        execution_runtime, ControlledExecutionRuntimeV2
                    )
                )
            )
        ):
            raise LocalAuthorityError("Controlled handler configuration is invalid")
        self.writer = writer
        self._execution_runtime = execution_runtime

    def __call__(
        self,
        context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
    ) -> Mapping[str, Any]:
        _require_server_context(
            context,
            caller=_CONTROLLED_CALLER,
            operation=self.operation,
            purpose=CONTROLLED_TRADER_HANDOFF_PURPOSE,
            environment=self.writer.environment,
        )
        _require_context_request_digest(context, payload)
        try:
            written = self.writer.consume_authority_server_handoff(
                context,
                payload,
                fds,
                self._execution_runtime,
            )
        except LocalAuthorityError:
            raise
        except Exception as exc:
            # The writer has already recorded FAILED/DENY when execution began.
            # Convert domain failures into the server's closed rejection shape.
            raise LocalAuthorityError("Controlled handoff execution rejected") from exc
        manifest = written.to_dict()
        content_digests = {
            name: _sha256_bytes(content)
            for name, content in sorted(written.contents.items())
        }
        if len(content_digests) != 10:
            raise LocalAuthorityError("Controlled writer returned an incomplete bundle")
        return {
            "status": "CONTROLLED_ARTIFACTS_COMMITTED",
            "handoff_id": manifest["handoff_id"],
            "manifest_id": manifest["manifest_id"],
            "manifest_digest": _sha256_bytes(written.canonical_manifest),
            "controlled_event_digest": manifest["controlled_event_digest"],
            "writer_key_id": manifest["writer_key_id"],
            "artifact_count": len(content_digests),
            "artifact_content_digests": content_digests,
            "one_shot": True,
            "automatic_promotion": False,
            "mass_research_enabled": False,
            "live_trading_enabled": False,
        }


def open_live_trader_authority_handler_v2(
) -> TraderAuthorizeExactFourBatchHumanPresentV2:
    """Build the positive Trader handler only for UnixAuthorityService."""

    activation = _load_live_activation_document()
    authority = _open_server_bound_exact_four_trader_authority_v2()
    return TraderAuthorizeExactFourBatchHumanPresentV2(
        authority=authority,
        controlled_socket_path=activation["controlled_execution_socket_path"],
        controlled_execution_uid=activation["controlled_execution_uid"],
    )


def open_live_controlled_execution_handler_v2(
    *, lifecycle: ControlledWriterLifecycleLeaseV2 | None = None
) -> ControlledExecutionConsumeTraderHandoffV2:
    """Build the positive Controlled handler only for UnixAuthorityService."""

    require_held_controlled_writer_lifecycle_v2(
        lifecycle,
        expected_environment=None,
    )
    writer = _open_server_bound_controlled_execution_writer_v2(
        lifecycle=lifecycle
    )
    require_held_controlled_writer_lifecycle_v2(
        lifecycle,
        expected_environment=writer.environment,
        expected_store_path=writer._path,
    )
    execution_runtime = _open_server_bound_controlled_execution_runtime_v2(
        lifecycle=lifecycle
    )
    require_held_controlled_writer_lifecycle_v2(
        lifecycle,
        expected_environment=writer.environment,
        expected_store_path=writer._path,
    )
    if execution_runtime._environment != writer.environment:
        raise ExactFourAuthorityContractError(
            "Controlled writer and runtime environments differ"
        )
    return ControlledExecutionConsumeTraderHandoffV2(
        writer=writer,
        execution_runtime=execution_runtime,
    )


__all__ = [
    "TRADER_AUTHORIZE_OPERATION",
    "TRADER_AUTHORIZE_PURPOSE",
    "TRADER_PHASE_ISSUE_CHALLENGE",
    "TRADER_PHASE_VERIFY_ASSERTION",
    "ControlledExecutionConsumeTraderHandoffV2",
    "TraderAuthorizeExactFourBatchHumanPresentV2",
    "open_live_controlled_execution_handler_v2",
    "open_live_trader_authority_handler_v2",
]
