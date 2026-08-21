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
    from research.unique_logic import all_unique_logic_specs

    specs = load_catalog_specs()
    ids = {s["logic_id"] for s in specs}
    py_ids = {s["logic_id"] for s in all_unique_logic_specs()}
    assert "overnight_level_cs_tilt" in ids
    assert "overnight_easy_cs_follow" in ids
    assert "xs_low_vol_mom" in ids
    assert "month_end_cs_fade" in ids
    assert len(ids) >= 20
    assert ids == py_ids
    for spec in specs:
        assert spec.get("go") is not True
        assert spec.get("promote_as_main") is not True


def test_repo_history_plane_status_discloses_sqlite_not_d1() -> None:
    from research.class_hyp_eval import repo_history_plane_status

    note = repo_history_plane_status()
    assert note["invent_complete"] is False
    assert note["ffill_applied"] is False
    assert note["d1_role"] == "hot_tip_only"
    assert note["pit_path"] == "fail_closed_until_READY"
    assert note["sqlite_rows"] >= 0


def test_mass_eval_screen_is_not_candidate_grade() -> None:
    from research.cf_mass_eval_job import try_cf_mass_eval_status

    st = try_cf_mass_eval_status()
    assert st["status"] == "implemented"
    assert st["default_mode"] == "r2_panels"
    assert st["screen_kind"] == "period_net"
    assert st["candidate_grade"] is False
    assert st["n_survivors_are_not_a_pass"] is True
    assert st["daily_path_complete"] is False


def test_factory_unique_eval_uses_package_dispatch() -> None:
    import inspect

    from research.mass_strategy_factory import _eval_research_unique_on_panel

    src = inspect.getsource(_eval_research_unique_on_panel)
    assert "evaluate_logic_daily_mtm" in src
    assert "scripts.run_w" not in src
    assert "from research.unique_logic.dispatch import" in src


def test_yaml_dispatch_worker_event_ids_align() -> None:
    import inspect

    from research.cf_daily_path_job import CF_EVENT_DAILY_PATH_IDS
    from research.mass_strategy_factory import RESEARCH_UNIQUE_LOGIC_IDS
    from research.unique_logic import all_unique_logic_specs
    from research.unique_logic.catalog import load_catalog_specs
    from research.unique_logic.constants import CF_EVENT_DAILY_PATH_IDS as CONST_EVENT
    from research.unique_logic.dispatch import evaluate_logic_daily_mtm

    yaml_ids = {s["logic_id"] for s in load_catalog_specs()}
    py_ids = {s["logic_id"] for s in all_unique_logic_specs()}
    assert yaml_ids == py_ids
    assert yaml_ids == set(RESEARCH_UNIQUE_LOGIC_IDS)
    assert set(CF_EVENT_DAILY_PATH_IDS) == set(CONST_EVENT)
    assert set(CF_EVENT_DAILY_PATH_IDS) <= yaml_ids
    src = inspect.getsource(evaluate_logic_daily_mtm)
    missing = [lid for lid in sorted(yaml_ids) if f'lid == "{lid}"' not in src]
    assert missing == []
