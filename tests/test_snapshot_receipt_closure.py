"""READY proof accepts only an opaque, fully bound receipt closure."""

from __future__ import annotations

import base64
from dataclasses import replace
import json
import sqlite3

import pytest

from data_contracts.coverage import coverage_contract_for, coverage_policy_binding
from tests.receipt_test_support import (
    _SignedReceiptAuthority,
    _reconcile_collection_evidence,
    write_test_scoped_receipt_registry,
)
from paper_runtime.snapshot import SnapshotRejected
from paper_runtime.ready_policy import CoverageEvidence, collect_typed_evidence
from paper_runtime.snapshot_coverage_proof import (
    CoverageProofVerificationError,
    VerifiedCoverageProof,
    _coverage_proof,
    persist_coverage_proof,
    require_persisted_coverage_proof,
)
from storage.coverage_ledger import (
    plan_required_segments,
    record_collection_receipt,
    record_required_segments,
)
from storage.receipt_crypto import (
    AUDIT_SIGNED_RECEIPT_CLAIMS_VERSION_V2,
    LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION,
    PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST,
    PRODUCTION_RECEIPT_ENVIRONMENT,
    body_digest,
    canonical_evidence_digest,
    canonical_receipt_body,
    receipt_authority_instance_digest,
)
from storage.sqlite_store import SqliteStore
from storage.verified_receipt import (
    ReceiptVerificationError,
    audit_collection_closure,
    audit_signed_receipt_claims,
    require_verified_collection_closure,
)


_DATASET = "markets_calendar"
_CHECKED_AT = "2026-08-25T00:00:00+00:00"
_POLICY_VERSION = coverage_policy_binding(_DATASET)["policy_version"]
_BUILD_ID = "build-exact-coverage-test"
_PUBLICATION_CUTOFF = "2008-01-31"


