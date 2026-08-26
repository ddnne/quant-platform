"""Behavioral invariants for the production Coverage transition boundary."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from data_contracts.coverage import coverage_contract_for
from cf_platform.ingest_premium.coverage import CheckResult
from storage.coverage_ledger import (
    compare_exact_coverage_inventory,
    record_collection_receipt,
    record_required_segments,
    refresh_coverage_ledger,
)
import storage.coverage_ledger as coverage_ledger_module
from storage.coverage_transition import (
    COVERAGE_TRANSITION_ALGORITHM,
    COVERAGE_TRANSITION_DOMAIN,
    COVERAGE_TRANSITION_FORMAT,
    COVERAGE_TRANSITION_ISSUER,
    CoverageTransitionAlreadyConsumed,
    CoverageTransitionAuthorityPending,
    CoverageTransitionError,
    CoverageTransitionPublicKeyRegistry,
    apply_signed_coverage_transition,
    build_coverage_transition_request,
    coverage_transition_availability,
)
import storage.coverage_transition as transition_module
from storage.sqlite_store import SqliteStore
from tests.receipt_test_support import (
    _SignedReceiptAuthority,
    _reconcile_collection_evidence,
)


_BUILD_ID = "build-c10-transition"
_CUTOFF = "2008-05-31"
_PUBLICATION_AT = "2008-05-31T12:00:00+00:00"
_CHECKED_AT = "2008-05-31T13:00:00+00:00"
_DATASETS = ("equities_bars_daily",)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _transition_clock() -> tuple[str, str]:
    issued = datetime.now(timezone.utc).replace(microsecond=0)
    expires = issued + timedelta(minutes=5)
    return (
        issued.isoformat().replace("+00:00", "Z"),
        expires.isoformat().replace("+00:00", "Z"),
    )


def _test_transition_key() -> tuple[str, Ed25519PrivateKey]:
    return "test-coverage-transition-v1", Ed25519PrivateKey.generate()


def _registry_for(
    key_id: str,
    private: Ed25519PrivateKey,
) -> CoverageTransitionPublicKeyRegistry:
    public_b64 = base64.b64encode(
        private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    return CoverageTransitionPublicKeyRegistry.from_document(
        {
            "schema_version": 1,
            "purpose": "coverage_complete_transition_verification",
            "keys": [
                {
                    "key_id": key_id,
                    "algorithm": "Ed25519",
                    "status": "active",
                    "public_key_b64": public_b64,
                }
            ],
        }
    )


def _sign_request(
    request: dict[str, Any],
    *,
    key_id: str,
    private: Ed25519PrivateKey,
) -> dict[str, Any]:
    document = {
        "format": request["format"],
        "authority_domain": request["authority_domain"],
        "issuer": COVERAGE_TRANSITION_ISSUER,
        "issuer_key_id": key_id,
        "algorithm": COVERAGE_TRANSITION_ALGORITHM,
        "transition_id": request["transition_id"],
        "body": request["body"],
    }
    document["signature"] = "ed25519:" + base64.b64encode(
        private.sign(_canonical(document))
    ).decode("ascii")
    return document


def _readdress(request: dict[str, Any]) -> None:
    request["transition_id"] = _digest(
        {
            "format": COVERAGE_TRANSITION_FORMAT,
            "authority_domain": COVERAGE_TRANSITION_DOMAIN,
            "body": request["body"],
        }
    )


def _insert_active_aggregate(
    conn: sqlite3.Connection,
    *,
    dataset: str,
    observed_start: str,
    observed_end: str,
    row_count: int,
    source_run_id: int,
) -> None:
    policy = coverage_contract_for(dataset)
    conn.execute(
        """
        INSERT INTO dataset_coverage (
            dataset,status,policy_version,collection_scope,
            history_target_start,history_target_end_rule,coverage_mode,
            expected_frequency,universe_rule,raw_retention_required,
            structured_reconciliation_required,governance_tier,
            observed_start,observed_end,row_count,source_run_id,
            evaluated_at,detail_json
        ) VALUES (?, 'PARTIAL', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dataset,
            policy.policy_version,
            policy.collection_scope,
            policy.history_target_start,
            policy.history_target_end_rule,
            policy.coverage_mode,
            policy.expected_frequency,
            policy.universe_rule,
            int(policy.raw_retention_required),
            int(policy.structured_reconciliation_required),
            policy.governance_tier,
            observed_start,
            observed_end,
            row_count,
            source_run_id,
            _CHECKED_AT,
            json.dumps(
                {
                    "checks": [
                        {
                            "check_id": "C2",
                            "dataset": dataset,
                            "status": "pass",
                            "detail": "fixture validation",
                            "metrics": {
                                "source": "ingestion_validation",
                                "validation_status": "pass",
                            },
                        }
                    ],
                    "global_failures": [],
                    "coverage_v2": {
                        "required_segments": row_count,
                        "status_counts": {"COMPLETE": row_count},
                        "aggregate_complete_gate": {
                            "mode": (
                                "generic_refresh_c10_transition_authority_unavailable"
                            ),
                            "computed_status": "COMPLETE",
                            "persisted_status": "PARTIAL",
                            "blocker": "transition_authority_required",
                            "current_policy_version": policy.policy_version,
                            "inventory_target_end": _CUTOFF,
                        },
                    }
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
    )


def _prepare_transition_db(
    path: Path,
    *,
    datasets: tuple[str, ...],
    receipt_signing_key: Any,
) -> None:
    store = SqliteStore(path)
    conn = store._conn  # noqa: SLF001
    receipt_authority = _SignedReceiptAuthority(
        signing_key=receipt_signing_key
    )
    next_run = 1
    for dataset in datasets:
        inventory = compare_exact_coverage_inventory(
            conn,
            (dataset,),
            target_end=_CUTOFF,
        )
        segments = inventory.segments_for(dataset)
        assert segments
        record_required_segments(conn, segments)
        selected: list[tuple[int, str, str, str, str]] = []
        for segment in segments:
            raw_record = {"segment": segment.segment_id, "value": 1}
            evidence = _reconcile_collection_evidence(
                required=segment,
                run_id=next_run,
                raw_pages=[
                    json.dumps({"data": [raw_record]}).encode("utf-8")
                ],
                raw_records=[raw_record],
                structured_records=[raw_record],
                checked_at=_CHECKED_AT,
                source_request={
                    "from": segment.segment_start,
                    "to": segment.segment_end,
                },
            )
            receipt = receipt_authority.issue(evidence)
            record_collection_receipt(conn, receipt)
            selected.append(
                (
                    next_run,
                    segment.source,
                    segment.dataset,
                    segment.segment_id,
                    policy_version := str(
                        coverage_contract_for(dataset).policy_version
                    ),
                )
            )
            assert policy_version == "collection-coverage/v3"
            next_run += 1
        conn.executemany(
            "UPDATE coverage_segments SET status='COMPLETE',receipt_run_id=? "
            "WHERE source=? AND dataset=? AND segment_id=? AND policy_version=?",
            selected,
        )
        _insert_active_aggregate(
            conn,
            dataset=dataset,
            observed_start=segments[0].segment_start,
            observed_end=segments[-1].segment_end,
            row_count=len(segments),
            source_run_id=next_run - 1,
        )

    conn.execute(
        """
        INSERT INTO snapshot_publications (
            build_id,state,staging_path,contract_version,
            coverage_policy_version,quality_policy_version,created_at
        ) VALUES (?, 'VALIDATING', ?, 'test-contract/v1',
                  'collection-coverage/v3', 'test-quality/v1', ?)
        """,
        (_BUILD_ID, str(path.resolve()), _PUBLICATION_AT),
    )
    conn.execute(
        """
        INSERT INTO local_snapshot_policy (
            singleton,require_manifest,snapshot_ready,publication_state,
            active_build_id
        ) VALUES (1,1,0,'VALIDATING',?)
        ON CONFLICT(singleton) DO UPDATE SET
            require_manifest=1,snapshot_ready=0,
            publication_state='VALIDATING',active_build_id=excluded.active_build_id
        """,
        (_BUILD_ID,),
    )
    conn.commit()
    store.close()


def _request(path: Path) -> dict[str, Any]:
    issued_at, expires_at = _transition_clock()
    return dict(
        build_coverage_transition_request(
            str(path),
            build_id=_BUILD_ID,
            datasets=_DATASETS,
            issued_at=issued_at,
            expires_at=expires_at,
        )
    )


def _configure_test_registry(
    monkeypatch: pytest.MonkeyPatch,
    registry: CoverageTransitionPublicKeyRegistry,
) -> None:
    monkeypatch.setattr(
        CoverageTransitionPublicKeyRegistry,
        "load_pinned",
        classmethod(lambda cls: registry),
    )


def test_unprovisioned_authority_is_pending_and_writes_nothing(
    tmp_path: Path,
    receipt_ed25519_keys: Any,
) -> None:
    path = tmp_path / "pending.sqlite"
    _prepare_transition_db(
        path,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    assert dict(coverage_transition_availability()) == {
        "status": "PENDING",
        "reason_code": "COVERAGE_TRANSITION_AUTHORITY_UNPROVISIONED",
    }
    with pytest.raises(CoverageTransitionAuthorityPending):
        apply_signed_coverage_transition(str(path), {})
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT status FROM dataset_coverage WHERE dataset=?",
            _DATASETS,
        ).fetchone()[0] == "PARTIAL"
        assert conn.execute(
            "SELECT COUNT(*) FROM coverage_complete_transition_tombstones"
        ).fetchone()[0] == 0


def test_real_generic_refresh_produces_only_a_signed_transition_candidate(
    tmp_path: Path,
    receipt_ed25519_keys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "refresh-candidate.sqlite"
    _prepare_transition_db(
        path,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    monkeypatch.setattr(
        coverage_ledger_module,
        "run_coverage",
        lambda *args, **kwargs: [
            CheckResult(
                "C2",
                _DATASETS[0],
                "pass",
                "fixture ingestion validation",
                {
                    "source": "ingestion_validation",
                    "validation_status": "pass",
                },
            )
        ],
    )
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        refreshed = refresh_coverage_ledger(
            conn,
            path,
            datasets=_DATASETS,
            today=_CUTOFF,
            _publication_build_id=_BUILD_ID,
        )[0]
    assert refreshed["status"] == "PARTIAL"
    gate = json.loads(refreshed["detail_json"])["coverage_v2"][
        "aggregate_complete_gate"
    ]
    assert gate["computed_status"] == "COMPLETE"
    assert gate["blocker"] == "transition_authority_required"

    request = _request(path)
    assert request["body"]["inventory_count"] == 1
    assert request["body"]["receipt_count"] == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT status FROM dataset_coverage WHERE dataset=?",
            _DATASETS,
        ).fetchone()[0] == "PARTIAL"


def test_signed_exact_transition_is_content_addressed_and_one_shot(
    tmp_path: Path,
    receipt_ed25519_keys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "success.sqlite"
    _prepare_transition_db(
        path,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    request = _request(path)
    key_id, private = _test_transition_key()
    registry = _registry_for(key_id, private)
    _configure_test_registry(monkeypatch, registry)
    document = _sign_request(request, key_id=key_id, private=private)

    result = dict(apply_signed_coverage_transition(str(path), document))
    assert result["status"] == "COMPLETE"
    assert result["transition_id"] == request["transition_id"]
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT status,detail_json FROM dataset_coverage WHERE dataset=?",
            _DATASETS,
        ).fetchone()
        assert row[0] == "COMPLETE"
        detail = json.loads(row[1])
        assert (
            detail["coverage_v2"]["complete_transition"]["transition_id"]
            == request["transition_id"]
        )
        applied_gate = detail["coverage_v2"]["aggregate_complete_gate"]
        assert applied_gate["mode"] == "signed_coverage_transition_authority"
        assert applied_gate["persisted_status"] == "COMPLETE"
        assert applied_gate["inventory_status"] == "EXACT"
        assert applied_gate["selected_receipt_status"] == "VERIFIED"
        assert applied_gate["blocker"] is None
        assert applied_gate["transition_id"] == request["transition_id"]
        tombstone = conn.execute(
            "SELECT transition_id,signed_evidence_json "
            "FROM coverage_complete_transition_tombstones"
        ).fetchone()
        assert tombstone[0] == request["transition_id"]
        assert json.loads(tombstone[1]) == document

    with pytest.raises(CoverageTransitionAlreadyConsumed):
        apply_signed_coverage_transition(str(path), document)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda body: body.__setitem__(
            "publication_cutoff", "2008-05-01"
        ),
        lambda body: body.__setitem__(
            "inventory_count", body["inventory_count"] + 1
        ),
        lambda body: body["target_state"][0].__setitem__(
            "status", "PARTIAL"
        ),
    ),
    ids=("caller-cutoff", "caller-count", "caller-target"),
)
def test_even_validly_signed_caller_claims_are_rederived_from_live_state(
    mutate: Any,
    tmp_path: Path,
    receipt_ed25519_keys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "signed-lie.sqlite"
    _prepare_transition_db(
        path,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    request = _request(path)
    mutate(request["body"])
    _readdress(request)
    key_id, private = _test_transition_key()
    _configure_test_registry(monkeypatch, _registry_for(key_id, private))
    document = _sign_request(request, key_id=key_id, private=private)

    with pytest.raises(CoverageTransitionError):
        apply_signed_coverage_transition(str(path), document)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT status FROM dataset_coverage WHERE dataset=?",
            _DATASETS,
        ).fetchone()[0] == "PARTIAL"
        assert conn.execute(
            "SELECT COUNT(*) FROM coverage_complete_transition_tombstones"
        ).fetchone()[0] == 0


def test_state_drift_after_signature_rejects_without_tombstone(
    tmp_path: Path,
    receipt_ed25519_keys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "drift.sqlite"
    _prepare_transition_db(
        path,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    request = _request(path)
    key_id, private = _test_transition_key()
    _configure_test_registry(monkeypatch, _registry_for(key_id, private))
    document = _sign_request(request, key_id=key_id, private=private)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE dataset_coverage SET detail_json='{}' WHERE dataset=?",
            _DATASETS,
        )

    with pytest.raises(CoverageTransitionError):
        apply_signed_coverage_transition(str(path), document)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM coverage_complete_transition_tombstones"
        ).fetchone()[0] == 0


def test_complete_candidate_rejects_fail_open_validation_marker(
    tmp_path: Path,
    receipt_ed25519_keys: Any,
) -> None:
    path = tmp_path / "validation-fail-open.sqlite"
    _prepare_transition_db(
        path,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    with sqlite3.connect(path) as conn:
        raw = conn.execute(
            "SELECT detail_json FROM dataset_coverage WHERE dataset=?",
            _DATASETS,
        ).fetchone()[0]
        detail = json.loads(raw)
        detail["checks"][0]["metrics"].pop("validation_status")
        conn.execute(
            "UPDATE dataset_coverage SET detail_json=? WHERE dataset=?",
            (json.dumps(detail), *_DATASETS),
        )

    issued_at, expires_at = _transition_clock()
    with pytest.raises(CoverageTransitionError, match="validation is not PASS"):
        build_coverage_transition_request(
            str(path),
            build_id=_BUILD_ID,
            datasets=_DATASETS,
            issued_at=issued_at,
            expires_at=expires_at,
        )


@pytest.mark.parametrize(
    "drift_sql",
    (
        "UPDATE coverage_segments SET receipt_run_id=NULL "
        "WHERE dataset='equities_bars_daily'",
        "UPDATE snapshot_publications SET state='REJECTED' "
        "WHERE build_id='build-c10-transition'",
    ),
    ids=("selected-receipt", "active-build"),
)
def test_target_evidence_and_build_are_reverified_after_signature(
    drift_sql: str,
    tmp_path: Path,
    receipt_ed25519_keys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "target-drift.sqlite"
    _prepare_transition_db(
        path,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    request = _request(path)
    key_id, private = _test_transition_key()
    _configure_test_registry(monkeypatch, _registry_for(key_id, private))
    document = _sign_request(request, key_id=key_id, private=private)
    with sqlite3.connect(path) as conn:
        conn.execute(drift_sql)

    with pytest.raises(CoverageTransitionError):
        apply_signed_coverage_transition(str(path), document)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT status FROM dataset_coverage WHERE dataset=?",
            _DATASETS,
        ).fetchone()[0] == "PARTIAL"
        assert conn.execute(
            "SELECT COUNT(*) FROM coverage_complete_transition_tombstones"
        ).fetchone()[0] == 0


def test_authorization_expiring_during_reverification_rolls_back(
    tmp_path: Path,
    receipt_ed25519_keys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "expiry.sqlite"
    _prepare_transition_db(
        path,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    request = _request(path)
    key_id, private = _test_transition_key()
    _configure_test_registry(monkeypatch, _registry_for(key_id, private))
    document = _sign_request(request, key_id=key_id, private=private)
    issued = datetime.fromisoformat(
        request["body"]["issued_at"].replace("Z", "+00:00")
    )
    expires = datetime.fromisoformat(
        request["body"]["expires_at"].replace("Z", "+00:00")
    )
    observed = iter((issued + timedelta(seconds=1), expires + timedelta(seconds=1)))
    monkeypatch.setattr(transition_module, "_utc_now", lambda: next(observed))

    with pytest.raises(CoverageTransitionError, match="expired during"):
        apply_signed_coverage_transition(str(path), document)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM coverage_complete_transition_tombstones"
        ).fetchone()[0] == 0


def test_authorization_expiring_during_postconditions_rolls_back_before_commit(
    tmp_path: Path,
    receipt_ed25519_keys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "postcondition-expiry.sqlite"
    _prepare_transition_db(
        path,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    request = _request(path)
    key_id, private = _test_transition_key()
    _configure_test_registry(monkeypatch, _registry_for(key_id, private))
    document = _sign_request(request, key_id=key_id, private=private)
    issued = datetime.fromisoformat(
        request["body"]["issued_at"].replace("Z", "+00:00")
    )
    expires = datetime.fromisoformat(
        request["body"]["expires_at"].replace("Z", "+00:00")
    )
    clock = {"now": issued + timedelta(seconds=1)}
    monkeypatch.setattr(transition_module, "_utc_now", lambda: clock["now"])
    original_postconditions = transition_module._assert_post_apply_state

    def _advance_clock_after_postconditions(*args: Any, **kwargs: Any) -> None:
        original_postconditions(*args, **kwargs)
        clock["now"] = expires + timedelta(seconds=1)

    monkeypatch.setattr(
        transition_module,
        "_assert_post_apply_state",
        _advance_clock_after_postconditions,
    )

    with pytest.raises(CoverageTransitionError, match="expired before commit"):
        apply_signed_coverage_transition(str(path), document)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT status FROM dataset_coverage WHERE dataset=?",
            _DATASETS,
        ).fetchone()[0] == "PARTIAL"
        assert conn.execute(
            "SELECT COUNT(*) FROM coverage_complete_transition_tombstones"
        ).fetchone()[0] == 0


def test_authorization_clock_rollback_before_commit_rolls_back(
    tmp_path: Path,
    receipt_ed25519_keys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "postcondition-clock-rollback.sqlite"
    _prepare_transition_db(
        path,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    request = _request(path)
    key_id, private = _test_transition_key()
    _configure_test_registry(monkeypatch, _registry_for(key_id, private))
    document = _sign_request(request, key_id=key_id, private=private)
    issued = datetime.fromisoformat(
        request["body"]["issued_at"].replace("Z", "+00:00")
    )
    observed = iter(
        (
            issued + timedelta(seconds=1),
            issued + timedelta(seconds=2),
            issued - timedelta(seconds=1),
        )
    )
    monkeypatch.setattr(transition_module, "_utc_now", lambda: next(observed))

    with pytest.raises(
        CoverageTransitionError,
        match="moved backwards before commit",
    ):
        apply_signed_coverage_transition(str(path), document)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT status FROM dataset_coverage WHERE dataset=?",
            _DATASETS,
        ).fetchone()[0] == "PARTIAL"
        assert conn.execute(
            "SELECT COUNT(*) FROM coverage_complete_transition_tombstones"
        ).fetchone()[0] == 0


def test_two_dataset_failure_rolls_back_tombstone_and_first_cas(
    tmp_path: Path,
    receipt_ed25519_keys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    datasets = tuple(sorted((
        "equities_bars_daily",
        "indices_bars_daily_topix",
    )))
    path = tmp_path / "atomic.sqlite"
    _prepare_transition_db(
        path,
        datasets=datasets,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    issued_at, expires_at = _transition_clock()
    request = dict(
        build_coverage_transition_request(
            str(path),
            build_id=_BUILD_ID,
            datasets=datasets,
            issued_at=issued_at,
            expires_at=expires_at,
        )
    )
    key_id, private = _test_transition_key()
    _configure_test_registry(monkeypatch, _registry_for(key_id, private))
    document = _sign_request(request, key_id=key_id, private=private)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TRIGGER reject_second_coverage_transition
            BEFORE UPDATE OF status ON dataset_coverage
            WHEN NEW.dataset='indices_bars_daily_topix'
             AND NEW.status='COMPLETE'
            BEGIN
                SELECT RAISE(ABORT, 'fixture second CAS failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="second CAS failure"):
        apply_signed_coverage_transition(str(path), document)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM dataset_coverage WHERE status='COMPLETE'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM coverage_complete_transition_tombstones"
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "trigger_body",
    (
        "UPDATE dataset_coverage SET status='PARTIAL' "
        "WHERE dataset=NEW.dataset;",
        "UPDATE dataset_coverage SET detail_json='{}' "
        "WHERE dataset=NEW.dataset;",
    ),
    ids=("revert-complete", "corrupt-evidence"),
)
def test_after_update_trigger_cannot_commit_false_complete(
    trigger_body: str,
    tmp_path: Path,
    receipt_ed25519_keys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "after-trigger.sqlite"
    _prepare_transition_db(
        path,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    request = _request(path)
    key_id, private = _test_transition_key()
    _configure_test_registry(monkeypatch, _registry_for(key_id, private))
    document = _sign_request(request, key_id=key_id, private=private)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TRIGGER adversarial_after_complete "
            "AFTER UPDATE OF status ON dataset_coverage "
            "WHEN NEW.status='COMPLETE' BEGIN "
            + trigger_body
            + " END"
        )

    with pytest.raises(
        CoverageTransitionError,
        match="target rows failed post-CAS verification",
    ):
        apply_signed_coverage_transition(str(path), document)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT status FROM dataset_coverage WHERE dataset=?",
            _DATASETS,
        ).fetchone()[0] == "PARTIAL"
        assert conn.execute(
            "SELECT COUNT(*) FROM coverage_complete_transition_tombstones"
        ).fetchone()[0] == 0


def test_path_swap_after_cas_rolls_back_opened_inode_and_returns_no_success(
    tmp_path: Path,
    receipt_ed25519_keys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "path-swap.sqlite"
    clone = tmp_path / "path-swap-clone.sqlite"
    displaced = tmp_path / "path-swap-displaced.sqlite"
    _prepare_transition_db(
        path,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    shutil.copy2(path, clone)
    request = _request(path)
    key_id, private = _test_transition_key()
    _configure_test_registry(monkeypatch, _registry_for(key_id, private))
    document = _sign_request(request, key_id=key_id, private=private)
    original_apply_cas = transition_module._apply_cas

    def _swap_path_after_cas(*args: Any, **kwargs: Any) -> Any:
        expected = original_apply_cas(*args, **kwargs)
        path.replace(displaced)
        shutil.copy2(clone, path)
        return expected

    monkeypatch.setattr(
        transition_module,
        "_apply_cas",
        _swap_path_after_cas,
    )
    with pytest.raises(
        CoverageTransitionError,
        match="no longer names the opened database",
    ):
        apply_signed_coverage_transition(str(path), document)

    for candidate in (path, displaced):
        with sqlite3.connect(candidate) as conn:
            assert conn.execute(
                "SELECT status FROM dataset_coverage WHERE dataset=?",
                _DATASETS,
            ).fetchone()[0] == "PARTIAL"
            assert conn.execute(
                "SELECT COUNT(*) "
                "FROM coverage_complete_transition_tombstones"
            ).fetchone()[0] == 0


def test_authority_input_rejects_stateful_mapping_and_string_subclasses(
    tmp_path: Path,
    receipt_ed25519_keys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "types.sqlite"
    _prepare_transition_db(
        path,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    request = _request(path)
    key_id, private = _test_transition_key()
    _configure_test_registry(monkeypatch, _registry_for(key_id, private))
    document = _sign_request(request, key_id=key_id, private=private)

    class StatefulDocument(dict):
        pass

    class EvilString(str):
        pass

    with pytest.raises(TypeError, match="exact JSON"):
        apply_signed_coverage_transition(str(path), StatefulDocument(document))
    evil = dict(document)
    evil["issuer_key_id"] = EvilString(key_id)
    with pytest.raises(TypeError, match="exact JSON"):
        apply_signed_coverage_transition(str(path), evil)


def test_transition_tombstone_is_immutable(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "immutable.sqlite")
    conn = store._conn  # noqa: SLF001
    values = (
        "sha256:" + "a" * 64,
        COVERAGE_TRANSITION_FORMAT,
        COVERAGE_TRANSITION_DOMAIN,
        "test-key",
        "build",
        _CUTOFF,
        *("sha256:" + char * 64 for char in "bcdefg"),
        "{}",
        _CHECKED_AT,
    )
    conn.execute(
        """
        INSERT INTO coverage_complete_transition_tombstones (
            transition_id,format,authority_domain,issuer_key_id,build_id,
            publication_cutoff,dataset_set_digest,from_state_digest,
            target_state_digest,coverage_policy_set_digest,
            inventory_set_digest,receipt_set_digest,signed_evidence_json,
            consumed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        values,
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE coverage_complete_transition_tombstones SET consumed_at='x'"
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("DELETE FROM coverage_complete_transition_tombstones")
    store.close()
