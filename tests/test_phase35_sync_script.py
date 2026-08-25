"""Phase 3.5 — private D1 export and legacy HTTP local-sync behavior.

No explicit source selects the pinned remote D1. Offline artifact tests never
touch the network; live HTTP smokes are ``@pytest.mark.live``.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import pit
from storage.sqlite_store import SqliteStore

_REPO = Path(__file__).resolve().parents[1]
_SYNC = _REPO / "scripts" / "sync_d1_to_sqlite.py"


def _record(value: int, *, ingested_at: str) -> dict:
    payload = {"Code": "8697", "Date": "2025-04-01", "Close": value}
    return {
        "source": "jquants",
        "dataset": "equities_bars_daily",
        "natural_key": '{"Code":"8697","Date":"2025-04-01"}',
        "event_time": "2025-04-01T15:30:00+09:00",
        "available_at": "2025-04-01T15:30:00+09:00",
        "ingested_at": ingested_at,
        "payload": json.dumps(payload, sort_keys=True, separators=(",", ":")),
        "raw_payload": json.dumps(payload, separators=(",", ":")),
    }


def _write_private_d1_export(
    path: Path,
    *,
    current_rows: tuple[dict, ...] = (),
    change_rows: tuple[dict, ...] = (),
) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE jquants_records (
                source TEXT NOT NULL,
                dataset TEXT NOT NULL,
                natural_key TEXT NOT NULL,
                event_time TEXT NOT NULL,
                available_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                payload TEXT,
                raw_payload TEXT,
                PRIMARY KEY (source, dataset, natural_key)
            );
            CREATE TABLE ingestion_change_log (
                change_seq INTEGER PRIMARY KEY,
                table_name TEXT NOT NULL,
                source TEXT NOT NULL,
                dataset TEXT NOT NULL,
                natural_key TEXT NOT NULL,
                event_time TEXT NOT NULL,
                available_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                raw_payload TEXT,
                changed_at TEXT NOT NULL
            );
            CREATE INDEX ix_records_dataset_avail
                ON jquants_records (dataset, available_at);
            """
        )
        record_columns = tuple(_record(0, ingested_at="x"))
        placeholders = ",".join("?" for _ in record_columns)
        for row in current_rows:
            conn.execute(
                f"INSERT INTO jquants_records ({','.join(record_columns)}) "
                f"VALUES ({placeholders})",
                tuple(row[column] for column in record_columns),
            )
        change_columns = ("change_seq", "table_name", *record_columns, "changed_at")
        change_placeholders = ",".join("?" for _ in change_columns)
        for row in change_rows:
            conn.execute(
                f"INSERT INTO ingestion_change_log ({','.join(change_columns)}) "
                f"VALUES ({change_placeholders})",
                tuple(row[column] for column in change_columns),
            )


def test_sync_script_exists():
    assert _SYNC.exists()


def test_sync_defaults_fail_before_provider_acquisition(
    tmp_path, sync_module, monkeypatch
):
    db = tmp_path / "x.sqlite"
    monkeypatch.setenv("INGESTION_PREMIUM_URL", "https://must-not-be-used.invalid")
    called = []

    def fail_private(argv, **_kwargs):
        called.append(argv)
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")

    monkeypatch.setattr(sync_module._private_export.subprocess, "run", fail_private)

    rc = sync_module.main(["--db", str(db)])
    assert rc == 1
    assert called == []
    assert not db.exists()


def test_sync_default_tables_include_pit_tables(sync_module):
    """The default table set covers every PIT fact table."""
    for t in (
        "jquants_records",
        "jquants_daily_bars",
        "jquants_listed_info",
        "jquants_market_calendar",
    ):
        assert t in sync_module.DEFAULT_TABLES
    assert "coverage_segments" in sync_module.DEFAULT_TABLES
    assert "collection_receipts" in sync_module.DEFAULT_TABLES