def _seed_closed_segment(tmp_path, receipt_ed25519_keys):
    store = SqliteStore(tmp_path / "snapshot-closure.sqlite")
    conn = store._conn  # noqa: SLF001
    required = plan_required_segments(
        coverage_contract_for(_DATASET),
        _PUBLICATION_CUTOFF,
        source="jquants",
    )[0]
    raw_record = {"Date": "2008-01-25", "HolidayDivision": "1"}
    evidence = _reconcile_collection_evidence(
        required=required,
        run_id=41,
        raw_pages=[json.dumps({"data": [raw_record]}).encode("utf-8")],
        raw_records=[raw_record],
        structured_records=[raw_record],
        checked_at=_CHECKED_AT,
        source_request={
            "from": required.segment_start,
            "to": required.segment_end,
        },
    )
    receipt = _SignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    ).issue(evidence)
    record_required_segments(conn, (required,), policy_version=_POLICY_VERSION)
    record_collection_receipt(conn, receipt)
    conn.execute(
        "UPDATE coverage_segments SET status='COMPLETE', receipt_run_id=? "
        "WHERE source=? AND dataset=? AND segment_id=? AND policy_version=?",
        (
            receipt.run_id,
            required.source,
            required.dataset,
            required.segment_id,
            _POLICY_VERSION,
        ),
    )
    conn.execute(
        """
        INSERT INTO dataset_coverage (
            dataset, status, policy_version, collection_scope,
            history_target_start, history_target_end_rule, coverage_mode,
            expected_frequency, universe_rule, raw_retention_required,
            structured_reconciliation_required, governance_tier,
            observed_start, observed_end, row_count, source_run_id,
            evaluated_at, detail_json
        ) VALUES (?, 'COMPLETE', ?, 'test-authoritative-scope',
                  '2008-01-01', 'fixed:2008-01-31', 'calendar', 'calendar_day',
                  'jpx_calendar_days', 1, 1, 'governed',
                  '2008-01-01', '2008-01-31',
                  1, 41, ?, '{}')
        """,
        (_DATASET, _POLICY_VERSION, _CHECKED_AT),
    )
    conn.execute(
        "CREATE TABLE ingestion_change_log (change_seq INTEGER NOT NULL)"
    )
    conn.execute("INSERT INTO ingestion_change_log VALUES (7)")
    conn.execute(
        "INSERT INTO sync_change_state "
        "(feed,last_applied_change_seq,updated_at) VALUES "
        "('jquants_records',7,?) "
        "ON CONFLICT(feed) DO UPDATE SET "
        "last_applied_change_seq=excluded.last_applied_change_seq, "
        "updated_at=excluded.updated_at",
        (_CHECKED_AT,),
    )
    conn.execute(
        """
        INSERT INTO snapshot_publications (
            build_id,state,staging_path,contract_version,
            coverage_policy_version,quality_policy_version,created_at
        ) VALUES (?, 'VALIDATING', ?, 'test-contract/v1', ?,
                  'test-quality/v1', ?)
        """,
        (
            _BUILD_ID,
            str(store.path),
            _POLICY_VERSION,
            _PUBLICATION_CUTOFF + "T23:59:59+00:00",
        ),
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
    conn.execute(
        """
        INSERT INTO snapshot_quality_results (
            build_id,status,policy_version,evaluated_at,summary_json,results_json
        ) VALUES (?, 'PASS', 'test-quality/v1', ?, '{}', '[]')
        """,
        (_BUILD_ID, _CHECKED_AT),
    )
    conn.commit()
    coverage_rows = [{
        "dataset": _DATASET,
        "policy_version": _POLICY_VERSION,
        "status": "COMPLETE",
    }]
    return store, receipt, coverage_rows


def _coverage_item(evidence):
    return next(
        item.to_item() for item in evidence if isinstance(item, CoverageEvidence)
    )


def test_persisted_coverage_proof_is_canonical_immutable_and_policy_eligible(
    tmp_path, receipt_ed25519_keys
):
    store, _receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001

    proof_id = persist_coverage_proof(
        conn, (_DATASET,), build_id=_BUILD_ID
    )
    capability = require_persisted_coverage_proof(
        conn, (_DATASET,), proof_id, build_id=_BUILD_ID
    )
    assert capability.proof_id == proof_id
    assert capability.required_datasets == (_DATASET,)
    assert capability.source_generation == capability.applied_generation == 7
    item = _coverage_item(
        collect_typed_evidence(
            conn,
            store.path,
            (_DATASET,),
            build_id=_BUILD_ID,
            coverage_proof_id=proof_id,
        )
    )
    assert item.passed is True
    assert item.detail["proof_id"] == proof_id
    assert item.detail["required_datasets"] == [_DATASET]

    row = conn.execute(
        "SELECT required_datasets_json,coverage_proof_json,"
        "source_generation,applied_generation "
        "FROM local_coverage_proofs_v2 WHERE proof_id=?",
        (proof_id,),
    ).fetchone()
    assert json.loads(row[0]) == [_DATASET]
    assert json.loads(row[1]) == capability.proof
    assert tuple(row[2:]) == (7, 7)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE local_coverage_proofs_v2 SET persisted_at='tampered' "
            "WHERE proof_id=?",
            (proof_id,),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "DELETE FROM local_coverage_proofs_v2 WHERE proof_id=?", (proof_id,)
        )
    conn.rollback()
    store.close()


def test_caller_constructed_verified_value_is_not_policy_authority(
    tmp_path, receipt_ed25519_keys
):
    store, _receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    proof_id = persist_coverage_proof(
        conn, (_DATASET,), build_id=_BUILD_ID
    )
    forged_id = "sha256:" + ("22" * 32)
    forged = VerifiedCoverageProof(
        proof_id=forged_id,
        _proof_json=json.dumps(
            {
                "status": "COMPLETE",
                "proof_digest": "sha256:" + ("33" * 32),
                "dataset_count": 999,
            }
        ),
        required_datasets=(_DATASET,),
        build_id=_BUILD_ID,
        publication_cutoff=_PUBLICATION_CUTOFF,
        source_generation=7,
        applied_generation=7,
    )
    assert forged.proof["status"] == "COMPLETE"
    assert CoverageEvidence(
        conn, (_DATASET,), forged.proof_id, _BUILD_ID
    ).to_item().passed is False
    store.close()


def test_local_v1_proof_is_audit_only_for_new_ready(
    tmp_path, receipt_ed25519_keys
):
    store, _receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    v1_id = "sha256:" + ("44" * 32)
    conn.execute(
        """
        INSERT INTO local_coverage_proofs (
            proof_id,format,required_datasets_json,coverage_proof_json,
            coverage_policy_version,coverage_policy_digest,
            source_generation,applied_generation,persisted_at
        ) VALUES (?, 'local-coverage-proof/v1', ?, '{}', ?, ?, 7, 7, ?)
        """,
        (
            v1_id,
            json.dumps([_DATASET]),
            _POLICY_VERSION,
            coverage_policy_binding(_DATASET)["policy_digest"],
            _CHECKED_AT,
        ),
    )
    conn.commit()
    with pytest.raises(CoverageProofVerificationError, match="unknown"):
        require_persisted_coverage_proof(
            conn,
            (_DATASET,),
            v1_id,
            build_id=_BUILD_ID,
        )
    store.close()


