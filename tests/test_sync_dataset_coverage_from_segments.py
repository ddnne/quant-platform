"""Unit tests for surgical dataset_coverage re-aggregate from segments."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

import storage.coverage_ledger as coverage_ledger_module
from data_contracts.coverage import coverage_contract_for
from storage.coverage_ledger import (
    aggregate_status_from_segment_counts,
    build_surgical_reagg_detail,
    compare_exact_coverage_inventory,
    honest_status_counts,
    plan_required_segments,
    record_collection_receipt,
    record_required_segments,
    refresh_coverage_ledger,
    sync_dataset_coverage_from_segments,
    verify_exact_coverage_complete,
)
from storage.coverage_ledger_io import (
    persist_refreshed_coverage,
    preserve_existing_complete_coverage_row,
    update_dataset_coverage_row,
)
from tests.receipt_test_support import (
    _SignedReceiptAuthority,
    _reconcile_collection_evidence,
)


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------


def test_aggregate_all_complete_is_complete():
    assert (
        aggregate_status_from_segment_counts({"COMPLETE": 104}) == "COMPLETE"
    )
    assert (
        aggregate_status_from_segment_counts({"COMPLETE": 164, "PARTIAL": 0})
        == "COMPLETE"
    )


def test_aggregate_any_partial_stays_partial():
    assert (
        aggregate_status_from_segment_counts({"COMPLETE": 100, "PARTIAL": 4})
        == "PARTIAL"
    )
    assert (
        aggregate_status_from_segment_counts({"PARTIAL": 3}) == "PARTIAL"
    )
    assert (
        aggregate_status_from_segment_counts(
            {"COMPLETE": 10, "STALE": 1}
        )
        == "PARTIAL"
    )


def test_aggregate_any_failed_is_failed():
    assert (
        aggregate_status_from_segment_counts(
            {"COMPLETE": 99, "FAILED": 1}
        )
        == "FAILED"
    )
    assert aggregate_status_from_segment_counts({"FAILED": 2}) == "FAILED"


def test_aggregate_empty_inventory_is_unknown_never_complete():
    assert aggregate_status_from_segment_counts({}) == "UNKNOWN"
    assert aggregate_status_from_segment_counts({"COMPLETE": 0}) == "UNKNOWN"


def test_honest_status_counts_drops_zeros():
    assert honest_status_counts({"COMPLETE": 104, "PARTIAL": 0}) == {
        "COMPLETE": 104
    }
    assert honest_status_counts({"COMPLETE": 100, "PARTIAL": 4}) == {
        "COMPLETE": 100,
        "PARTIAL": 4,
    }


def test_build_surgical_reagg_detail_merges_counts():
    existing = {
        "checks": [{"id": "C8", "status": "pass"}],
        "coverage_v2": {
            "required_segments": 104,
            "status_counts": {"COMPLETE": 100, "PARTIAL": 4},
        },
    }
    detail = build_surgical_reagg_detail(
        existing,
        status_counts={"COMPLETE": 104},
        required_segments=104,
        audit={"wave": "W70", "at": "2026-08-16T00:00:00+00:00"},
    )
    assert detail["aggregate_source"] == "surgical_reagg_from_coverage_segments"
    assert detail["coverage_v2"]["status_counts"] == {"COMPLETE": 104}
    assert detail["coverage_v2"]["required_segments"] == 104
    assert detail["coverage_v2"]["surgical_reagg"]["wave"] == "W70"
    assert detail["coverage_v2"]["surgical_reagg"]["prev_status_counts"] == {
        "COMPLETE": 100,
        "PARTIAL": 4,
    }
    # Preserve unrelated checks.
    assert detail["checks"] == [{"id": "C8", "status": "pass"}]


def test_generic_io_helpers_cannot_mint_or_preserve_new_complete() -> None:
    conn = _make_conn()
    policy = coverage_contract_for(_DATASET)
    _insert_dataset_coverage(
        conn,
        dataset=_DATASET,
        status="PARTIAL",
        policy_version=policy.policy_version,
        status_counts={"PARTIAL": 1},
    )
    row = dict(conn.execute(
        "SELECT * FROM dataset_coverage WHERE dataset=?",
        (_DATASET,),
    ).fetchone())
    row["status"] = "COMPLETE"
    row["raw_retention_required"] = 0
    row["structured_reconciliation_required"] = 0

    with pytest.raises(ValueError, match="cannot write aggregate COMPLETE"):
        persist_refreshed_coverage(
            conn,
            delete_keys=(),
            segment_rows=(),
            coverage_rows=(row,),
        )
    with pytest.raises(ValueError, match="cannot write aggregate COMPLETE"):
        update_dataset_coverage_row(
            conn,
            dataset=_DATASET,
            status="COMPLETE",
            detail_json="{}",
            evaluated_at=_CHECKED_AT,
        )
    with pytest.raises(RuntimeError, match="disappeared or changed policy"):
        preserve_existing_complete_coverage_row(conn, row)
    assert conn.execute(
        "SELECT status FROM dataset_coverage WHERE dataset=?", (_DATASET,)
    ).fetchone()[0] == "PARTIAL"


def test_generic_io_freezes_mapping_before_complete_policy_check() -> None:
    class ConfusedStatus(dict):
        def get(self, key, default=None):
            if key == "status":
                return "PARTIAL"
            return super().get(key, default)

        def __getitem__(self, key):
            if key == "status":
                return "COMPLETE"
            return super().__getitem__(key)

    conn = _make_conn()
    policy = coverage_contract_for(_DATASET)
    _insert_dataset_coverage(
        conn,
        dataset=_DATASET,
        status="PARTIAL",
        policy_version=policy.policy_version,
        status_counts={"PARTIAL": 1},
    )
    row = dict(conn.execute(
        "SELECT * FROM dataset_coverage WHERE dataset=?",
        (_DATASET,),
    ).fetchone())
    row["raw_retention_required"] = 0
    row["structured_reconciliation_required"] = 0
    conn.execute("DELETE FROM dataset_coverage WHERE dataset=?", (_DATASET,))
    conn.commit()

    with pytest.raises(ValueError, match="cannot write aggregate COMPLETE"):
        persist_refreshed_coverage(
            conn,
            delete_keys=(),
            segment_rows=(),
            coverage_rows=(ConfusedStatus(row),),
        )
    assert conn.execute("SELECT COUNT(*) FROM dataset_coverage").fetchone()[0] == 0


def test_generic_io_rejects_status_string_subclass_adapter_confusion() -> None:
    class EvilStr(str):
        def __eq__(self, other):
            return False

    conn = _make_conn()
    policy = coverage_contract_for(_DATASET)
    _insert_dataset_coverage(
        conn,
        dataset=_DATASET,
        status="PARTIAL",
        policy_version=policy.policy_version,
        status_counts={"PARTIAL": 1},
    )

    with pytest.raises(TypeError, match="exact built-in SQLite scalar"):
        update_dataset_coverage_row(
            conn,
            dataset=_DATASET,
            status=EvilStr("COMPLETE"),
            detail_json="{}",
            evaluated_at=_CHECKED_AT,
        )
    assert conn.execute(
        "SELECT status FROM dataset_coverage WHERE dataset=?", (_DATASET,)
    ).fetchone()[0] == "PARTIAL"


def test_complete_preserver_freezes_policy_once_and_never_rewrites_it() -> None:
    class StatefulPolicy(dict):
        def __init__(self, value):
            super().__init__(value)
            self.policy_reads = 0

        def __getitem__(self, key):
            if key == "policy_version":
                self.policy_reads += 1
                return (
                    "collection-coverage/v3"
                    if self.policy_reads == 1
                    else "collection-coverage/v2"
                )
            return super().__getitem__(key)

    conn = _make_conn()
    _insert_dataset_coverage(
        conn,
        dataset=_DATASET,
        status="COMPLETE",
        policy_version="collection-coverage/v2",
        status_counts={"COMPLETE": 1},
    )
    row = dict(conn.execute(
        "SELECT * FROM dataset_coverage WHERE dataset=?",
        (_DATASET,),
    ).fetchone())
    row["raw_retention_required"] = 0
    row["structured_reconciliation_required"] = 0
    hostile = StatefulPolicy(row)

    with pytest.raises(RuntimeError, match="disappeared or changed policy"):
        preserve_existing_complete_coverage_row(conn, hostile)
    assert hostile.policy_reads == 1
    assert tuple(conn.execute(
        "SELECT status,policy_version FROM dataset_coverage WHERE dataset=?",
        (_DATASET,),
    ).fetchone()) == ("COMPLETE", "collection-coverage/v2")


# ---------------------------------------------------------------------------
# DB integration (in-memory; never invents segments)
# ---------------------------------------------------------------------------


def _make_conn(path=":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE coverage_segments (
            source TEXT NOT NULL,
            dataset TEXT NOT NULL,
            segment_id TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            segment_start TEXT,
            segment_end TEXT,
            expected_scope TEXT,
            expected_items INTEGER,
            status TEXT NOT NULL,
            receipt_run_id INTEGER,
            evaluated_at TEXT,
            detail_json TEXT,
            PRIMARY KEY (source, dataset, segment_id, policy_version)
        );
        CREATE TABLE dataset_coverage (
            dataset TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            policy_version TEXT,
            collection_scope TEXT,
            history_target_start TEXT,
            history_target_end_rule TEXT,
            coverage_mode TEXT,
            expected_frequency TEXT,
            universe_rule TEXT,
            raw_retention_required INTEGER,
            structured_reconciliation_required INTEGER,
            governance_tier TEXT,
            observed_start TEXT,
            observed_end TEXT,
            row_count INTEGER,
            source_run_id INTEGER,
            evaluated_at TEXT,
            detail_json TEXT
        );
        CREATE TABLE collection_receipts (
            source TEXT NOT NULL,
            dataset TEXT NOT NULL,
            segment_id TEXT NOT NULL,
            segment_start TEXT NOT NULL,
            segment_end TEXT NOT NULL,
            expected_scope TEXT NOT NULL,
            expected_items INTEGER,
            observed_items INTEGER NOT NULL,
            raw_page_count INTEGER NOT NULL,
            raw_row_count INTEGER NOT NULL,
            structured_row_count INTEGER NOT NULL,
            pagination_exhausted INTEGER NOT NULL,
            digests_json TEXT NOT NULL,
            run_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            checked_at TEXT NOT NULL,
            PRIMARY KEY (source, dataset, segment_id, run_id)
        );
        """
    )
    return conn


