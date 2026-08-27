"""Smoke tests for scripts/issue_receipts_parallel.py (Track A3)."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest


def _load_mod():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "issue_receipts_parallel.py"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    name = "issue_receipts_parallel"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve module namespace.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _seed_db(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE coverage_segments (
            source TEXT, dataset TEXT, segment_id TEXT, policy_version TEXT,
            segment_start TEXT, segment_end TEXT, expected_scope TEXT,
            expected_items INTEGER, status TEXT, receipt_run_id INTEGER
        );
        CREATE TABLE jquants_records (
            dataset TEXT, event_time TEXT
        );
        CREATE TABLE collection_receipts (
            source TEXT, dataset TEXT, segment_id TEXT,
            segment_start TEXT, segment_end TEXT,
            expected_scope TEXT, expected_items INTEGER,
            observed_items INTEGER, raw_page_count INTEGER,
            raw_row_count INTEGER, structured_row_count INTEGER,
            pagination_exhausted INTEGER, digests_json TEXT,
            run_id INTEGER, status TEXT, error TEXT, checked_at TEXT
        );
        """
    )
    scope = json.dumps(
        {
            "coverage_mode": "periodic_reconciled",
            "expected_frequency": "weekly",
            "expected_item_unit": "source_query",
            "segment_end": "2025-01-31",
            "segment_start": "2025-01-01",
        }
    )
    # Candidate with both raw+struct path
    conn.execute(
        "INSERT INTO coverage_segments VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "jquants",
            "markets_short_ratio",
            "2025-01",
            "collection-coverage/v2",
            "2025-01-01",
            "2025-01-31",
            scope,
            1,
            "PARTIAL",
            None,
        ),
    )
    # No structured → skip
    conn.execute(
        "INSERT INTO coverage_segments VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "jquants",
            "markets_short_ratio",
            "2025-02",
            "collection-coverage/v2",
            "2025-02-01",
            "2025-02-28",
            scope,
            1,
            "PARTIAL",
            None,
        ),
    )
    # Structured but no raw → skip no_raw
    conn.execute(
        "INSERT INTO coverage_segments VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "jquants",
            "markets_short_ratio",
            "2025-03",
            "collection-coverage/v2",
            "2025-03-01",
            "2025-03-31",
            scope,
            1,
            "PARTIAL",
            None,
        ),
    )
    # Structured rows for Jan + Mar only
    for day in ("2025-01-05", "2025-01-12", "2025-03-04"):
        conn.execute(
            "INSERT INTO jquants_records VALUES (?,?)",
            ("markets_short_ratio", f"{day}T00:00:00+09:00"),
        )
    conn.commit()
    conn.close()


def test_raw_index_and_prepare_skips_no_raw(tmp_path: Path):
    mod = _load_mod()
    db = tmp_path / "t.sqlite"
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "jquants" / "2026" / "08" / "11"
    raw_dir.mkdir(parents=True)
    # Raw only for 2025-01 window
    raw_path = raw_dir / (
        "markets_short_ratio_from=2025-01-01_to=2025-01-31_test.json"
    )
    raw_path.write_text('{"rows":[1,2]}', encoding="utf-8")
    raw_path.chmod(0o444)
    _seed_db(db)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    jobs = mod.load_candidate_segments(
        conn,
        datasets=["markets_short_ratio"],
        segment_id="",
        limit_per_dataset=10,
        include_complete=False,
        order="asc",
    )
    conn.close()
    assert len(jobs) == 3

    raw_idx = mod.build_raw_index(data_dir, ["markets_short_ratio"])
    assert len(raw_idx["markets_short_ratio"]) == 1

    results = mod.prepare_parallel(
        jobs,
        db_path=db,
        raw_by_dataset=raw_idx,
        min_structured=1,
        workers=3,
    )
    by_id = {r.job.segment_id: r for r in results}
    assert by_id["2025-01"].prepared is not None
    assert by_id["2025-01"].prepared.structured == 2
    assert by_id["2025-02"].skip_reason and "no_struct" in by_id["2025-02"].skip_reason
    assert by_id["2025-03"].skip_reason == "no_raw"


def test_cli_dry_run_exits_ready(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    mod = _load_mod()
    db = tmp_path / "t.sqlite"
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "jquants" / "2026" / "08" / "11"
    raw_dir.mkdir(parents=True)
    raw_path = (
        raw_dir / "markets_short_ratio_from=2025-01-01_to=2025-01-31_test.json"
    )
    raw_path.write_text('{"ok":true,"rows":[1,2]}', encoding="utf-8")
    raw_path.chmod(0o444)
    # Empty stub must not count as raw for another segment.
    (
        raw_dir / "markets_short_ratio_date=2025-03-04_stub.json"
    ).write_text("[]", encoding="utf-8")
    _seed_db(db)

    rc = mod.main(
        [
            "--db",
            str(db),
            "--data-dir",
            str(data_dir),
            "--datasets",
            "markets_short_ratio",
            "--limit",
            "10",
            "--workers",
            "2",
            "--order",
            "asc",
            "--dry-run",
            "--json-summary",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "ready markets_short_ratio/2025-01" in out
    assert "skip markets_short_ratio/2025-03: no_raw" in out
    # Last non-empty line is JSON summary
    summary_line = [ln for ln in out.splitlines() if ln.strip().startswith("{")][-1]
    summary = json.loads(summary_line)
    assert summary["ready"] == 1
    assert summary["skipped"]["no_raw"] == 1
    assert summary["skipped"]["no_struct"] == 1
    assert summary["dry_run"] is True


def test_empty_array_raw_rejected(tmp_path: Path):
    mod = _load_mod()
    assert mod._is_usable_raw(b"[]") is False
    assert mod._is_usable_raw(b"[\n]") is False
    assert mod._is_usable_raw(b'{"rows":[1]}') is True
    # J-Quants envelope with zero rows must not pass empty-raw ban.
    assert mod._is_usable_raw(b'{"data":[]}') is False
    assert mod._is_usable_raw(b'{"data": []}') is False
    assert mod._is_usable_raw(b'{"data":[1]}') is True
    assert mod._is_usable_raw(b'{"rows":[]}') is False


def test_struct_hint_skips_empty_months(tmp_path: Path):
    """--struct-hint must not spend --limit on months with zero structured rows."""
    mod = _load_mod()
    db = tmp_path / "t.sqlite"
    _seed_db(db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    all_jobs = mod.load_candidate_segments(
        conn,
        datasets=["markets_short_ratio"],
        segment_id="",
        limit_per_dataset=10,
        include_complete=False,
        order="asc",
        struct_hint=False,
    )
    hinted = mod.load_candidate_segments(
        conn,
        datasets=["markets_short_ratio"],
        segment_id="",
        limit_per_dataset=10,
        include_complete=False,
        order="asc",
        struct_hint=True,
    )
    conn.close()
    assert {j.segment_id for j in all_jobs} == {"2025-01", "2025-02", "2025-03"}
    # 2025-02 has no structured rows in seed
    assert {j.segment_id for j in hinted} == {"2025-01", "2025-03"}


def test_empty_data_envelope_and_size_gate():
    mod = _load_mod()
    assert mod._is_usable_raw(b'{"data": []}') is False
    # large non-empty still ok
    body = b'{"data":[' + b'1,' * 100 + b'2]}'
    assert mod._is_usable_raw(body) is True
