"""Quant Data must read the inode it verified, never a later pathname."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import data_access.adapter as adapter_module
from data_access import QuantDataAccess, QuantDataConfig
from paper_runtime.snapshot import ReadySnapshot
from pit.query import connect_readonly as pit_connect_readonly
from storage.coverage_ledger_io import _connect_readonly as coverage_connect_readonly
from storage.sqlite_store import SqliteStore


def _identity(path: Path) -> tuple[int, ...]:
    metadata = path.stat()
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_uid,
        stat.S_IMODE(metadata.st_mode),
        metadata.st_nlink,
    )


def _ready(path: Path) -> ReadySnapshot:
    raw = path.read_bytes()
    return ReadySnapshot(
        snapshot_id="sha256:" + "a" * 64,
        db_path=path,
        manifest_path=path.with_suffix(".manifest.json"),
        manifest={"state": "READY", "source_run": {"id": 1}},
        artifact_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        artifact_identity=_identity(path),
    )


def test_quant_data_passes_only_descriptor_path_to_pit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = tmp_path / "ready.sqlite"
    snapshot.write_bytes(b"verified immutable placeholder")
    snapshot.chmod(0o400)
    ready = _ready(snapshot)
    access = QuantDataAccess(QuantDataConfig(snapshot_dir=tmp_path))
    monkeypatch.setattr(access, "_snapshot", lambda _snapshot_id=None: ready)
    observed: list[Path] = []

    def read(**kwargs: object) -> SimpleNamespace:
        path = Path(kwargs["db_path"])
        observed.append(path)
        assert path != snapshot
        assert path.name.isdigit()
        assert path.parent in {Path("/dev/fd"), Path("/proc/self/fd")}
        assert path.exists()
        return SimpleNamespace(rows=[], metadata={})

    monkeypatch.setattr(adapter_module.pit, "get_jquants_records", read)
    result = access.query_dataset(
        dataset="equities_bars_daily",
        as_of="2025-01-02T09:00:00+09:00",
        start="2025-01-01",
        end="2025-01-01",
    )
    assert result["rows"] == []
    assert len(observed) == 1


@pytest.mark.parametrize(
    "connect",
    (pit_connect_readonly, coverage_connect_readonly),
)
def test_sqlite_connector_preserves_fd_uri_across_path_swap(
    tmp_path: Path,
    connect: object,
) -> None:
    source = tmp_path / "source.sqlite"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE marker(value TEXT NOT NULL)")
    connection.execute("INSERT INTO marker VALUES ('verified-inode')")
    connection.commit()
    connection.close()
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        fd_path = Path(f"/dev/fd/{descriptor}")
        if not fd_path.exists():
            fd_path = Path(f"/proc/self/fd/{descriptor}")
        assert fd_path.exists()
        displaced = source.with_name("verified.sqlite")
        source.rename(displaced)
        attacker = sqlite3.connect(source)
        attacker.execute("CREATE TABLE marker(value TEXT NOT NULL)")
        attacker.execute("INSERT INTO marker VALUES ('attacker-path')")
        attacker.commit()
        attacker.close()
        reader = connect(fd_path)  # type: ignore[operator]
        try:
            assert reader.execute("SELECT value FROM marker").fetchone()[0] == (
                "verified-inode"
            )
        finally:
            reader.close()
    finally:
        os.close(descriptor)


def test_same_uid_mutation_is_detected_before_result_is_returned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = tmp_path / "ready.sqlite"
    with SqliteStore(snapshot) as store:
        store.upsert(
            "jquants_records",
            [
                {
                    "source": "jquants",
                    "dataset": "equities_bars_daily",
                    "natural_key": "row-1",
                    "event_time": "2025-01-01T15:30:00+09:00",
                    "available_at": "2025-01-01T16:00:00+09:00",
                    "ingested_at": "2025-01-01T16:01:00+09:00",
                    "payload": '{"value":"original"}',
                    "raw_payload": '{"value":"original"}',
                }
            ],
        )
    snapshot.chmod(0o400)
    ready = _ready(snapshot)
    access = QuantDataAccess(QuantDataConfig(snapshot_dir=tmp_path))
    monkeypatch.setattr(access, "_snapshot", lambda _snapshot_id=None: ready)
    real_read = adapter_module.pit.get_jquants_records

    def mutate_then_read(**kwargs: object) -> object:
        snapshot.chmod(0o600)
        connection = sqlite3.connect(snapshot)
        connection.execute(
            "UPDATE jquants_records SET payload=? WHERE natural_key=?",
            ('{"value":"attacker"}', "row-1"),
        )
        connection.commit()
        connection.close()
        snapshot.chmod(0o400)
        return real_read(**kwargs)

    monkeypatch.setattr(
        adapter_module.pit,
        "get_jquants_records",
        mutate_then_read,
    )
    with pytest.raises(RuntimeError, match="changed during read|changed while"):
        access.query_dataset(
            dataset="equities_bars_daily",
            as_of="2025-01-02T09:00:00+09:00",
            start="2025-01-01",
            end="2025-01-01",
        )
