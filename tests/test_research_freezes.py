"""Single freeze surface: pins, Mass/READY/GO, tracks. Not a scorecard."""

from __future__ import annotations

from tests.research_eval_util import _disc_event, _event_eval_kw


def test_unknown_event_gate_fails_closed() -> None:
    from research.unique_logic.constants import KNOWN_EVENT_GATES
    from research.unique_logic.event_combos import spec_by_id, evaluate_combo_daily_mtm

    assert "not_a_real_gate" not in KNOWN_EVENT_GATES
    spec = spec_by_id("event_eqar_high_pead")
    assert spec is not None
    forged = dict(spec)
    params = dict(forged.get("params") or {})
    params["gates"] = ["not_a_real_gate"]
    forged["params"] = params
    forged["gates"] = ("not_a_real_gate",)
    pack = evaluate_combo_daily_mtm(
        forged,
        bars={"13010": [("2019-01-04", 100.0), ("2019-01-07", 101.0)]},
        overnight={"2019-01-04": 0.05, "2019-01-07": 0.04},
        curve={"spread_by_date": {"2019-01-04": 0.01, "2019-01-07": 0.01}},
        events={
            "13010": [
                _disc_event(
                    "2019-01-04",
                    disc_time="12:00:00",
                    eps=12.0,
                    feps=10.0,
                    prior_eps=9.0,
                    eq_ar=0.5,
                    ta=100.0,
                    prior_ta=90.0,
                )
            ]
        },
        margin_by_code={},
        **_event_eval_kw(period_end="2019-01-31"),
    )
    occ = pack.get("occupancy") or pack.get("occupancy_frac") or 0.0
    n_on = int(pack.get("n_gate_on_days") or 0)
    assert n_on == 0 or float(occ) == 0.0 or pack.get("status") != "ok" or pack.get("n_entered") in (0, None)


def test_unknown_cs_gate_fails_closed() -> None:
    from research.unique_logic.event_combos import spec_by_id, evaluate_combo_daily_mtm

    spec = spec_by_id("cs_margin_up_chase")
    assert spec is not None
    assert spec.get("kind") == "cs"
    forged = dict(spec)
    params = dict(forged.get("params") or {})
    params["cs_gate"] = "not_a_real_cs_gate"
    forged["params"] = params
    forged["cs_gate"] = "not_a_real_cs_gate"
    pack = evaluate_combo_daily_mtm(
        forged,
        bars={
            "13010": [("2019-01-04", 100.0), ("2019-01-07", 101.0)],
            "72030": [("2019-01-04", 200.0), ("2019-01-07", 199.0)],
        },
        overnight={"2019-01-04": 0.05, "2019-01-07": 0.04},
        curve={"spread_by_date": {"2019-01-04": 0.01, "2019-01-07": 0.01}},
        events={},
        margin_by_code={},
        **_event_eval_kw(period_end="2019-01-31"),
    )
    occ = pack.get("occupancy") or pack.get("occupancy_frac") or 0.0
    n_on = int(pack.get("n_gate_on_days") or 0)
    assert float(occ) == 0.0
    assert n_on == 0
    assert pack.get("n_entered") in (0, None)
    assert pack.get("always_on_cs_sticky") is not True
    assert pack.get("go") is not True


def test_factory_templates_do_not_clone_combo_catalog() -> None:
    from research.offline.factory import LOGIC_TEMPLATES
    from research.unique_logic.constants import RESEARCH_UNIQUE_LOGIC_IDS
    from research.unique_logic.event_combos import NEW_COMBO_LOGIC

    combo_ids = {s["logic_id"] for s in NEW_COMBO_LOGIC}
    cloned = sorted(combo_ids & set(LOGIC_TEMPLATES))
    assert cloned == []
    assert "event_eqar_high_pead" not in LOGIC_TEMPLATES
    assert "event_funding_stress_skip" in RESEARCH_UNIQUE_LOGIC_IDS
    assert "event_funding_stress_skip" not in LOGIC_TEMPLATES


def test_cf_combo_specs_carry_gates() -> None:
    from research.cf_mass_eval_job import default_logic_specs

    rows = default_logic_specs(["event_eqar_high_pead", "event_eqar_high_liq_high"])
    by = {r["logic_id"]: r for r in rows}
    assert by["event_eqar_high_pead"]["params"].get("gates")
    assert "eq_ar_high" in by["event_eqar_high_pead"]["params"]["gates"]
    assert "liq_high" in by["event_eqar_high_liq_high"]["params"]["gates"]


def test_cheap_pb_event_not_csfundsnaps() -> None:
    from research.unique_logic.constants import (
        CHEAP_PB_CS_SOURCE,
        CHEAP_PB_EVENT_SOURCE,
        CHEAP_PB_UNIFIED,
    )

    assert CHEAP_PB_UNIFIED is False
    assert CHEAP_PB_EVENT_SOURCE == "bars_x_fins_bps_over_close"
    assert CHEAP_PB_CS_SOURCE == "cs_fund_snaps"


def test_propose_calendar_gates_excluded_from_llm() -> None:
    from research.unique_logic.constants import (
        COMBO_EVENT_GATES,
        PROPOSE_ALLOWED_GATES,
        PROPOSE_CALENDAR_GATES,
    )

    assert PROPOSE_CALENDAR_GATES <= COMBO_EVENT_GATES
    assert PROPOSE_ALLOWED_GATES == COMBO_EVENT_GATES - PROPOSE_CALENDAR_GATES
    assert "skip_monday" in PROPOSE_CALENDAR_GATES
    assert "liq_high" in PROPOSE_ALLOWED_GATES


def test_cost_defaults_are_shared() -> None:
    from research.cost_defaults import DEFAULT_ONE_WAY_COST, DEFAULT_ONE_WAY_COST_BP
    from research.cost_models import DEFAULT_ONE_WAY_COST as cost_cost
    from research.holding_metrics import DEFAULT_ONE_WAY_COST as hold_cost
    from research.paper_candidate_adapt import DEFAULT_ONE_WAY_COST as paper_cost
    from research.robustness_gate import DEFAULT_ONE_WAY_COST as gate_cost

    assert DEFAULT_ONE_WAY_COST_BP == 10.0
    assert DEFAULT_ONE_WAY_COST == 0.001
    assert cost_cost == hold_cost == paper_cost == gate_cost == DEFAULT_ONE_WAY_COST



def test_default_logic_specs_leftover_and_bar_native() -> None:
    from research.cf_mass_eval_job import default_logic_specs

    leftover = default_logic_specs(["rate_abs_level_xs"])
    assert leftover
    assert leftover[0]["logic_id"] == "rate_abs_level_xs"
    assert leftover[0]["family_id"] == "unknown"
    native = default_logic_specs(["mdh_sticky_momentum"])
    assert native[0]["logic_id"] == "mdh_sticky_momentum"
    assert native[0]["family_id"] == "multi_day_hold"
    assert native[0]["params"]
