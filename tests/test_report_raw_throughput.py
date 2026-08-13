"""Smoke tests for scripts/report_raw_throughput.py helpers."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


def _load_report_mod():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "report_raw_throughput.py"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("report_raw_throughput", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_collect_metrics_on_temp_db(tmp_path: Path):
    mod = _load_report_mod()
    db = tmp_path / "t.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE raw_retention_manifests (
            dataset TEXT, run_id INTEGER, manifest_key TEXT,
            page_count INTEGER, row_count INTEGER, raw_bytes INTEGER,
            data_digest TEXT, completeness TEXT, created_at TEXT,
            PRIMARY KEY (dataset, run_id)
        );
        INSERT INTO raw_retention_manifests VALUES
          ('equities_bars_daily', 1, 'k', 2, 100, 500, 'd', 'COMPLETE', 't'),
          ('fins_summary', 2, 'k2', 1, 10, 50, 'd2', 'FAILED', 't');
        CREATE TABLE jquants_records (
            dataset TEXT, event_time TEXT
        );
        INSERT INTO jquants_records VALUES
          ('equities_bars_daily', '2004-01-05T00:00:00+09:00'),
          ('equities_bars_daily', '2004-01-06T00:00:00+09:00'),
          ('markets_margin_interest', '2025-02-28T00:00:00+09:00');
        CREATE TABLE coverage_segments (
            source TEXT, dataset TEXT, segment_id TEXT, policy_version TEXT,
            segment_start TEXT, segment_end TEXT, status TEXT
        );
        INSERT INTO coverage_segments VALUES
          ('jquants','equities_bars_daily','2004-01','v','2004-01-01','2004-01-31','COMPLETE'),
          ('jquants','equities_bars_daily','2004-02','v','2004-02-01','2004-02-29','PARTIAL'),
          ('jquants','markets_margin_interest','2025-02','v','2025-02-01','2025-02-28','PARTIAL');
        CREATE TABLE dataset_coverage (
            dataset TEXT, status TEXT
        );
        INSERT INTO dataset_coverage VALUES
          ('markets_calendar', 'COMPLETE'),
          ('markets_margin_interest', 'STALE'),
          ('equities_bars_daily', 'PARTIAL');
        """
    )
    conn.commit()
    conn.close()

    report = mod.collect_metrics(db, label="PRE")
    assert report["label"] == "PRE"
    assert report["raw_retention_manifests"]["total"] == 2
    assert report["raw_retention_manifests"]["complete"] == 1
    assert report["coverage_segments"]["complete"] == 1
    assert report["coverage_segments"]["partial"] == 2
    assert report["dataset_coverage"]["stale"] == 1
    assert "markets_margin_interest" in report["dataset_coverage"]["stale_datasets"]
    assert report["dataset_coverage"]["complete"] == 1
    assert "equities_bars_daily" in report["track_a"]
    ta = report["track_a"]["equities_bars_daily"]
    assert ta["complete_segments"] == 1
    assert ta["total_segments"] == 2
    assert ta["records"]["rows"] == 2
    # Request-rate block (theoretical upstream from Worker floor).
    rr = report["request_rate"]
    assert rr["worker_rate_limit_ms"] == 120
    assert rr["theoretical_upstream_rpm"] == 500.0
    assert rr["client_defaults"]["general_rpm"] >= 495
    assert rr["client_defaults"]["general_workers"] >= 8

    md = mod.to_markdown(report)
    assert "raw_retention_manifests" in md
    assert "markets_margin_interest" in md
    assert "never forges COMPLETE" in md
    assert "request rate" in md.lower() or "theoretical_upstream_rpm" in md

    post = dict(report)
    post["raw_retention_manifests"] = dict(report["raw_retention_manifests"])
    post["raw_retention_manifests"]["total"] = 5
    post["coverage_segments"] = dict(report["coverage_segments"])
    post["coverage_segments"]["complete"] = 3
    d = mod.delta_metrics(report, post)
    assert d["raw_manifests_total"] == 3
    assert d["complete_segments"] == 2


def test_attach_request_rate_from_state_jsonl(tmp_path: Path):
    mod = _load_report_mod()
    state = tmp_path / "state.jsonl"
    lines = [
        json.dumps(
            {
                "finished_at": "2026-08-12T12:00:00+00:00",
                "rate_pool": "general",
                "state": "pass",
                "http_status": 200,
            }
        ),
        json.dumps(
            {
                "finished_at": "2026-08-12T12:00:12+00:00",
                "rate_pool": "general",
                "state": "pass",
                "http_status": 200,
            }
        ),
        json.dumps(
            {
                "finished_at": "2026-08-12T12:00:24+00:00",
                "rate_pool": "fins",
                "state": "retry",
                "http_status": 429,
                "reason_code": "http_429",
            }
        ),
    ]
    state.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report: dict = {"request_rate": {}}
    mod.attach_request_rate(report, state_jsonl=state, worker_rate_limit_ms=120)
    host = report["request_rate"]["host_dispatch"]
    assert host["n_events"] == 3
    # 2 intervals over 24s → 5 req/min
    assert host["requests_per_min"] == 5.0
    assert host["http_429_count"] == 1
    assert report["request_rate"]["theoretical_upstream_rpm"] == 500.0

    md = mod.to_markdown(
        {
            "label": "rpm",
            "generated_at": "t",
            "db_path": "x",
            "db_note": "n",
            "request_rate": report["request_rate"],
            "raw_retention_manifests": {},
            "coverage_segments": {},
            "dataset_coverage": {},
            "track_a": {},
        }
    )
    assert "host_dispatch_requests_per_min" in md
    assert "5.0" in md


def test_cli_smoke_missing_db(tmp_path: Path):
    mod = _load_report_mod()
    missing = tmp_path / "nope.sqlite"
    rc = mod.main(
        [
            "--db",
            str(missing),
            "--format",
            "json",
            "--label",
            "missing",
            "--out-json",
            str(tmp_path / "out.json"),
        ]
    )
    assert rc == 0
    data = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert data["errors"]
    assert "missing" in data["errors"][0]
    assert data["request_rate"]["theoretical_upstream_rpm"] == 500.0
