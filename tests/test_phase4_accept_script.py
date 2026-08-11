"""Phase 4 P0-5 — accept report script smoke test.

Covers the offline path of ``scripts/run_phase4_accept.py`` end-to-end so
the script cannot silently regress. The live path is exercised by
``tests/test_phase4_live_*.py`` under ``QP_LIVE=1``.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "run_phase4_accept.py"


@pytest.fixture(scope="module")
def accept_module():
    spec = importlib.util.spec_from_file_location("run_phase4_accept", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_offline_accept_script_writes_report(tmp_path, accept_module):
    """Offline: the script builds a fixture DB, runs the accept checks,
    and writes a JSON report under the chosen --reports-dir."""
    out = tmp_path / "phase4_accept.json"
    rc = accept_module.main(["--out", str(out)])
    assert rc == 0
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["live"] is False
    assert payload["ok"] is True

    # F1 — registry integrity
    f1 = payload["sections"]["registry_integrity"]
    assert f1["ok"] is True
    role_ids = {f["id"]: f["intended_role"] for f in f1["features"]}
    assert role_ids == {
        "return_1d": "signal",
        "momentum_n": "signal",
        "volatility_n": "signal",
    }

    # F2 — feature hit rates
    f2 = payload["sections"]["feature_hit_rates"]
    for fid in ("return_1d", "momentum_n", "volatility_n"):
        assert fid in f2
        assert f2[fid]["hit_rate"] > 0.0
        assert f2[fid]["non_none"] > 0

    # F3 — feature-using backtest
    f3 = payload["sections"]["backtest"]
    assert f3["ok"] is True
    assert f3["strategy_id"] == "momentum_top_pick_v1"
    assert f3["trading_days"] >= 20
    assert f3["n_trades"] >= 1
    assert f3["core_engine_version"]


def test_offline_accept_persists_to_reports_dir(tmp_path, accept_module):
    """When --out is omitted the script writes under --reports-dir."""
    reports_dir = tmp_path / "reports"
    rc = accept_module.main(["--reports-dir", str(reports_dir)])
    assert rc == 0
    files = list(reports_dir.glob("phase4_accept_*.json"))
    assert len(files) == 1


def test_accept_script_returns_nonzero_when_backtest_floor_unmet(
    tmp_path, accept_module
):
    """``--min-trading-days`` above the fixture's day count must fail."""
    rc = accept_module.main([
        "--out", str(tmp_path / "x.json"),
        "--min-trading-days", "1000",
    ])
    assert rc == 1
    payload = json.loads((tmp_path / "x.json").read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["section_ok"]["backtest"] is False
