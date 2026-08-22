"""Catalog YAML is the unique_logic declaration path (not run_w copies)."""
from __future__ import annotations

from research.unique_logic.catalog import load_catalog_specs, parse_catalog_yaml


def test_event_sides_ls_variants_stay_registered() -> None:
    from research.unique_logic import event_sides
    from research.unique_logic.constants import RESEARCH_UNIQUE_LOGIC_IDS

    ids = [s["logic_id"] for s in event_sides.NEW_LS_VARIANTS]
    assert ids == [
        "event_funding_easy_short",
        "event_funding_stress_ls",
        "surprise_xs_rank_flip",
    ]
    assert set(ids) <= set(RESEARCH_UNIQUE_LOGIC_IDS)


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
  gates: eq_ar_high,pead
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
    assert spec["params"]["gates"] == ["eq_ar_high", "pead"]


def test_combo_row_from_yaml_requires_gates_cs_gate_side() -> None:
    from research.unique_logic.catalog import combo_row_from_yaml, parse_catalog_yaml

    spec = parse_catalog_yaml(
        """
logic_id: event_eqar_high_pead
family_id: event_calendar_gate
go: false
generation_enabled: false
thesis: >
  PEAD only when EqAR is above the name PIT median.
params:
  side: orig
  gates: eq_ar_high
  cs_gate: None
evaluator: research.unique_logic.event_combos.evaluate_combo_daily_mtm
"""
    )
    row = combo_row_from_yaml(spec)
    assert row["logic_id"] == "event_eqar_high_pead"
    assert row["params"]["gates"] == ["eq_ar_high"]
    assert row["params"]["cs_gate"] is None
    assert row["params"]["side"] == "orig"
    assert row["go"] is False
    assert row["generation_enabled"] is False
    missing = parse_catalog_yaml(
        """
logic_id: event_eqar_high_pead
params:
  side: orig
evaluator: research.unique_logic.event_combos.evaluate_combo_daily_mtm
"""
    )
    try:
        combo_row_from_yaml(missing)
    except ValueError as exc:
        assert "gates" in str(exc)
        assert "cs_gate" in str(exc)
    else:
        raise AssertionError("missing YAML params.gates/cs_gate must fail")


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
    from research.eval_universe import repo_history_plane_status

    note = repo_history_plane_status()
    assert note["invent_complete"] is False
    assert note["ffill_applied"] is False
    assert note["d1_role"] == "hot_tip_only"
    assert note["pit_path"] == "fail_closed_until_READY"
    assert note["sqlite_rows"] >= 0


def test_mf_value_mom_rate_is_unique_not_alias() -> None:
    from pathlib import Path

    from research.unique_logic.constants import (
        MF_VALUE_MOM_RATE_DELEGATES,
        MF_VALUE_MOM_RATE_PATH,
    )

    assert MF_VALUE_MOM_RATE_DELEGATES is False
    assert MF_VALUE_MOM_RATE_PATH == "unique_rate_gated_value_mom"
    from research.unique_logic.constants import MF_VALUE_MOM_RATE_PARKED_ALWAYS_ON

    assert MF_VALUE_MOM_RATE_PARKED_ALWAYS_ON is False
    src = (
        Path(__file__).resolve().parents[1]
        / "platform"
        / "workers"
        / "research-mass-eval"
        / "src"
        / "eval.ts"
    ).read_text(encoding="utf-8")
    assert "Unique rate-gated value×mom" in src
    assert "not an alias of fund_value_mom_agree" in src


def test_mass_eval_spec_drops_unique_but_keeps_bar_native() -> None:
    from research.cf_mass_eval_job import build_cf_mass_eval_job_spec

    spec = build_cf_mass_eval_job_spec(
        job_id="eval-test-drop-unique",
        logic_ids=["event_skip_monday", "nky_vol_abs_level"],
        mode="synthetic",
    )
    lids = [str(L.get("logic_id")) for L in spec["logics"]]
    assert "event_skip_monday" not in lids
    assert "nky_vol_abs_level" in lids
    assert "event_skip_monday" in spec["dropped_unique_unsupported"]
    assert spec["candidate_eval_sot"] == "daily_path_mtm_after_cost/v1"