_DATASET = "markets_calendar"
_CUTOFF = "2008-02-29"
_CHECKED_AT = "2008-02-29T12:00:00+00:00"


def _freeze_cutoff(monkeypatch) -> None:
    monkeypatch.setattr(coverage_ledger_module, "_now", lambda: _CHECKED_AT)


def _insert_dataset_coverage(
    conn: sqlite3.Connection,
    *,
    dataset: str,
    status: str,
    policy_version: str,
    status_counts: dict[str, int],
    checks: list[dict] | None = None,
) -> None:
    detail = {
        "checks": checks if checks is not None else [{"id": "C8", "status": "pass"}],
        "coverage_v2": {
            "required_segments": sum(status_counts.values()),
            "status_counts": status_counts,
        },
    }
    conn.execute(
        """
        INSERT INTO dataset_coverage (
            dataset,status,policy_version,governance_tier,detail_json
        ) VALUES (?, ?, ?, 'governed', ?)
        """,
        (dataset, status, policy_version, json.dumps(detail)),
    )


def _seed_exact_inventory(
    conn: sqlite3.Connection,
    *,
    dc_status: str,
    authority: _SignedReceiptAuthority | None,
    statuses: tuple[str, ...] = ("COMPLETE", "COMPLETE"),
    checks: list[dict] | None = None,
):
    policy = coverage_contract_for(_DATASET)
    segments = plan_required_segments(
        policy,
        _CUTOFF,
        source="jquants",
    )
    assert len(segments) == len(statuses) == 2
    record_required_segments(conn, segments)
    for run_id, (segment, status) in enumerate(zip(segments, statuses), start=1):
        selected_run: int | None = None
        if status == "COMPLETE":
            selected_run = run_id if authority is not None else 999 + run_id
            if authority is not None:
                raw_record = {"segment": segment.segment_id, "value": 1}
                evidence = _reconcile_collection_evidence(
                    required=segment,
                    run_id=run_id,
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
                record_collection_receipt(conn, authority.issue(evidence))
        conn.execute(
            """
            UPDATE coverage_segments
            SET status=?,receipt_run_id=?,evaluated_at=?
            WHERE source=? AND dataset=? AND segment_id=? AND policy_version=?
            """,
            (
                status,
                selected_run,
                _CHECKED_AT,
                segment.source,
                segment.dataset,
                segment.segment_id,
                policy.policy_version,
            ),
        )
    counts = {
        status: statuses.count(status) for status in sorted(set(statuses))
    }
    _insert_dataset_coverage(
        conn,
        dataset=_DATASET,
        status=dc_status,
        policy_version=policy.policy_version,
        status_counts=counts,
        checks=checks,
    )
    conn.commit()
    return segments


def _signed_authority(receipt_ed25519_keys) -> _SignedReceiptAuthority:
    return _SignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    )


