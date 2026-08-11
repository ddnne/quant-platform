"""Phase 6.2.3 signature forgery rejection and staging-only JSDA."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from storage.coverage_ledger import (
    RequiredCoverageSegment,
    is_complete_eligible_receipt,
)
from storage.receipt_crypto import ReceiptSigningKey, generate_keypair
from storage.trusted_receipt import SignedReceiptAuthority


def test_forged_signature_rejected(tmp_path: Path):
    import storage.receipt_crypto as rc

    priv_pem, pub, kid = generate_keypair(key_id="k1")
    keys_path = rc.PUBLIC_KEYS_PATH
    try:
        doc = json.loads(keys_path.read_text(encoding="utf-8"))
    except Exception:
        doc = {"schema_version": 1, "keys": []}
    klist = [k for k in (doc.get("keys") or []) if k.get("key_id") != kid]
    klist.append(
        {
            "key_id": kid,
            "public_key_b64": base64.b64encode(pub).decode(),
            "algorithm": "Ed25519",
        }
    )
    doc["keys"] = klist
    keys_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    priv = load_pem_private_key(priv_pem, password=None)
    assert isinstance(priv, Ed25519PrivateKey)
    auth = SignedReceiptAuthority(signing_key=ReceiptSigningKey(key_id=kid, _private=priv))
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
        required=req, run_id=1, raw=b"{}", observed_items=1, structured_row_count=1
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