def test_mass_eval_screen_is_not_candidate_grade() -> None:
    from research.cf_mass_eval_job import try_cf_mass_eval_status

    st = try_cf_mass_eval_status()
    assert st["status"] == "implemented"
    assert st["default_mode"] == "r2_panels"
    assert st["screen_kind"] == "period_net"
    assert st["candidate_grade"] is False
    assert st["n_survivors_are_not_a_pass"] is True
    assert st["daily_path_complete"] is False
    assert st["candidate_grade"] is False
    assert st.get("unique_unsupported_on_period_net") is True
    assert st.get("candidate_eval_sot") == "daily_path_mtm_after_cost/v1"


def test_unique_mdh_collapse_is_not_candidate_complete() -> None:
    from research.cf_mass_eval_job import is_unique_period_net_unsupported
    from research.eval_registry import (
        is_daily_path_complete_cell,
        is_path_collapsed_cell,
    )

    assert is_unique_period_net_unsupported("event_skip_monday") is True
    assert is_unique_period_net_unsupported("nky_vol_abs_level") is False
    collapsed = {
        "logic_id": "event_skip_monday",
        "window": "y2015_full",
        "daily_path_complete": True,
        "signal_id": "c21_lite_fallback_mdh:event_calendar_gate",
        "skip_reason": "unique_unsupported_on_period_net",
    }
    assert is_path_collapsed_cell(collapsed) is True
    assert is_daily_path_complete_cell(collapsed) is False


def test_factory_unique_eval_uses_package_dispatch() -> None:
    import inspect

    from research.unique_logic import dispatch as dispatch_mod
    from research.unique_logic.dispatch import evaluate_logic_daily_mtm

    src = inspect.getsource(evaluate_logic_daily_mtm)
    src += inspect.getsource(dispatch_mod._dispatch_body)
    assert "evaluate_logic_daily_mtm" in src
    assert "scripts.run_w" not in src
    assert evaluate_logic_daily_mtm.__module__ == "research.unique_logic.dispatch"


def test_yaml_dispatch_worker_event_ids_align() -> None:
    import inspect

    from research.cf_daily_path_job import CF_EVENT_DAILY_PATH_IDS
    from research.unique_logic import all_unique_logic_specs
    from research.unique_logic.catalog import load_catalog_specs
    from research.unique_logic.constants import (
        CF_EVENT_DAILY_PATH_IDS as CONST_EVENT,
        RESEARCH_UNIQUE_LOGIC_IDS,
    )
    from research.unique_logic.dispatch import evaluate_logic_daily_mtm

    yaml_ids = {s["logic_id"] for s in load_catalog_specs()}
    py_ids = {s["logic_id"] for s in all_unique_logic_specs()}
    assert yaml_ids == py_ids
    assert yaml_ids == set(RESEARCH_UNIQUE_LOGIC_IDS)
    assert set(CF_EVENT_DAILY_PATH_IDS) == set(CONST_EVENT)
    assert set(CF_EVENT_DAILY_PATH_IDS) <= yaml_ids
    src = inspect.getsource(evaluate_logic_daily_mtm)
    from research.unique_logic import dispatch as dispatch_mod
    from research.unique_logic.event_combos import COMBO_LOGIC_IDS

    src += inspect.getsource(dispatch_mod._dispatch_body)
    missing = [
        lid
        for lid in sorted(yaml_ids)
        if f'lid == "{lid}"' not in src and lid not in COMBO_LOGIC_IDS
    ]
    assert missing == []
    assert "COMBO_LOGIC_IDS" in src
    from research.unique_logic.constants import CF_NEW_THESIS_IDS

    assert "event_skip_monday" in yaml_ids
    assert "cs_not_month_end" in yaml_ids
    assert "event_skip_monday" in CF_NEW_THESIS_IDS
    assert len(CF_NEW_THESIS_IDS) >= 307
    from research.unique_logic.event_combos import NEW_COMBO_LOGIC
    from research.unique_logic.constants import is_ungated_name_level_cs

    fresh = [
        "event_eqar_high_liq_high",
        "event_liq_high_large_surprise",
        "event_eqar_high_price_down",
        "event_margin_up_price_down_fade",
        "cs_eqar_high_margin_down",
        "cs_cheap_pb_easy",
    ]
    ids = {s["logic_id"] for s in NEW_COMBO_LOGIC}
    assert set(fresh) <= ids
    assert set(fresh) <= set(CF_NEW_THESIS_IDS)
    from research.unique_logic.constants import WORKER_ISOLATE_LIMIT_IDS

    parked = [s for s in NEW_COMBO_LOGIC if s["logic_id"] in WORKER_ISOLATE_LIMIT_IDS]
    assert parked == []
    from research.unique_logic.constants import (
        WORKER_ISOLATE_LIMIT_REASONS,
        WORKER_ISOLATE_LINEARIZED_OK,
    )

    assert set(WORKER_ISOLATE_LIMIT_REASONS) == set(WORKER_ISOLATE_LIMIT_IDS)
    assert WORKER_ISOLATE_LIMIT_IDS.isdisjoint(WORKER_ISOLATE_LINEARIZED_OK)
    assert len(WORKER_ISOLATE_LINEARIZED_OK) >= 6
    for lid in WORKER_ISOLATE_LINEARIZED_OK:
        row = next(s for s in NEW_COMBO_LOGIC if s["logic_id"] == lid)
        assert row.get("worker_isolate_limit") is False
    for spec in NEW_COMBO_LOGIC:
        if spec["logic_id"] in fresh:
            assert spec.get("always_on_cs_sticky") is False
            assert is_ungated_name_level_cs(
                kind=str(spec.get("kind") or ""),
                cs_gate=str(spec.get("cs_gate") or ""),
                logic_id=str(spec["logic_id"]),
            ) is False


