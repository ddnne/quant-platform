"""W87 / w0816v — mass strategy factory: diversity, ID stability, fail-one-safe."""

from __future__ import annotations

import pytest

from research.hypothesis_classes import (
    CLASS_CROSS_SECTION_RELATIVE,
    CLASS_EVENT_POST,
    CLASS_FLOW_DEMAND,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_MACRO_CONDITIONED,
    CLASS_MULTI_DAY_HOLD,
    CLASS_SIMPLE_DAILY_SIGN,
)
from research.mass_strategy_factory import (
    CONTINUOUS_PAPER,
    DEFAULT_FAMILY_RATIOS,
    DEFAULT_MAX_FAMILY_SHARE,
    DEFAULT_N,
    FAMILY_DEFINITIONS,
    FAMILY_VOL_RISK_ADJUSTED,
    FACTORY_FAMILY_IDS,
    MASS_FACTORY_VERSION,
    MASS_FACTORY_WAVE,
    MASS_RESEARCH,
    OPERATIONAL_GO,
    PHASE7,
    READY_DECLARED,
    REJECT_LOOKAHEAD,
    REJECT_SIMPLE_DAILY_SIGN,
    MassFactoryConfig,
    evaluate_one_strategy,
    family_definitions_document,
    generate_strategy_batch,
    load_batch_data_context,
    mass_factory_document,
    run_batch_eval,
    run_mass_factory,
    screen_strategy_result,
    stable_strategy_id,
    validate_strategy_at_gen,
)


def test_freezes_closed():
    doc = mass_factory_document()
    assert doc["mass_research"] == "NO-GO"
    assert doc["phase7"] == "OFF"
    assert doc["ready_declared"] is False
    assert doc["operational_go"] is False
    assert doc["continuous_paper"] == "UNARMED"
    assert MASS_RESEARCH == "NO-GO"
    assert PHASE7 == "OFF"
    assert READY_DECLARED is False
    assert OPERATIONAL_GO is False
    assert CONTINUOUS_PAPER == "UNARMED"
    assert "W87" in MASS_FACTORY_WAVE
    assert MASS_FACTORY_VERSION.startswith("mass-strategy-factory/")


def test_families_defined_and_multi_axis():
    fams = family_definitions_document()
    assert len(fams["family_ids"]) >= 6
    # core hypothesis classes present
    for cid in (
        CLASS_MULTI_DAY_HOLD,
        CLASS_EVENT_POST,
        CLASS_CROSS_SECTION_RELATIVE,
        CLASS_MACRO_CONDITIONED,
        CLASS_FUNDAMENTALS_PRICE,
        CLASS_FLOW_DEMAND,
    ):
        assert cid in FAMILY_DEFINITIONS
        assert cid in FACTORY_FAMILY_IDS
        assert len(FAMILY_DEFINITIONS[cid].param_axes) >= 2
    assert FAMILY_VOL_RISK_ADJUSTED in FAMILY_DEFINITIONS
    # simple_daily_sign is NOT a factory diversity family
    assert CLASS_SIMPLE_DAILY_SIGN not in FAMILY_DEFINITIONS
    assert CLASS_SIMPLE_DAILY_SIGN not in DEFAULT_FAMILY_RATIOS


def test_sampling_diversity_n100_anti_bias():
    gen = generate_strategy_batch(seed=870816, n=100)
    assert gen["n_generated_accepted"] >= 100
    assert gen["n_ge_100"] is True
    assert gen["n_families_used"] >= 5
    dist = gen["family_distribution"]
    # multi-family, not one family flood
    assert len([v for v in dist.values() if v > 0]) >= 5
    # anti-bias: no family exceeds max share (+1 for integer rounding)
    max_share = gen["max_family_share_observed"]
    assert max_share <= DEFAULT_MAX_FAMILY_SHARE + 0.05
    # not mom-grid-only: cross_section params must vary multiple axes
    xs = [
        s
        for s in gen["strategies"]
        if s["family_id"] == CLASS_CROSS_SECTION_RELATIVE
    ]
    assert len(xs) >= 5
    mom_vals = {s["params"].get("momentum_n") for s in xs}
    hold_vals = {s["params"].get("hold_days") for s in xs}
    frac_vals = {(s["params"].get("long_frac"), s["params"].get("short_frac")) for s in xs}
    # diversity across axes (not only mom 3/4/5…)
    assert len(hold_vals) >= 2
    assert len(mom_vals) >= 2
    assert len(frac_vals) >= 2
    # no simple_daily_sign
    assert all(s["family_id"] != CLASS_SIMPLE_DAILY_SIGN for s in gen["strategies"])


