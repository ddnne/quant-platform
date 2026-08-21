"""Catalog YAML is the unique_logic declaration path (not run_w copies)."""
from __future__ import annotations

from research.unique_logic.catalog import load_catalog_specs, parse_catalog_yaml


def test_parse_catalog_yaml_folded_and_params() -> None:
    spec = parse_catalog_yaml(
        """
logic_id: overnight_level_cs_tilt
headline: true
go: false
thesis: >
  Tight overnight level should be faded.
datasets:
  - jsda_tokyo_repo_rates
  - equities_bars_daily
params:
  hold_days: 10
  momentum_n: 5
evaluator: research.unique_logic.cs_overlays.evaluate_overnight_level_cs_tilt_daily_mtm
"""
    )
    assert spec["logic_id"] == "overnight_level_cs_tilt"
    assert spec["headline"] is True
    assert spec["go"] is False
    assert "overnight" in spec["thesis"]
    assert spec["datasets"] == ["jsda_tokyo_repo_rates", "equities_bars_daily"]
    assert spec["params"]["hold_days"] == 10
    assert spec["params"]["momentum_n"] == 5


def test_dispatch_unknown_logic_is_incomplete() -> None:
    from research.unique_logic.dispatch import evaluate_logic_daily_mtm

    pack = evaluate_logic_daily_mtm(
        {"logic_id": "not_a_real_logic"},
        bars={},
        overnight={},
        curve={},
        events={},
        margin_by_code={},
        topix_by_date={},
        one_way_cost=0.001,
    )
    assert pack["daily_path_complete"] is False
    assert pack["status"] == "unknown_logic"


def test_repo_catalog_yaml_loads() -> None:
    specs = load_catalog_specs()
    ids = {s["logic_id"] for s in specs}
    assert "overnight_level_cs_tilt" in ids
    assert "xs_low_vol_mom" in ids
    assert "month_end_cs_fade" in ids
    for spec in specs:
        assert spec.get("go") is not True
        assert spec.get("promote_as_main") is not True