@pytest.mark.parametrize("state", ("BUILDING", "SYNCED", "REJECTED"))
def test_non_authoritative_publication_state_cannot_choose_proof_cutoff(
    tmp_path,
    receipt_ed25519_keys,
    state: str,
) -> None:
    store, _receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    conn.execute(
        "UPDATE snapshot_publications SET state=? WHERE build_id=?",
        (state, _BUILD_ID),
    )
    conn.commit()

    with pytest.raises(
        CoverageProofVerificationError,
        match="not authoritative",
    ):
        persist_coverage_proof(conn, (_DATASET,), build_id=_BUILD_ID)
    store.close()


def test_orphan_validating_row_cannot_choose_proof_cutoff(
    tmp_path,
    receipt_ed25519_keys,
) -> None:
    store, _receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    conn.execute(
        "UPDATE local_snapshot_policy SET active_build_id='caller-forged' "
        "WHERE singleton=1"
    )
    conn.commit()

    with pytest.raises(
        CoverageProofVerificationError,
        match="unique active VALIDATING build",
    ):
        persist_coverage_proof(conn, (_DATASET,), build_id=_BUILD_ID)
    store.close()


def test_ready_reopen_requires_exact_manifest_proof_linkage(
    tmp_path,
    receipt_ed25519_keys,
) -> None:
    store, _receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    proof_id = persist_coverage_proof(
        conn,
        (_DATASET,),
        build_id=_BUILD_ID,
    )
    snapshot_id = "sha256:" + ("55" * 32)
    row = conn.execute(
        "SELECT created_at FROM snapshot_publications WHERE build_id=?",
        (_BUILD_ID,),
    ).fetchone()
    forged_manifest = {
        "state": "READY",
        "build_id": _BUILD_ID,
        "snapshot_id": snapshot_id,
        "created_at": str(row[0]),
        "coverage_proof_id": "sha256:" + ("66" * 32),
    }
    conn.execute(
        "UPDATE snapshot_publications SET state='READY',snapshot_id=?,"
        "artifact_path=?,manifest_json=? WHERE build_id=?",
        (
            snapshot_id,
            str(store.path),
            json.dumps(forged_manifest),
            _BUILD_ID,
        ),
    )
    conn.execute(
        "UPDATE local_snapshot_policy SET publication_state='READY',"
        "snapshot_ready=1,active_snapshot_id=? WHERE singleton=1",
        (snapshot_id,),
    )
    conn.execute(
        """
        INSERT INTO local_snapshot_manifests (
            snapshot_id,format,committed_at,source_run_id,change_seq,manifest_json
        ) VALUES (?, 'research-snapshot-manifest/v1', ?, 41, 7, ?)
        """,
        (snapshot_id, _CHECKED_AT, json.dumps(forged_manifest)),
    )
    conn.commit()

    with pytest.raises(
        CoverageProofVerificationError,
        match="READY manifest linkage",
    ):
        require_persisted_coverage_proof(
            conn,
            (_DATASET,),
            proof_id,
            build_id=_BUILD_ID,
        )
    store.close()


def test_mutable_source_ready_row_cannot_reopen_coverage_proof(
    tmp_path,
    receipt_ed25519_keys,
) -> None:
    store, _receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    proof_id = persist_coverage_proof(
        conn,
        (_DATASET,),
        build_id=_BUILD_ID,
    )
    snapshot_id = "sha256:" + ("77" * 32)
    created_at = conn.execute(
        "SELECT created_at FROM snapshot_publications WHERE build_id=?",
        (_BUILD_ID,),
    ).fetchone()[0]
    manifest = {
        "state": "READY",
        "build_id": _BUILD_ID,
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        "coverage_proof_id": proof_id,
    }
    manifest_json = json.dumps(manifest)
    conn.execute(
        "UPDATE snapshot_publications SET state='READY',snapshot_id=?,"
        "artifact_path=?,manifest_json=? WHERE build_id=?",
        (snapshot_id, str(store.path), manifest_json, _BUILD_ID),
    )
    # Source publication rows deliberately remain unreadable after publish.
    conn.execute(
        "UPDATE local_snapshot_policy SET publication_state='READY',"
        "snapshot_ready=0,active_snapshot_id=? WHERE singleton=1",
        (snapshot_id,),
    )
    conn.execute(
        """
        INSERT INTO local_snapshot_manifests (
            snapshot_id,format,committed_at,source_run_id,change_seq,manifest_json
        ) VALUES (?, 'research-snapshot-manifest/v1', ?, 41, 7, ?)
        """,
        (snapshot_id, _CHECKED_AT, manifest_json),
    )
    conn.commit()

    with pytest.raises(
        CoverageProofVerificationError,
        match="active READY publication",
    ):
        require_persisted_coverage_proof(
            conn,
            (_DATASET,),
            proof_id,
            build_id=_BUILD_ID,
        )
    store.close()