def test_sync_preserves_nullable_collection_receipt_evidence(tmp_path, sync_module):
    path = tmp_path / "receipt-sync.sqlite"
    store = SqliteStore(path)
    receipt = {
        "source": "jquants",
        "dataset": "fins_summary",
        "segment_id": "2025-01",
        "segment_start": "2025-01-01",
        "segment_end": "2025-01-31",
        "expected_scope": '{"expected_frequency":"event_driven"}',
        "expected_items": None,
        "observed_items": 0,
        "raw_page_count": 1,
        "raw_row_count": 0,
        "structured_row_count": 0,
        "pagination_exhausted": 1,
        "digests_json": '{"raw":"sha256:test"}',
        "run_id": 7,
        "status": "SUCCESS",
        "error": None,
        "checked_at": "2025-02-01T00:00:00Z",
    }

    assert sync_module._sync_one(store, "collection_receipts", [receipt]) == (1, 1)
    saved = store.fetch_all("collection_receipts")
    assert saved[0]["expected_items"] is None
    assert saved[0]["error"] is None
    assert saved[0]["pagination_exhausted"] == 1
    store.close()


def test_sync_preserves_request_planned_coverage_inventory(tmp_path, sync_module):
    store = SqliteStore(tmp_path / "segment-sync.sqlite")
    segment = {
        "source": "jquants",
        "dataset": "equities_bars_daily",
        "segment_id": "2025-01",
        "policy_version": "collection-coverage/v2",
        "segment_start": "2025-01-01",
        "segment_end": "2025-01-31",
        "expected_scope": '{"expected_frequency":"trading_day"}',
        "expected_items": 31,
        "status": "UNKNOWN",
        "receipt_run_id": None,
        "evaluated_at": "2025-01-01T00:00:00Z",
        "detail_json": '{"expected_item_unit":"source_query"}',
    }

    assert sync_module._sync_one(store, "coverage_segments", [segment]) == (1, 1)
    saved = store.fetch_all("coverage_segments")
    assert saved[0]["expected_items"] == 31
    assert saved[0]["receipt_run_id"] is None
    store.close()


def test_cf_export_sync_reaches_nonempty_pit_path(synced_cf_d1_db):
    """CF-shaped export → paginated sync → generic-record PIT bars."""
    assert synced_cf_d1_db.rc == 0
    assert len(synced_cf_d1_db.calls) > 1
    queries = [parse_qs(urlparse(url).query) for url in synced_cf_d1_db.calls]
    assert all(query["limit"] == ["2"] for query in queries)
    assert any("cursor" in query for query in queries[1:])

    bars = pit.get_equity_bars_daily(
        as_of="2025-04-04T15:30:00+09:00",
        code="8697",
        db_path=synced_cf_d1_db.db,
    )
    assert len(bars.rows) == 4
    assert [row["close"] for row in bars.rows] == [100.0, 102.0, 101.0, 104.0]


def test_private_sqlite_export_bootstraps_without_worker_url(
    tmp_path, sync_module, monkeypatch
):
    export = tmp_path / "d1-export.sqlite"
    row = _record(100, ingested_at="2025-04-02T01:00:00+09:00")
    _write_private_d1_export(export, current_rows=(row,))
    monkeypatch.delenv("INGESTION_PREMIUM_URL", raising=False)

    local = tmp_path / "local.sqlite"
    rc = sync_module.main(
        [
            "--db",
            str(local),
            "--d1-export",
            str(export),
            "--table",
            "jquants_records",
        ]
    )

    assert rc == 0
    with sqlite3.connect(local) as conn:
        assert conn.execute("SELECT COUNT(*) FROM jquants_records").fetchone()[0] == 1
        audit = conn.execute(
            "SELECT source_mode,status,source_change_seq,applied_change_seq "
            "FROM local_d1_export_sync_runs"
        ).fetchone()
        assert audit == ("LOCAL_ARTIFACT", "COMPLETE", None, 0)
        policy = conn.execute(
            "SELECT snapshot_ready,publication_state FROM local_snapshot_policy "
            "WHERE singleton=1"
        ).fetchone()
        assert policy == (0, "REJECTED")
    assert sync_module._authenticated_export_cursor_chain(local) == (None, None)


