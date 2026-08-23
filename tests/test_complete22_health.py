"""W73 / w0816g — COMPLETE 22 health floor check (fixtures; no live D1 required).

Maintain thresholds only — not growth targets. Never invent COMPLETE 23.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_complete22_health.py"


def _load_mod():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    name = "check_complete22_health"
    if name in sys.modules:
        # reload so edits during session are picked up in repeated runs
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def health():
    return _load_mod()


def test_good_fixture_passes(health):
    snap = health.good_fixture_snapshot()
    rep = health.evaluate_complete22_health(snap)
    assert rep["all_checks_pass"] is True
    assert rep["checks"]["COMPLETE_eq_22"] is True
    assert rep["checks"]["PARTIAL_includes_tip_only_defer4"] is True
    assert rep["checks"]["PARTIAL_n_eq_4"] is True
    assert rep["checks"]["fins_segs_104"] is True
    assert rep["checks"]["empty_complete_0"] is True
    assert rep["checks"]["otc_complete_ge_93"] is True
    assert rep["checks"]["bars_am_complete_ge_1"] is True
    assert rep["checks"]["no_invent_complete_23"] is True
    assert rep["mass"] == "NO-GO"
    assert rep["ready"] == "not_declared"
    assert rep["phase7"] == "OFF"
    assert "tip-wait" in rep["residual_note"]


def test_complete_21_fails(health):
    snap = health.good_fixture_snapshot()
    snap["dataset_complete"] = 21
    rep = health.evaluate_complete22_health(snap)
    assert rep["all_checks_pass"] is False
    assert rep["checks"]["COMPLETE_eq_22"] is False


def test_invent_complete_23_fails_exact_mode(health):
    snap = health.good_fixture_snapshot()
    snap["dataset_complete"] = 23
    rep = health.evaluate_complete22_health(snap, exact_complete=True)
    assert rep["all_checks_pass"] is False
    assert rep["checks"]["COMPLETE_eq_22"] is False
    assert rep["checks"]["no_invent_complete_23"] is False


def test_official_domain_2008_05_07_is_not_invent_23(health):
    """Official listed-info start is allowed; floor-bump to TODAY is still forbidden."""
    snap = health.good_fixture_snapshot()
    snap["official_domain_start"] = "2008-05-07"
    snap["dataset_complete"] = 22
    rep = health.evaluate_complete22_health(snap)
    assert rep["checks"]["no_invent_complete_23"] is True
    assert rep["all_checks_pass"] is True

    snap["dataset_complete"] = 23
    snap["history_target_start"] = date.today().isoformat()
    rep = health.evaluate_complete22_health(snap, exact_complete=True)
    assert rep["checks"]["no_invent_complete_23"] is False
    assert rep["all_checks_pass"] is False


def test_missing_partial_tip_only_fails(health):
    snap = health.good_fixture_snapshot()
    # drop bars_am from PARTIAL list
    snap["partial_datasets"] = [
        d for d in snap["partial_datasets"] if d != "equities_bars_daily_am"
    ]
    snap["dataset_partial"] = len(snap["partial_datasets"])
    rep = health.evaluate_complete22_health(snap)
    assert rep["all_checks_pass"] is False
    assert rep["checks"]["PARTIAL_includes_tip_only_defer4"] is False
    assert "equities_bars_daily_am" in rep["missing_partial_datasets"]


def test_empty_complete_nonzero_fails(health):
    snap = health.good_fixture_snapshot()
    snap["empty_complete"] = 1
    rep = health.evaluate_complete22_health(snap)
    assert rep["all_checks_pass"] is False
    assert rep["checks"]["empty_complete_0"] is False


def test_otc_below_floor_fails(health):
    snap = health.good_fixture_snapshot()
    snap["otc_complete"] = 92
    rep = health.evaluate_complete22_health(snap)
    assert rep["all_checks_pass"] is False
    assert rep["checks"]["otc_complete_ge_93"] is False


def test_bars_am_below_floor_fails(health):
    snap = health.good_fixture_snapshot()
    snap["bars_am_complete"] = 0
    rep = health.evaluate_complete22_health(snap)
    assert rep["all_checks_pass"] is False
    assert rep["checks"]["bars_am_complete_ge_1"] is False


def test_fins_below_104_fails_when_required(health):
    snap = health.good_fixture_snapshot()
    snap["fins_complete_segments"] = 103
    rep = health.evaluate_complete22_health(snap, require_fins=True)
    assert rep["all_checks_pass"] is False
    assert rep["checks"]["fins_segs_104"] is False


def test_fins_optional_when_require_fins_false(health):
    snap = health.good_fixture_snapshot()
    snap["fins_complete_segments"] = None
    rep = health.evaluate_complete22_health(snap, require_fins=False)
    assert rep["all_checks_pass"] is True
    assert rep["checks"]["fins_segs_104"] is True


def test_complete_floor_mode_allows_ge_22(health):
    snap = health.good_fixture_snapshot()
    snap["dataset_complete"] = 22
    rep = health.evaluate_complete22_health(snap, exact_complete=False)
    assert rep["all_checks_pass"] is True
    assert rep["checks"]["COMPLETE_ge_22"] is True


def test_partial_expected_set_matches_permanent_defer(health):
    from data_contracts import PERMANENT_DEFER_DATASETS

    assert health.EXPECTED_PARTIAL_DATASETS == PERMANENT_DEFER_DATASETS


def test_collect_local_sqlite_roundtrip(health, tmp_path):
    """Minimal schema fixture → collect_local_sqlite → evaluate pass."""
    db = tmp_path / "health.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE dataset_coverage (
            dataset TEXT PRIMARY KEY,
            status TEXT NOT NULL
        );
        CREATE TABLE coverage_segments (
            source TEXT,
            dataset TEXT,
            segment_id TEXT,
            status TEXT,
            receipt_run_id INTEGER,
            PRIMARY KEY (source, dataset, segment_id)
        );
        """
    )
    # 22 COMPLETE + 4 PARTIAL
    complete_ds = [f"ds_complete_{i:02d}" for i in range(22)]
    for ds in complete_ds:
        conn.execute(
            "INSERT INTO dataset_coverage(dataset, status) VALUES (?, 'COMPLETE')",
            (ds,),
        )
    for ds in sorted(health.EXPECTED_PARTIAL_DATASETS):
        conn.execute(
            "INSERT INTO dataset_coverage(dataset, status) VALUES (?, 'PARTIAL')",
            (ds,),
        )
    # fins 104 COMPLETE segs
    for i in range(104):
        conn.execute(
            "INSERT INTO coverage_segments VALUES (?,?,?,?,?)",
            ("jquants", "fins_earnings_date", f"seg_{i:03d}", "COMPLETE", 1000 + i),
        )
    # bars_am tip 1 + OTC 93
    conn.execute(
        "INSERT INTO coverage_segments VALUES (?,?,?,?,?)",
        ("jquants", "equities_bars_daily_am", "2026-08", "COMPLETE", 2000),
    )
    for i in range(93):
        conn.execute(
            "INSERT INTO coverage_segments VALUES (?,?,?,?,?)",
            ("jsda", "jsda_otc_bond_reference_prices", f"d{i:04d}", "COMPLETE", 3000 + i),
        )
    conn.commit()
    conn.close()

    snap = health.collect_local_sqlite(db)
    assert snap["dataset_complete"] == 22
    assert snap["dataset_partial"] == 4
    assert set(snap["partial_datasets"]) == health.EXPECTED_PARTIAL_DATASETS
    assert snap["fins_complete_segments"] == 104
    assert snap["empty_complete"] == 0
    assert snap["otc_complete"] == 93
    assert snap["bars_am_complete"] == 1

    rep = health.evaluate_complete22_health(snap)
    assert rep["all_checks_pass"] is True