@pytest.mark.parametrize("dc_status", ("PARTIAL", "COMPLETE"))
def test_fake_selected_receipts_never_mint_or_retain_complete(
    monkeypatch,
    dc_status: str,
) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    _seed_exact_inventory(conn, dc_status=dc_status, authority=None)
    conn.execute("DROP TABLE collection_receipts")
    conn.commit()

    result = sync_dataset_coverage_from_segments(conn, datasets=[_DATASET])[0]

    assert result["inventory_status"] == "EXACT"
    assert result["selected_receipt_status"] == "INVALID"
    assert result["action"] == "selected_receipt_invalid"
    assert result["to"] == "PARTIAL"
    assert conn.execute(
        "SELECT status FROM dataset_coverage WHERE dataset=?", (_DATASET,)
    ).fetchone()[0] == "PARTIAL"


def test_generic_sync_requires_transition_authority_even_with_exact_signed_closure(
    monkeypatch,
    receipt_ed25519_keys,
) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    _seed_exact_inventory(
        conn,
        dc_status="PARTIAL",
        authority=_signed_authority(receipt_ed25519_keys),
    )

    result = sync_dataset_coverage_from_segments(conn, datasets=[_DATASET])[0]

    assert result["inventory_status"] == "EXACT"
    assert result["selected_receipt_status"] == "VERIFIED"
    assert result["action"] == "transition_authority_required"
    assert result["to"] == "PARTIAL"


