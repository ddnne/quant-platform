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


def _tmp_service(receipt_ed25519_keys):
    """Governed service bound to an ephemeral key; never production keys."""
    from ingestion.runtime_authority import open_governed_receipt_service

    return open_governed_receipt_service(pem=receipt_ed25519_keys.private_pem)


def _persisted_market_calendar_row(store: SqliteStore) -> dict:
    row = {
        "source": "jquants",
        "dataset": "markets_calendar",
        "natural_key": '{"Date":"2026-08-11"}',
        "event_time": "2026-08-11T09:00:00+09:00",
        "available_at": "2026-08-11T09:00:00+09:00",
        "ingested_at": "2026-08-11T09:00:00+09:00",
        "payload": '{"Date":"2026-08-11"}',
        "raw_payload": '{"Date":"2026-08-11"}',
    }
    store.upsert("jquants_records", [row], commit=False)
    return row


def test_emit_segment_receipt_requires_authority(tmp_path: Path):
    from ingestion.jquants.receipts import emit_segment_receipt

    store = SqliteStore(tmp_path / "t.sqlite")
    policy = coverage_contract_for("markets_calendar")
    req = list(plan_required_segments(policy, "2026-08-11", source="jquants"))[0]
    raw_path = tmp_path / "raw.json"
    raw_path.write_bytes(b'[{"Date":"2026-08-11"}]')
    raw_path.chmod(0o444)
    row = _persisted_market_calendar_row(store)
    with pytest.raises(TypeError, match="GovernedReceiptService is required"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=1,
            raw_artifact_paths=(raw_path,),
            raw_records=({"Date": "2026-08-11"},),
            structured_table="jquants_records",
            normalized_records=(row,),
            service=None,  # type: ignore[arg-type]
        )
    store.close()


def test_require_governed_receipt_service_fails_closed_without_key(monkeypatch):
    from ingestion.jquants.receipts import require_governed_receipt_service

    monkeypatch.setattr(
        "storage.trusted_receipt.load_signing_key",
        lambda **kwargs: None,
    )
    with pytest.raises(RuntimeError, match="signing authority is not configured"):
        require_governed_receipt_service()


def test_emit_segment_receipt_rejects_empty_raw_success(
    tmp_path: Path, receipt_ed25519_keys
):
    from ingestion.jquants.receipts import emit_segment_receipt

    store = SqliteStore(tmp_path / "t.sqlite")
    policy = coverage_contract_for("markets_calendar")
    req = list(plan_required_segments(policy, "2026-08-11", source="jquants"))[0]
    raw_path = tmp_path / "empty.json"
    raw_path.write_bytes(b"")
    raw_path.chmod(0o444)
    row = _persisted_market_calendar_row(store)
    with pytest.raises(ValueError, match="non-empty raw pages"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=1,
            raw_artifact_paths=(raw_path,),
            raw_records=({"Date": "2026-08-11"},),
            structured_table="jquants_records",
            normalized_records=(row,),
            service=_tmp_service(receipt_ed25519_keys),
        )
    n = store._conn.execute("select count(*) from collection_receipts").fetchone()[0]
    assert n == 0
    store.close()


def test_emit_segment_receipt_records_verified_signature(
    tmp_path: Path, receipt_ed25519_keys
):
    from ingestion.jquants.receipts import emit_segment_receipt
    from storage.coverage_ledger import is_complete_eligible_receipt
    from storage.receipt_crypto import verify_receipt_signature

    store = SqliteStore(tmp_path / "t.sqlite")
    policy = coverage_contract_for("markets_calendar")
    req = list(plan_required_segments(policy, "2026-08-11", source="jquants"))[0]
    record_required_segments(store._conn, [req])
    raw = b'{"data":[{"Date":"2026-08-11"}]}'
    raw_path = tmp_path / "market-calendar.json"
    raw_path.write_bytes(raw)
    raw_path.chmod(0o444)
    row = _persisted_market_calendar_row(store)
    receipt = emit_segment_receipt(
        store,
        required=req,
        run_id=1,
        raw_artifact_paths=(raw_path,),
        raw_records=({"Date": "2026-08-11"},),
        structured_table="jquants_records",
        normalized_records=(row,),
        service=_tmp_service(receipt_ed25519_keys),
    )
    assert receipt.status == "SUCCESS"
    assert receipt.digests.get("eligibility") == "TRUSTED_COLLECTION"
    assert str(receipt.digests.get("signature") or "").startswith("ed25519:")
    assert verify_receipt_signature(receipt.digests)
    assert is_complete_eligible_receipt(receipt)
    n = store._conn.execute("select count(*) from collection_receipts").fetchone()[0]
    assert n == 1
    store.close()


def test_emit_segment_receipt_rejects_same_count_forged_raw_records(
    tmp_path: Path, receipt_ed25519_keys
):
    """The signed raw digest must bind content, not merely caller row count."""
    from ingestion.jquants.receipts import emit_segment_receipt

    store = SqliteStore(tmp_path / "t.sqlite")
    policy = coverage_contract_for("markets_calendar")
    req = list(plan_required_segments(policy, "2026-08-11", source="jquants"))[0]
    raw_path = tmp_path / "market-calendar.json"
    raw_path.write_bytes(b'{"data":[{"Date":"2026-08-11"}]}')
    raw_path.chmod(0o444)
    row = _persisted_market_calendar_row(store)

    with pytest.raises(ValueError, match="do not match content"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=1,
            raw_artifact_paths=(raw_path,),
            raw_records=({"Date": "2099-01-01"},),
            structured_table="jquants_records",
            normalized_records=(row,),
            service=_tmp_service(receipt_ed25519_keys),
        )

    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    store.close()
