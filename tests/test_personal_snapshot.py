"""Behavior tests for the small, unsigned personal SQLite snapshot."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

import pytest
import pit

from _coreseed import draft_pit_observation_clock
from personal_history_compact_support import (
    insert_compact_bar,
    insert_compact_master,
    install_compact_schema,
    stamp_compact_manifest,
)
from paper_runtime.personal_snapshot import (
    PERSONAL_SNAPSHOT_FORMAT,
    PersonalSnapshotError,
    materialize_personal_snapshot,
    verify_personal_snapshot,
)
from paper_runtime.snapshot import data_snapshot_id


_CLOSURE_A = "sha256:" + "a" * 64
_CLOSURE_B = "sha256:" + "b" * 64


def _open_wal_source(
    path: Path, *, policy_state: str | None = None
) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.executescript(
        """
        CREATE TABLE research_rows (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE jquants_records (
            source TEXT NOT NULL,
            dataset TEXT NOT NULL,
            natural_key TEXT NOT NULL,
            event_time TEXT NOT NULL,
            available_at TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            payload TEXT NOT NULL,
            raw_payload TEXT NOT NULL,
            PRIMARY KEY (source,dataset,natural_key)
        );
        """
    )
    connection.execute("INSERT INTO research_rows VALUES (1, 'main-file')")
    records = (
        (
            "markets_calendar",
            "cal-0101",
            "2024-01-01",
            {"Date": "2024-01-01", "HolidayDivision": "0"},
        ),
        (
            "markets_calendar",
            "cal-0102",
            "2024-01-02",
            {"Date": "2024-01-02", "HolidayDivision": "1"},
        ),
        (
            "markets_calendar",
            "cal-1230",
            "2024-12-30",
            {"Date": "2024-12-30", "HolidayDivision": "1"},
        ),
        (
            "markets_calendar",
            "cal-1231",
            "2024-12-31",
            {"Date": "2024-12-31", "HolidayDivision": "0"},
        ),
        (
            "equities_bars_daily",
            "bar-0102",
            "2024-01-02",
            {"Code": "1301", "Date": "2024-01-02", "Close": 100.0},
        ),
        (
            "equities_bars_daily",
            "bar-1230",
            "2024-12-30",
            {"Code": "1301", "Date": "2024-12-30", "Close": 110.0},
        ),
    )
    connection.executemany(
        "INSERT INTO jquants_records VALUES ('jquants',?,?,?,"
        "'2023-01-01T00:00:00+09:00','2024-01-01T00:00:00+09:00',?,?)",
        tuple(
            (
                dataset,
                key,
                f"{day}T15:00:00+09:00",
                json.dumps(payload, sort_keys=True),
                json.dumps(payload, sort_keys=True),
            )
            for dataset, key, day, payload in records
        ),
    )
    if policy_state is not None:
        connection.executescript(
            """
            CREATE TABLE local_snapshot_policy (
                singleton INTEGER PRIMARY KEY CHECK (singleton=1),
                require_manifest INTEGER NOT NULL,
                snapshot_ready INTEGER NOT NULL,
                sync_started_at TEXT,
                last_error TEXT,
                publication_state TEXT NOT NULL CHECK (
                    publication_state IN
                    ('BUILDING','SYNCED','VALIDATING','READY','REJECTED')
                ),
                active_build_id TEXT,
                active_snapshot_id TEXT
            );
            CREATE TABLE local_snapshot_manifests (
                snapshot_id TEXT PRIMARY KEY,
                format TEXT NOT NULL,
                committed_at TEXT NOT NULL,
                source_run_id INTEGER NOT NULL,
                change_seq INTEGER NOT NULL,
                manifest_json TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO local_snapshot_policy VALUES "
            "(1,1,0,'2024-12-31T00:00:00Z','source-deferred',?,NULL,NULL)",
            (policy_state,),
        )
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.execute("INSERT INTO research_rows VALUES (2, 'wal-committed')")
    connection.commit()
    return connection


def _materialize(source: Path, destination: Path):
    return materialize_personal_snapshot(
        source,
        destination,
        required_datasets=("markets_calendar", "equities_bars_daily"),
        period_start="2024-01-01",
        period_end="2024-12-31",
        closure_digests=(_CLOSURE_B, _CLOSURE_A),
    )


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_materialize_captures_committed_wal_and_publishes_unsigned_read_only_artifacts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "current.sqlite"
    writer = _open_wal_source(source)
    try:
        wal = source.with_name(source.name + "-wal")
        assert wal.stat().st_size > 0

        snapshot = _materialize(source, tmp_path / "snapshots")

        with sqlite3.connect(snapshot.db_path) as copied:
            rows = copied.execute(
                "SELECT id, value FROM research_rows ORDER BY id"
            ).fetchall()
            assert copied.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert rows == [(1, "main-file"), (2, "wal-committed")]

        manifest = json.loads(snapshot.manifest_path.read_text(encoding="utf-8"))
        assert manifest == {
            "closure_digests": [_CLOSURE_A, _CLOSURE_B],
            "database_file": snapshot.db_path.name,
            "database_sha256": snapshot.database_sha256,
            "format": PERSONAL_SNAPSHOT_FORMAT,
            "logical_data_snapshot_id": snapshot.logical_data_snapshot_id,
            "observed_datasets": [
                {
                    "dataset_id": "equities_bars_daily",
                    "evidence_status": "OBSERVED",
                    "row_count": 2,
                    "min_event_date": "2024-01-02",
                    "max_event_date": "2024-12-30",
                },
                {
                    "dataset_id": "markets_calendar",
                    "evidence_status": "OBSERVED",
                    "row_count": 4,
                    "min_event_date": "2024-01-01",
                    "max_event_date": "2024-12-31",
                },
            ],
            "period": {"end": "2024-12-31", "start": "2024-01-01"},
            "personal_policy": {
                "format": "personal-draft-policy/v1",
                "local_snapshot_policy_state": "SYNCED",
                "publication_state": "PERSONAL_DRAFT",
                "require_manifest": 0,
                "snapshot_ready": 0,
            },
            "required_datasets": ["equities_bars_daily", "markets_calendar"],
            "snapshot_id": snapshot.snapshot_id,
            "source_policy_provenance": {
                "last_error": None,
                "publication_state": None,
                "require_manifest": None,
                "row_present": False,
                "snapshot_ready": None,
                "table_present": False,
            },
        }
        assert snapshot.database_sha256 == _sha256(snapshot.db_path)
        assert snapshot.logical_data_snapshot_id == data_snapshot_id(snapshot.db_path)
        assert snapshot.db_path.name == (
            snapshot.database_sha256.replace(":", "_", 1) + ".sqlite"
        )
        assert snapshot.manifest_path.name == (
            snapshot.snapshot_id.replace(":", "_", 1) + ".manifest.json"
        )
        assert not ({"ready", "signature", "attestation"} & set(manifest))
        for artifact in (snapshot.db_path, snapshot.manifest_path):
            mode = artifact.stat().st_mode
            assert stat.S_IMODE(mode) == 0o444
            assert not mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        assert verify_personal_snapshot(snapshot) == snapshot
        assert snapshot.verify() == snapshot
    finally:
        writer.close()


def test_materialize_accepts_typed_personal_bars_with_generic_calendar(
    tmp_path: Path,
) -> None:
    source = tmp_path / "typed.sqlite"
    writer = _open_wal_source(source)
    try:
        writer.executescript(
            """
            CREATE TABLE jquants_daily_bars (
                source TEXT NOT NULL,
                code TEXT NOT NULL,
                date TEXT NOT NULL,
                event_time TEXT NOT NULL,
                available_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                close REAL,
                raw_payload TEXT,
                PRIMARY KEY (source,code,date)
            );
            INSERT INTO jquants_daily_bars VALUES
                ('jquants','1301','2024-01-02','2024-01-02T15:00:00+09:00',
                 '2024-01-02T15:00:00+09:00','2024-01-02T16:00:00+09:00',
                 100.0,NULL),
                ('jquants','1301','2024-12-30','2024-12-30T15:30:00+09:00',
                 '2024-12-30T15:30:00+09:00','2024-12-30T16:00:00+09:00',
                 110.0,NULL);
            DELETE FROM jquants_records
            WHERE dataset='equities_bars_daily';
            """
        )
        writer.commit()
        snapshot = _materialize(source, tmp_path / "snapshots")
    finally:
        writer.close()

    manifest = json.loads(snapshot.manifest_path.read_text(encoding="utf-8"))
    bars_evidence = next(
        item
        for item in manifest["observed_datasets"]
        if item["dataset_id"] == "equities_bars_daily"
    )
    assert bars_evidence == {
        "dataset_id": "equities_bars_daily",
        "evidence_status": "OBSERVED",
        "row_count": 2,
        "min_event_date": "2024-01-02",
        "max_event_date": "2024-12-30",
    }
    with draft_pit_observation_clock("2025-01-01T00:00:00+09:00"):
        assert pit.get_jquants_records(
            as_of="2025-01-01",
            dataset="equities_bars_daily",
            db_path=snapshot.db_path,
        ).rows == []
        bars = pit.get_equity_bars_daily(
            as_of="2025-01-01", db_path=snapshot.db_path
        ).rows
    assert [(row["date"], row["close"]) for row in bars] == [
        ("2024-01-02", 100.0),
        ("2024-12-30", 110.0),
    ]


def test_materialize_rejects_mixed_generic_and_typed_bars(tmp_path: Path) -> None:
    source = tmp_path / "mixed.sqlite"
    writer = _open_wal_source(source)
    try:
        writer.executescript(
            """
            CREATE TABLE jquants_daily_bars (
                source TEXT NOT NULL,
                code TEXT NOT NULL,
                date TEXT NOT NULL,
                event_time TEXT NOT NULL,
                available_at TEXT NOT NULL,
                PRIMARY KEY (source,code,date)
            );
            INSERT INTO jquants_daily_bars VALUES
                ('jquants','1301','2024-01-02','2024-01-02T15:00:00+09:00',
                 '2024-01-02T15:00:00+09:00');
            """
        )
        writer.commit()
        with pytest.raises(PersonalSnapshotError, match="mix generic and typed"):
            _materialize(source, tmp_path / "snapshots")
    finally:
        writer.close()


def test_materialize_is_idempotent_for_same_database_and_canonical_scope(
    tmp_path: Path,
) -> None:
    source = tmp_path / "current.sqlite"
    writer = _open_wal_source(source)
    try:
        first = _materialize(source, tmp_path / "snapshots")
        second = materialize_personal_snapshot(
            source,
            tmp_path / "snapshots",
            required_datasets=(
                "equities_bars_daily",
                "markets_calendar",
                "equities_bars_daily",
            ),
            period_start="2024-01-01",
            period_end="2024-12-31",
            closure_digests=(_CLOSURE_A, _CLOSURE_B, _CLOSURE_A),
        )
    finally:
        writer.close()

    assert second == first
    assert {path.name for path in (tmp_path / "snapshots").iterdir()} == {
        first.manifest_path.name,
        first.db_path.name,
    }


@pytest.mark.parametrize("source_state", ["SYNCED", "REJECTED"])
def test_materialize_neutralizes_only_the_copy_of_a_managed_non_ready_database(
    tmp_path: Path,
    source_state: str,
) -> None:
    source = tmp_path / "managed.sqlite"
    writer = _open_wal_source(source, policy_state=source_state)
    try:
        snapshot = _materialize(source, tmp_path / "snapshots")
        source_policy = writer.execute(
            "SELECT require_manifest,snapshot_ready,publication_state,last_error "
            "FROM local_snapshot_policy WHERE singleton=1"
        ).fetchone()
    finally:
        writer.close()

    assert source_policy == (1, 0, source_state, "source-deferred")
    manifest = json.loads(snapshot.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_policy_provenance"] == {
        "last_error": "source-deferred",
        "publication_state": source_state,
        "require_manifest": 1,
        "row_present": True,
        "snapshot_ready": 0,
        "table_present": True,
    }
    assert manifest["personal_policy"]["publication_state"] == "PERSONAL_DRAFT"

    with sqlite3.connect(snapshot.db_path) as copied:
        copied_policy = copied.execute(
            "SELECT require_manifest,snapshot_ready,publication_state,last_error "
            "FROM local_snapshot_policy WHERE singleton=1"
        ).fetchone()
        marker = copied.execute(
            "SELECT target_publication_state,target_local_publication_state,"
            "source_policy_json FROM personal_snapshot_provenance WHERE singleton=1"
        ).fetchone()
    assert copied_policy == (0, 0, "SYNCED", None)
    assert marker[:2] == ("PERSONAL_DRAFT", "SYNCED")
    assert json.loads(marker[2]) == manifest["source_policy_provenance"]

    with draft_pit_observation_clock("2025-01-02T15:30:00+09:00"):
        rows = pit.get_jquants_records(
            as_of="2025-01-02T15:30:00+09:00",
            dataset="markets_calendar",
            db_path=snapshot.db_path,
        ).rows
    assert len(rows) == 4
    assert verify_personal_snapshot(snapshot) == snapshot


@pytest.mark.parametrize("state", ["BUILDING", "VALIDATING"])
def test_materialize_rejects_explicitly_unstable_local_policy(
    tmp_path: Path,
    state: str,
) -> None:
    source = tmp_path / "current.sqlite"
    with sqlite3.connect(source) as connection:
        connection.executescript(
            """
            CREATE TABLE research_rows (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO research_rows VALUES (1, 'committed');
            CREATE TABLE local_snapshot_policy (
                singleton INTEGER PRIMARY KEY,
                publication_state TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO local_snapshot_policy VALUES (1, ?)", (state,)
        )
        connection.commit()

    with pytest.raises(PersonalSnapshotError, match=state):
        _materialize(source, tmp_path / "snapshots")


def test_materialize_rejects_absent_required_dataset_or_observed_range(
    tmp_path: Path,
) -> None:
    source = tmp_path / "current.sqlite"
    writer = _open_wal_source(source)
    try:
        with pytest.raises(PersonalSnapshotError, match="fins_summary.*no observed"):
            materialize_personal_snapshot(
                source,
                tmp_path / "missing",
                required_datasets=("fins_summary",),
                period_start="2024-01-01",
                period_end="2024-12-31",
                closure_digests=(_CLOSURE_A,),
            )
        with pytest.raises(PersonalSnapshotError, match="observed range"):
            materialize_personal_snapshot(
                source,
                tmp_path / "short-range",
                required_datasets=("markets_calendar",),
                period_start="2024-01-01",
                period_end="2025-01-01",
                closure_digests=(_CLOSURE_A,),
            )
    finally:
        writer.close()


def test_verify_detects_database_tamper_and_value_object_drift(tmp_path: Path) -> None:
    source = tmp_path / "current.sqlite"
    writer = _open_wal_source(source)
    try:
        snapshot = _materialize(source, tmp_path / "snapshots")
    finally:
        writer.close()

    drifted = replace(snapshot, logical_data_snapshot_id="sha256:" + "0" * 64)
    with pytest.raises(PersonalSnapshotError, match="value does not match"):
        verify_personal_snapshot(drifted)

    os.chmod(snapshot.db_path, 0o644)
    with snapshot.db_path.open("ab") as handle:
        handle.write(b"tamper")
    os.chmod(snapshot.db_path, 0o444)
    with pytest.raises(PersonalSnapshotError, match="database hash mismatch"):
        verify_personal_snapshot(snapshot.manifest_path)


def test_verify_detects_manifest_id_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "current.sqlite"
    writer = _open_wal_source(source)
    try:
        snapshot = _materialize(source, tmp_path / "snapshots")
    finally:
        writer.close()

    manifest = json.loads(snapshot.manifest_path.read_text(encoding="utf-8"))
    manifest["snapshot_id"] = "sha256:" + "f" * 64
    os.chmod(snapshot.manifest_path, 0o644)
    snapshot.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    os.chmod(snapshot.manifest_path, 0o444)
    with pytest.raises(PersonalSnapshotError, match="filename/id mismatch"):
        verify_personal_snapshot(snapshot.manifest_path)


def _install_compact_v7(
    connection: sqlite3.Connection,
    *,
    master_days: tuple[str, ...] = ("2024-01-02", "2024-06-01"),
    bar_days: tuple[str, ...] = ("2024-01-02", "2024-12-30"),
    replace_generic_bars: bool = True,
) -> None:
    install_compact_schema(connection)
    for day in master_days:
        insert_compact_master(connection, snapshot_date=day)
    for day in bar_days:
        insert_compact_bar(
            connection,
            day=day,
            available_at=f"{day}T15:30:00+09:00",
            ingested_at=f"{day}T16:00:00+09:00",
        )
    if replace_generic_bars:
        connection.execute(
            "DELETE FROM jquants_records WHERE dataset='equities_bars_daily'"
        )
    connection.commit()


def _observed(manifest: dict, dataset_id: str) -> dict:
    return next(
        item
        for item in manifest["observed_datasets"]
        if item["dataset_id"] == dataset_id
    )


def test_materialize_reports_compact_v7_master_and_bar_ranges(
    tmp_path: Path,
) -> None:
    source = tmp_path / "compact.sqlite"
    writer = _open_wal_source(source)
    try:
        fins = json.dumps({"Code": "1301", "DiscDate": "2024-03-31"}, sort_keys=True)
        writer.execute(
            "INSERT INTO jquants_records VALUES ('jquants','fins_summary',"
            "'fin-1301','2024-03-31T15:00:00+09:00',"
            "'2024-03-31T15:00:00+09:00','2024-03-31T16:00:00+09:00',?,?)",
            (fins, fins),
        )
        _install_compact_v7(writer)
        snapshot = materialize_personal_snapshot(
            source,
            tmp_path / "snapshots",
            required_datasets=(
                "markets_calendar",
                "equities_master",
                "fins_summary",
                "equities_bars_daily",
            ),
            period_start="2024-01-01",
            period_end="2024-12-31",
            closure_digests=(_CLOSURE_A,),
        )
    finally:
        writer.close()

    manifest = json.loads(snapshot.manifest_path.read_text(encoding="utf-8"))
    assert _observed(manifest, "equities_master") == {
        "dataset_id": "equities_master",
        "evidence_status": "OBSERVED",
        "row_count": 2,
        "min_event_date": "2024-01-02",
        "max_event_date": "2024-06-01",
    }
    assert _observed(manifest, "equities_bars_daily") == {
        "dataset_id": "equities_bars_daily",
        "evidence_status": "OBSERVED",
        "row_count": 2,
        "min_event_date": "2024-01-02",
        "max_event_date": "2024-12-30",
    }
    assert _observed(manifest, "markets_calendar")["row_count"] == 4
    assert _observed(manifest, "fins_summary") == {
        "dataset_id": "fins_summary",
        "evidence_status": "OBSERVED",
        "row_count": 1,
        "min_event_date": "2024-03-31",
        "max_event_date": "2024-03-31",
    }


def test_materialize_fail_closed_state_mapping(tmp_path: Path) -> None:
    invalid = tmp_path / "compact-invalid.sqlite"
    writer = _open_wal_source(invalid)
    try:
        stamp_compact_manifest(writer)
        writer.commit()
        with pytest.raises(
            PersonalSnapshotError, match="compact v7 marker or schema"
        ):
            _materialize(invalid, tmp_path / "snapshots-invalid")
    finally:
        writer.close()

    mixed = tmp_path / "compact-mixed.sqlite"
    writer = _open_wal_source(mixed)
    try:
        _install_compact_v7(writer, replace_generic_bars=False)
        with pytest.raises(PersonalSnapshotError, match="cannot mix compact"):
            materialize_personal_snapshot(
                mixed,
                tmp_path / "snapshots-mixed",
                required_datasets=("markets_calendar", "equities_bars_daily"),
                period_start="2024-01-01",
                period_end="2024-12-31",
                closure_digests=(_CLOSURE_A,),
            )
    finally:
        writer.close()


def test_materialize_keeps_legacy_evidence_for_non_v7_manifest_without_compact(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy-manifest.sqlite"
    writer = _open_wal_source(source)
    try:
        stamp_compact_manifest(writer, "personal-draft-history/v6")
        writer.commit()
        snapshot = _materialize(source, tmp_path / "snapshots")
    finally:
        writer.close()

    manifest = json.loads(snapshot.manifest_path.read_text(encoding="utf-8"))
    assert _observed(manifest, "equities_bars_daily")["row_count"] == 2
    assert _observed(manifest, "markets_calendar")["row_count"] == 4


def test_materialize_rejects_compact_bars_outside_calendar_trading_days(
    tmp_path: Path,
) -> None:
    source = tmp_path / "compact-short-bars.sqlite"
    writer = _open_wal_source(source)
    try:
        _install_compact_v7(writer, bar_days=("2024-01-02",))
        with pytest.raises(
            PersonalSnapshotError,
            match="equities_bars_daily observed range does not cover requested",
        ):
            _materialize(source, tmp_path / "snapshots")
    finally:
        writer.close()


def test_compact_table_content_change_updates_logical_snapshot_id(
    tmp_path: Path,
) -> None:
    first_source = tmp_path / "compact-a.sqlite"
    second_source = tmp_path / "compact-b.sqlite"
    first_writer = _open_wal_source(first_source)
    second_writer = _open_wal_source(second_source)
    try:
        _install_compact_v7(first_writer, master_days=("2024-01-02",))
        _install_compact_v7(
            second_writer, master_days=("2024-01-02", "2024-06-01")
        )
        first = materialize_personal_snapshot(
            first_source,
            tmp_path / "snapshots-a",
            required_datasets=("markets_calendar", "equities_master"),
            period_start="2024-01-01",
            period_end="2024-12-31",
            closure_digests=(_CLOSURE_A,),
        )
        second = materialize_personal_snapshot(
            second_source,
            tmp_path / "snapshots-b",
            required_datasets=("markets_calendar", "equities_master"),
            period_start="2024-01-01",
            period_end="2024-12-31",
            closure_digests=(_CLOSURE_A,),
        )
    finally:
        first_writer.close()
        second_writer.close()

    assert first.logical_data_snapshot_id != second.logical_data_snapshot_id
    assert _observed(
        json.loads(first.manifest_path.read_text(encoding="utf-8")),
        "equities_master",
    )["row_count"] == 1
    assert _observed(
        json.loads(second.manifest_path.read_text(encoding="utf-8")),
        "equities_master",
    )["row_count"] == 2
