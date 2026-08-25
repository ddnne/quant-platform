"""CLI wiring for scripts/issue_receipts_parallel.py.

Pins argparse ``--index-text PATH`` and the ``index_text=`` kwarg forwarded
to ``storage.coverage_ledger.refresh_coverage_ledger``. Missing flag →
``index_text is None`` (fail-closed empty OTC required set, not 8784
calendar replay). Does not run a live ledger, fetch JSDA HTML, or apply
remotely. Does not invent COMPLETE.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "issue_receipts_parallel.py"
_FIXTURE = _REPO / "tests" / "fixtures" / "jsda_otc_official_index_tiny.html"
V2_REQUIRED = 8784


def _load_mod():
    name = "issue_receipts_parallel_cli"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli_module():
    return _load_mod()


def _stub_db(tmp_path: Path) -> Path:
    db = tmp_path / "ledger.sqlite"
    conn = sqlite3.connect(db)
    conn.close()
    return db


def _seed_ready(tmp_path: Path, cli_module) -> tuple[Path, Path]:
    db = tmp_path / "t.sqlite"
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "jquants" / "2026" / "08" / "11"
    raw_dir.mkdir(parents=True)
    raw_path = (
        raw_dir / "markets_short_ratio_from=2025-01-01_to=2025-01-31_test.json"
    )
    raw_path.write_text('{"ok":true,"rows":[1]}', encoding="utf-8")
    raw_path.chmod(0o444)
    store = cli_module.SqliteStore(db)
    conn = store._conn
    scope = json.dumps(
        {
            "coverage_mode": "periodic_reconciled",
            "expected_frequency": "weekly",
            "expected_item_unit": "source_query",
            "segment_end": "2025-01-31",
            "segment_start": "2025-01-01",
        }
    )
    conn.execute(
        """INSERT INTO coverage_segments (
               source, dataset, segment_id, policy_version,
               segment_start, segment_end, expected_scope, expected_items,
               status, receipt_run_id, evaluated_at, detail_json
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
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
            "2025-02-01T00:00:00+00:00",
            "{}",
        ),
    )
    conn.execute(
        """INSERT INTO jquants_records (
               source, dataset, natural_key, event_time, available_at,
               ingested_at, payload, raw_payload
           ) VALUES (?,?,?,?,?,?,?,?)""",
        (
            "jquants",
            "markets_short_ratio",
            '{"Date":"2025-01-05"}',
            "2025-01-05T00:00:00+09:00",
            "2025-01-05T00:00:00+09:00",
            "2025-01-05T00:00:00+09:00",
            "{}",
            "{}",
        ),
    )
    conn.commit()
    store.close()
    return db, data_dir


def _stub_refresh(cli_module, monkeypatch) -> dict:
    captured: dict = {}

    def fake_refresh(conn, db_path, **kw):
        captured["kwargs"] = kw
        captured["index_text"] = kw.get("index_text", "MISSING_KEY")
        captured["called"] = True
        return [
            {
                "dataset": "markets_short_ratio",
                "status": "PARTIAL",
                "detail_json": "{}",
            }
        ]

    def fake_issue(store, prepared_list, *, receipt_service, start_run_id):
        assert receipt_service is captured["receipt_service"]
        captured["issued"] = True
        return [
            {
                "dataset": "markets_short_ratio",
                "segment_id": "2025-01",
                "run_id": start_run_id,
                "structured": 1,
                "raw_bytes": 10,
            }
        ]

    def fake_receipt_service():
        service = object()
        captured["receipt_service"] = service
        return service

    def fake_sync(conn, datasets=None, wave=None):
        return []

    monkeypatch.setattr(cli_module, "refresh_coverage_ledger", fake_refresh)
    monkeypatch.setattr(cli_module, "issue_prepared", fake_issue)
    monkeypatch.setattr(
        cli_module, "open_governed_receipt_service", fake_receipt_service
    )
    monkeypatch.setattr(cli_module, "sync_dataset_coverage_from_segments", fake_sync)
    return captured


def test_argparse_index_text_is_optional_path(cli_module) -> None:
    parser = cli_module._build_parser()
    omitted = parser.parse_args([])
    assert omitted.index_text is None
    supplied = parser.parse_args(
        ["--index-text", "tests/fixtures/jsda_otc_official_index_tiny.html"]
    )
    assert supplied.index_text == (
        "tests/fixtures/jsda_otc_official_index_tiny.html"
    )
    action = next(
        item for item in parser._actions if "--index-text" in item.option_strings
    )
    assert action.required is False
    assert action.default is None


def test_read_index_text_missing_path_is_none(cli_module) -> None:
    assert cli_module._read_index_text(None) is None


def test_main_passes_local_index_text_through(
    cli_module, monkeypatch, tmp_path: Path,
) -> None:
    db, data_dir = _seed_ready(tmp_path, cli_module)
    captured = _stub_refresh(cli_module, monkeypatch)
    html = _FIXTURE.read_text(encoding="utf-8")
    assert "https://" not in html
    rc = cli_module.main(
        [
            "--db",
            str(db),
            "--data-dir",
            str(data_dir),
            "--datasets",
            "markets_short_ratio",
            "--index-text",
            str(_FIXTURE),
        ]
    )
    assert rc == 0
    assert captured.get("called") is True
    assert "index_text" in captured["kwargs"]
    assert captured["index_text"] == html
    assert captured["index_text"] is not None
    assert captured["index_text"].strip() != ""
    assert captured["index_text"] != V2_REQUIRED


def test_main_omitted_index_text_is_none_not_calendar_replay(
    cli_module, monkeypatch, tmp_path: Path,
) -> None:
    db, data_dir = _seed_ready(tmp_path, cli_module)
    captured = _stub_refresh(cli_module, monkeypatch)
    rc = cli_module.main(
        [
            "--db",
            str(db),
            "--data-dir",
            str(data_dir),
            "--datasets",
            "markets_short_ratio",
        ]
    )
    assert rc == 0
    assert captured.get("called") is True
    assert "index_text" in captured["kwargs"]
    assert captured["index_text"] is None
    assert captured["index_text"] != V2_REQUIRED


def test_main_missing_index_file_does_not_call_refresh(
    cli_module, monkeypatch, tmp_path: Path,
) -> None:
    db = _stub_db(tmp_path)
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("refresh must not run when index HTML is missing")

    monkeypatch.setattr(cli_module, "refresh_coverage_ledger", boom)
    rc = cli_module.main(
        ["--db", str(db), "--index-text", str(tmp_path / "missing.html")]
    )
    assert rc == 1
    assert called["n"] == 0
