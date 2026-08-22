"""Single freeze surface: pins, Mass/READY/GO, tracks. Not a scorecard."""

from __future__ import annotations


def test_three_default_pins_untouched() -> None:
    from research.daily_path_eval import assert_frozen_pins_untouched
    from research.freezes import (
        FROZEN_DEFAULT_PATH,
        FROZEN_PIN_SNAPSHOT,
        MASS_RESEARCH,
        PHASE7,
        READY_DECLARED,
    )
    from research.mass_strategy_factory import FROZEN_DEFAULT_PATH as FACTORY_PINS

    pack = assert_frozen_pins_untouched()
    assert pack["pins_untouched"] is True
    assert pack["frozen_defaults_retuned"] is False
    assert len(FROZEN_PIN_SNAPSHOT) == 3
    assert len(FROZEN_DEFAULT_PATH) == 3
    assert FACTORY_PINS is FROZEN_DEFAULT_PATH
    assert MASS_RESEARCH == "NO-GO"
    assert READY_DECLARED is False
    assert PHASE7 == "OFF"


def test_freeze_sot_reexports_match() -> None:
    from features.research_freezes import MASS_RESEARCH as FEAT
    from research.cf_daily_path_job import MASS_RESEARCH as CF
    from research.freezes import MASS_RESEARCH as SOT
    from research.hypothesis_classes import MASS_RESEARCH as HC
    from research.mass_strategy_factory import MASS_RESEARCH as FAC

    assert SOT == FEAT == HC == FAC == CF == "NO-GO"


def test_factory_templates_do_not_clone_combo_catalog() -> None:
    from research.mass_strategy_factory import LOGIC_TEMPLATES
    from research.unique_logic.event_combos import NEW_COMBO_LOGIC

    combo_ids = {s["logic_id"] for s in NEW_COMBO_LOGIC}
    cloned = sorted(combo_ids & set(LOGIC_TEMPLATES))
    assert cloned == []
    assert "event_eqar_high_pead" not in LOGIC_TEMPLATES
    assert "event_funding_stress_skip" in LOGIC_TEMPLATES


def test_panel_builder_does_not_head_n_slice() -> None:
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1]
        / "packages"
        / "product"
        / "research"
        / "cf_mass_eval_job.py"
    ).read_text(encoding="utf-8")
    assert "selected[: int(max_codes)]" not in src
    assert "select_eval_universe" in src


def test_eval_tracks_forbid_head_n_and_are_not_a_pass() -> None:
    from research.eval_tracks import (
        EVAL_TRACKS,
        NEXT_RESEARCH_QUEUE,
        eval_track,
    )

    assert set(EVAL_TRACKS) == {"mid_n_explore", "liq_large"}
    for tid in EVAL_TRACKS:
        t = eval_track(tid)
        assert t["head_n_forbidden"] is True
        assert t["go"] is False
        assert t["not_a_pass"] is True
        assert t["universe_select"] == "adv_desc_skip_missing_bars_and_fins"
    assert all(q.get("go") is not True for q in NEXT_RESEARCH_QUEUE)


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
                {
                    "disc_date": "2019-01-04",
                    "disc_time": "12:00:00",
                    "eps": 12.0,
                    "feps": 10.0,
                    "prior_eps": 9.0,
                    "eq_ar": 0.5,
                    "ta": 100.0,
                    "prior_ta": 90.0,
                }
            ]
        },
        margin_by_code={},
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-31",
    )
    # Unknown gate must not silently always-on.
    occ = pack.get("occupancy") or pack.get("occupancy_frac") or 0.0
    n_on = int(pack.get("n_gate_on_days") or 0)
    assert n_on == 0 or float(occ) == 0.0 or pack.get("status") != "ok" or pack.get("n_entered") in (0, None)


def test_harness_default_eval_codes_are_smoke_three() -> None:
    from research.eval_harness import DEFAULT_EVAL_CODES, HARNESS_SMOKE_CODES

    assert DEFAULT_EVAL_CODES == HARNESS_SMOKE_CODES == ("13010", "72030", "67580")


def test_cf_combo_specs_carry_gates() -> None:
    from research.cf_mass_eval_job import default_logic_specs

    rows = default_logic_specs(["event_eqar_high_pead", "event_eqar_high_liq_high"])
    by = {r["logic_id"]: r for r in rows}
    assert by["event_eqar_high_pead"]["params"].get("gates")
    assert "eq_ar_high" in by["event_eqar_high_pead"]["params"]["gates"]
    assert "liq_high" in by["event_eqar_high_liq_high"]["params"]["gates"]
