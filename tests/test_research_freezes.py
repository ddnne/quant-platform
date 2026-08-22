"""Single freeze surface: pins, Mass/READY/GO, tracks. Not a scorecard."""

from __future__ import annotations

from tests.research_eval_util import _disc_event, _event_eval_kw


def test_three_default_pins_untouched() -> None:
    from research.daily_path_eval import assert_frozen_pins_untouched
    from research.freezes import (
        FROZEN_DEFAULT_PATH,
        FROZEN_PIN_SNAPSHOT,
        MASS_RESEARCH,
        PHASE7,
        READY_DECLARED,
    )

    pack = assert_frozen_pins_untouched()
    assert pack["pins_untouched"] is True
    assert pack["frozen_defaults_retuned"] is False
    assert len(FROZEN_PIN_SNAPSHOT) == 3
    assert len(FROZEN_DEFAULT_PATH) == 3
    assert MASS_RESEARCH == "NO-GO"
    assert READY_DECLARED is False
    assert PHASE7 == "OFF"


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


def test_harness_default_eval_codes_are_smoke_three() -> None:
    import research.eval_universe as eu

    assert eu.HARNESS_SMOKE_CODES == ("13010", "72030", "67580")
    assert not hasattr(eu, "DEFAULT_EVAL_CODES")
    assert len(eu.EVAL_UNIVERSE_POOL) > 3


def test_research_modules_ast_bans_mass_ready_orders() -> None:
    from agents.mass_research import start_mass_research
    from selection.budget_ledger import MassResearchDisabledError
    from tests.research_eval_util import (
        HARNESS_AST_PATHS,
        assert_ast_bans_mass_ready_orders,
    )
    import pytest

    assert HARNESS_AST_PATHS
    for path in HARNESS_AST_PATHS:
        assert path.is_file(), path
        assert_ast_bans_mass_ready_orders(path)
    with pytest.raises(MassResearchDisabledError):
        start_mass_research(budget=None, readiness=None)


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


def test_unique22_leftover_occupancy_not_unified() -> None:
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1]
        / "platform"
        / "workers"
        / "research-mass-eval"
        / "src"
        / "daily_path.ts"
    ).read_text(encoding="utf-8")
    assert "momentumAt(entryIdx)" in src
    assert "entryIdx - 1" in src or "entryIdx-1" in src


def test_cheap_pb_event_not_csfundsnaps() -> None:
    from pathlib import Path

    from research.unique_logic.constants import (
        CHEAP_PB_CS_SOURCE,
        CHEAP_PB_EVENT_SOURCE,
        CHEAP_PB_UNIFIED,
    )

    assert CHEAP_PB_UNIFIED is False
    assert CHEAP_PB_EVENT_SOURCE == "bars_x_fins_bps_over_close"
    assert CHEAP_PB_CS_SOURCE == "cs_fund_snaps"
    src = (
        Path(__file__).resolve().parents[1]
        / "platform"
        / "workers"
        / "research-mass-eval"
        / "src"
        / "daily_path.ts"
    ).read_text(encoding="utf-8")
    assert "Event cheap_pb is bars×fins" in src
    assert "CS cheap_pb is csFundSnaps" in src or "csFundSnaps extras.cheapPb" in src


def test_unique22_lift_park_partition() -> None:
    from research.unique_logic.worker_bodies import (
        unique22_occupancy_equal_lifted,
        unique22_occupancy_park,
        unique_leftover_logic_ids,
    )

    leftover = unique_leftover_logic_ids()
    lifted = unique22_occupancy_equal_lifted()
    parked = unique22_occupancy_park()
    assert lifted | parked == leftover
    assert "event_pre_mom_agree_hold" in parked
    assert "afterclose_only_event_hold" in lifted
    assert len(lifted) == 5
    assert len(parked) == 17