def test_caller_supplied_remote_audit_fields_cannot_bind_projection_cursor(
    tmp_path, sync_module
):
    local = tmp_path / "local.sqlite"
    store = SqliteStore(local)
    sync_module._ensure_control_tables(store._conn)
    sync_module._record_change_seq(store, 7)
    content_digest, table_counts = sync_module._governed_local_content_identity(store)
    sync_module._mark_untrusted_export_sync(
        store,
        export_digest="sha256:" + "a" * 64,
        artifact_format="sql",
        source_mode="WRANGLER_REMOTE",
        sync_kind="FULL",
        source_change_seq=7,
        source_content_digest="sha256:" + "b" * 64,
        local_content_digest=content_digest,
        table_counts=table_counts,
        status="COMPLETE",
    )
    store.close()
    assert sync_module._authenticated_export_cursor_chain(local) == (None, None)
    with sqlite3.connect(local) as conn:
        assert conn.execute(
            "SELECT authority_id,audit_digest,signature,signed_evidence_json "
            "FROM local_d1_export_sync_runs"
        ).fetchone() == (None, None, None, None)


def test_unprovisioned_authority_cannot_persist_signed_complete(
    tmp_path, sync_module
):
    from ops import d1_sync_signing

    consumed = []

    class CallerCapability:
        def _consume_for_signing(self):
            consumed.append(True)
            return {"source_change_seq": 999}

    d1_sync_signing._bind_authenticated_export_authority(
        CallerCapability,
        CallerCapability._consume_for_signing,
    )
    store = SqliteStore(tmp_path / "local.sqlite")
    with pytest.raises(
        d1_sync_signing.D1SyncAuditError,
        match="full-source authority is not provisioned",
    ):
        sync_module._mark_authenticated_export_complete(
            store,
            CallerCapability(),
        )

    assert consumed == []
    assert (
        store._conn.execute(
            "SELECT COUNT(*) FROM local_d1_export_sync_runs"
        ).fetchone()[0]
        == 0
    )
    store.close()


def test_unsigned_mirror_cannot_open_authenticated_handle(
    tmp_path, sync_module
):
    export = tmp_path / "d1-export.sqlite"
    row = _record(100, ingested_at="2025-04-02T01:00:00+09:00")
    _write_private_d1_export(export, current_rows=(row,))
    local = tmp_path / "local.sqlite"
    assert sync_module.main(
        [
            "--db",
            str(local),
            "--d1-export",
            str(export),
            "--table",
            "jquants_records",
        ]
    ) == 0

    with pytest.raises(
        ValueError,
        match="not an authenticated current D1 export",
    ):
        sync_module.open_authenticated_applied_mirror(local)


def test_structural_schema_manifest_rejects_relaxed_pk_and_unique_constraints(
    sync_module,
):
    source = sqlite3.connect(":memory:")
    local = sqlite3.connect(":memory:")
    try:
        source.executescript(
            "CREATE TABLE governed ("
            "id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, "
            "parent_id INTEGER REFERENCES governed(id));"
            "CREATE INDEX ix_governed_parent ON governed(parent_id);"
            "CREATE TRIGGER governed_guard AFTER UPDATE ON governed "
            "BEGIN SELECT NEW.id; END;"
            "INSERT INTO governed VALUES (1,'A',NULL);"
        )
        local.executescript(
            "CREATE TABLE governed (id INTEGER, code TEXT, parent_id INTEGER);"
            "INSERT INTO governed VALUES (1,'A',NULL);"
        )
        with pytest.raises(ValueError, match="schema mismatch"):
            sync_module._private_export._exact_source_local_reconciliation(
                source,
                local,
                ("governed",),
            )
        source_manifest = sync_module._private_export._table_schema_manifest(
            source, "governed"
        )
        assert source_manifest["table_xinfo"][0]["primary_key_ordinal"] == 1
        assert any(index["unique"] == 1 for index in source_manifest["indexes"])
        assert source_manifest["foreign_keys"][0]["from"] == "parent_id"
        assert any(
            row["type"] == "trigger"
            for row in source_manifest["sqlite_master"]
        )
    finally:
        source.close()
        local.close()


