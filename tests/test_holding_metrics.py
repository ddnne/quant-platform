"""W65 research holding-period / turnover metrics — 研究用・未宣言."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from research.holding_metrics import (
    DEFAULT_ONE_WAY_COST,
    DEFAULT_ONE_WAY_COST_BP,
    HOLDING_METRICS_LABEL,
    HOLDING_METRICS_VERSION,
    cost_amortization_report,
    cost_amortization_table,
    extract_sign_panel_from_batch_summary,
    holding_metrics_report,
    panel_run_length_stats,
    run_length_distribution,
    run_lengths_for_sign_sequence,
    sign_from_value,
)

REPO = Path(__file__).resolve().parents[1]
MOD_PATH = REPO / "packages" / "product" / "research" / "holding_metrics.py"


# ---------------------------------------------------------------------------
# Freeze / closed surface
# ---------------------------------------------------------------------------


def test_document_freeze_mass_ready_off():
    assert HOLDING_METRICS_VERSION.startswith("research-holding-metrics/")
    assert "仮定に依存" in HOLDING_METRICS_LABEL
    assert "研究用" in HOLDING_METRICS_LABEL
    assert "未宣言" in HOLDING_METRICS_LABEL


def test_report_api_dicts_freeze_closed():
    records = [
        {"date": "2020-01-01", "code": "A", "sign": 1},
        {"date": "2020-01-02", "code": "A", "sign": 1},
        {"date": "2020-01-03", "code": "A", "sign": -1},
    ]
    report = holding_metrics_report(records)
    for key in (
        "ready_declared",
        "operational_go",
        "edge_claimed",
        "significance_claimed",
        "connected_to_ready",
        "connected_to_mass",
    ):
        assert report[key] is False
    assert report["mass_research"] == "NO-GO"
    assert report["phase7"] == "OFF"

    amort = cost_amortization_report()
    assert amort["ready_declared"] is False
    assert amort["mass_research"] == "NO-GO"
    assert amort["phase7"] == "OFF"
    assert amort["operational_go"] is False

    stats = panel_run_length_stats(records)
    assert stats["ready_declared"] is False
    assert stats["mass_research"] == "NO-GO"


def test_module_source_has_no_ready_mint_or_mass_arm():
    """Static guard: holding_metrics must not mint READY or arm Mass."""
    src = MOD_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    banned_calls = {
        "require_mass_research_start",
        "VerifiedResearchReadiness",
        "mint_ready",
        "declare_ready",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            assert name not in banned_calls
    assert "READY_DECLARED" in src
    assert "MASS_RESEARCH" in src


# ---------------------------------------------------------------------------
# Run-length known sequences
# ---------------------------------------------------------------------------


def test_sign_from_value():
    assert sign_from_value(1.0) == 1
    assert sign_from_value(-0.5) == -1
    assert sign_from_value(0) == 0
    assert sign_from_value(None) is None
    assert sign_from_value("+1") == 1
    assert sign_from_value("-1") == -1
    assert sign_from_value("flat") == 0


def test_run_lengths_known_sequence():
    # ++-++--  → runs of 2, 1, 2, 2
    signs = [1, 1, -1, 1, 1, -1, -1]
    assert run_lengths_for_sign_sequence(signs) == [2, 1, 2, 2]


def test_run_lengths_zero_and_null_break():
    # ++0++ → 2, 2  (zero breaks)
    assert run_lengths_for_sign_sequence([1, 1, 0, 1, 1]) == [2, 2]
    # ++None++ → 2, 2
    assert run_lengths_for_sign_sequence([1, 1, None, 1, 1]) == [2, 2]
    # all flat / null → no runs
    assert run_lengths_for_sign_sequence([0, 0, None, 0]) == []
    # single day
    assert run_lengths_for_sign_sequence([1]) == [1]


def test_run_length_distribution_stats():
    # runs: 1, 2, 2, 4  → n=4, mean=2.25, median=2, p50=2, p90=4 (nearest-rank)
    dist = run_length_distribution([1, 2, 2, 4])
    assert dist["n_runs"] == 4
    assert dist["mean"] == pytest.approx(2.25)
    assert dist["median"] == pytest.approx(2.0)
    assert dist["p50"] == pytest.approx(2.0)
    assert dist["p90"] == pytest.approx(4.0)
    assert dist["min"] == 1.0
    assert dist["max"] == 4.0
    # histogram has buckets and total counts sum to n_runs
    hist = dist["histogram"]
    assert sum(h["count"] for h in hist) == 4
    labels = {h["label"]: h["count"] for h in hist}
    assert labels["1"] == 1
    assert labels["2"] == 2
    assert labels["4-5"] == 1


def test_panel_run_length_two_codes():
    records = [
        {"date": "2020-01-01", "code": "A", "sign": 1},
        {"date": "2020-01-02", "code": "A", "sign": 1},
        {"date": "2020-01-03", "code": "A", "sign": 1},
        {"date": "2020-01-01", "code": "B", "sign": -1},
        {"date": "2020-01-02", "code": "B", "sign": 1},
        {"date": "2020-01-03", "code": "B", "sign": 1},
    ]
    stats = panel_run_length_stats(records)
    assert stats["n_codes"] == 2
    assert stats["n_runs_total"] == 3  # A:[3], B:[1,2]
    assert stats["run_length"]["mean"] == pytest.approx(2.0)
    assert stats["per_code_mean_run_length"]["A"] == pytest.approx(3.0)
    assert stats["per_code_mean_run_length"]["B"] == pytest.approx(1.5)
    assert stats["ready_declared"] is False
    assert stats["mass_research"] == "NO-GO"


# ---------------------------------------------------------------------------
# Cost amortization table
# ---------------------------------------------------------------------------


def test_amortization_table_10bp():
    rows = cost_amortization_table(one_way_cost=0.001, hold_days=[1, 2, 5, 10])
    assert len(rows) == 4
    by_n = {r["hold_days_N"]: r for r in rows}
    assert by_n[1]["effective_daily_cost"] == pytest.approx(0.001)
    assert by_n[1]["effective_daily_cost_bp"] == pytest.approx(10.0)
    assert by_n[2]["effective_daily_cost"] == pytest.approx(0.0005)
    assert by_n[2]["effective_daily_cost_bp"] == pytest.approx(5.0)
    assert by_n[5]["effective_daily_cost"] == pytest.approx(0.0002)
    assert by_n[5]["effective_daily_cost_bp"] == pytest.approx(2.0)
    assert by_n[10]["effective_daily_cost"] == pytest.approx(0.0001)
    assert by_n[10]["effective_daily_cost_bp"] == pytest.approx(1.0)
    # round-trip = 2 * one_way / N
    assert by_n[1]["effective_daily_cost_round_trip"] == pytest.approx(0.002)
    assert by_n[10]["effective_daily_cost_round_trip_bp"] == pytest.approx(2.0)


def test_amortization_defaults_match_gate_cost():
    assert DEFAULT_ONE_WAY_COST_BP == 10.0
    assert DEFAULT_ONE_WAY_COST == pytest.approx(0.001)
    rows = cost_amortization_table()
    assert rows[0]["one_way_cost"] == pytest.approx(0.001)
    assert rows[0]["hold_days_N"] == 1


def test_amortization_rejects_non_positive_hold():
    with pytest.raises(ValueError):
        cost_amortization_table(hold_days=[0, 1])


# ---------------------------------------------------------------------------
# Batch-summary extract (synthetic artifact shape)
# ---------------------------------------------------------------------------


def test_extract_panel_unanimous_majority():
    batch = {
        "signal_id": "c21_topix_relative_sign",
        "job_id": "synthetic",
        "codes": ["13010", "72030"],
        "per_day": [
            {
                "date": "2015-10-16",
                "sign_distribution": {"+1": 0, "-1": 2, "0": 0, "null": 0},
                "sample_values": [
                    {"code": "13010", "value": -1.0},
                    {"code": "72030", "value": -1.0},
                ],
            },
            {
                "date": "2015-10-19",
                "sign_distribution": {"+1": 2, "-1": 0, "0": 0, "null": 0},
                "sample_values": [
                    {"code": "13010", "value": 1.0},
                    {"code": "72030", "value": 1.0},
                ],
            },
            {
                "date": "2015-10-20",
                "sign_distribution": {"+1": 2, "-1": 0, "0": 0, "null": 0},
                "sample_values": [
                    {"code": "13010", "value": 1.0},
                    {"code": "72030", "value": 1.0},
                ],
            },
        ],
    }
    panel = extract_sign_panel_from_batch_summary(batch)
    assert panel["source"] == "sign_distribution_majority_expanded_unanimous"
    assert panel["n_records"] == 6  # 3 days × 2 codes
    assert panel["ready_declared"] is False
    assert panel["mass_research"] == "NO-GO"
    report = holding_metrics_report(panel["records"])
    # each code: -1, +1, +1 → runs [1, 2]; two codes → 4 runs mean 1.5
    assert report["run_length_stats"]["run_length"]["mean"] == pytest.approx(1.5)
    assert report["ready_declared"] is False
    assert report["edge_claimed"] is False