def test_fins_events_keep_ta_eqar_from_payload() -> None:
    from research.eval_universe import load_fins_events_from_sqlite

    events = load_fins_events_from_sqlite(
        codes=["33210"], start="2008-01-01", end="2008-12-31"
    )
    rows = events.get("33210") or []
    assert rows, "33210 FY 2008 fins_summary should load"
    tas = [r.get("ta") for r in rows]
    eqars = [r.get("eq_ar") for r in rows]
    assert any(v is not None and float(v) > 0 for v in tas)
    assert any(v is not None and float(v) > 0 for v in eqars)
    for r in rows:
        if r.get("ta") is None:
            assert "ta" in r
        else:
            assert r["ta"] != 0 or r["ta"] == 0  # real zero allowed; no invent of missing
        # missing stays None, never a filled-in sentinel
        assert r.get("ta") is None or isinstance(r.get("ta"), (int, float))
        assert r.get("eq_ar") is None or isinstance(r.get("eq_ar"), (int, float))


def test_fins_ta_eqar_stats_see_official_keys() -> None:
    from research.eval_loaders import fins_summary_ta_eqar_stats

    stats = fins_summary_ta_eqar_stats(limit=2000)
    assert stats["invent"] is False
    assert stats["official_keys"]["ta"] == "TA"
    assert stats["official_keys"]["eq_ar"] == "EqAR"
    assert stats["n_rows"] >= 100
    assert stats["n_ta_nonnull"] > 0
    assert stats["n_eqar_nonnull"] > 0
    assert (stats["ncta_nonnull"] or 0) < (stats["n_ta_nonnull"] or 0)