def test_cli_fixture_path_via_main_json(health, tmp_path, capsys):
    """CLI against temp db exits 0 and reports all_checks_pass."""
    db = tmp_path / "cli.sqlite"
    # reuse collect fixture builder via direct insert (same as above, compact)
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE dataset_coverage (dataset TEXT PRIMARY KEY, status TEXT NOT NULL);
        CREATE TABLE coverage_segments (
            source TEXT, dataset TEXT, segment_id TEXT, status TEXT,
            receipt_run_id INTEGER,
            PRIMARY KEY (source, dataset, segment_id)
        );
        """
    )
    for i in range(22):
        conn.execute(
            "INSERT INTO dataset_coverage VALUES (?, 'COMPLETE')",
            (f"c{i}",),
        )
    for ds in sorted(health.EXPECTED_PARTIAL_DATASETS):
        conn.execute(
            "INSERT INTO dataset_coverage VALUES (?, 'PARTIAL')",
            (ds,),
        )
    for i in range(104):
        conn.execute(
            "INSERT INTO coverage_segments VALUES (?,?,?,?,?)",
            ("jquants", "fins_earnings_date", f"f{i}", "COMPLETE", i + 1),
        )
    conn.execute(
        "INSERT INTO coverage_segments VALUES (?,?,?,?,?)",
        ("jquants", "equities_bars_daily_am", "tip", "COMPLETE", 9),
    )
    for i in range(93):
        conn.execute(
            "INSERT INTO coverage_segments VALUES (?,?,?,?,?)",
            ("jsda", "jsda_otc_bond_reference_prices", f"o{i}", "COMPLETE", 10 + i),
        )
    conn.commit()
    conn.close()

    out = tmp_path / "report.json"
    rc = health.main(["--db", str(db), "--json", "--out", str(out)])
    assert rc == 0
    assert out.is_file()
    captured = capsys.readouterr().out
    assert "all_checks_pass" in captured