def test_existing_complete_is_retained_only_after_exact_signed_verification(
    monkeypatch,
    receipt_ed25519_keys,
) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    _seed_exact_inventory(
        conn,
        dc_status="COMPLETE",
        authority=_signed_authority(receipt_ed25519_keys),
    )

    result = sync_dataset_coverage_from_segments(conn, datasets=[_DATASET])[0]

    assert result["action"] == "verify_only"
    assert result["status"] == "COMPLETE"
    assert result["inventory_status"] == "EXACT"
    assert result["selected_receipt_status"] == "VERIFIED"


def test_old_policy_complete_aggregate_cannot_retain_exact_v3_segments(
    monkeypatch,
    receipt_ed25519_keys,
) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    _seed_exact_inventory(
        conn,
        dc_status="COMPLETE",
        authority=_signed_authority(receipt_ed25519_keys),
    )
    conn.execute(
        "UPDATE dataset_coverage SET policy_version='collection-coverage/v2' "
        "WHERE dataset=?",
        (_DATASET,),
    )
    conn.commit()

    result = sync_dataset_coverage_from_segments(conn, datasets=[_DATASET])[0]

    assert result["action"] == "prior_aggregate_policy_mismatch"
    assert result["old_policy_version"] == "collection-coverage/v2"
    assert result["current_policy_version"] == "collection-coverage/v3"
    assert result["to"] == "PARTIAL"


def _allow_refresh_validation(monkeypatch) -> None:
    monkeypatch.setattr(coverage_ledger_module, "run_coverage", lambda *a, **k: [])
    monkeypatch.setattr(
        coverage_ledger_module,
        "_dataset_status",
        lambda _results: ("COMPLETE", 1, _CUTOFF, _CUTOFF),
    )
    monkeypatch.setattr(
        coverage_ledger_module,
        "_jsda_validation_status",
        lambda _conn, _dataset: ("COMPLETE", 1, "2002-08-02", "2002-08-06"),
    )


