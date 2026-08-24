"""Phase 6.2.3 signature forgery rejection and staging-only JSDA."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from storage.coverage_ledger import (
    RequiredCoverageSegment,
    evaluate_segment,
    is_complete_eligible_receipt,
)
from storage.trusted_receipt import SignedReceiptAuthority
from storage.verified_receipt import ReceiptVerificationError, verify


def test_storage_package_hides_synthetic() -> None:
    import storage

    assert not hasattr(storage, "build_synthetic_complete_receipt")
    assert hasattr(storage, "SignedReceiptAuthority") or hasattr(
        storage, "TrustedReceiptIssuer"
    )


def test_forged_signature_rejected(receipt_ed25519_keys: SimpleNamespace):
    auth = SignedReceiptAuthority(signing_key=receipt_ed25519_keys.signing_key)
    req = RequiredCoverageSegment(
        source="jquants",
        dataset="markets_calendar",
        segment_id="2025-01",
        segment_start="2025-01-01",
        segment_end="2025-01-31",
        expected_scope={"month": "2025-01"},
        expected_items=1,
    )
    good = auth.issue(
        required=req,
        run_id=1,
        raw=b'{"data":[{"Date":"2025-01-01"}]}',
        observed_items=1,
        structured_row_count=1,
    )
    assert is_complete_eligible_receipt(good)
    # Tamper signature
    bad_digests = dict(good.digests)
    bad_digests["signature"] = "ed25519:" + base64.b64encode(b"\x00" * 64).decode()
    from storage.coverage_ledger import CollectionReceipt

    forged = CollectionReceipt(
        source=good.source,
        dataset=good.dataset,
        segment_id=good.segment_id,
        segment_start=good.segment_start,
        segment_end=good.segment_end,
        expected_scope=good.expected_scope,
        expected_items=good.expected_items,
        observed_items=good.observed_items,
        raw_page_count=good.raw_page_count,
        raw_row_count=good.raw_row_count,
        structured_row_count=good.structured_row_count,
        pagination_exhausted=good.pagination_exhausted,
        digests=bad_digests,
        run_id=good.run_id,
        status=good.status,
        error=good.error,
        checked_at=good.checked_at,
    )
    assert not is_complete_eligible_receipt(forged)


def _calendar_required() -> RequiredCoverageSegment:
    return RequiredCoverageSegment(
        source="jquants",
        dataset="markets_calendar",
        segment_id="2025-01",
        segment_start="2025-01-01",
        segment_end="2025-01-31",
        expected_scope={"month": "2025-01"},
        expected_items=1,
    )


def test_signature_transplant_onto_mutated_outer_receipt_rejected(
    receipt_ed25519_keys: SimpleNamespace,
):
    from data_contracts import coverage_contract_for

    auth = SignedReceiptAuthority(signing_key=receipt_ed25519_keys.signing_key)
    req = _calendar_required()
    raw = b'{"data":[{"Date":"2025-01-01"}]}'
    good = auth.issue(
        required=req, run_id=1, raw=raw, observed_items=1, structured_row_count=1
    )
    verify(good, required=req, raw=raw)
    assert is_complete_eligible_receipt(good)

    transplanted = replace(
        good,
        segment_id="2099-12",
        segment_start="2099-12-01",
        segment_end="2099-12-31",
    )
    assert transplanted.digests["signature"] == good.digests["signature"]
    assert transplanted.digests["signed_body_b64"] == good.digests["signed_body_b64"]
    with pytest.raises(ReceiptVerificationError):
        verify(transplanted)
    assert not is_complete_eligible_receipt(transplanted)

    spoofed_required = replace(
        req,
        segment_id="2099-12",
        segment_start="2099-12-01",
        segment_end="2099-12-31",
    )
    policy = coverage_contract_for("markets_calendar")
    status, _detail = evaluate_segment(policy, spoofed_required, transplanted)
    assert status != "COMPLETE"


def test_extra_digests_cannot_override_standard_claims(
    receipt_ed25519_keys: SimpleNamespace,
):
    from storage.coverage_ledger import compute_raw_digest

    auth = SignedReceiptAuthority(signing_key=receipt_ed25519_keys.signing_key)
    req = _calendar_required()
    raw = b'{"data":[{"Date":"2025-01-01"}]}'
    receipt = auth.issue(
        required=req,
        run_id=1,
        raw=raw,
        observed_items=1,
        structured_row_count=1,
        extra_digests={
            "dataset": "evil-dataset",
            "raw_digest": "sha256:" + "f" * 64,
            "eligibility": "TRUSTED_COLLECTION",
            "origin": "operator-note",
        },
    )
    body = json.loads(base64.b64decode(receipt.digests["signed_body_b64"]))
    assert body["dataset"] == req.dataset
    assert "dataset" not in body["extra_digests"]
    assert "raw_digest" not in body["extra_digests"]
    assert body["extra_digests"]["origin"] == "operator-note"
    assert receipt.digests["raw"] == compute_raw_digest(raw)
    assert receipt.digests["raw"] != "sha256:" + "f" * 64
    verify(receipt, required=req, raw=raw)
    assert is_complete_eligible_receipt(receipt)


def test_jsda_staging_never_complete_eligible(tmp_path: Path):
    from ingestion.jsda.r2_parse import run_jsda_staging_parse
    import sqlite3
    from storage.sqlite_store import SqliteStore

    raw = tmp_path / "raw" / "jsda" / "jsda_tokyo_repo_rates" / "file_trrts"
    raw.mkdir(parents=True)
    # minimal csv
    (raw / "x.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    db = tmp_path / "t.sqlite"
    store = SqliteStore(db)
    result = run_jsda_staging_parse(
        raw_root=tmp_path / "raw", conn=store._conn, run_id=1
    )
    assert result.state == "PARSED_STAGING_ONLY"
    assert result.staging_evidence_written >= 1
    # digests may be JSON column or expanded; re-read via ledger helper
    assert result.rows_parsed >= 1
    # Staging path must not produce COMPLETE-eligible signed digests.
    row = store._conn.execute(
        "SELECT digests_json FROM collection_receipts LIMIT 1"
    ).fetchone()
    if row is None:
        # schema may store digests as TEXT digests column
        cols = [
            r[1]
            for r in store._conn.execute(
                "PRAGMA table_info(collection_receipts)"
            ).fetchall()
        ]
        dig_col = "digests" if "digests" in cols else cols[-1]
        row = store._conn.execute(
            f"SELECT {dig_col} FROM collection_receipts LIMIT 1"
        ).fetchone()
    assert row is not None
    digests = json.loads(row[0]) if isinstance(row[0], str) else dict(row[0] or {})
    assert digests.get("origin") == "parsed-staging-only" or digests.get(
        "state"
    ) == "PARSED_STAGING_ONLY"
    assert digests.get("eligibility") != "TRUSTED_COLLECTION" or not digests.get(
        "signature"
    )
