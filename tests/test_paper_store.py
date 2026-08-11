"""Paper result JSON persistence and CLI smoke tests."""

from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

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
    return run_paper(Return1dFeatureStrategy(db), config), db, config


def test_json_store_round_trip_by_path_and_run_id(tmp_path):
    result, _, _ = _fixture_run(tmp_path)
    store = JsonPaperStore(root=tmp_path / "paper")

    path = store.save(result)

    assert path.is_file()
    assert path.suffix == ".json"
    assert path.is_relative_to(tmp_path / "paper")
    assert store.load(path).to_dict() == result.to_dict()
    assert store.load(result.run_id).to_dict() == result.to_dict()


def test_run_paper_persists_when_store_is_supplied(tmp_path):
    _, db, config = _fixture_run(tmp_path)
    store = JsonPaperStore(root=tmp_path / "paper")

    result = run_paper(Return1dFeatureStrategy(db), config, store=store)

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