def test_private_export_incremental_replay_is_idempotent_and_monotonic(
    tmp_path, sync_module
):
    first = _record(100, ingested_at="2025-04-02T01:00:00+09:00")
    second = _record(101, ingested_at="2025-04-02T02:00:00+09:00")
    change_rows = (
        {"change_seq": 1, "table_name": "jquants_records", **first,
         "changed_at": "2025-04-02T01:00:00+09:00"},
        {"change_seq": 2, "table_name": "jquants_records", **second,
         "changed_at": "2025-04-02T02:00:00+09:00"},
    )
    export = tmp_path / "d1-export.sqlite"
    _write_private_d1_export(export, change_rows=change_rows)
    local = tmp_path / "local.sqlite"
    argv = [
        "--db",
        str(local),
        "--d1-export",
        str(export),
        "--table",
        "jquants_records",
        "--incremental",
        "--page-limit",
        "1",
    ]

    assert sync_module.main(argv) == 0
    assert sync_module.main(argv) == 0
    with sqlite3.connect(local) as conn:
        assert conn.execute(
            "SELECT last_applied_change_seq FROM sync_change_state "
            "WHERE feed='jquants_records'"
        ).fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM jquants_records").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM jquants_records_revisions"
        ).fetchone()[0] == 1
        payload = conn.execute("SELECT payload FROM jquants_records").fetchone()[0]
        assert json.loads(payload)["Close"] == 101


def test_private_change_feed_recovers_after_apply_before_cursor_crash(
    tmp_path, sync_module, monkeypatch
):
    first = _record(100, ingested_at="2025-04-02T01:00:00+09:00")
    second = _record(101, ingested_at="2025-04-02T02:00:00+09:00")
    export = tmp_path / "d1-export.sqlite"
    _write_private_d1_export(
        export,
        change_rows=(
            {"change_seq": 1, "table_name": "jquants_records", **first,
             "changed_at": first["ingested_at"]},
            {"change_seq": 2, "table_name": "jquants_records", **second,
             "changed_at": second["ingested_at"]},
        ),
    )
    source = sync_module._open_export_sqlite(export)
    store = SqliteStore(tmp_path / "local.sqlite")
    real_record_cursor = sync_module._record_change_seq
    crashed = False

    def crash_before_cursor(_store, _value):
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("simulated process interruption")
        return real_record_cursor(_store, _value)

    monkeypatch.setattr(sync_module, "_record_change_seq", crash_before_cursor)
    with pytest.raises(RuntimeError, match="simulated process interruption"):
        sync_module._sync_export_changes(store, source, page_limit=1)
    assert sync_module._last_change_seq(store) == 0
    assert store.count("jquants_records") == 1

    monkeypatch.setattr(sync_module, "_record_change_seq", real_record_cursor)
    assert sync_module._sync_export_changes(store, source, page_limit=1) == (2, 2, 2, 2)
    assert sync_module._last_change_seq(store) == 2
    assert store.count("jquants_records") == 1
    assert store.count("jquants_records_revisions") == 1
    store.close()
    source.close()


def test_private_export_rejects_cursor_rollback(tmp_path, sync_module):
    export = tmp_path / "stale-export.sqlite"
    row = _record(100, ingested_at="2025-04-02T01:00:00+09:00")
    _write_private_d1_export(
        export,
        change_rows=(
            {"change_seq": 2, "table_name": "jquants_records", **row,
             "changed_at": row["ingested_at"]},
        ),
    )
    source = sync_module._open_export_sqlite(export)
    store = SqliteStore(tmp_path / "local.sqlite")
    sync_module._record_change_seq(store, 3)

    with pytest.raises(ValueError, match="older than the local applied cursor"):
        sync_module._sync_export_changes(store, source, page_limit=10)
    assert sync_module._last_change_seq(store) == 3
    store.close()
    source.close()


