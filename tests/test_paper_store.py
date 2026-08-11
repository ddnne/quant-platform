"""Paper result JSON persistence and CLI smoke tests."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from strategies.examples import Return1dFeatureStrategy
from strategies.paper import JsonPaperStore, Lifecycle, PaperRunConfig, run_paper

from _coreseed import CODES, seed_db


def _fixture_run(tmp_path):
    days: list[str] = []
    cursor = date(2025, 4, 1)
    while len(days) < 8:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    prices = {
        code: {day: 100.0 + i + j for j, day in enumerate(days)}
        for i, code in enumerate(CODES)
    }
    db = seed_db(tmp_path, codes=CODES, days=days, prices=prices)
    config = PaperRunConfig(
        start=days[0],
        end=days[-1],
        db_path=db,
        universe=tuple(CODES),
        lifecycle=Lifecycle.PAPER,
    )
    return run_paper(Return1dFeatureStrategy(), config), db, config


def test_json_store_round_trip_by_path_and_run_id(tmp_path):
    result, _, _ = _fixture_run(tmp_path)
    store = JsonPaperStore(root=tmp_path / "paper")

    path = store.save(result)

    assert path.is_file()
    assert path.suffix == ".json"
    assert path.is_relative_to(tmp_path / "paper")
    assert path.parent.name == result.experiment_id
    assert store.load(path).to_dict() == result.to_dict()
    assert store.load(result.run_id).to_dict() == result.to_dict()
    assert (
        store.load_by_experiment_id(result.experiment_id).to_dict()
        == result.to_dict()
    )


def test_save_idempotently_indexes_immutable_result_in_sqlite_wal(tmp_path):
    result, _, config = _fixture_run(tmp_path)
    store = JsonPaperStore(root=tmp_path / "paper")

    path = store.save(result)
    store.save(result)

    with sqlite3.connect(store.index_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = [
            dict(row)
            for row in conn.execute("SELECT * FROM paper_experiments").fetchall()
        ]
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert len(rows) == 1
    assert rows[0]["experiment_id"] == result.experiment_id
    assert rows[0]["run_id"] == result.run_id
    assert rows[0]["lifecycle"] == Lifecycle.PAPER.value
    assert rows[0]["start_date"] == config.start
    assert rows[0]["end_date"] == config.end
    assert json.loads(rows[0]["feature_ids_json"]) == sorted(
        result.metadata["feature_versions"]
    )
    assert rows[0]["result_path"] == path.relative_to(store.root).as_posix()
    assert store.load_by_experiment_id(result.experiment_id).lifecycle is Lifecycle.PAPER


def test_save_rejects_different_json_at_existing_run_path(tmp_path):
    result, _, _ = _fixture_run(tmp_path)
    store = JsonPaperStore(root=tmp_path / "paper")
    path = store.save(result)
    original = path.read_bytes()

    with pytest.raises(FileExistsError, match="immutable paper result"):
        store.save(replace(result, lifecycle=Lifecycle.DRAFT))

    assert path.read_bytes() == original
    assert store.load_by_experiment_id(result.experiment_id).lifecycle is Lifecycle.PAPER


def test_parallel_identical_saves_share_one_index_record(tmp_path):
    result, _, _ = _fixture_run(tmp_path)
    root = tmp_path / "paper"

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(lambda _: JsonPaperStore(root).save(result), range(16)))

    assert len(set(paths)) == 1
    with sqlite3.connect(root / "index.sqlite3") as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM paper_experiments"
        ).fetchone()[0] == 1


def test_loads_v1_result_with_legacy_run_identity(tmp_path):
    result, _, _ = _fixture_run(tmp_path)
    payload = result.to_dict()
    payload["schema_version"] = "paper-result/v1"
    payload.pop("experiment_id")
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = JsonPaperStore(root=tmp_path / "paper").load(path)

    assert loaded.experiment_id == result.run_id
    assert loaded.run_id == result.run_id
    assert loaded.lifecycle is result.lifecycle


def test_run_paper_persists_when_store_is_supplied(tmp_path):
    _, db, config = _fixture_run(tmp_path)
    store = JsonPaperStore(root=tmp_path / "paper")

    result = run_paper(Return1dFeatureStrategy(), config, store=store)

    assert store.load(result.run_id).to_dict() == result.to_dict()


def test_json_store_default_root_is_data_paper():
    assert Path(JsonPaperStore().root).parts[-2:] == ("data", "paper")


def test_run_paper_once_help_is_offline_and_successful():
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, str(repo / "scripts" / "run_paper_once.py"), "--help"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    assert "paper" in proc.stdout.lower()
    assert "--db" in proc.stdout
    assert "--start" in proc.stdout
    assert "--end" in proc.stdout
