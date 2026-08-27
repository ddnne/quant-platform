"""Behavior tests for sealed snapshot/provider and persistent budget runtime."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest

from execution.controlled_execution_budget_v2 import (
    ControlledBudgetLedgerV2Error,
    ControlledPersistentBudgetLedgerV2,
)
from execution.exact_four_codec import canonical_authority_digest
from execution.controlled_execution_runtime_v2 import (
    CONTROLLED_PROVIDER_USAGE_FORMAT,
    ControlledExecutionProviderV2,
    ControlledExecutionRuntimeV2Error,
    ControlledProviderTimeoutV2,
    _build_server_controlled_execution_runtime_v2,
    _build_test_controlled_execution_runtime_v2,
    open_pinned_controlled_snapshot_v2,
)
from research.readiness import derive_ready_authority_resource_digest
from selection.budget_ledger import ResearchBudgetCapability
from selection.screen import OfflineExperimentBudget


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


class _RecordingProvider(ControlledExecutionProviderV2):
    def __init__(self, *, failure: BaseException | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.failure = failure

    def execute_bytes(
        self,
        request: bytes,
        *,
        snapshot_fd: int,
        projection_fd: int,
    ) -> Mapping[str, Any]:
        assert snapshot_fd >= 0
        assert projection_fd >= 0
        self.calls.append(json.loads(request))
        if self.failure is not None:
            raise self.failure
        manifest = b'{"provider":"test"}'
        contents = {
                **{f"Paper:{ordinal}": f"paper-{ordinal}".encode() for ordinal in range(1, 5)},
                **{f"Risk:{ordinal}": f"risk-{ordinal}".encode() for ordinal in range(1, 5)},
                "Selection:0": b"selection",
                "Knowledge:0": b"knowledge",
        }
        context = self.calls[-1]["context"]
        usage_body = {
            "format": CONTROLLED_PROVIDER_USAGE_FORMAT,
            "environment": context["environment"],
            "budget_id": context["budget_id"],
            "reservation_id": context["budget_reservation_id"],
            "idempotency_key": context["idempotency_key"],
            "snapshot_digest": context["immutable_snapshot_digest"],
            "projection_digest": context["projection_document_digest"],
            "manifest_digest": _digest(manifest),
            "contents_digest": canonical_authority_digest(
                {key: _digest(value) for key, value in contents.items()}
            ),
            "generations": 1,
            "model_calls": 3,
            "input_tokens": 101,
            "output_tokens": 29,
            "cached_tokens": 7,
            "paper_runs": 4,
            "compute_time_ms": 1234,
            "estimated_cost_micros": 4321,
        }
        return {
            "manifest": manifest,
            "contents": contents,
            "usage": {
                **usage_body,
                "usage_digest": canonical_authority_digest(usage_body),
            },
        }


def _system(
    tmp_path: Path,
    *,
    provider: ControlledExecutionProviderV2 | None = None,
) -> tuple[Any, ControlledPersistentBudgetLedgerV2, dict[str, Any], _RecordingProvider]:
    snapshot_raw = b"immutable-controlled-snapshot\n"
    projection_raw = b'{"format":"signed-projection-test/v1"}\n'
    snapshot_path = (tmp_path / "snapshot.sqlite3").resolve()
    projection_path = (tmp_path / "projection.json").resolve()
    snapshot_path.write_bytes(snapshot_raw)
    projection_path.write_bytes(projection_raw)
    snapshot_path.chmod(0o400)
    projection_path.chmod(0o400)
    snapshot = open_pinned_controlled_snapshot_v2(
        snapshot_path=str(snapshot_path),
        projection_path=str(projection_path),
    )
    now = datetime.now(timezone.utc)
    budget = ResearchBudgetCapability(
        budget_id="controlled-exact-four-test-budget",
        ledger_path=(tmp_path / "budget.sqlite3").resolve(),
        limits=OfflineExperimentBudget(),
    )
    ledger = ControlledPersistentBudgetLedgerV2(
        budget=budget,
        environment="staging",
        clock=lambda: now,
    )
    actual_provider = provider or _RecordingProvider()
    runtime = _build_test_controlled_execution_runtime_v2(
        environment="staging",
        provider=actual_provider,
        budget=ledger,
        snapshot=snapshot,
    )
    snapshot_id = _digest(b"snapshot-id")
    ready_manifest_digest = _digest(b"ready-manifest")
    context = {
        "format": "bounded-controlled-pilot-execution-context/v2",
        "environment": "staging",
        "ready_environment": "staging",
        "ready_authority_instance_id": "ready-authority/staging/v1",
        "ready_authority_resource_digest": derive_ready_authority_resource_digest(
            environment="staging",
            authority_instance_id="ready-authority/staging/v1",
            snapshot_id=snapshot_id,
            immutable_db_digest=_digest(snapshot_raw),
            ready_manifest_digest=ready_manifest_digest,
            signed_projection_document_digest=_digest(projection_raw),
        ),
        "snapshot_id": snapshot_id,
        "immutable_snapshot_digest": _digest(snapshot_raw),
        "ready_manifest_digest": ready_manifest_digest,
        "trader_authorization_id": _digest(b"trader-handoff"),
        "idempotency_key": _digest(b"provider-idempotency"),
        "lease_id": _digest(b"untrusted-pre-reservation-lease"),
    }
    assert isinstance(actual_provider, _RecordingProvider)
    return runtime, ledger, context, actual_provider


def test_provider_call_occurs_only_after_persistent_reservation_and_fd_binding(
    tmp_path: Path,
) -> None:
    runtime, ledger, context, provider = _system(tmp_path)
    attempt = runtime.begin(context)
    assert ledger.state(attempt.reservation_id) == "RESERVED"
    assert provider.calls == []
    output = attempt.invoke()
    assert ledger.state(attempt.reservation_id) == "EXECUTING"
    assert len(provider.calls) == 1
    provider_context = provider.calls[0]["context"]
    assert provider_context["budget_reservation_id"] == attempt.reservation_id
    assert provider_context["lease_id"] != context["lease_id"]
    assert provider_context["snapshot_handle"] == "SCM_RIGHTS:0"
    assert provider_context["projection_handle"] == "SCM_RIGHTS:1"
    assert type(output["manifest"]) is bytes
    assert all(type(value) is bytes for value in output["contents"].values())
    attempt.settle(outcome="success")
    assert ledger.state(attempt.reservation_id) == "SUCCEEDED"
    settlement = ledger.settlement(attempt.reservation_id)
    assert settlement is not None
    assert settlement["usage_source"] == "verified_provider_evidence"
    assert settlement["charged"] == {
        "generations": 1,
        "model_calls": 3,
        "input_tokens": 101,
        "output_tokens": 29,
        "cached_tokens": 7,
        "paper_runs": 4,
        "compute_time_ms": 1234,
        "estimated_cost_micros": 4321,
    }
    assert settlement["usage_evidence_digest"].startswith("sha256:")


def test_production_runtime_rejects_in_process_provider_substitution(
    tmp_path: Path,
) -> None:
    runtime, ledger, _context, provider = _system(tmp_path)
    with pytest.raises(
        ControlledExecutionRuntimeV2Error,
        match="server-constructed components",
    ):
        _build_server_controlled_execution_runtime_v2(
            environment="staging",
            provider=provider,
            budget=ledger,
            snapshot=runtime._snapshot,
        )


@pytest.mark.parametrize(
    ("failure", "outcome"),
    (
        (ControlledExecutionRuntimeV2Error("provider failed"), "provider_error"),
        (ControlledProviderTimeoutV2("provider timed out"), "timeout"),
    ),
)
def test_provider_failure_and_timeout_are_finally_settled(
    tmp_path: Path,
    failure: BaseException,
    outcome: str,
) -> None:
    provider = _RecordingProvider(failure=failure)
    runtime, ledger, context, _ = _system(tmp_path, provider=provider)
    attempt = runtime.begin(context)
    with pytest.raises(type(failure)):
        attempt.invoke()
    attempt.settle(outcome=outcome, error=failure)
    assert ledger.state(attempt.reservation_id) == "FAILED"
    settlement = ledger.settlement(attempt.reservation_id)
    assert settlement is not None
    assert settlement["usage_source"] == "reserved_estimate"
    assert len(provider.calls) == 1


def test_schema_reject_is_charged_and_settled_once(tmp_path: Path) -> None:
    runtime, ledger, context, provider = _system(tmp_path)
    attempt = runtime.begin(context)
    attempt.invoke()
    error = ValueError("canonical output schema rejected")
    attempt.settle(outcome="schema_reject", error=error)
    assert ledger.state(attempt.reservation_id) == "FAILED"
    # The durable ledger settlement is idempotent and cannot charge twice.
    ledger.settle(
        attempt._reservation,
        outcome="schema_reject",
        error_class=type(error).__name__,
    )
    with pytest.raises(ControlledExecutionRuntimeV2Error, match="already settled"):
        attempt.settle(outcome="schema_reject", error=error)
    assert len(provider.calls) == 1


def test_unsettled_post_provider_state_recovers_without_retry(tmp_path: Path) -> None:
    runtime, ledger, context, provider = _system(tmp_path)
    attempt = runtime.begin(context)
    attempt.invoke()
    assert ledger.state(attempt.reservation_id) == "EXECUTING"
    assert ledger.recover_unfinished() == 1
    assert ledger.state(attempt.reservation_id) == "RECOVERY_REQUIRED"
    with pytest.raises(ControlledBudgetLedgerV2Error, match="recovery"):
        runtime.begin({**context, "idempotency_key": _digest(b"second")})
    assert len(provider.calls) == 1
    ledger.settle_recovery_required(attempt.reservation_id)
    assert ledger.state(attempt.reservation_id) == "FAILED"
    assert len(provider.calls) == 1


@pytest.mark.parametrize("attack", ["snapshot", "resource", "environment"])
def test_snapshot_or_ready_resource_mismatch_rejects_before_reservation_and_provider(
    tmp_path: Path,
    attack: str,
) -> None:
    runtime, ledger, context, provider = _system(tmp_path)
    attacked = dict(context)
    if attack == "snapshot":
        attacked["immutable_snapshot_digest"] = _digest(b"wrong snapshot")
    elif attack == "resource":
        attacked["ready_authority_resource_digest"] = _digest(b"wrong resource")
    else:
        attacked["ready_environment"] = "production"
        attacked["ready_authority_instance_id"] = "ready-authority/production/v1"
    with pytest.raises(ControlledExecutionRuntimeV2Error):
        runtime.begin(attacked)
    assert provider.calls == []
    assert ledger.state(_digest(b"absent")) is None


def test_duplicate_idempotency_cannot_create_second_reservation(tmp_path: Path) -> None:
    runtime, ledger, context, provider = _system(tmp_path)
    first = runtime.begin(context)
    with pytest.raises(ControlledBudgetLedgerV2Error, match="already consumed"):
        runtime.begin(context)
    first.settle(outcome="commit_error", error=RuntimeError("before provider"))
    assert ledger.state(first.reservation_id) == "FAILED"
    assert provider.calls == []


class _InvalidUsageProvider(_RecordingProvider):
    def __init__(self, *, exceed: bool) -> None:
        super().__init__()
        self._exceed = exceed

    def execute_bytes(
        self,
        request: bytes,
        *,
        snapshot_fd: int,
        projection_fd: int,
    ) -> Mapping[str, Any]:
        output = dict(
            super().execute_bytes(
                request,
                snapshot_fd=snapshot_fd,
                projection_fd=projection_fd,
            )
        )
        usage = dict(output["usage"])
        if self._exceed:
            usage["input_tokens"] = self.calls[-1]["context"][
                "budget_reserved_maximums"
            ]["input_tokens"] + 1
            body = {key: value for key, value in usage.items() if key != "usage_digest"}
            usage["usage_digest"] = canonical_authority_digest(body)
        else:
            usage["usage_digest"] = _digest(b"forged usage digest")
        output["usage"] = usage
        return output


@pytest.mark.parametrize("exceed", [False, True])
def test_unverified_or_over_reservation_usage_fails_closed_and_charges_estimate(
    tmp_path: Path,
    exceed: bool,
) -> None:
    provider = _InvalidUsageProvider(exceed=exceed)
    runtime, ledger, context, _ = _system(tmp_path, provider=provider)
    attempt = runtime.begin(context)
    with pytest.raises(ControlledExecutionRuntimeV2Error):
        attempt.invoke()
    attempt.settle(outcome="provider_error", error=RuntimeError("usage rejected"))
    settlement = ledger.settlement(attempt.reservation_id)
    assert settlement is not None
    assert settlement["state"] == "FAILED"
    assert settlement["usage_source"] == "reserved_estimate"


class _DescriptorDriftProvider(_RecordingProvider):
    def execute_bytes(
        self,
        request: bytes,
        *,
        snapshot_fd: int,
        projection_fd: int,
    ) -> Mapping[str, Any]:
        output = super().execute_bytes(
            request,
            snapshot_fd=snapshot_fd,
            projection_fd=projection_fd,
        )
        os.fchmod(snapshot_fd, 0o600)
        return output


def test_snapshot_descriptor_drift_is_detected_after_provider(tmp_path: Path) -> None:
    provider = _DescriptorDriftProvider()
    runtime, ledger, context, _ = _system(tmp_path, provider=provider)
    attempt = runtime.begin(context)
    attempt.invoke()
    with pytest.raises(ControlledExecutionRuntimeV2Error, match="drifted"):
        attempt.reverify_snapshot()
    error = RuntimeError("snapshot drift")
    attempt.settle(outcome="schema_reject", error=error)
    assert ledger.state(attempt.reservation_id) == "FAILED"


def test_pinned_resources_reject_hardlinks_and_same_inode(tmp_path: Path) -> None:
    snapshot = (tmp_path / "snapshot.sqlite3").resolve()
    projection = (tmp_path / "projection.json").resolve()
    alias = (tmp_path / "snapshot-alias.sqlite3").resolve()
    snapshot.write_bytes(b"snapshot")
    projection.write_bytes(b"projection")
    snapshot.chmod(0o400)
    projection.chmod(0o400)
    os.link(snapshot, alias)
    with pytest.raises(ControlledExecutionRuntimeV2Error, match="single-link"):
        open_pinned_controlled_snapshot_v2(
            snapshot_path=str(snapshot),
            projection_path=str(projection),
        )
    alias.unlink()
    with pytest.raises(ControlledExecutionRuntimeV2Error, match="distinct inodes"):
        open_pinned_controlled_snapshot_v2(
            snapshot_path=str(snapshot),
            projection_path=str(snapshot),
        )
