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
