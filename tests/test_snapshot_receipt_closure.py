"""READY proof accepts only an opaque, fully bound receipt closure."""

from __future__ import annotations

import base64
from dataclasses import replace
import json

import pytest

from data_contracts.coverage import coverage_policy_binding
from tests.receipt_test_support import (
    _SignedReceiptAuthority,
    _reconcile_collection_evidence,
)
from paper_runtime.snapshot import SnapshotRejected
from paper_runtime.snapshot_coverage_proof import _coverage_proof
from storage.coverage_ledger import (
    RequiredCoverageSegment,
    record_collection_receipt,
    record_required_segments,
)
from storage.receipt_crypto import (
    LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION,
    body_digest,
    canonical_receipt_body,
)
from storage.sqlite_store import SqliteStore
from storage.verified_receipt import (
    ReceiptVerificationError,
    audit_signed_receipt_claims,
    require_verified_collection_closure,
)


_DATASET = "markets_calendar"
_CHECKED_AT = "2026-08-25T00:00:00+00:00"
_POLICY_VERSION = coverage_policy_binding(_DATASET)["policy_version"]


def _seed_closed_segment(tmp_path, receipt_ed25519_keys):
    store = SqliteStore(tmp_path / "snapshot-closure.sqlite")
    conn = store._conn  # noqa: SLF001
    required = RequiredCoverageSegment(
        source="jquants",
        dataset=_DATASET,
        segment_id="2026-08",
        segment_start="2026-08-01",
        segment_end="2026-08-31",
        expected_scope={
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "expected_item_unit": "calendar_day",
        },
        expected_items=1,
    )
    raw_record = {"Date": "2026-08-25", "HolidayDivision": "1"}
    evidence = _reconcile_collection_evidence(
        required=required,
        run_id=41,
        raw_pages=[json.dumps({"data": [raw_record]}).encode("utf-8")],
        raw_records=[raw_record],
        structured_records=[raw_record],
        checked_at=_CHECKED_AT,
        source_request={"from": "2026-08-01", "to": "2026-08-31"},
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
    conn.commit()
    coverage_rows = [{
        "dataset": _DATASET,
        "policy_version": _POLICY_VERSION,
        "status": "COMPLETE",
    }]
    return store, receipt, coverage_rows


def test_snapshot_proof_hashes_verified_closure_and_rejects_outer_mutation(
    tmp_path, receipt_ed25519_keys
):
    store, receipt, coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    proof = _coverage_proof(conn, (_DATASET,), coverage_rows)
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
        _coverage_proof(conn, (_DATASET,), coverage_rows)
    store.close()


def test_snapshot_proof_rejects_validly_signed_legacy_v1(
    tmp_path, receipt_ed25519_keys
):
    store, receipt, coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    digests = dict(receipt.digests)
    claims = json.loads(base64.b64decode(digests["signed_body_b64"]))
    claims["version"] = LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION
    legacy_body = canonical_receipt_body(claims)
    digests["signed_body_b64"] = base64.b64encode(legacy_body).decode("ascii")
    digests["signature"] = receipt_ed25519_keys.signing_key.sign(legacy_body)
    digests["body_digest"] = body_digest(legacy_body)
    legacy_receipt = replace(receipt, digests=digests)
    assert (
        audit_signed_receipt_claims(legacy_receipt)["version"]
        == LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION
    )
    with pytest.raises(ReceiptVerificationError, match="audit-only"):
        require_verified_collection_closure(legacy_receipt)

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
        SnapshotRejected, match="v1 is audit-only and not COMPLETE-eligible"
    ):
        _coverage_proof(conn, (_DATASET,), coverage_rows)
    store.close()