def test_generic_refresh_never_promotes_exact_signed_inventory(
    monkeypatch,
    receipt_ed25519_keys,
) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    _allow_refresh_validation(monkeypatch)
    _seed_exact_inventory(
        conn,
        dc_status="PARTIAL",
        authority=_signed_authority(receipt_ed25519_keys),
    )

    row = refresh_coverage_ledger(
        conn,
        ":memory:",
        datasets=(_DATASET,),
        today=_CUTOFF,
    )[0]

    gate = json.loads(row["detail_json"])["coverage_v2"][
        "aggregate_complete_gate"
    ]
    assert gate["computed_status"] == "COMPLETE"
    assert gate["blocker"] == "transition_authority_required"
    assert row["status"] == "PARTIAL"
    assert conn.execute(
        "SELECT status FROM dataset_coverage WHERE dataset=?", (_DATASET,)
    ).fetchone()[0] == "PARTIAL"


def test_refresh_caller_cutoff_cannot_shrink_and_retain_complete(
    monkeypatch,
    receipt_ed25519_keys,
) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    _allow_refresh_validation(monkeypatch)
    _seed_exact_inventory(
        conn,
        dc_status="COMPLETE",
        authority=_signed_authority(receipt_ed25519_keys),
    )

    row = refresh_coverage_ledger(
        conn,
        ":memory:",
        datasets=(_DATASET,),
        today="2008-01-31",
    )[0]

    gate = json.loads(row["detail_json"])["coverage_v2"][
        "aggregate_complete_gate"
    ]
    assert gate["inventory_target_end"] == _CUTOFF
    assert gate["inventory_status"] == "MISMATCH"
    assert gate["blocker"] == "inventory_mismatch"
    assert row["status"] == "PARTIAL"
    assert conn.execute(
        "SELECT COUNT(*) FROM coverage_segments WHERE dataset=?", (_DATASET,)
    ).fetchone()[0] == 1


