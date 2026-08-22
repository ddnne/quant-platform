"""Phase 3.5 — coverage CLI, B0 gates, and ingestion_validation honesty.

Remainder of the coverage-matrix suite: QP_LIVE / --strict-live-gates,
C1/C2/C9/C10 validation-log paths, persist-report, and weekly completion
mode. Shared builders: ``tests/phase35_matrix_util.py``.

Offline-only: no network, no Cloudflare, no API keys.
"""

from __future__ import annotations

import json

from cf_platform.ingest_premium.coverage import (
    CheckResult,
    has_failures,
    not_implemented_skips,
    run_coverage,
)
from ingestion.jquants.normalize import normalize_generic
from storage.sqlite_store import SqliteStore

from tests.phase35_matrix_util import (
    INGESTED,
    _REPO,
    _build_specialized_db,
    _build_year_span_db,
    _results_by_id,
    matrix_db,
    specialized_db,
)


# ---------------------------------------------------------------------------
# Daily tier — strict-live-gates emits B0 rows on real-data scale
# ---------------------------------------------------------------------------
def test_strict_live_gates_emits_B0_rows_on_daily(specialized_db):
    """When strict_live_gates=True the daily tier surfaces B0 gate rows.

    These rows use ``check_id="B0"`` (Phase-4 shared gate; not part of the
    formal catalog which starts at B1). Each gate emits one row whose
    status mirrors ``cf_platform.live_gates.measure_b0``.
    """
    out = run_coverage(specialized_db, tier="daily", strict_live_gates=True)
    b0 = _results_by_id(out, "B0")
    # Three gates: master, bars issuers, latest-day rows.
    assert len(b0) == 3
    names = {r.dataset for r in b0}
    assert names == {"B0_master", "B0_bars_issuers", "B0_bars_latest_day"}
    # The tiny fixture (2 codes, 4 days) misses every gate → fail.
    assert all(r.status == "fail" for r in b0)


def test_strict_live_gates_off_by_default_daily(specialized_db):
    """Without strict_live_gates, no B0 rows are emitted on the daily tier."""
    out = run_coverage(specialized_db, tier="daily")
    b0 = _results_by_id(out, "B0")
    assert b0 == []


# ---------------------------------------------------------------------------
# b0_pass strict resolution — QP_LIVE=1 implies strict
# ---------------------------------------------------------------------------
def test_b0_pass_treats_qp_live_as_strict(monkeypatch, tmp_path):
    """``b0_pass(db, strict=None)`` reads QP_LIVE=1 as strict=True."""
    from cf_platform.live_gates import b0_pass
    p = _build_year_span_db(tmp_path, days=("2025-04-01", "2025-04-04"))
    monkeypatch.setenv("QP_LIVE", "1")
    ok, results = b0_pass(p)  # strict defaults to None → env lookup
    # Fixture-scale DB misses gates, so under strict it must fail.
    assert ok is False
    assert all(r.name.startswith("B0_") for r in results)


def test_b0_pass_no_qp_live_is_soft(monkeypatch, tmp_path):
    """Without QP_LIVE=1 the same call returns ok=True (soft path)."""
    from cf_platform.live_gates import b0_pass
    p = _build_year_span_db(tmp_path, days=("2025-04-01", "2025-04-04"))
    monkeypatch.delenv("QP_LIVE", raising=False)
    ok, _ = b0_pass(p)
    assert ok is True