def test_persisted_coverage_proof_rejects_tampered_unknown_and_stale_ids(
    tmp_path, receipt_ed25519_keys
):
    store, _receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    proof_id = persist_coverage_proof(
        conn, (_DATASET,), build_id=_BUILD_ID
    )
    tampered_id = proof_id[:-1] + ("0" if proof_id[-1] != "0" else "1")
    for invalid_id in (None, "UNKNOWN", tampered_id):
        with pytest.raises(CoverageProofVerificationError):
            require_persisted_coverage_proof(
                conn, (_DATASET,), invalid_id, build_id=_BUILD_ID
            )
    with pytest.raises(CoverageProofVerificationError, match="exact, sorted"):
        require_persisted_coverage_proof(
            conn, (_DATASET, _DATASET), proof_id, build_id=_BUILD_ID
        )

    conn.execute("INSERT INTO ingestion_change_log VALUES (8)")
    conn.execute(
        "UPDATE sync_change_state SET last_applied_change_seq=8 "
        "WHERE feed='jquants_records'"
    )
    conn.commit()
    with pytest.raises(CoverageProofVerificationError, match="stale"):
        require_persisted_coverage_proof(
            conn, (_DATASET,), proof_id, build_id=_BUILD_ID
        )
    assert _coverage_item(
        collect_typed_evidence(
            conn,
            store.path,
            (_DATASET,),
            build_id=_BUILD_ID,
            coverage_proof_id=proof_id,
        )
    ).passed is False
    store.close()


def test_persisted_coverage_proof_rejects_receipt_ledger_mutation(
    tmp_path, receipt_ed25519_keys
):
    store, receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    proof_id = persist_coverage_proof(
        conn, (_DATASET,), build_id=_BUILD_ID
    )
    conn.execute(
        "UPDATE collection_receipts SET observed_items=0 "
        "WHERE source=? AND dataset=? AND segment_id=? AND run_id=?",
        (receipt.source, receipt.dataset, receipt.segment_id, receipt.run_id),
    )
    conn.commit()
    with pytest.raises(
        CoverageProofVerificationError, match="cannot be reproduced"
    ):
        require_persisted_coverage_proof(
            conn, (_DATASET,), proof_id, build_id=_BUILD_ID
        )
    store.close()


def test_copied_coverage_record_without_receipt_cannot_mint_capability(
    tmp_path, receipt_ed25519_keys
):
    source, _receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    source_conn = source._conn  # noqa: SLF001
    proof_id = persist_coverage_proof(
        source_conn, (_DATASET,), build_id=_BUILD_ID
    )

    target = SqliteStore(tmp_path / "copied-record.sqlite")
    target_conn = target._conn  # noqa: SLF001
    for table in (
        "dataset_coverage",
        "local_coverage_proofs_v2",
        "snapshot_publications",
    ):
        cursor = source_conn.execute(f"SELECT * FROM {table}")
        columns = [item[0] for item in cursor.description]
        rows = cursor.fetchall()
        target_conn.executemany(
            f"INSERT INTO {table} ({','.join(columns)}) "
            f"VALUES ({','.join('?' for _ in columns)})",
            [tuple(row) for row in rows],
        )
    target_conn.execute(
        "CREATE TABLE ingestion_change_log (change_seq INTEGER NOT NULL)"
    )
    target_conn.execute("INSERT INTO ingestion_change_log VALUES (7)")
    target_conn.execute(
        "INSERT INTO sync_change_state "
        "(feed,last_applied_change_seq,updated_at) VALUES "
        "('jquants_records',7,?)",
        (_CHECKED_AT,),
    )
    target_conn.commit()

    with pytest.raises(
        CoverageProofVerificationError, match="active publication policy"
    ):
        require_persisted_coverage_proof(
            target_conn, (_DATASET,), proof_id, build_id=_BUILD_ID
        )
    target.close()
    source.close()


