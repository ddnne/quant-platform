"""Structural Coverage V2 invariants: planned segments plus receipts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

from data_contracts import coverage_contract_for
from storage import (
    CollectionReceipt,
    evaluate_required_segments,
    evaluate_segment,
    plan_required_segments,
    read_collection_receipts,
    record_collection_receipt,
)
from storage.sqlite_store import SqliteStore

_REPO = Path(__file__).resolve().parents[1]


def _receipt(
    segment,
    *,
    run_id: int = 1,
    observed: int = 1,
    raw_rows: int | None = None,
    structured_rows: int | None = None,
    pagination_exhausted: bool = True,
) -> CollectionReceipt:
    raw_count = observed if raw_rows is None else raw_rows
    structured_count = raw_count if structured_rows is None else structured_rows
    return CollectionReceipt(
        source=segment.source,
        dataset=segment.dataset,
        segment_id=segment.segment_id,
        segment_start=segment.segment_start,
        segment_end=segment.segment_end,
        expected_scope=segment.expected_scope,
        expected_items=segment.expected_items,
        observed_items=observed,
        raw_page_count=1,
        raw_row_count=raw_count,
        structured_row_count=structured_count,
        pagination_exhausted=pagination_exhausted,
        digests=_signed_digests(
            dataset=segment.dataset,
            segment_id=segment.segment_id,
            source=segment.source,
            run_id=run_id,
            raw_digest="sha256:" + "a" * 64,
        ),
        run_id=run_id,
        status="SUCCESS",
        error=None,
        checked_at=f"2025-04-01T00:00:0{run_id}+00:00",
    )


_SIGNED_KEY = None


def _signed_digests(*, dataset, segment_id, source, run_id, raw_digest):
    """Module-level test signing authority (Ed25519)."""
    global _SIGNED_KEY
    import base64
    import json
    from pathlib import Path
    import storage.receipt_crypto as rc
    from storage.receipt_crypto import (
        ReceiptSigningKey,
        build_signed_digest_fields,
        generate_keypair,
    )
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if _SIGNED_KEY is None:
        priv_pem, pub, kid = generate_keypair(key_id="phase61-test")
        # Append to repo public-key registry so other tests keep verifying.
        keys_path = rc.PUBLIC_KEYS_PATH
        try:
            doc = json.loads(keys_path.read_text(encoding="utf-8"))
        except Exception:
            doc = {"schema_version": 1, "keys": []}
        keys = list(doc.get("keys") or [])
        keys = [k for k in keys if k.get("key_id") != kid]
        keys.append(
            {
                "key_id": kid,
                "public_key_b64": base64.b64encode(pub).decode(),
                "algorithm": "Ed25519",
            }
        )
        doc["keys"] = keys
        keys_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        priv = load_pem_private_key(priv_pem, password=None)
        assert isinstance(priv, Ed25519PrivateKey)
        _SIGNED_KEY = ReceiptSigningKey(key_id=kid, _private=priv)
    signed = build_signed_digest_fields(
        signing_key=_SIGNED_KEY,
        dataset=dataset,
        segment_id=segment_id,
        source=source,
        run_id=run_id,
        raw_digest=raw_digest,
        raw_count=1,
        structured_count=1,
        structured_digest=None,
        pagination_exhausted=True,
        source_request_digest=None,
        raw_manifest_digest=raw_digest,
        structured_generation=run_id,
    )
    signed["raw"] = raw_digest
    return signed



def _short_event_policy():
    return replace(
        coverage_contract_for("fins_summary"),
        history_target_start="2025-01-01",
    )


def test_missing_middle_segment_is_partial_even_with_early_and_late_receipts():
    policy = _short_event_policy()
    required = plan_required_segments(policy, "2025-03-31")
    assert [segment.segment_id for segment in required] == [
        "2025-01", "2025-02", "2025-03",
    ]

    status, evaluated = evaluate_required_segments(
        policy,
        required,
        [_receipt(required[0]), _receipt(required[2], run_id=2)],
    )

    assert status == "PARTIAL"
    assert [item[2] for item in evaluated] == ["COMPLETE", "PARTIAL", "COMPLETE"]
    assert evaluated[1][1] is None


def test_event_zero_successful_exhausted_raw_receipt_is_complete():
    policy = _short_event_policy()
    required = plan_required_segments(policy, "2025-01-31")[0]

    status, detail = evaluate_segment(policy, required, _receipt(required, observed=0))

    assert status == "COMPLETE"
    assert detail["event_zero"] is True


def test_pagination_incomplete_is_not_complete():
    policy = _short_event_policy()
    required = plan_required_segments(policy, "2025-01-31")[0]

    status, detail = evaluate_segment(
        policy, required, _receipt(required, pagination_exhausted=False)
    )

    assert status == "PARTIAL"
    assert detail["reason"] == "pagination not exhausted"


def test_raw_structured_mismatch_is_not_complete():
    policy = _short_event_policy()
    required = plan_required_segments(policy, "2025-01-31")[0]

    status, detail = evaluate_segment(
        policy, required, _receipt(required, observed=3, structured_rows=2)
    )

    assert status == "FAILED"
    assert detail["reason"] == "raw/structured row mismatch"


def test_non_event_month_needs_explicit_expected_items():
    policy = replace(
        coverage_contract_for("equities_bars_daily"),
        history_target_start="2025-01-01",
    )
    required = plan_required_segments(policy, "2025-01-31")[0]

    status, detail = evaluate_segment(
        policy, required, _receipt(required, observed=1)
    )

    assert status == "PARTIAL"
    assert detail["reason"] == "non-event segment lacks explicit expected items"


def test_non_event_month_completes_with_independent_matching_query_plan():
    policy = replace(
        coverage_contract_for("equities_bars_daily"),
        history_target_start="2025-01-01",
    )
    required = plan_required_segments(
        policy,
        "2025-01-31",
        expected_items_by_segment={"2025-01": 31},
    )[0]

    status, detail = evaluate_segment(
        policy, required, _receipt(required, observed=31)
    )

    assert status == "COMPLETE"
    assert detail["event_zero"] is False


def test_receipts_are_run_scoped_and_do_not_define_required_inventory(tmp_path):
    path = tmp_path / "coverage-v2.sqlite"
    store = SqliteStore(path)
    policy = _short_event_policy()
    required = plan_required_segments(policy, "2025-01-31")[0]
    record_collection_receipt(store._conn, _receipt(required))  # noqa: SLF001
    store._conn.commit()  # noqa: SLF001

    tables = {
        row[0]
        for row in store._conn.execute(  # noqa: SLF001
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"coverage_segments", "collection_receipts"} <= tables
    assert store._conn.execute(  # noqa: SLF001
        "SELECT COUNT(*) FROM coverage_segments"
    ).fetchone()[0] == 0
    store.close()

    rows = read_collection_receipts(path, dataset="fins_summary")
    assert [(row["segment_id"], row["run_id"]) for row in rows] == [
        ("2025-01", 1),
    ]


def test_worker_d1_receipt_migration_has_reconciliation_evidence():
    migration = (
        _REPO
        / "platform/workers/ingestion-premium/migrations"
        / "0007_collection_coverage_v2.sql"
    )
    conn = sqlite3.connect(":memory:")
    conn.executescript(migration.read_text(encoding="utf-8"))

    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(collection_receipts)")
    }
    assert {
        "segment_id", "expected_scope", "observed_items", "raw_page_count",
        "raw_row_count", "structured_row_count", "pagination_exhausted",
        "digests_json", "run_id", "status", "error", "checked_at",
    } <= columns
    segment_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(coverage_segments)")
    }
    assert {
        "source", "dataset", "segment_id", "policy_version",
        "segment_start", "segment_end", "expected_scope", "expected_items",
        "status", "receipt_run_id", "evaluated_at", "detail_json",
    } <= segment_columns
    conn.close()


def test_worker_plans_non_event_query_units_before_collection():
    source = (
        _REPO / "platform/workers/ingestion-premium/src/index.ts"
    ).read_text(encoding="utf-8")
    assert "INSERT INTO coverage_segments" in source
    assert 'expected_frequency === "event_driven"' in source
    assert ": queries.length" in source
    assert "if (segment.canonicalMonth)" in source
    assert "await writeRequiredCoverageSegment" in source