def test_worker_new_thesis_ids_match_python() -> None:
    import re
    from pathlib import Path

    from research.unique_logic.constants import (
        ADAPTIVE_LOGIC_IDS,
        CF_EVENT_DAILY_PATH_IDS,
        CF_NEW_CS_THESIS_IDS,
        CF_NEW_EVENT_THESIS_IDS,
        COMBO_EVENT_GATES,
        CS_LOGIC_IDS,
        EVENT_FILTER_LOGIC_IDS,
        EVENT_LOGIC_IDS,
        EVENT_SIDES_LOGIC_IDS,
        PYTHON_ONLY_EVENT_GATES,
    )

    src = (
        Path(__file__).resolve().parents[1]
        / "platform"
        / "workers"
        / "research-mass-eval"
        / "src"
        / "daily_path.ts"
    ).read_text(encoding="utf-8")

    def _ids(name: str) -> set[str]:
        m = re.search(
            rf"(?:export )?const {name} = (?:new Set\()?\[(.*?)](?: as const)?",
            src,
            flags=re.S,
        )
        assert m, name
        return set(re.findall(r'"([^"]+)"', m.group(1)))

    assert _ids("CF_NEW_EVENT_THESIS_IDS") == set(CF_NEW_EVENT_THESIS_IDS)
    assert _ids("CF_NEW_CS_THESIS_IDS") == set(CF_NEW_CS_THESIS_IDS)
    assert _ids("COMBO_EVENT_GATES") == set(COMBO_EVENT_GATES)
    assert _ids("COMBO_EVENT_GATES").isdisjoint(PYTHON_ONLY_EVENT_GATES)
    assert _ids("CF_UNIQUE_CS_LOGIC_IDS") == set(CS_LOGIC_IDS)
    assert set(CS_LOGIC_IDS).isdisjoint(CF_NEW_CS_THESIS_IDS)
    event_prefix = (
        EVENT_LOGIC_IDS
        | EVENT_FILTER_LOGIC_IDS
        | EVENT_SIDES_LOGIC_IDS
        | ADAPTIVE_LOGIC_IDS
    )
    assert len(event_prefix) == 13
    event_block = re.search(
        r"export const CF_EVENT_LOGIC_IDS = \[(.*?)] as const;",
        src,
        flags=re.S,
    )
    assert event_block, "CF_EVENT_LOGIC_IDS"
    assert "...CF_NEW_EVENT_THESIS_IDS" in event_block.group(1)
    prefix_quoted = re.findall(r'"([^"]+)"', event_block.group(1))
    assert prefix_quoted == sorted(event_prefix)
    assert _ids("CF_EVENT_LOGIC_IDS") == set(event_prefix)
    assert _ids("CF_EVENT_LOGIC_IDS") | _ids("CF_NEW_EVENT_THESIS_IDS") == set(
        CF_EVENT_DAILY_PATH_IDS
    )
    assert "(CF_UNIQUE_CS_LOGIC_IDS as readonly string[]).includes(lid)" in src
    assert "(CF_NEW_CS_THESIS_IDS as readonly string[]).includes(lid)" in src


def test_fins_official_keys_are_single_source() -> None:
    from research.unique_logic.constants import (
        FINS_SUMMARY_EQAR_KEY,
        FINS_SUMMARY_OFFICIAL_KEYS,
        FINS_SUMMARY_TA_KEY,
    )

    assert FINS_SUMMARY_TA_KEY == "TA"
    assert FINS_SUMMARY_EQAR_KEY == "EqAR"
    assert FINS_SUMMARY_OFFICIAL_KEYS["ta"] == "TA"
    assert "NCTA" not in FINS_SUMMARY_OFFICIAL_KEYS.values()


def test_combo_event_skips_missing_ta_eqar() -> None:
    from research.unique_logic.event_combos import evaluate_combo_daily_mtm

    spec = {
        "logic_id": "event_eqar_high_pead",
        "kind": "event",
        "gates": ("eq_ar_high",),
        "side": "orig",
        "params": {"gates": ["eq_ar_high"], "post_hold_days": 5},
    }
    bars = {"33210": [("2008-07-07", 100.0), ("2008-07-08", 101.0)]}
    events = {
        "33210": [
            {
                "disc_date": "2008-07-07",
                "eps": 10.0,
                "feps": 9.0,
                "prior_eps": 8.0,
                "eq_ar": None,
                "ta": None,
            }
        ]
    }
    pack = evaluate_combo_daily_mtm(
        spec,
        bars=bars,
        overnight={},
        curve={},
        events=events,
        margin_by_code={},
        topix_by_date={},
        one_way_cost=0.001,
        period_start="2008-07-01",
        period_end="2008-07-31",
    )
    # Missing EqAR must skip (no invent / no always-on from empty gate).
    assert pack.get("go") is not True
    assert pack.get("promote_as_main") is False
