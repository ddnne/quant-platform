"""Behavioral invariants for the connection-owned C4 candidate renderer."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import inspect
import json
from pathlib import Path
import sqlite3
from types import MappingProxyType

import pytest

from ops.projection_candidate import (
    UNSIGNED_CANDIDATE_SCHEMA,
    UnsignedOpsProjectionCandidate,
)
from ops.d1_sync_signing import d1_sync_digest
from ops.projection_signing import (
    _load_pinned_active_keys,
    open_ops_projection_signing_service,
)
from scripts import export_ops_projection as exporter
from scripts import sync_d1_to_sqlite as sync_script
from tests.test_ops_projection_publish import _source, _test_mirror_identity


FIXED_NOW = "2026-08-26T12:00:00+00:00"


def _projection_source(path: Path, marker: str = "trusted") -> None:
    _source(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS opaque_source_marker (value TEXT NOT NULL)"
        )
        conn.execute("DELETE FROM opaque_source_marker")
        conn.execute("INSERT INTO opaque_source_marker VALUES (?)", (marker,))
        conn.execute(
            "INSERT OR REPLACE INTO sync_change_state "
            "(feed,last_applied_change_seq,updated_at) VALUES (?,?,?)",
            ("jquants_records", 7, "2026-08-26T00:00:00Z"),
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert conn.execute("PRAGMA journal_mode=DELETE").fetchone() == (
            "delete",
        )


def _open_projection_handle(
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    monkeypatch.setattr(
        sync_script,
        "_authenticated_applied_mirror_identity_from_conn",
        _test_mirror_identity(),
    )
    return sync_script.open_authenticated_applied_mirror(path)


def _frozen_test_identity(conn: sqlite3.Connection) -> MappingProxyType:
    identity = _test_mirror_identity()(conn)
    identity["table_counts"] = MappingProxyType(identity["table_counts"])
    return MappingProxyType(identity)


def _tuple_row_factory(
    _cursor: sqlite3.Cursor,
    row: tuple[object, ...],
) -> tuple[object, ...]:
    return tuple(row)


def _assert_exclusive_writer_blocked(path: Path) -> None:
    writer = sqlite3.connect(path, timeout=0)
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            writer.execute("BEGIN EXCLUSIVE")
    finally:
        writer.rollback()
        writer.close()


def _assert_exclusive_writer_available(path: Path) -> None:
    writer = sqlite3.connect(path, timeout=0)
    try:
        writer.execute("BEGIN EXCLUSIVE")
        assert writer.in_transaction
    finally:
        writer.rollback()
        writer.close()


def test_connection_candidate_matches_canonical_renderer_and_is_addressed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _projection_source(source)
    monkeypatch.setattr(exporter, "_now", lambda: FIXED_NOW)
    handle = _open_projection_handle(source, monkeypatch)

    candidate = exporter._render_trusted_projection_candidate(handle)

    assert isinstance(candidate, UnsignedOpsProjectionCandidate)
    assert candidate.candidate_digest == "sha256:" + hashlib.sha256(
        candidate.candidate_bytes
    ).hexdigest()
    assert candidate.identity_digest == "sha256:" + hashlib.sha256(
        candidate.identity_bytes
    ).hexdigest()
    document = json.loads(candidate.candidate_bytes)
    assert document["schema_version"] == UNSIGNED_CANDIDATE_SCHEMA
    assert document["authority_status"] == "PENDING"
    projection = document["projection"]
    assert (
        projection["source_cursor"],
        projection["export_cursor"],
        projection["applied_cursor"],
    ) == (7, 7, 7)
    assert "ops_projection_active" not in projection["sql"]
    assert "SET status='SEALED'" not in projection["sql"]
    assert projection["activation_included"] is False
    assert "issuer_key_id" not in candidate.identity

    equivalent = exporter._render_projection_bundle(
        source,
        generation_id=projection["generation_id"],
        producer_commit_sha=projection["producer_commit_sha"],
        refresh_status=None,
        source_cursor=7,
        export_cursor=7,
        _generated_at=FIXED_NOW,
        _seal_and_activate=False,
    )
    assert projection["source_db_digest"] == equivalent.source_db_digest
    assert projection["content_digest"] == equivalent.content_digest
    assert projection["row_counts"] == dict(equivalent.row_counts)
    assert projection["metadata"] == dict(equivalent.metadata)
    assert projection["envelope"] == dict(equivalent.envelope)
    assert projection["sql"] == equivalent.sql


def test_candidate_captures_one_contract_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _projection_source(source)
    handle = _open_projection_handle(source, monkeypatch)
    capture = exporter._capture_projection_contract_snapshot
    calls = 0

    def observed_capture():
        nonlocal calls
        calls += 1
        return capture()

    monkeypatch.setattr(
        exporter, "_capture_projection_contract_snapshot", observed_capture
    )
    assert exporter._render_trusted_projection_candidate(handle).candidate_bytes
    assert calls == 1


def test_candidate_renderer_never_reopens_the_source_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _projection_source(source)
    monkeypatch.setattr(exporter, "_now", lambda: FIXED_NOW)
    handle = _open_projection_handle(source, monkeypatch)

    def reject_reopen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("candidate renderer reopened a SQLite path")

    monkeypatch.setattr(exporter.sqlite3, "connect", reject_reopen)
    candidate = exporter._render_trusted_projection_candidate(handle)
    assert candidate.candidate_bytes


def test_candidate_renderer_restores_the_authority_connection_row_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _projection_source(source)
    base = _test_mirror_identity()
    observed_row_factories: list[object] = []

    def observed_identity(conn: sqlite3.Connection) -> dict[str, object]:
        observed_row_factories.append(conn.row_factory)
        return base(conn)

    monkeypatch.setattr(
        sync_script,
        "_authenticated_applied_mirror_identity_from_conn",
        observed_identity,
    )
    handle = sync_script.open_authenticated_applied_mirror(source)
    assert exporter._render_trusted_projection_candidate(handle).candidate_bytes
    assert len(observed_row_factories) >= 4
    assert all(row_factory is None for row_factory in observed_row_factories)


def test_caller_owned_renderer_requires_an_existing_snapshot(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _projection_source(source)
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = _tuple_row_factory
    try:
        with pytest.raises(RuntimeError, match="requires an active snapshot"):
            exporter._render_projection_bundle(conn)
        assert conn.in_transaction is False
        assert conn.row_factory is _tuple_row_factory
        _assert_exclusive_writer_available(source)
    finally:
        conn.close()


def test_caller_owned_renderer_preserves_snapshot_and_restores_factory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _projection_source(source)
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = _tuple_row_factory
    conn.execute("BEGIN")
    try:
        bundle = exporter._render_projection_bundle(
            conn,
            generation_id="caller-snapshot-normal",
            producer_commit_sha="a" * 40,
            source_cursor=7,
            export_cursor=7,
            _generated_at=FIXED_NOW,
            _seal_and_activate=False,
        )
        assert bundle.content_digest.startswith("sha256:")
        assert conn.in_transaction is True
        assert conn.row_factory is _tuple_row_factory
        _assert_exclusive_writer_blocked(source)
    finally:
        conn.rollback()
        conn.close()
    _assert_exclusive_writer_available(source)


def test_caller_owned_renderer_rejects_temp_shadow_objects(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _projection_source(source)
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    conn.execute(
        "CREATE TEMP TABLE dataset_coverage AS "
        "SELECT * FROM main.dataset_coverage"
    )
    conn.execute(
        "UPDATE temp.dataset_coverage SET status='COMPLETE' "
        "WHERE dataset='equities_bars_daily'"
    )
    conn.commit()
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    try:
        identity = _frozen_test_identity(conn)
        with pytest.raises(RuntimeError, match="contains TEMP objects"):
            exporter._render_projection_candidate_from_connection(conn, identity)
        with pytest.raises(RuntimeError, match="contains TEMP objects"):
            exporter._render_projection_bundle(
                conn,
                generation_id="temp-shadow",
                producer_commit_sha="a" * 40,
                source_cursor=7,
                export_cursor=7,
                _generated_at=FIXED_NOW,
                _seal_and_activate=False,
            )
        assert conn.in_transaction is True
    finally:
        conn.rollback()
        conn.close()


def test_source_reads_are_authorized_only_from_main(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _projection_source(source)
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    reads: list[tuple[str | None, str | None]] = []

    def authorize(
        action: int,
        table: str | None,
        _column: str | None,
        database: str | None,
        _trigger: str | None,
    ) -> int:
        if action == sqlite3.SQLITE_READ:
            reads.append((table, database))
        return sqlite3.SQLITE_OK

    conn.set_authorizer(authorize)
    try:
        bundle = exporter._render_projection_bundle(
            conn,
            generation_id="main-only",
            producer_commit_sha="a" * 40,
            source_cursor=7,
            export_cursor=7,
            _generated_at=FIXED_NOW,
            _seal_and_activate=False,
        )
        assert bundle.content_digest.startswith("sha256:")
    finally:
        conn.set_authorizer(None)
        conn.rollback()
        conn.close()

    material_reads = [
        (table, database)
        for table, database in reads
        if table is not None and not table.startswith("sqlite_")
    ]
    assert ("dataset_coverage", "main") in material_reads
    assert material_reads
    assert all(database == "main" for _table, database in material_reads)


def test_caller_owned_renderer_exception_preserves_snapshot_and_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.sqlite"
    _projection_source(source)
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = _tuple_row_factory
    conn.execute("BEGIN")

    def fail_inventory(
        _snapshot: object,
    ) -> list[dict[str, object]]:
        raise LookupError("forced renderer failure")

    monkeypatch.setattr(exporter, "_source_inventory", fail_inventory)
    try:
        with pytest.raises(LookupError, match="forced renderer failure"):
            exporter._render_projection_bundle(conn)
        assert conn.in_transaction is True
        assert conn.row_factory is _tuple_row_factory
        _assert_exclusive_writer_blocked(source)
    finally:
        conn.rollback()
        conn.close()
    _assert_exclusive_writer_available(source)


def test_non_ascii_sync_identity_uses_one_canonical_utf8_serialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _projection_source(source)
    base = _test_mirror_identity()

    def unicode_identity(conn: sqlite3.Connection) -> dict[str, object]:
        identity = base(conn)
        identity["issuer_key_id"] = "同期鍵-日本"
        return identity

    monkeypatch.setattr(
        sync_script,
        "_authenticated_applied_mirror_identity_from_conn",
        unicode_identity,
    )
    monkeypatch.setattr(exporter, "_now", lambda: FIXED_NOW)
    first = exporter._render_trusted_projection_candidate(
        sync_script.open_authenticated_applied_mirror(source)
    )
    second = exporter._render_trusted_projection_candidate(
        sync_script.open_authenticated_applied_mirror(source)
    )
    document = json.loads(first.candidate_bytes)
    assert document["sync_identity"]["issuer_key_id"] == "同期鍵-日本"
    assert document["sync_identity_digest"] == d1_sync_digest(
        document["sync_identity"]
    )
    assert "同期鍵-日本".encode("utf-8") in first.candidate_bytes
    assert first.candidate_bytes == second.candidate_bytes
    assert first.identity_bytes == second.identity_bytes


@pytest.mark.parametrize(
    "forged",
    [
        {"generation_id": "caller-generation"},
        {"source_cursor": 999},
        {"row_counts": {"caller": 1}},
        {"envelope": {"caller_complete": True}},
        {"projection_signer": object()},
        {"snapshot_dir": "/caller/path"},
    ],
)
def test_trusted_candidate_rejects_caller_authored_projection_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forged: dict[str, object],
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _projection_source(source)
    handle = _open_projection_handle(source, monkeypatch)
    assert tuple(inspect.signature(exporter._render_trusted_projection_candidate).parameters) == (
        "applied_mirror",
    )
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        exporter._render_trusted_projection_candidate(handle, **forged)
    # Argument rejection happens before the positive capability is consumed.
    assert exporter._render_trusted_projection_candidate(handle).candidate_bytes


def test_connection_renderer_rejects_writable_or_unpinned_connections(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _projection_source(source)
    with sqlite3.connect(source) as writable:
        writable.execute("BEGIN")
        identity = _frozen_test_identity(writable)
        with pytest.raises(RuntimeError, match="source connection is writable"):
            exporter._render_projection_candidate_from_connection(
                writable, identity
            )
        writable.rollback()

    ordinary_ro = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        ordinary_ro.execute("PRAGMA query_only=ON")
        ordinary_ro.execute("BEGIN")
        identity = _frozen_test_identity(ordinary_ro)
        with pytest.raises(RuntimeError, match="not descriptor-bound"):
            exporter._render_projection_candidate_from_connection(
                ordinary_ro, identity
            )
    finally:
        ordinary_ro.rollback()
        ordinary_ro.close()


def test_connection_renderer_rejects_inability_to_hold_one_snapshot(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _projection_source(source)
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        identity = _frozen_test_identity(conn)
        with pytest.raises(RuntimeError, match="cannot hold one SQLite read snapshot"):
            exporter._render_projection_candidate_from_connection(conn, identity)
    finally:
        conn.close()


def test_candidate_fails_closed_on_descriptor_or_schema_identity_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _projection_source(source)
    handle = _open_projection_handle(source, monkeypatch)
    measure = exporter._measure_connection_snapshot
    calls = 0

    def changed_snapshot(conn: sqlite3.Connection):
        nonlocal calls
        calls += 1
        measured = measure(conn)
        return replace(measured, schema_version=measured.schema_version + (calls > 1))

    monkeypatch.setattr(exporter, "_measure_connection_snapshot", changed_snapshot)
    with pytest.raises(RuntimeError, match="source snapshot changed during render"):
        exporter._render_trusted_projection_candidate(handle)
    with pytest.raises(RuntimeError, match="already consumed"):
        exporter._render_trusted_projection_candidate(handle)


def test_candidate_fails_closed_on_sync_content_identity_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _projection_source(source)
    base = _test_mirror_identity()
    calls = 0

    def changing_identity(conn: sqlite3.Connection) -> dict[str, object]:
        nonlocal calls
        calls += 1
        identity = base(conn)
        if calls > 4:
            changed = "sha256:" + "a" * 64
            identity["source_content_digest"] = changed
            identity["local_content_digest"] = changed
        return identity

    monkeypatch.setattr(
        sync_script,
        "_authenticated_applied_mirror_identity_from_conn",
        changing_identity,
    )
    handle = sync_script.open_authenticated_applied_mirror(source)
    with pytest.raises(RuntimeError, match="final identity changed"):
        exporter._render_trusted_projection_candidate(handle)
    with pytest.raises(RuntimeError, match="already consumed"):
        exporter._render_trusted_projection_candidate(handle)


def test_candidate_rejects_path_inode_swap_before_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    _projection_source(source, "trusted")
    _projection_source(replacement, "attacker")
    handle = _open_projection_handle(source, monkeypatch)
    replacement.replace(source)

    with pytest.raises(RuntimeError, match="path was replaced"):
        exporter._render_trusted_projection_candidate(handle)
    with pytest.raises(RuntimeError, match="already consumed"):
        exporter._render_trusted_projection_candidate(handle)


def test_candidate_handle_is_one_shot_and_publication_remains_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _projection_source(source)
    handle = _open_projection_handle(source, monkeypatch)
    candidate = exporter._render_trusted_projection_candidate(handle)
    with pytest.raises(RuntimeError, match="already consumed"):
        exporter._render_trusted_projection_candidate(handle)
    assert candidate.identity["source_cursor"] == 7
    assert open_ops_projection_signing_service() is None
    assert dict(_load_pinned_active_keys()) == {}
