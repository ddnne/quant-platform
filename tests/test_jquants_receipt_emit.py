"""Lane H: J-Quants collection receipt helpers are honest and wireable."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from data_contracts import coverage_contract_for
from storage.coverage_ledger import (
    SYNTHETIC_RECEIPT_MARKER,
    build_collection_receipt,
    build_synthetic_complete_receipt,
    compute_raw_digest,
    is_synthetic_receipt,
    plan_required_segments,
    record_collection_receipt,
    record_required_segments,
    refresh_coverage_ledger,
)
from storage.sqlite_store import SqliteStore


def test_compute_raw_digest_is_sha256():
    raw = b'{"data":[1]}'
    d = compute_raw_digest(raw)
    assert d.startswith("sha256:")
    assert len(d) == len("sha256:") + 64


def test_build_collection_receipt_real_digest(tmp_path: Path):
    policy = coverage_contract_for("markets_calendar")
    segs = list(plan_required_segments(policy, "2026-08-11", source="jquants"))
    assert segs
    req = segs[0]
    raw = b'{"data":[{"Date":"2026-08-11"}]}'
    r = build_collection_receipt(
        required=req,
        run_id=1,
        raw=raw,
        observed_items=1,
        structured_row_count=1,
    )
    assert r.digests["raw"] == compute_raw_digest(raw)
    assert not is_synthetic_receipt(r)


def test_synthetic_receipt_marked(tmp_path: Path):
    policy = coverage_contract_for("markets_calendar")
    segs = list(plan_required_segments(policy, "2026-08-11", source="jquants"))
    req = segs[0]
    r = build_synthetic_complete_receipt(required=req, run_id=1)
    assert is_synthetic_receipt(r)
    assert r.digests.get("origin") == SYNTHETIC_RECEIPT_MARKER["origin"]


def test_record_receipt_into_db(tmp_path: Path):
    db = tmp_path / "t.sqlite"
    store = SqliteStore(db)
    policy = coverage_contract_for("markets_calendar")
    segs = list(plan_required_segments(policy, "2026-08-11", source="jquants"))
    req = segs[0]
    record_required_segments(store._conn, [req])
    raw = b'{"data":[]}'
    r = build_collection_receipt(
        required=req,
        run_id=1,
        raw=raw,
        observed_items=0,
        structured_row_count=0,
    )
    record_collection_receipt(store._conn, r)
    store._conn.commit()
    n = store._conn.execute("select count(*) from collection_receipts").fetchone()[0]
    assert n == 1
    store.close()


def _unsigned_authority():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    from storage.receipt_crypto import ReceiptSigningKey, generate_keypair
    from storage.trusted_receipt import SignedReceiptAuthority

    priv_pem, _pub, kid = generate_keypair(key_id="emit-test")
    priv = load_pem_private_key(priv_pem, password=None)
    assert isinstance(priv, Ed25519PrivateKey)
    return SignedReceiptAuthority(
        signing_key=ReceiptSigningKey(key_id=kid, _private=priv)
    )


def test_emit_segment_receipt_requires_authority(tmp_path: Path):
    from ingestion.jquants.receipts import emit_segment_receipt

    store = SqliteStore(tmp_path / "t.sqlite")
    policy = coverage_contract_for("markets_calendar")
    req = list(plan_required_segments(policy, "2026-08-11", source="jquants"))[0]
    with pytest.raises(TypeError, match="SignedReceiptAuthority is required"):
        emit_segment_receipt(
            store._conn,
            required=req,
            run_id=1,
            raw=b'{"data":[1]}',
            observed_items=1,
            structured_row_count=1,
            authority=None,  # type: ignore[arg-type]
        )
    store.close()


def test_require_signed_receipt_authority_fails_closed_without_key(monkeypatch):
    from ingestion.jquants.receipts import require_signed_receipt_authority

    monkeypatch.setattr(
        "storage.trusted_receipt.load_signing_key",
        lambda **kwargs: None,
    )
    with pytest.raises(RuntimeError, match="signing key not configured"):
        require_signed_receipt_authority()


def test_emit_segment_receipt_rejects_empty_raw_success(tmp_path: Path):
    from ingestion.jquants.receipts import emit_segment_receipt

    store = SqliteStore(tmp_path / "t.sqlite")
    policy = coverage_contract_for("markets_calendar")
    req = list(plan_required_segments(policy, "2026-08-11", source="jquants"))[0]
    auth = _unsigned_authority()
    with pytest.raises(ValueError, match="empty-raw SUCCESS is forbidden"):
        emit_segment_receipt(
            store._conn,
            required=req,
            run_id=1,
            raw=b"",
            observed_items=1,
            structured_row_count=1,
            authority=auth,
        )
    n = store._conn.execute("select count(*) from collection_receipts").fetchone()[0]
    assert n == 0
    store.close()
