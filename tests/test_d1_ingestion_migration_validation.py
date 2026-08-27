"""Populated and interruption tests for the governed ingestion migration gate."""

from __future__ import annotations

import sqlite3

import pytest

from scripts import d1_ingestion_migration_validation as migration


def _statements(sql: str) -> list[str]:
    statements: list[str] = []
    pending = ""
    for line in sql.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            if pending.strip():
                statements.append(pending)
            pending = ""
    assert not pending.strip()
    return statements


def _connection_through_0011(
    environment: str = "production",
) -> sqlite3.Connection:
    binding = migration.canonical_binding(environment)
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    migration._new_history(conn, binding["migrations_table"])
    for path in migration.MIGRATIONS[:11]:
        conn.executescript(path.read_text(encoding="utf-8"))
        migration._record(conn, binding["migrations_table"], path.name)

    now = "2026-08-24T02:00:00.000Z"
    root = (
        "root-a",
        "root-a",
        "jsda_otc_bond_reference_prices",
        "discover_root",
        "https://market.jsda.or.jp/archive/",
        "root",
        None,
        "c" * 64,
        "completed",
        1,
        1,
        "d" * 64,
        "raw/root.html",
        "audit/root.json",
        "e" * 64,
        "cron",
        now,
        now,
        now,
        now,
    )
    child = (
        "child-a",
        "root-a",
        "jsda_otc_bond_reference_prices",
        "fetch_file",
        "https://market.jsda.or.jp/archive/otc-20020802.csv",
        "2002-08-02",
        "root-a",
        "c" * 64,
        "completed",
        1,
        0,
        "f" * 64,
        "raw/child.csv",
        "audit/child.json",
        "a" * 64,
        "cron",
        now,
        now,
        now,
        now,
    )
    sql = """
        INSERT INTO jsda_acquisition_jobs_v2 (
            work_key,run_key,dataset,job_type,target_url,segment_id,
            parent_work_key,contract_digest,state,attempt,cursor,
            content_digest,raw_key,audit_receipt_key,audit_receipt_digest,
            requested_by,requested_at,first_seen_at,updated_at,completed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    conn.execute(sql, root)
    conn.execute(sql, child)
    conn.execute(
        "INSERT INTO jsda_acquisition_discoveries_v2 "
        "(parent_work_key,child_work_key,run_key,discovered_at) VALUES (?,?,?,?)",
        ("root-a", "child-a", "root-a", now),
    )
    conn.execute(
        """
        INSERT INTO jsda_acquisition_events_v2 (
            work_key,run_key,dataset,job_type,segment_id,attempt,cursor,result,
            reason_code,detail,content_digest,raw_key,audit_receipt_key,
            audit_receipt_digest,occurred_at
        ) VALUES (?,?,?,?,?,?,?,'completed',NULL,?,?,?,?,?,?)
        """,
        (
            "child-a",
            "root-a",
            "jsda_otc_bond_reference_prices",
            "fetch_file",
            "2002-08-02",
            1,
            0,
            "legacy",
            "f" * 64,
            "raw/child.csv",
            "audit/child.json",
            "a" * 64,
            now,
        ),
    )
    conn.commit()
    return conn


def _finish(conn: sqlite3.Connection, environment: str = "production") -> None:
    table = migration.canonical_binding(environment)["migrations_table"]
    for path in migration.MIGRATIONS[11:]:
        conn.executescript(path.read_text(encoding="utf-8"))
        migration._record(conn, table, path.name)
        conn.commit()


def test_populated_legacy_chain_is_resumable_and_preserves_every_graph_row() -> None:
    conn = _connection_through_0011()
    try:
        preflight = migration.validate_preflight_connection(
            conn, environment="production"
        )
        assert preflight["status"] == "RESUMABLE_EXACT_PREFIX"
        simulated = preflight["simulated_postflight"]
        assert simulated["status"] == "EXACT_POSTFLIGHT"
        assert simulated["preservation"] == {
            "jobs": {
                "legacy_rows": 2,
                "current_rows": 2,
                "missing_rows": 0,
                "unexpected_rows": 0,
                "validation_mode": "EXACT_CUTOVER_COPY",
            },
            "events": {
                "legacy_rows": 1,
                "current_rows": 1,
                "missing_rows": 0,
                "unexpected_rows": 0,
                "validation_mode": "EXACT_CUTOVER_COPY",
            },
            "discoveries": {
                "legacy_rows": 1,
                "current_rows": 1,
                "missing_rows": 0,
                "unexpected_rows": 0,
                "validation_mode": "EXACT_CUTOVER_COPY",
            },
        }

        _finish(conn)
        postflight = migration.validate_postflight_connection(
            conn, environment="production"
        )
        assert postflight["applied_migrations"] == list(migration.MIGRATION_NAMES)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute(
            "SELECT COUNT(*) FROM jsda_acquisition_jobs_v2"
        ).fetchone() == (2,)
        assert conn.execute(
            "SELECT COUNT(*) FROM jsda_acquisition_jobs_v3"
        ).fetchone() == (2,)
    finally:
        conn.close()


def test_recorded_postflight_accepts_new_v3_rows_but_never_missing_legacy() -> None:
    conn = _connection_through_0011()
    try:
        _finish(conn)
        now = "2026-08-26T01:30:00Z"
        common = """
            work_key,run_key,dataset,job_type,target_url,segment_id,
            parent_work_key,contract_digest,state,attempt,cursor,requested_by,
            requested_at,first_seen_at,updated_at
        """
        conn.execute(
            f"INSERT INTO jsda_acquisition_jobs_v3 ({common}) "
            "VALUES (?,?,?,?,?,?,NULL,?,'pending',0,0,'cron',?,?,?)",
            (
                "root-new",
                "root-new",
                "jsda_tokyo_repo_rates",
                "discover_root",
                "https://www.jsda.or.jp/trr/",
                "root",
                "b" * 64,
                now,
                now,
                now,
            ),
        )
        conn.execute(
            f"INSERT INTO jsda_acquisition_jobs_v3 ({common}) "
            "VALUES (?,?,?,?,?,?,?,?, 'pending',0,0,'cron',?,?,?)",
            (
                "child-new",
                "root-new",
                "jsda_tokyo_repo_rates",
                "fetch_file",
                "https://www.jsda.or.jp/trr/new.xls",
                "new",
                "root-new",
                "b" * 64,
                now,
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO jsda_acquisition_discoveries_v3 VALUES (?,?,?,?)",
            ("root-new", "child-new", "root-new", now),
        )
        conn.execute(
            """
            INSERT INTO jsda_acquisition_events_v3 (
                work_key,run_key,dataset,job_type,segment_id,attempt,cursor,
                result,audit_receipt_key,audit_receipt_digest,occurred_at
            ) VALUES (?,?,?,?,?,0,0,'continued',?,?,?)
            """,
            (
                "child-new",
                "root-new",
                "jsda_tokyo_repo_rates",
                "fetch_file",
                "new",
                "audit/new.json",
                "c" * 64,
                now,
            ),
        )
        conn.commit()
        # Existing v3 work legitimately advances after cutover.  Mutable
        # state/attempt/cursor are not part of the frozen legacy identity.
        conn.execute(
            "UPDATE jsda_acquisition_jobs_v3 "
            "SET state='running',attempt=attempt+1,cursor=cursor+1,"
            "updated_at=? WHERE work_key='child-a'",
            (now,),
        )
        conn.commit()
        evidence = migration.validate_preflight_connection(
            conn, environment="production"
        )
        assert evidence["status"] == "ALREADY_EXACT"
        preservation = evidence["simulated_postflight"]["preservation"]
        assert preservation["jobs"]["unexpected_rows"] == 2
        assert preservation["events"]["unexpected_rows"] == 1
        assert preservation["discoveries"]["unexpected_rows"] == 1
        assert {
            row["validation_mode"] for row in preservation.values()
        } == {"LEGACY_SUBSET_OF_ACTIVE"}

        with pytest.raises(
            migration.IngestionMigrationError,
            match="cutover copy is incomplete or divergent",
        ):
            migration.validate_postflight_connection(
                conn,
                environment="production",
                require_exact_cutover=True,
            )

        conn.execute("DELETE FROM jsda_acquisition_events_v3 WHERE legacy_event_id=1")
        conn.commit()
        with pytest.raises(migration.IngestionMigrationError, match="lost legacy"):
            migration.validate_postflight_connection(
                conn, environment="production"
            )
    finally:
        conn.close()


def test_every_independently_committed_0012_prefix_resumes_exactly() -> None:
    statements = _statements(migration.MIGRATIONS[11].read_text(encoding="utf-8"))
    assert len(statements) > 20
    for prefix in range(len(statements) + 1):
        conn = _connection_through_0011()
        try:
            for statement in statements[:prefix]:
                conn.executescript(statement)
                conn.commit()
            assert conn.execute(
                "SELECT COUNT(*) FROM jsda_acquisition_jobs_v2"
            ).fetchone() == (2,), prefix
            assert conn.execute(
                "SELECT COUNT(*) FROM jsda_acquisition_events_v2"
            ).fetchone() == (1,), prefix
            assert conn.execute(
                "SELECT COUNT(*) FROM jsda_acquisition_discoveries_v2"
            ).fetchone() == (1,), prefix
            evidence = migration.validate_preflight_connection(
                conn, environment="production"
            )
            assert evidence["status"] == "RESUMABLE_EXACT_PREFIX", prefix
            assert evidence["simulated_postflight"]["status"] == (
                "EXACT_POSTFLIGHT"
            )
        finally:
            conn.close()


def test_old_worker_writes_during_partial_cutover_are_bridged_and_reproved() -> None:
    statements = _statements(migration.MIGRATIONS[11].read_text(encoding="utf-8"))
    conn = _connection_through_0011()
    try:
        # Stop after the v3/control tables and both job bridge triggers, then
        # emulate a still-running v2 Worker before the populated snapshot.
        through_job_bridges = next(
            index
            for index, statement in enumerate(statements, start=1)
            if "jsda_migration_v2_jobs_update_to_v3" in statement
        )
        for statement in statements[:through_job_bridges]:
            conn.executescript(statement)
            conn.commit()
        conn.execute(
            """
            INSERT INTO jsda_acquisition_jobs_v2 (
                work_key,run_key,dataset,job_type,target_url,segment_id,
                parent_work_key,contract_digest,state,attempt,cursor,
                requested_by,requested_at,first_seen_at,updated_at
            ) VALUES (
                'root-b','root-b','jsda_tokyo_repo_rates','discover_root',
                'https://www.jsda.or.jp/trr/','root',NULL,?,'pending',0,0,
                'cron',?,?,?
            )
            """,
            ("b" * 64, "2026-08-25T01:30:00Z", "2026-08-25T01:30:00Z", "2026-08-25T01:30:00Z"),
        )
        conn.commit()
        assert conn.execute(
            "SELECT COUNT(*) FROM jsda_acquisition_jobs_v3 WHERE work_key='root-b'"
        ).fetchone() == (1,)
        evidence = migration.validate_preflight_connection(
            conn, environment="production"
        )
        assert evidence["simulated_postflight"]["preservation"]["jobs"][
            "legacy_rows"
        ] == 3
    finally:
        conn.close()


def test_old_and_new_event_sequences_cannot_collide_during_worker_cutover() -> None:
    statements = _statements(migration.MIGRATIONS[11].read_text(encoding="utf-8"))
    through_legacy_index = next(
        index
        for index, statement in enumerate(statements, start=1)
        if "ux_jsda_events_v3_legacy_event" in statement
    )
    conn = _connection_through_0011()
    try:
        for statement in statements[:through_legacy_index]:
            conn.executescript(statement)
            conn.commit()
        now = "2026-08-25T02:00:00Z"
        event_columns = """
            work_key,run_key,dataset,job_type,segment_id,attempt,cursor,result,
            reason_code,detail,content_digest,raw_key,audit_receipt_key,
            audit_receipt_digest,occurred_at
        """
        values = (
            "child-a",
            "root-a",
            "jsda_otc_bond_reference_prices",
            "fetch_file",
            "2002-08-02",
            2,
            0,
            "completed",
            None,
            "cutover",
            "f" * 64,
            "raw/child.csv",
            "audit/child.json",
            "a" * 64,
            now,
        )
        # New Worker allocates v3 event_id=2.  The old Worker then independently
        # allocates v2 event_id=2.  legacy_event_id keeps both observations.
        conn.execute(
            f"INSERT INTO jsda_acquisition_events_v3 ({event_columns}) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            values,
        )
        conn.execute(
            f"INSERT INTO jsda_acquisition_events_v2 ({event_columns}) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            values,
        )
        conn.commit()
        rows = conn.execute(
            "SELECT event_id,legacy_event_id FROM jsda_acquisition_events_v3 "
            "ORDER BY event_id"
        ).fetchall()
        assert rows == [(1, 1), (2, None), (3, 2)]
    finally:
        conn.close()


def test_bridge_cannot_clobber_newer_v3_and_active_cutover_retires_v2() -> None:
    conn = _connection_through_0011()
    try:
        _finish(conn)
        conn.execute(
            "UPDATE jsda_acquisition_jobs_v3 "
            "SET state='running',updated_at='2026-08-26T00:00:00Z' "
            "WHERE work_key='child-a'"
        )
        conn.execute(
            "UPDATE jsda_acquisition_jobs_v2 "
            "SET state='queued',updated_at='2026-08-25T00:00:00Z' "
            "WHERE work_key='child-a'"
        )
        assert conn.execute(
            "SELECT state,updated_at FROM jsda_acquisition_jobs_v3 "
            "WHERE work_key='child-a'"
        ).fetchone() == ("running", "2026-08-26T00:00:00Z")

        conn.execute(
            "UPDATE jsda_v3_cutover_control SET phase='v3_active', "
            "activated_at='2026-08-26T00:01:00Z', activated_source_sha=?, "
            "drain_evidence_digest=? WHERE singleton=1",
            ("a" * 40, "sha256:" + "b" * 64),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match="v2 acquisition graph is retired"):
            conn.execute(
                "UPDATE jsda_acquisition_jobs_v2 SET attempt=attempt+1 "
                "WHERE work_key='child-a'"
            )
    finally:
        conn.close()


def test_malformed_or_falsely_recorded_partial_0012_fails_closed() -> None:
    malformed = _connection_through_0011()
    try:
        malformed.execute("CREATE TABLE jsda_acquisition_jobs_v3 (work_key TEXT)")
        malformed.commit()
        with pytest.raises(
            migration.IngestionMigrationError,
            match="cannot safely resume 0012",
        ):
            migration.validate_preflight_connection(
                malformed, environment="production"
            )
    finally:
        malformed.close()

    recorded = _connection_through_0011()
    try:
        first = _statements(
            migration.MIGRATIONS[11].read_text(encoding="utf-8")
        )[0]
        recorded.executescript(first)
        migration._record(
            recorded,
            migration.canonical_binding("production")["migrations_table"],
            migration.MIGRATIONS[11].name,
        )
        recorded.commit()
        with pytest.raises(migration.IngestionMigrationError):
            migration.validate_preflight_connection(
                recorded, environment="production"
            )
    finally:
        recorded.close()


def test_history_gaps_foreign_key_breakage_and_cross_environment_fail() -> None:
    gap = _connection_through_0011()
    try:
        table = migration.canonical_binding("production")["migrations_table"]
        gap.execute(f"DELETE FROM {table} WHERE name=?", (migration.MIGRATION_NAMES[4],))
        gap.commit()
        with pytest.raises(migration.IngestionMigrationError, match="exact prefix"):
            migration.validate_preflight_connection(gap, environment="production")
    finally:
        gap.close()

    broken = _connection_through_0011()
    try:
        broken.execute("PRAGMA foreign_keys=OFF")
        broken.execute(
            "INSERT INTO jsda_acquisition_discoveries_v2 VALUES "
            "('missing-parent','missing-child','missing-run','2026-08-25T00:00:00Z')"
        )
        broken.commit()
        with pytest.raises(migration.IngestionMigrationError, match="foreign-key"):
            migration.validate_preflight_connection(
                broken, environment="production"
            )
    finally:
        broken.close()

    staging = _connection_through_0011("staging")
    try:
        with pytest.raises(migration.IngestionMigrationError, match="history is missing"):
            migration.validate_preflight_connection(
                staging, environment="production"
            )
    finally:
        staging.close()