def test_id_stability_reproducible():
    g1 = generate_strategy_batch(seed=42, n=30)
    g2 = generate_strategy_batch(seed=42, n=30)
    ids1 = [s["strategy_id"] for s in g1["strategies"]]
    ids2 = [s["strategy_id"] for s in g2["strategies"]]
    assert ids1 == ids2
    assert len(ids1) == len(set(ids1))  # unique
    # stable_strategy_id pure helper
    p = {"hold_days": 10, "momentum_n": 5}
    a = stable_strategy_id(seed=1, family_id="multi_day_hold", params=p, generation_index=0)
    b = stable_strategy_id(seed=1, family_id="multi_day_hold", params=p, generation_index=0)
    c = stable_strategy_id(seed=1, family_id="multi_day_hold", params=p, generation_index=1)
    assert a == b
    assert a != c
    # different seed → different ids
    g3 = generate_strategy_batch(seed=43, n=30)
    ids3 = [s["strategy_id"] for s in g3["strategies"]]
    assert ids1 != ids3


def test_gen_time_reject_lookahead_and_simple_daily():
    ok, reason = validate_strategy_at_gen(
        CLASS_SIMPLE_DAILY_SIGN, {"x": 1}
    )
    assert ok is False
    assert reason == REJECT_SIMPLE_DAILY_SIGN

    ok2, reason2 = validate_strategy_at_gen(
        CLASS_EVENT_POST,
        {"post_hold_days": 5, "entry_mode": "same_day_close_always"},
    )
    assert ok2 is False
    assert reason2 == REJECT_LOOKAHEAD

    ok3, reason3 = validate_strategy_at_gen(
        CLASS_EVENT_POST,
        {"post_hold_days": 5, "entry_mode": "same_day_close_if_pre_close"},
    )
    assert ok3 is True
    assert reason3 is None

    ok4, reason4 = validate_strategy_at_gen(
        CLASS_EVENT_POST,
        {"post_hold_days": 5, "entry_mode": "look_ahead_close"},
    )
    assert ok4 is False
    assert reason4 == REJECT_LOOKAHEAD


def test_gen_time_reject_missing_datasets():
    ok, reason = validate_strategy_at_gen(
        CLASS_MACRO_CONDITIONED,
        {
            "mode": "rate_change",
            "momentum_n": 5,
            "hold_days": 5,
            "high_threshold": 0.05,
            "low_threshold": 0.0,
        },
        available_datasets=frozenset({"equities_bars_daily"}),
    )
    assert ok is False
    assert reason is not None
    assert "required_datasets_unavailable" in reason


def test_fail_one_continue_and_screen():
    cfg = MassFactoryConfig(seed=7, n=12, max_codes=4)
    gen = generate_strategy_batch(cfg)
    ctx = load_batch_data_context(cfg, synthetic=True)
    # inject a poison strategy that will hard-fail evaluate path if family unknown
    poison = {
        "strategy_id": "poison_unknown_family",
        "family_id": "not_a_real_family_xyz",
        "params": {},
    }
    gen2 = dict(gen)
    gen2["strategies"] = list(gen["strategies"]) + [poison]
    batch = run_batch_eval(gen2, config=cfg, ctx=ctx, synthetic=True)
    assert batch["n_strategies_evaluated"] == len(gen2["strategies"])
    # fail-one-continue: still finished
    assert batch["n_eval_ok"] + batch["n_eval_fail"] == batch["n_strategies_evaluated"]
    # screens present
    assert len(batch["screens"]) == batch["n_strategies_evaluated"]
    assert batch["continuous_paper"] == "UNARMED"
    assert batch["human_main_candidates_selected"] is False
    assert batch["ready_declared"] is False
    assert batch["mass_research"] == "NO-GO"

    # screen helper near-zero
    scr = screen_strategy_result(
        {
            "strategy_id": "x",
            "family_id": CLASS_MULTI_DAY_HOLD,
            "n_periods_ok": 3,
            "mean_gross": 0.0001,
            "mean_net": 0.0001,
            "mean_activation": 0.05,
            "sign_selection": {"decision": "reject", "chosen_sign": None},
            "period_rows": [{"status": "ok"}] * 3,
            "errors": [],
        }
    )
    assert scr["survived"] is False
    assert "near_zero_after_cost" in scr["reject_reasons"] or "both_signs" in str(
        scr["reject_reasons"]
    )


def test_run_mass_factory_synthetic_smoke():
    pack = run_mass_factory(seed=99, n=20, synthetic=True)
    sm = pack["summary"]
    assert sm["n_generated_accepted"] == 20
    assert sm["n_families_used"] >= 4
    assert sm["human_main_candidates_selected"] is False
    assert sm["continuous_paper"] == "UNARMED"
    assert pack["mass_research"] == "NO-GO"
    # batch ran
    assert pack["batch"]["n_strategies_evaluated"] == 20
    assert isinstance(pack["batch_ranking"], list)


def test_evaluate_one_strategy_synthetic():
    cfg = MassFactoryConfig(seed=1, n=5)
    gen = generate_strategy_batch(cfg)
    ctx = load_batch_data_context(cfg, synthetic=True)
    strat = gen["strategies"][0]
    res = evaluate_one_strategy(strat, ctx)
    assert res["strategy_id"] == strat["strategy_id"]
    assert res["status"] == "evaluated"
    assert res["n_periods_total"] >= 1
    assert "sign_selection" in res
    assert res["mass_research"] == "NO-GO"


def test_default_n_is_at_least_100():
    assert DEFAULT_N >= 100
    cfg = MassFactoryConfig()
    assert cfg.n >= 100