@pytest.mark.parametrize(
    "mutation_sql",
    (
        "DELETE FROM coverage_segments WHERE dataset='markets_calendar'",
        """
        INSERT INTO coverage_segments
        SELECT source,dataset,'2099-surprise',policy_version,
               segment_start,segment_end,expected_scope,expected_items,
               status,receipt_run_id,evaluated_at,detail_json
        FROM coverage_segments WHERE dataset='markets_calendar'
        """,
        """
        INSERT INTO coverage_segments
        SELECT 'alternate-source',dataset,segment_id,policy_version,
               segment_start,segment_end,expected_scope,expected_items,
               status,receipt_run_id,evaluated_at,detail_json
        FROM coverage_segments WHERE dataset='markets_calendar'
        """,
        "UPDATE coverage_segments SET policy_version='collection-coverage/v999' "
        "WHERE dataset='markets_calendar'",
        "UPDATE coverage_segments SET expected_scope='{\"tampered\":true}' "
        "WHERE dataset='markets_calendar'",
    ),
    ids=(
        "deleted-orphan-receipt",
        "unexpected-segment",
        "duplicate-cross-source",
        "wrong-policy",
        "wrong-scope-window",
    ),
)
def test_snapshot_proof_requires_exact_canonical_inventory(
    tmp_path,
    receipt_ed25519_keys,
    mutation_sql,
):
    store, _receipt, coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    conn.execute(mutation_sql)
    conn.commit()
    with pytest.raises(SnapshotRejected, match="exact inventory rejected"):
        _coverage_proof(
            conn,
            (_DATASET,),
            coverage_rows,
            publication_cutoff=_PUBLICATION_CUTOFF,
        )
    store.close()


def test_snapshot_proof_hashes_verified_closure_and_rejects_outer_mutation(
    tmp_path, receipt_ed25519_keys
):
    store, receipt, coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    proof = _coverage_proof(
        conn,
        (_DATASET,),
        coverage_rows,
        publication_cutoff=_PUBLICATION_CUTOFF,
    )
    assert proof["status"] == "COMPLETE"
    assert proof["receipt_count"] == 1
    assert proof["proof_digest"].startswith("sha256:")

    # The receipt row is only a transport DTO. Even though the segment row is
    # still marked COMPLETE, changing a gating mirror invalidates its closure.
    conn.execute(
        "UPDATE collection_receipts SET observed_items=0 "
        "WHERE source=? AND dataset=? AND segment_id=? AND run_id=?",
        (receipt.source, receipt.dataset, receipt.segment_id, receipt.run_id),
    )
    conn.commit()
    with pytest.raises(SnapshotRejected, match="receipt closure invalid"):
        _coverage_proof(
            conn,
            (_DATASET,),
            coverage_rows,
            publication_cutoff=_PUBLICATION_CUTOFF,
        )
    store.close()


@pytest.mark.parametrize(
    "audit_version",
    [
        LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION,
        AUDIT_SIGNED_RECEIPT_CLAIMS_VERSION_V2,
    ],
)
def test_snapshot_proof_rejects_validly_signed_audit_version(
    tmp_path, receipt_ed25519_keys, audit_version
):
    store, receipt, coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    digests = dict(receipt.digests)
    claims = json.loads(base64.b64decode(digests["signed_body_b64"]))
    claims["version"] = audit_version
    claims.pop("environment")
    claims.pop("authority_instance_digest")
    legacy_scope = {
        key: claims[key]
        for key in (
            "coverage_policy_version",
            "source",
            "dataset",
            "segment_id",
            "segment_start",
            "segment_end",
            "expected_scope",
            "expected_items",
        )
    }
    claims["scope_digest"] = canonical_evidence_digest(legacy_scope)
    legacy_observation = {
        key: value
        for key, value in claims.items()
        if key not in {
            "version",
            "parser_normalizer_version",
            "issuer_id",
            "issued_at",
            "observation_digest",
        }
    }
    claims["observation_digest"] = canonical_evidence_digest(legacy_observation)
    legacy_body = canonical_receipt_body(claims)
    digests["signed_body_b64"] = base64.b64encode(legacy_body).decode("ascii")
    digests["signature"] = receipt_ed25519_keys.signing_key.sign(legacy_body)
    digests["body_digest"] = body_digest(legacy_body)
    digests.pop("environment")
    digests.pop("authority_instance_digest")
    digests["scope_digest"] = claims["scope_digest"]
    digests["observation_digest"] = claims["observation_digest"]
    legacy_receipt = replace(receipt, digests=digests)
    assert (
        audit_signed_receipt_claims(legacy_receipt)["version"]
        == audit_version
    )
    assert (
        audit_collection_closure(
            legacy_receipt,
            expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
            expected_authority_instance_digest=(
                PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
            ),
        )["version"]
        == audit_version
    )
    with pytest.raises(ReceiptVerificationError, match="audit-only"):
        require_verified_collection_closure(
            legacy_receipt,
            expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
            expected_authority_instance_digest=(
                PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
            ),
        )

    conn = store._conn  # noqa: SLF001
    conn.execute(
        "UPDATE collection_receipts SET digests_json=? "
        "WHERE source=? AND dataset=? AND segment_id=? AND run_id=?",
        (
            json.dumps(digests, sort_keys=True, separators=(",", ":")),
            receipt.source,
            receipt.dataset,
            receipt.segment_id,
            receipt.run_id,
        ),
    )
    conn.commit()
    with pytest.raises(
        SnapshotRejected, match="is audit-only and not COMPLETE-eligible"
    ):
        _coverage_proof(
            conn,
            (_DATASET,),
            coverage_rows,
            publication_cutoff=_PUBLICATION_CUTOFF,
        )
    store.close()