def test_local_export_is_apply_only_and_cannot_publish_ready(
    tmp_path, sync_module, monkeypatch
):
    export = tmp_path / "d1-export.sqlite"
    row = _record(100, ingested_at="2025-04-02T01:00:00+09:00")
    _write_private_d1_export(
        export,
        current_rows=(row,),
        change_rows=(
            {"change_seq": 1, "table_name": "jquants_records", **row,
             "changed_at": row["ingested_at"]},
        ),
    )
    evidence = tmp_path / "caller-evidence.json"
    evidence.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(sync_module, "DEFAULT_TABLES", ("jquants_records",))
    local = tmp_path / "local.sqlite"

    rc = sync_module.main(
        [
            "--db",
            str(local),
            "--d1-export",
            str(export),
            "--pilot-ready-evidence",
            str(evidence),
        ]
    )

    assert rc == 1
    with sqlite3.connect(local) as conn:
        policy = conn.execute(
            "SELECT snapshot_ready,publication_state,last_error "
            "FROM local_snapshot_policy WHERE singleton=1"
        ).fetchone()
        assert policy[0:2] == (0, "REJECTED")
        assert "authenticated production D1" in policy[2]
        assert conn.execute(
            "SELECT COUNT(*) FROM local_snapshot_manifests"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT last_applied_change_seq FROM sync_change_state "
            "WHERE feed='jquants_records'"
        ).fetchone()[0] == 1


def test_wrangler_export_uses_argv_and_withholds_provider_output(
    tmp_path, sync_module, monkeypatch
):
    calls = []
    secret = "cf-secret-must-not-appear"
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", secret)

    def failed_runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            returncode=1,
            stdout=f"account output {secret}".encode(),
            stderr=f"provider error {secret}".encode(),
        )

    monkeypatch.setattr(sync_module._private_export.subprocess, "run", failed_runner)
    with pytest.raises(RuntimeError, match="provider output withheld") as caught:
        sync_module._private_export.run_wrangler_d1_export(
            output_path=tmp_path / "remote.sql",
        )

    assert secret not in str(caught.value)
    argv, kwargs = calls[0]
    assert secret not in argv
    assert argv[1:4] == ["d1", "export", "quant-ingest"]
    assert "--remote" in argv
    assert "--skip-confirmation" in argv
    assert kwargs["stdin"] is not None
    assert kwargs["stdout"] is not None
    assert kwargs["stderr"] is not None
    assert "shell" not in kwargs

    with pytest.raises(TypeError, match="unexpected keyword argument 'runner'"):
        sync_module._private_export.run_wrangler_d1_export(
            output_path=tmp_path / "cannot-inject.sql",
            runner=failed_runner,
        )


@pytest.mark.parametrize(
    "forbidden",
    [
        ["--wrangler-d1", "fake-db"],
        ["--wrangler-bin", "/tmp/fake-wrangler"],
        ["--wrangler-config", "/tmp/fake.toml"],
        ["--wrangler-env", "staging"],
        ["--token", "secret-on-argv"],
    ],
)
def test_production_wrangler_authority_has_no_public_override(sync_module, forbidden):
    parser = sync_module._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--db=test.sqlite", *forbidden])