def test_refresh_write_snapshot_blocks_preverify_segment_mutation(
    monkeypatch,
    tmp_path,
    receipt_ed25519_keys,
) -> None:
    db_path = tmp_path / "refresh-race.sqlite"
    conn = _make_conn(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    _freeze_cutoff(monkeypatch)
    _allow_refresh_validation(monkeypatch)
    _seed_exact_inventory(
        conn,
        dc_status="COMPLETE",
        authority=_signed_authority(receipt_ed25519_keys),
    )
    attacker = sqlite3.connect(db_path, timeout=0)
    attack_state = {"ran": False, "blocked": False}

    def mutate_after_prior_aggregate_read(sql: str) -> None:
        if attack_state["ran"] or not sql.startswith(
            "SELECT source,dataset,segment_id,policy_version"
        ):
            return
        attack_state["ran"] = True
        try:
            attacker.execute(
                "UPDATE coverage_segments SET expected_scope='{}' "
                "WHERE dataset=? AND segment_id='2008-01'",
                (_DATASET,),
            )
            attacker.commit()
        except sqlite3.OperationalError as exc:
            attacker.rollback()
            attack_state["blocked"] = "locked" in str(exc).lower()

    conn.set_trace_callback(mutate_after_prior_aggregate_read)
    row = refresh_coverage_ledger(
        conn,
        db_path,
        datasets=(_DATASET,),
        today=_CUTOFF,
    )[0]
    conn.set_trace_callback(None)

    gate = json.loads(row["detail_json"])["coverage_v2"][
        "aggregate_complete_gate"
    ]
    assert attack_state == {"ran": True, "blocked": True}
    assert gate["inventory_status"] == "EXACT"
    assert gate["selected_receipt_status"] == "VERIFIED"
    assert gate["blocker"] is None
    assert row["status"] == "COMPLETE"
    attacker.close()
    conn.close()


def test_refresh_caller_index_subset_cannot_retain_complete(
    monkeypatch,
    receipt_ed25519_keys,
) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    _allow_refresh_validation(monkeypatch)
    dataset = "jsda_otc_bond_reference_prices"
    policy = coverage_contract_for(dataset)
    full_index = (
        Path(__file__).parent / "fixtures" / "jsda_otc_official_index_tiny.html"
    ).read_text(encoding="utf-8")
    segments = plan_required_segments(
        policy,
        "2002-08-06",
        source="jsda",
        index_text=full_index,
    )
    assert len(segments) == 3
    authority = _signed_authority(receipt_ed25519_keys)
    record_required_segments(conn, segments)
    for run_id, segment in enumerate(segments, start=10):
        raw_record = {"segment": segment.segment_id, "value": 1}
        evidence = _reconcile_collection_evidence(
            required=segment,
            run_id=run_id,
            raw_pages=[json.dumps({"data": [raw_record]}).encode("utf-8")],
            raw_records=[raw_record],
            structured_records=[raw_record],
            checked_at=_CHECKED_AT,
            source_request={"date": segment.segment_id},
        )
        record_collection_receipt(conn, authority.issue(evidence))
        conn.execute(
            "UPDATE coverage_segments SET status='COMPLETE',receipt_run_id=? "
            "WHERE source=? AND dataset=? AND segment_id=? AND policy_version=?",
            (
                run_id,
                segment.source,
                segment.dataset,
                segment.segment_id,
                policy.policy_version,
            ),
        )
    _insert_dataset_coverage(
        conn,
        dataset=dataset,
        status="COMPLETE",
        policy_version=policy.policy_version,
        status_counts={"COMPLETE": 3},
    )
    conn.commit()
    subset_index = """
        <table><tr><td>2002.8.2</td>
        <td><a href='files/S020802.csv'>CSV</a></td></tr></table>
    """

    row = refresh_coverage_ledger(
        conn,
        ":memory:",
        datasets=(dataset,),
        today="2002-08-06",
        index_text=subset_index,
    )[0]

    gate = json.loads(row["detail_json"])["coverage_v2"][
        "aggregate_complete_gate"
    ]
    assert gate["inventory_status"] == "PENDING"
    assert gate["blocker"] == "inventory_authority_pending"
    assert row["status"] == "PARTIAL"
    assert conn.execute(
        "SELECT COUNT(*) FROM coverage_segments WHERE dataset=?", (dataset,)
    ).fetchone()[0] == 1


def test_shared_verifier_pins_identity_and_receipt_reads_to_one_snapshot(
    tmp_path,
    receipt_ed25519_keys,
) -> None:
    db_path = tmp_path / "snapshot-race.sqlite"
    conn = _make_conn(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    _seed_exact_inventory(
        conn,
        dc_status="COMPLETE",
        authority=_signed_authority(receipt_ed25519_keys),
    )
    attacker = sqlite3.connect(db_path, timeout=1)
    attack_state = {"ran": False, "reader_in_transaction": False}

    def mutate_between_compare_and_receipt_join(sql: str) -> None:
        if attack_state["ran"] or "LEFT JOIN collection_receipts" not in sql:
            return
        attack_state["ran"] = True
        attack_state["reader_in_transaction"] = conn.in_transaction
        attacker.execute(
            "UPDATE coverage_segments SET expected_scope='{}' "
            "WHERE dataset=? AND segment_id='2008-01'",
            (_DATASET,),
        )
        attacker.commit()

    conn.set_trace_callback(mutate_between_compare_and_receipt_join)
    verified = verify_exact_coverage_complete(
        conn,
        (_DATASET,),
        target_end=_CUTOFF,
    )
    conn.set_trace_callback(None)

    assert attack_state == {"ran": True, "reader_in_transaction": True}
    assert verified.complete_eligible is True
    # The concurrent mutation becomes visible only after the pinned verifier
    # snapshot ends, and an immediate new comparison rejects it.
    assert compare_exact_coverage_inventory(
        conn,
        (_DATASET,),
        target_end=_CUTOFF,
    ).exact is False
    attacker.close()
    conn.close()


def test_sync_write_lock_prevents_post_verify_preupdate_mutation(
    monkeypatch,
    tmp_path,
    receipt_ed25519_keys,
) -> None:
    db_path = tmp_path / "sync-race.sqlite"
    conn = _make_conn(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    _freeze_cutoff(monkeypatch)
    _seed_exact_inventory(
        conn,
        dc_status="COMPLETE",
        authority=_signed_authority(receipt_ed25519_keys),
    )
    attacker = sqlite3.connect(db_path, timeout=0)
    attack_state = {"ran": False, "blocked": False}

    def attempt_mutation_during_sync(sql: str) -> None:
        if attack_state["ran"] or "FROM coverage_segments" not in sql:
            return
        attack_state["ran"] = True
        try:
            attacker.execute(
                "UPDATE coverage_segments SET expected_scope='{}' "
                "WHERE dataset=? AND segment_id='2008-01'",
                (_DATASET,),
            )
            attacker.commit()
        except sqlite3.OperationalError as exc:
            attacker.rollback()
            attack_state["blocked"] = "locked" in str(exc).lower()

    conn.set_trace_callback(attempt_mutation_during_sync)
    result = sync_dataset_coverage_from_segments(conn, datasets=[_DATASET])[0]
    conn.set_trace_callback(None)

    assert attack_state == {"ran": True, "blocked": True}
    assert result["action"] == "verify_only"
    assert result["status"] == "COMPLETE"
    assert compare_exact_coverage_inventory(
        conn,
        (_DATASET,),
        target_end=_CUTOFF,
    ).exact is True
    attacker.close()
    conn.close()


@pytest.mark.parametrize("dc_status", ("PARTIAL", "COMPLETE"))
def test_deleted_required_segment_cannot_promote_or_remain_complete(
    monkeypatch,
    receipt_ed25519_keys,
    dc_status: str,
) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    segments = _seed_exact_inventory(
        conn,
        dc_status=dc_status,
        authority=_signed_authority(receipt_ed25519_keys),
    )
    conn.execute(
        "DELETE FROM coverage_segments WHERE dataset=? AND segment_id=?",
        (_DATASET, segments[-1].segment_id),
    )
    conn.commit()

    result = sync_dataset_coverage_from_segments(conn, datasets=[_DATASET])[0]

    assert result["action"] == "inventory_mismatch"
    assert result["inventory"]["expected_count"] == 2
    assert result["inventory"]["actual_count"] == 1
    assert result["inventory"]["missing"]
    assert result["to"] == "PARTIAL"


def test_failed_then_deleted_segment_stays_noncomplete(
    monkeypatch,
    receipt_ed25519_keys,
) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    segments = _seed_exact_inventory(
        conn,
        dc_status="COMPLETE",
        authority=_signed_authority(receipt_ed25519_keys),
        statuses=("COMPLETE", "FAILED"),
    )
    first = sync_dataset_coverage_from_segments(conn, datasets=[_DATASET])[0]
    assert first["to"] == "FAILED"
    conn.execute(
        "DELETE FROM coverage_segments WHERE dataset=? AND segment_id=?",
        (_DATASET, segments[-1].segment_id),
    )
    conn.commit()

    second = sync_dataset_coverage_from_segments(conn, datasets=[_DATASET])[0]

    assert second["action"] == "inventory_mismatch"
    assert second["to"] == "PARTIAL"
    assert second["inventory"]["missing"]


def test_unexpected_current_policy_segment_demotes_complete(
    monkeypatch,
    receipt_ed25519_keys,
) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    segments = _seed_exact_inventory(
        conn,
        dc_status="COMPLETE",
        authority=_signed_authority(receipt_ed25519_keys),
    )
    row = conn.execute(
        "SELECT * FROM coverage_segments WHERE dataset=? AND segment_id=?",
        (_DATASET, segments[-1].segment_id),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO coverage_segments VALUES (
            ?,?,?,?,'2008-03-01','2008-03-31',?,?, 'COMPLETE',77,?,?
        )
        """,
        (
            row["source"],
            row["dataset"],
            "2008-03",
            row["policy_version"],
            row["expected_scope"],
            row["expected_items"],
            _CHECKED_AT,
            "{}",
        ),
    )
    conn.commit()

    result = sync_dataset_coverage_from_segments(conn, datasets=[_DATASET])[0]

    assert result["action"] == "inventory_mismatch"
    assert result["inventory"]["unexpected"]
    assert result["to"] == "PARTIAL"


def test_cross_source_duplicate_demotes_complete(
    monkeypatch,
    receipt_ed25519_keys,
) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    segments = _seed_exact_inventory(
        conn,
        dc_status="COMPLETE",
        authority=_signed_authority(receipt_ed25519_keys),
    )
    row = conn.execute(
        "SELECT * FROM coverage_segments WHERE dataset=? AND segment_id=?",
        (_DATASET, segments[0].segment_id),
    ).fetchone()
    values = dict(row)
    values["source"] = "jsda"
    conn.execute(
        "INSERT INTO coverage_segments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        tuple(values.values()),
    )
    conn.commit()

    result = sync_dataset_coverage_from_segments(conn, datasets=[_DATASET])[0]

    assert result["action"] == "inventory_mismatch"
    assert result["inventory"]["duplicate"]
    assert result["inventory"]["unexpected"]
    assert result["to"] == "PARTIAL"


def test_wrong_policy_replacement_is_rejected_but_old_audit_copy_is_ignored(
    monkeypatch,
    receipt_ed25519_keys,
) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    segments = _seed_exact_inventory(
        conn,
        dc_status="COMPLETE",
        authority=_signed_authority(receipt_ed25519_keys),
    )
    row = conn.execute(
        "SELECT * FROM coverage_segments WHERE dataset=? AND segment_id=?",
        (_DATASET, segments[0].segment_id),
    ).fetchone()
    values = dict(row)
    values["policy_version"] = "collection-coverage/v2"
    conn.execute(
        "INSERT INTO coverage_segments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        tuple(values.values()),
    )
    # Coexisting V2 audit history does not invalidate the exact V3 row.
    retained = sync_dataset_coverage_from_segments(conn, datasets=[_DATASET])[0]
    assert retained["status"] == "COMPLETE"

    conn.execute(
        "DELETE FROM coverage_segments WHERE source=? AND dataset=? "
        "AND segment_id=? AND policy_version=?",
        (
            row["source"],
            row["dataset"],
            row["segment_id"],
            row["policy_version"],
        ),
    )
    conn.commit()
    replaced = sync_dataset_coverage_from_segments(conn, datasets=[_DATASET])[0]

    assert replaced["action"] == "inventory_mismatch"
    assert replaced["inventory"]["wrong_policy"]
    assert replaced["to"] == "PARTIAL"


@pytest.mark.parametrize(
    "dataset",
    (
        "equities_bars_daily_am",
        "jsda_otc_bond_reference_prices",
        "jsda_tokyo_repo_rates",
        "equities_investor_types",
    ),
    ids=("tip", "archive-index", "time-series", "non-v3"),
)
def test_non_deterministic_or_non_v3_inventory_is_authority_pending(
    monkeypatch,
    dataset: str,
) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    policy = coverage_contract_for(dataset)
    conn.execute(
        """
        INSERT INTO coverage_segments VALUES (
            'jquants',?,?,?,'2008-02-01','2008-02-29','{}',1,
            'COMPLETE',1,?,'{}'
        )
        """,
        (dataset, "observed-only", policy.policy_version, _CHECKED_AT),
    )
    _insert_dataset_coverage(
        conn,
        dataset=dataset,
        status="COMPLETE",
        policy_version=policy.policy_version,
        status_counts={"COMPLETE": 1},
    )
    conn.commit()

    result = sync_dataset_coverage_from_segments(conn, datasets=[dataset])[0]

    assert result["action"] == "inventory_authority_pending"
    assert result["inventory_status"] == "PENDING"
    assert result["to"] == "PARTIAL"
    detail = json.loads(conn.execute(
        "SELECT detail_json FROM dataset_coverage WHERE dataset=?", (dataset,)
    ).fetchone()[0])
    assert "required_segments" not in detail["coverage_v2"]
    assert detail["coverage_v2"]["surgical_reagg"]["inventory_status"] == "PENDING"


def test_dry_run_reports_rejection_without_write(
    monkeypatch,
    receipt_ed25519_keys,
) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    _seed_exact_inventory(
        conn,
        dc_status="PARTIAL",
        authority=_signed_authority(receipt_ed25519_keys),
    )

    result = sync_dataset_coverage_from_segments(
        conn,
        datasets=[_DATASET],
        dry_run=True,
    )[0]

    assert result["action"] == "transition_authority_required"
    assert result["dry_run"] is True
    assert conn.execute(
        "SELECT status FROM dataset_coverage WHERE dataset=?", (_DATASET,)
    ).fetchone()[0] == "PARTIAL"


def test_sync_skip_missing_dataset_coverage(monkeypatch) -> None:
    conn = _make_conn()
    _freeze_cutoff(monkeypatch)
    conn.execute(
        """
        INSERT INTO coverage_segments VALUES (
            'jquants','orphan','2020-01','collection-coverage/v2',
            '2020-01-01','2020-01-31','{}',1,
            'COMPLETE',1,?,'{}'
        )
        """,
        (_CHECKED_AT,),
    )
    conn.commit()

    result = sync_dataset_coverage_from_segments(conn, datasets=["orphan"])[0]

    assert result["action"] == "skip_missing_dataset_coverage"
    assert conn.execute(
        "SELECT COUNT(*) FROM dataset_coverage WHERE dataset='orphan'"
    ).fetchone()[0] == 0