def test_production_verifier_rejects_staging_receipt(
    receipt_ed25519_keys,
):
    required = plan_required_segments(
        coverage_contract_for(_DATASET),
        _PUBLICATION_CUTOFF,
        source="jquants",
    )[0]
    evidence = _reconcile_collection_evidence(
        required=required,
        run_id=991,
        raw_pages=(b'{"data":[{"Date":"2008-01-01"}]}',),
        raw_records=({"Date": "2008-01-01"},),
        structured_records=({"Date": "2008-01-01"},),
        checked_at=_CHECKED_AT,
        environment="staging",
        authority_instance_digest=receipt_authority_instance_digest("staging"),
    )
    receipt = _SignedReceiptAuthority(
        receipt_ed25519_keys.signing_key
    ).issue(evidence)
    with pytest.raises(ReceiptVerificationError, match="signed environment"):
        require_verified_collection_closure(
            receipt,
            expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
            expected_authority_instance_digest=receipt_authority_instance_digest(
                PRODUCTION_RECEIPT_ENVIRONMENT
            ),
        )


def test_revoked_v3_audit_rejects_outer_and_digest_pointer_mutation(
    tmp_path, receipt_ed25519_keys, monkeypatch
):
    import storage.receipt_crypto as crypto

    store, receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    production_path = write_test_scoped_receipt_registry(
        receipt_ed25519_keys.scoped_path,
        key_id=receipt_ed25519_keys.key_id,
        public_raw=receipt_ed25519_keys.public_raw,
        environment=PRODUCTION_RECEIPT_ENVIRONMENT,
        authority_instance_digest=PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST,
        status="revoked",
    )
    raw_pins = dict(crypto.PINNED_SCOPED_RECEIPT_REGISTRY_RAW_DIGESTS)
    raw_pins[PRODUCTION_RECEIPT_ENVIRONMENT] = body_digest(
        production_path.read_bytes()
    )
    monkeypatch.setattr(
        crypto, "PINNED_SCOPED_RECEIPT_REGISTRY_RAW_DIGESTS", raw_pins
    )
    crypto._parse_scoped_registry_document.cache_clear()

    with pytest.raises(ReceiptVerificationError, match="signature is invalid"):
        require_verified_collection_closure(
            receipt,
            expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
            expected_authority_instance_digest=(
                PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
            ),
        )
    audited = audit_collection_closure(
        receipt,
        expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
        expected_authority_instance_digest=(
            PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
        ),
    )
    assert audited["version"] == "signed-receipt-claims/v3"

    mutations = (
        replace(receipt, raw_row_count=receipt.raw_row_count + 1),
        replace(receipt, status="FAILED", error="mutated"),
        replace(
            receipt,
            digests={
                **receipt.digests,
                "structured_digest": "sha256:" + "f" * 64,
            },
        ),
    )
    for mutated in mutations:
        with pytest.raises(ReceiptVerificationError):
            audit_collection_closure(
                mutated,
                expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
                expected_authority_instance_digest=(
                    PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
                ),
            )
    store.close()