def test_governed_wrangler_rejects_wrong_production_database_binding(
    tmp_path, sync_module, monkeypatch
):
    fake_config = tmp_path / "wrangler.toml"
    fake_config.write_text(
        """name = "fake"
[env.production]
name = "fake"
[[env.production.d1_databases]]
binding = "DB"
database_name = "quant-ingest"
database_id = "00000000-0000-0000-0000-000000000000"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sync_module._private_export, "DEFAULT_WRANGLER_CONFIG", fake_config
    )
    with pytest.raises(RuntimeError, match="production Wrangler config"):
        sync_module._private_export.run_wrangler_d1_export(
            output_path=tmp_path / "remote.sql"
        )


def test_ops_projection_failure_propagates_nonzero(
    tmp_path, sync_module, monkeypatch
):
    export = tmp_path / "d1.sqlite"
    row = _record(100, ingested_at="2025-04-02T01:00:00+09:00")
    _write_private_d1_export(export, current_rows=(row,))
    monkeypatch.setattr(sync_module, "_maybe_publish_ops_projection", lambda *a, **k: 9)
    assert sync_module.main(
        [
            "--db",
            str(tmp_path / "local.sqlite"),
            "--d1-export",
            str(export),
            "--table",
            "jquants_records",
            "--publish-ops",
        ]
    ) == 9


def test_sql_export_import_rejects_sqlite_dot_commands(tmp_path, sync_module):
    malicious = tmp_path / "malicious.sql"
    malicious.write_text(".shell echo should-not-run\n", encoding="utf-8")

    with pytest.raises(ValueError, match="dot-commands"):
        sync_module._materialize_d1_export(
            malicious,
            tmp_path / "materialized.sqlite",
        )


def test_wrangler_sql_export_materializes_without_loading_whole_file(
    tmp_path, sync_module
):
    sqlite_export = tmp_path / "source.sqlite"
    row = _record(100, ingested_at="2025-04-02T01:00:00+09:00")
    _write_private_d1_export(sqlite_export, current_rows=(row,))
    sql_export = tmp_path / "wrangler-export.sql"
    with sqlite3.connect(sqlite_export) as conn:
        sql_export.write_text("\n".join(conn.iterdump()) + "\n", encoding="utf-8")

    digest, size, artifact_format = sync_module._materialize_d1_export(
        sql_export,
        tmp_path / "materialized.sqlite",
    )

    assert digest.startswith("sha256:")
    assert size == sql_export.stat().st_size
    assert artifact_format == "sql"
    with sqlite3.connect(tmp_path / "materialized.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM jquants_records").fetchone()[0] == 1


def test_publish_ops_flag_default_off(sync_module):
    """--publish-ops is parsed and defaults OFF; not auto-apply."""
    parser = sync_module._build_parser()
    on = parser.parse_args(["--db=test.sqlite", "--publish-ops"])
    assert on.publish_ops is True
    off = parser.parse_args(["--db=test.sqlite"])
    assert off.publish_ops is False
    help_text = parser.format_help()
    assert "Default OFF for safety" in help_text or "default off" in help_text.lower()
    assert "--apply-remote" in help_text or "apply-remote" in help_text


def test_unsigned_pilot_ready_json_is_rejected(
    tmp_path, sync_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    class OfflineClient:
        def close(self) -> None:
            return None

    monkeypatch.setattr(sync_module, "_new_http_client", OfflineClient)
    monkeypatch.setattr(
        sync_module,
        "_sync_table",
        lambda *_args, **_kwargs: (1, 0, 0, 0, None),
    )
    rc = sync_module.main(
        [
            "--db",
            str(tmp_path / "local.sqlite"),
            "--url",
            "https://offline.invalid",
            "--pilot-ready-evidence",
            str(tmp_path / "unsigned.json"),
        ]
    )
    assert rc == 1


@pytest.mark.live
def test_sync_live_requires_worker_url(tmp_path, sync_module):
    """Live smoke. Skipped unless ``QP_LIVE=1`` and a worker URL is set.

    Run with:
      QP_LIVE=1 INGESTION_PREMIUM_URL=https://... INGESTION_PROXY_TOKEN=... \\
        .venv/bin/python -m pytest tests/test_phase35_sync_script.py::test_sync_live_requires_worker_url
    """
    if not os.environ.get("QP_LIVE"):
        pytest.skip("set QP_LIVE=1 to run live sync smoke")
    url = os.environ.get("INGESTION_PREMIUM_URL")
    if not url:
        pytest.skip("INGESTION_PREMIUM_URL not set")
    rc = sync_module.main([
        "--db", str(tmp_path / "live.sqlite"),
        "--url", url,
        "--table", "jquants_market_calendar",
    ])
    assert rc == 0