def test_near_empty_park_is_not_countable_or_basket_material() -> None:
    from research.combo_basket_catalog import validate_basket_members
    from research.unique_logic.constants import (
        CANDIDATE_POLICY,
        NEAR_EMPTY_OCCUPANCY,
        NEAR_EMPTY_PARK_IDS,
    )
    from research.unique_logic.worker_bodies import (
        NearEmptyBatchError,
        assert_new_batch_occupancy_not_near_empty,
        countable_thesis_ids,
        is_countable_spec,
        near_empty_occupancy_park,
    )
    from research.unique_logic.catalog import catalog_spec

    parked = near_empty_occupancy_park()
    assert parked == NEAR_EMPTY_PARK_IDS
    assert "event_cheap_iv_eqar_rising_steep" in parked
    assert "event_nkyvol_steep_uncrowded" in parked
    countable = countable_thesis_ids()
    for lid in parked:
        spec = catalog_spec(lid)
        assert spec is not None
        assert is_countable_spec(spec) is False
        assert lid not in countable
    reasons = validate_basket_members(
        ["event_eqar_high_liq_high", next(iter(parked))]
    )
    assert "near_empty_member" in reasons
    assert "near_empty_parked" in CANDIDATE_POLICY["exclude"]
    occ = {lid: 0.20 for lid in ("a", "b", "c")}
    ok = assert_new_batch_occupancy_not_near_empty(occ)
    assert ok["ok"] is True
    assert ok["n_near_empty"] == 0
    try:
        assert_new_batch_occupancy_not_near_empty(
            {"ok_one": 0.20, "empty_one": NEAR_EMPTY_OCCUPANCY}
        )
        raise AssertionError("near_empty batch must reject")
    except NearEmptyBatchError:
        pass

    from pathlib import Path
    import json
    from research.unique_logic.worker_bodies import (
        assert_near_empty_park_covers,
        mean_occupancy_by_logic,
    )

    cells_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "ops"
        / "research_eval"
        / "eval-cf-dp-liq100-plus32vf-20260823h_cells.json"
    )
    if cells_path.is_file():
        occ_map = mean_occupancy_by_logic(json.loads(cells_path.read_text(encoding="utf-8")))
        cover = assert_near_empty_park_covers(occ_map)
        assert cover["ok"] is True
        assert cover["n_recorded"] >= 4
        assert cover["missing_from_park"] == []

    from research.unique_logic.constants import SPARSE_GATE_COMBOS

    sparse = [combo for combo, _ in SPARSE_GATE_COMBOS]
    for lid in parked:
        spec = catalog_spec(lid)
        params = spec.get("params") if isinstance(spec.get("params"), dict) else {}
        gates = frozenset(str(g) for g in (params.get("gates") or []) if str(g).strip())
        assert any(combo <= gates for combo in sparse), (
            f"{lid} parked empty but no SPARSE_GATE_COMBOS subset covers {sorted(gates)}"
        )


def test_always_on_batch_guard_and_empty_park() -> None:
    from research.combo_basket_catalog import validate_basket_members
    from research.unique_logic.constants import (
        ALWAYS_ON_OCCUPANCY_WARN,
        ALWAYS_ON_PARK_IDS,
        CANDIDATE_POLICY,
    )
    from research.unique_logic.worker_bodies import (
        AlwaysOnBatchError,
        always_on_occupancy_park,
        assert_new_batch_occupancy_in_material_band,
        assert_new_batch_occupancy_not_always_on,
        countable_thesis_ids,
    )

    assert always_on_occupancy_park() == ALWAYS_ON_PARK_IDS
    assert "always_on_parked" in CANDIDATE_POLICY["exclude"]
    assert ALWAYS_ON_PARK_IDS.isdisjoint(countable_thesis_ids())
    ok = assert_new_batch_occupancy_not_always_on(
        {"a": 0.20, "b": 0.40, "c": 0.30}
    )
    assert ok["ok"] is True
    assert ok["n_always_on"] == 0
    try:
        assert_new_batch_occupancy_not_always_on(
            {"ok_one": 0.20, "sticky": ALWAYS_ON_OCCUPANCY_WARN}
        )
        raise AssertionError("always_on batch must reject")
    except AlwaysOnBatchError:
        pass
    band = assert_new_batch_occupancy_in_material_band(
        {"a": 0.20, "b": 0.40}
    )
    assert band["ok"] is True
    try:
        assert_new_batch_occupancy_in_material_band({"sticky": 0.90})
        raise AssertionError("material band must reject always_on")
    except AlwaysOnBatchError:
        pass
    if ALWAYS_ON_PARK_IDS:
        reasons = validate_basket_members(
            ["event_eqar_high_liq_high", next(iter(ALWAYS_ON_PARK_IDS))]
        )
        assert "always_on_member" in reasons


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