# ---------------------------------------------------------------------------
# CLI parser — QP_LIVE=1 default for --strict-live-gates
# ---------------------------------------------------------------------------
def test_cli_strict_live_gates_defaults_off_without_qp_live(monkeypatch):
    """Without QP_LIVE the flag defaults to False (offline green path)."""
    import importlib.util
    monkeypatch.delenv("QP_LIVE", raising=False)
    cli_path = _REPO / "scripts" / "run_phase35_validation.py"
    spec = importlib.util.spec_from_file_location("run_phase35_validation", cli_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    args = mod._build_parser().parse_args(["--db", "x.sqlite"])
    # main() resolves None → False when QP_LIVE unset; the parser itself
    # surfaces None so the env check happens at call time.
    assert args.strict_live_gates is None


def test_cli_strict_live_gates_defaults_on_with_qp_live(monkeypatch, tmp_path):
    """When QP_LIVE=1, main() resolves strict=True even without the flag."""
    import importlib.util
    cli_path = _REPO / "scripts" / "run_phase35_validation.py"
    spec = importlib.util.spec_from_file_location("run_phase35_validation", cli_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    # Build an empty DB so run_coverage emits failures (not a crash).
    p = tmp_path / "empty.sqlite"
    SqliteStore(p).close()
    monkeypatch.setenv("QP_LIVE", "1")

    # Spy on the resolved flag by patching run_coverage.
    captured: dict = {}

    def fake_run(db_path, **kw):
        captured["strict_live_gates"] = kw.get("strict_live_gates")
        return []

    monkeypatch.setattr(mod, "run_coverage", fake_run)
    rc = mod.main(["--db", str(p), "--tier", "daily"])
    assert rc == 0
    assert captured["strict_live_gates"] is True


def test_cli_no_strict_flag_overrides_qp_live(monkeypatch, tmp_path):
    """``--no-strict-live-gates`` overrides QP_LIVE=1."""
    import importlib.util
    cli_path = _REPO / "scripts" / "run_phase35_validation.py"
    spec = importlib.util.spec_from_file_location("run_phase35_validation", cli_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    p = tmp_path / "empty.sqlite"
    SqliteStore(p).close()
    monkeypatch.setenv("QP_LIVE", "1")

    captured: dict = {}

    def fake_run(db_path, **kw):
        captured["strict_live_gates"] = kw.get("strict_live_gates")
        return []

    monkeypatch.setattr(mod, "run_coverage", fake_run)
    rc = mod.main(["--db", str(p), "--tier", "daily",
                   "--no-strict-live-gates"])
    assert rc == 0
    assert captured["strict_live_gates"] is False


# ---------------------------------------------------------------------------
# P0-2 — Validation honesty: C1/C2 prefer real run logs when available
# ---------------------------------------------------------------------------
def _ingestion_validation_rows():
    """Synthetic per-dataset validation rows simulating a CF D1 sync."""
    return [
        {
            "source": "jquants", "dataset": "equities_bars_daily",
            "natural_key": '{"Date":"2025-04-01"}',
            "event_time": "2025-04-01T09:00:00+09:00",
            "available_at": "2025-04-01T15:30:00+09:00",
            "ingested_at": "2025-04-01T15:30:00+09:00",
            "payload": '{"Code":"8697","Date":"2025-04-01","Close":100.0}',
            "raw_payload": "{}",
        },
    ]


def _seed_validation_table(store, rows):
    """Insert synthetic rows into ``ingestion_validation`` for tests."""
    store._conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ingestion_validation (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          INTEGER,
            dataset         TEXT NOT NULL,
            started_at      TEXT NOT NULL,
            finished_at     TEXT NOT NULL,
            status          TEXT NOT NULL,
            rows_seen       INTEGER NOT NULL DEFAULT 0,
            rows_inserted   INTEGER NOT NULL DEFAULT 0,
            rows_revisions  INTEGER NOT NULL DEFAULT 0,
            available_at_min TEXT,
            available_at_max TEXT,
            detail          TEXT
        );
        """
    )
    for r in rows:
        store._conn.execute(
            "INSERT INTO ingestion_validation "
            "(run_id, dataset, started_at, finished_at, status, "
            " rows_seen, rows_inserted, rows_revisions, "
            " available_at_min, available_at_max, detail) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (r.get("run_id"), r["dataset"], r["started_at"], r["finished_at"],
             r["status"], r.get("rows_seen", 0), r.get("rows_inserted", 0),
             r.get("rows_revisions", 0), r.get("available_at_min"),
             r.get("available_at_max"), r.get("detail", "")),
        )
    store._conn.commit()


def test_C1_C2_prefer_ingestion_validation_when_present(tmp_path):
    """When ``ingestion_validation`` exists, C1/C2 mirror its status."""
    p = tmp_path / "valid.sqlite"
    store = SqliteStore(p)
    # Seed some data so the "facts-only" fallback would also pass.
    store.upsert(
        "jquants_records",
        normalize_generic(
            [{"Code": "8697", "Date": "2025-04-01", "Close": 100.0}],
            dataset="equities_bars_daily", ingested_at=INGESTED,
        ),
    )
    _seed_validation_table(store, [
        {"dataset": "equities_bars_daily",
         "started_at": "2025-04-01T15:00:00+09:00",
         "finished_at": "2025-04-01T15:30:00+09:00",
         "status": "pass",
         "rows_seen": 10, "rows_inserted": 10,
         "available_at_min": "2025-04-01T15:30:00+09:00",
         "available_at_max": "2025-04-01T15:30:00+09:00",
         "detail": "ok"},
    ])
    store.close()

    out = run_coverage(p, tier="daily", datasets=["equities_bars_daily"])
    c1 = _results_by_id(out, "C1")
    c2 = _results_by_id(out, "C2")
    assert c1[0].status == "pass"
    assert c1[0].metrics["source"] == "ingestion_validation"
    assert c1[0].metrics["validation_status"] == "pass"
    assert c2[0].status == "pass"
    assert c2[0].metrics["source"] == "ingestion_validation"


def test_C1_C2_mirror_failure_from_ingestion_validation(tmp_path):
    """A failed validation row surfaces as a hard fail (not silently passing)."""
    p = tmp_path / "failed.sqlite"
    store = SqliteStore(p)
    store.upsert(
        "jquants_records",
        normalize_generic(
            [{"Code": "8697", "Date": "2025-04-01", "Close": 100.0}],
            dataset="equities_bars_daily", ingested_at=INGESTED,
        ),
    )
    _seed_validation_table(store, [
        {"dataset": "equities_bars_daily",
         "started_at": "2025-04-01T15:00:00+09:00",
         "finished_at": "2025-04-01T15:30:00+09:00",
         "status": "fail",
         "rows_seen": 10, "rows_inserted": 0,
         "available_at_min": None,
         "detail": "HTTP 503"},
    ])
    store.close()

    out = run_coverage(p, tier="daily", datasets=["equities_bars_daily"])
    c1 = _results_by_id(out, "C1")
    c2 = _results_by_id(out, "C2")
    assert c1[0].status == "fail"
    assert c2[0].status == "fail"
    assert "HTTP 503" in c2[0].detail or "status=fail" in c2[0].detail


def test_C2_warns_with_data_only_when_no_validation_table(matrix_db):
    """P0-2 contract: without ``ingestion_validation``, C2 is ``warn`` not pass."""
    out = run_coverage(
        matrix_db, tier="daily",
        datasets=["equities_bars_daily", "equities_master", "markets_calendar"],
    )
    c2 = _results_by_id(out, "C2")
    assert c2  # at least one row
    # The default fixture has no ``ingestion_validation`` table → every C2 row
    # is "warn" (data present only).
    for r in c2:
        assert r.status == "warn", (r.dataset, r.detail)
        assert r.metrics["source"] == "facts_only"
        assert r.metrics["reason_code"] == "no_run_log"


# ---------------------------------------------------------------------------
# P0-2 — Weekly completion mode: skip + not_implemented is a failure
# ---------------------------------------------------------------------------
def test_has_failures_weekly_completion_mode_treats_not_implemented_as_fail():
    """``has_failures(..., require_implemented=True)`` fails on skip+not_implemented."""
    rs = [
        CheckResult("C9", None, "skip", "needs history",
                    {"reason_code": "not_implemented"}),
        CheckResult("C10", None, "skip", "needs history",
                    {"reason_code": "not_implemented"}),
        CheckResult("C11", None, "skip", "needs R2",
                    {"reason_code": "needs_r2"}),
        CheckResult("B1", "x", "pass", "ok"),
    ]
    # Soft mode (default): skip is not a failure.
    assert not has_failures(rs)
    # Completion mode: not_implemented is a failure (needs_r2 is exempt).
    assert has_failures(rs, require_implemented=True)


def test_not_implemented_skips_helper():
    rs = [
        CheckResult("C9", None, "skip", "needs history",
                    {"reason_code": "not_implemented"}),
        CheckResult("C11", None, "skip", "needs R2",
                    {"reason_code": "needs_r2"}),
    ]
    ni = not_implemented_skips(rs)
    assert len(ni) == 1
    assert ni[0].check_id == "C9"


# ---------------------------------------------------------------------------
# P0-2 — C9/C10 offline approximations when ingestion_validation is present
# ---------------------------------------------------------------------------
def test_C9_C10_implemented_when_validation_history_present(tmp_path):
    """Multiple runs in ``ingestion_validation`` enable real C9/C10 logic."""
    p = tmp_path / "valid.sqlite"
    store = SqliteStore(p)
    store.upsert(
        "jquants_records",
        normalize_generic(
            [{"Code": "8697", "Date": "2025-04-01", "Close": 100.0}],
            dataset="equities_bars_daily", ingested_at=INGESTED,
        ),
    )
    _seed_validation_table(store, [
        {"dataset": "equities_bars_daily",
         "started_at": "2025-04-01T15:00:00+09:00",
         "finished_at": "2025-04-01T15:30:00+09:00",
         "status": "pass",
         "rows_seen": 10, "rows_inserted": 10,
         "available_at_min": "2025-04-01T15:30:00+09:00",
         "available_at_max": "2025-04-01T15:30:00+09:00"},
        {"dataset": "equities_bars_daily",
         "started_at": "2025-04-02T15:00:00+09:00",
         "finished_at": "2025-04-02T15:30:00+09:00",
         "status": "pass",
         "rows_seen": 12, "rows_inserted": 2,
         "available_at_min": "2025-04-02T15:30:00+09:00",
         "available_at_max": "2025-04-02T15:30:00+09:00"},
    ])
    store.close()
    out = run_coverage(p, tier="weekly", datasets=["equities_bars_daily"])
    c9 = _results_by_id(out, "C9")
    c10 = _results_by_id(out, "C10")
    c11 = _results_by_id(out, "C11")
    assert c9 and c9[0].status == "pass"
    assert c9[0].metrics["source"] == "ingestion_validation"
    assert c9[0].metrics["datasets_progressed"] >= 1
    assert c10 and c10[0].status == "pass"
    assert c10[0].metrics["source"] == "ingestion_validation"
    # C11 must skip with the explicit needs_r2 reason (not generic not_implemented).
    assert c11 and c11[0].status == "skip"
    assert c11[0].metrics["reason_code"] == "needs_r2"


def test_C9_C10_skip_without_validation_table(specialized_db):
    """Without ``ingestion_validation`` the new C9/C10 logic degrades to skip."""
    out = run_coverage(specialized_db, tier="weekly")
    c9 = _results_by_id(out, "C9")
    c10 = _results_by_id(out, "C10")
    c11 = _results_by_id(out, "C11")
    assert c9[0].status == "skip"
    assert c9[0].metrics["reason_code"] == "not_implemented"
    assert c10[0].status == "skip"
    assert c10[0].metrics["reason_code"] == "not_implemented"
    assert c11[0].status == "skip"
    assert c11[0].metrics["reason_code"] == "needs_r2"


# ---------------------------------------------------------------------------
# P0-2 — Persist validation report JSON
# ---------------------------------------------------------------------------
def test_persist_report_writes_json_under_data_reports(tmp_path):
    """``persist_report`` writes a timestamped JSON file under data/reports/."""
    from cf_platform.ingest_premium.coverage import persist_report
    rs = [
        CheckResult("C1", "x", "pass", "ok"),
        CheckResult("C2", "x", "skip", "needs history",
                    {"reason_code": "not_implemented"}),
    ]
    out_dir = tmp_path / "reports"
    p = persist_report(rs, tier="weekly", db_path="/tmp/x.sqlite",
                       reports_dir=out_dir, when="20250101_000000")
    assert p.exists()
    assert p.name == "validation_20250101_000000.json"
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["tier"] == "weekly"
    assert payload["summary"] == {"pass": 1, "fail": 0, "skip": 1, "warn": 0}
    assert payload["not_implemented"]
    assert payload["not_implemented"][0]["check_id"] == "C2"
    assert len(payload["results"]) == 2


def test_cli_persists_report_and_exits_nonzero_when_weekly_not_implemented(
    monkeypatch, tmp_path
):
    """Weekly tier with stubbed checks must fail under --require-implemented,
    and the JSON report must be persisted so the operator can audit it."""
    import importlib.util
    cli_path = _REPO / "scripts" / "run_phase35_validation.py"
    spec = importlib.util.spec_from_file_location("run_phase35_validation", cli_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    # Build a tiny fixture DB so the runner has something to read.
    p = tmp_path / "fixture.sqlite"
    _build_specialized_db(p)

    reports_dir = tmp_path / "reports"
    rc = mod.main([
        "--db", str(p),
        "--tier", "weekly",
        "--reports-dir", str(reports_dir),
        "--no-strict-live-gates",
    ])
    # Weekly default is --require-implemented, and the catalog has many
    # not_implemented weekly stubs → must exit 1.
    assert rc == 1
    # A report file should exist under reports_dir.
    files = list(reports_dir.glob("validation_*.json"))
    assert files, f"no validation_*.json under {reports_dir}"
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["tier"] == "weekly"
    assert payload["summary"]["skip"] > 0
    assert payload["not_implemented"]


def test_cli_allow_not_implemented_for_daily(tmp_path):
    """Daily tier with --allow-not-implemented tolerates stubs.

    Scoped to the three datasets the fixture populates so C8 doesn't fail
    on the empty 20 datasets the way the full daily run does.
    """
    import importlib.util
    cli_path = _REPO / "scripts" / "run_phase35_validation.py"
    spec = importlib.util.spec_from_file_location("run_phase35_validation", cli_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    p = tmp_path / "fixture.sqlite"
    _build_specialized_db(p)
    reports_dir = tmp_path / "daily_reports"
    # Daily default is allow-not-implemented; pass it explicitly to be safe.
    rc = mod.main([
        "--db", str(p),
        "--tier", "daily",
        "--datasets", "equities_bars_daily,equities_master,markets_calendar",
        "--allow-not-implemented",
        "--reports-dir", str(reports_dir),
        "--no-strict-live-gates",
    ])
    assert rc == 0


def test_cli_no_persist_report_skips_writing(monkeypatch, tmp_path):
    """``--no-persist-report`` skips the JSON file entirely."""
    import importlib.util
    cli_path = _REPO / "scripts" / "run_phase35_validation.py"
    spec = importlib.util.spec_from_file_location("run_phase35_validation", cli_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    p = tmp_path / "fixture.sqlite"
    _build_specialized_db(p)
    reports_dir = tmp_path / "no_persist_reports"
    rc = mod.main([
        "--db", str(p),
        "--tier", "daily",
        "--datasets", "equities_bars_daily,equities_master,markets_calendar",
        "--allow-not-implemented",
        "--no-persist-report",
        "--reports-dir", str(reports_dir),
        "--no-strict-live-gates",
    ])
    assert rc == 0
    assert not reports_dir.exists() or not list(reports_dir.glob("validation_*.json"))
