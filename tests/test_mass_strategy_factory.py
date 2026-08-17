"""W88 / w0816w — logic-diversity mass factory: templates, near-dup, freezes."""

from __future__ import annotations

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
    DEFAULT_MAX_FAMILY_SHARE,
    DEFAULT_N,
    DEFAULT_NEAR_DUP_THRESHOLD,
    FAMILY_DEFINITIONS,
    FAMILY_VOL_RISK_ADJUSTED,
    FACTORY_FAMILY_IDS,
    FROZEN_DEFAULT_PATH,
    LOGIC_TEMPLATE_IDS,
    LOGIC_TEMPLATES,
    MASS_FACTORY_VERSION,
    MASS_FACTORY_WAVE,
    MASS_RESEARCH,
    OPERATIONAL_GO,
    PHASE7,
    READY_DECLARED,
    REJECT_LOOKAHEAD,
    REJECT_NEAR_DUPLICATE,
    REJECT_SIMPLE_DAILY_SIGN,
    MassFactoryConfig,
    dedup_strategies,
    evaluate_one_strategy,
    family_definitions_document,
    generate_strategy_batch,
    llm_logic_entry_status,
    load_batch_data_context,
    logic_templates_document,
    mass_factory_document,
    run_batch_eval,
    run_mass_factory,
    screen_strategy_result,
    similarity_score,
    stable_strategy_id,
    try_cf_minimal_mass_batch,
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
    assert "W88" in MASS_FACTORY_WAVE
    assert MASS_FACTORY_VERSION.startswith("mass-strategy-factory/")
    assert doc["frozen_defaults_retuned"] is False


def test_frozen_defaults_not_retuned():
    assert len(FROZEN_DEFAULT_PATH) == 3
    ids = {r["representative_id"] for r in FROZEN_DEFAULT_PATH}
    assert "cross_section_hold_10" in ids
    assert "cross_section_hold_10_mom3" in ids
    assert "fundamentals_hold_10" in ids
    # pins
    mom5 = next(
        r for r in FROZEN_DEFAULT_PATH if r["representative_id"] == "cross_section_hold_10"
    )
    mom3 = next(
        r
        for r in FROZEN_DEFAULT_PATH
        if r["representative_id"] == "cross_section_hold_10_mom3"
    )
    fund = next(
        r for r in FROZEN_DEFAULT_PATH if r["representative_id"] == "fundamentals_hold_10"
    )
    assert mom5["momentum_n"] == 5 and mom5["hold_days"] == 10
    assert mom3["momentum_n"] == 3 and mom3["hold_days"] == 10
    assert fund["momentum_n"] == 10 and fund["hold_days"] == 10
    assert mass_factory_document()["frozen_defaults_retuned"] is False


def test_logic_templates_distinct_economic_logic():
    doc = logic_templates_document()
    assert doc["n_logic_templates"] >= 12
    assert len(LOGIC_TEMPLATE_IDS) == len(set(LOGIC_TEMPLATE_IDS))
    # each template has required fields
    fps = set()
    for lid, tpl in LOGIC_TEMPLATES.items():
        d = tpl.to_dict()
        assert d["thesis"]
        assert d["signal_definition"]
        assert d["position_rule"]
        assert d["datasets_used"]
        assert d["logic_id"] == lid
        assert d["logic_fingerprint"]
        fps.add(d["logic_fingerprint"])
    # fingerprints unique
    assert len(fps) == len(LOGIC_TEMPLATES)
    # simple_daily_sign not a template
    assert all(
        CLASS_SIMPLE_DAILY_SIGN not in (t.family_id, t.logic_id)
        for t in LOGIC_TEMPLATES.values()
    )
    # diversity rules documented
    rules = doc["diversity_rules"]
    assert "hold_days only" in str(rules["does_not_count"])
    assert "info source" in str(rules["counts_as_different"]).lower() or any(
        "info" in x.lower() for x in rules["counts_as_different"]
    )


def test_families_still_documented_for_eval_dispatch():
    fams = family_definitions_document()
    assert len(fams["family_ids"]) >= 5
    for cid in (
        CLASS_MULTI_DAY_HOLD,
        CLASS_EVENT_POST,
        CLASS_CROSS_SECTION_RELATIVE,
        CLASS_MACRO_CONDITIONED,
        CLASS_FUNDAMENTALS_PRICE,
        CLASS_FLOW_DEMAND,
    ):
        assert cid in FAMILY_DEFINITIONS or cid in FACTORY_FAMILY_IDS
    assert FAMILY_VOL_RISK_ADJUSTED in FAMILY_DEFINITIONS
    assert CLASS_SIMPLE_DAILY_SIGN not in FAMILY_DEFINITIONS


def test_generation_logic_diversity_metrics():
    gen = generate_strategy_batch(seed=870816, n=100)
    assert gen["n_generated"] >= gen["n_unique_logic"]
    assert gen["n_unique_logic"] >= 12
    assert gen["n_after_dedup"] >= 12
    assert gen["n_after_dedup"] <= gen["n_generated"]
    # unique logics should dominate; numeric variants may exist but near-dup drops them
    assert gen["n_after_dedup"] <= gen["n_unique_logic"] + 2
    assert gen["logic_diversity_ok"] is True
    # every after-dedup row has logic fields
    for s in gen["strategies_after_dedup"]:
        assert s.get("logic_id")
        assert s.get("thesis")
        assert s.get("signal_definition")
        assert s.get("position_rule")
        assert s.get("logic_fingerprint")
        assert s.get("datasets_used") or s.get("datasets_required")
    # not simple_daily_sign
    assert all(s["family_id"] != CLASS_SIMPLE_DAILY_SIGN for s in gen["strategies"])
    # metrics aliases
    assert gen["unique_logic_count"] == gen["n_unique_logic"]
    assert gen["numeric_variant_count"] == gen["n_numeric_variant"]


def test_not_hold_mom_frac_grid_as_100_unique():
    """Grid-only mutations must not inflate unique_logic / after_dedup."""
    gen = generate_strategy_batch(seed=870816, n=100)
    # unique_logic << 100 even if capacity is 100
    assert gen["n_unique_logic"] < 40
    assert gen["n_after_dedup"] < 40
    # each logic appears at most a few times after dedup
    from collections import Counter

    logic_counts = Counter(s["logic_id"] for s in gen["strategies_after_dedup"])
    assert max(logic_counts.values()) <= 2


def test_near_duplicate_scores_grid_mutations_high():
    base = {
        "logic_id": "xs_rank_ls_sticky",
        "logic_fingerprint": "abc123",
        "family_id": CLASS_CROSS_SECTION_RELATIVE,
        "signal_definition": "rank mom L-S",
        "position_rule": "sticky L/S",
        "datasets_used": ["equities_bars_daily"],
        "params": {
            "hold_days": 10,
            "momentum_n": 5,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "book_mode": "balanced_ls",
        },
    }
    # hold/mom/frac only change
    clone = {
        **base,
        "params": {
            "hold_days": 15,
            "momentum_n": 3,
            "long_frac": 0.4,
            "short_frac": 0.2,
            "book_mode": "balanced_ls",
        },
    }
    # same fingerprint → near-dup
    assert similarity_score(base, clone) >= DEFAULT_NEAR_DUP_THRESHOLD

    # different thesis / signal → low similarity
    other = {
        "logic_id": "event_post_disclosure_hold",
        "logic_fingerprint": "zzz999",
        "family_id": CLASS_EVENT_POST,
        "signal_definition": "surprise post disc",
        "position_rule": "post hold PIT",
        "datasets_used": ["fins_summary", "equities_bars_daily"],
        "params": {"post_hold_days": 5, "entry_mode": "same_day_close_if_pre_close"},
    }
    assert similarity_score(base, other) < 0.7

    # dedup drops clone
    dedup = dedup_strategies(
        [
            {**base, "strategy_id": "a"},
            {**clone, "strategy_id": "b", "logic_fingerprint": base["logic_fingerprint"]},
            {**other, "strategy_id": "c"},
        ]
    )
    assert dedup["n_after_dedup"] == 2
    assert dedup["n_dropped"] == 1
    assert dedup["dropped"][0]["reject_reason"] == REJECT_NEAR_DUPLICATE


def test_id_stability_reproducible():
    g1 = generate_strategy_batch(seed=42, n=30)
    g2 = generate_strategy_batch(seed=42, n=30)
    ids1 = [s["strategy_id"] for s in g1["strategies"]]
    ids2 = [s["strategy_id"] for s in g2["strategies"]]
    assert ids1 == ids2
    assert len(ids1) == len(set(ids1))
    p = {"hold_days": 10, "momentum_n": 5}
    a = stable_strategy_id(
        seed=1,
        family_id="multi_day_hold",
        params=p,
        generation_index=0,
        logic_id="mdh_sticky_momentum",
    )
    b = stable_strategy_id(
        seed=1,
        family_id="multi_day_hold",
        params=p,
        generation_index=0,
        logic_id="mdh_sticky_momentum",
    )
    c = stable_strategy_id(
        seed=1,
        family_id="multi_day_hold",
        params=p,
        generation_index=1,
        logic_id="mdh_sticky_momentum",
    )
    assert a == b
    assert a != c
    g3 = generate_strategy_batch(seed=43, n=30)
    ids3 = [s["strategy_id"] for s in g3["strategies"]]
    assert ids1 != ids3


def test_gen_time_reject_lookahead_and_simple_daily():
    ok, reason = validate_strategy_at_gen(CLASS_SIMPLE_DAILY_SIGN, {"x": 1})
    assert ok is False
    assert reason == REJECT_SIMPLE_DAILY_SIGN

    ok2, reason2 = validate_strategy_at_gen(
        CLASS_EVENT_POST,
        {"post_hold_days": 5, "entry_mode": "same_day_close_always"},
        logic_id="event_post_disclosure_hold",
    )
    assert ok2 is False
    assert reason2 == REJECT_LOOKAHEAD

    ok3, reason3 = validate_strategy_at_gen(
        CLASS_EVENT_POST,
        {"post_hold_days": 5, "entry_mode": "same_day_close_if_pre_close"},
        logic_id="event_post_disclosure_hold",
    )
    assert ok3 is True
    assert reason3 is None

    ok4, reason4 = validate_strategy_at_gen(
        CLASS_EVENT_POST,
        {"post_hold_days": 5, "entry_mode": "look_ahead_close"},
        logic_id="event_post_disclosure_hold",
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
        logic_id="macro_repo_rate_change",
    )
    assert ok is False
    assert reason is not None
    assert "required_datasets_unavailable" in reason


def test_fail_one_continue_and_screen():
    cfg = MassFactoryConfig(seed=7, n=12, max_codes=4)
    gen = generate_strategy_batch(cfg)
    ctx = load_batch_data_context(cfg, synthetic=True)
    poison = {
        "strategy_id": "poison_unknown_family",
        "family_id": "not_a_real_family_xyz",
        "logic_id": "poison",
        "params": {},
    }
    gen2 = dict(gen)
    # inject into after_dedup so eval sees it
    gen2["strategies_after_dedup"] = list(gen["strategies_after_dedup"]) + [poison]
    batch = run_batch_eval(gen2, config=cfg, ctx=ctx, synthetic=True)
    assert batch["n_strategies_evaluated"] == len(gen2["strategies_after_dedup"])
    assert batch["n_eval_ok"] + batch["n_eval_fail"] == batch["n_strategies_evaluated"]
    assert len(batch["screens"]) == batch["n_strategies_evaluated"]
    assert batch["continuous_paper"] == "UNARMED"
    assert batch["human_main_candidates_selected"] is False
    assert batch["ready_declared"] is False
    assert batch["mass_research"] == "NO-GO"
    assert batch["frozen_defaults_retuned"] is False
    assert batch["eval_set"] == "after_dedup"

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
    assert sm["n_unique_logic"] >= 12
    assert sm["n_after_dedup"] >= 12
    assert sm["n_strategies_evaluated"] == sm["n_after_dedup"]
    assert sm["human_main_candidates_selected"] is False
    assert sm["continuous_paper"] == "UNARMED"
    assert sm["frozen_defaults_retuned"] is False
    assert pack["mass_research"] == "NO-GO"
    assert pack["batch"]["n_strategies_evaluated"] == sm["n_after_dedup"]
    assert isinstance(pack["batch_ranking"], list)


def test_evaluate_one_strategy_synthetic():
    cfg = MassFactoryConfig(seed=1, n=5)
    gen = generate_strategy_batch(cfg)
    ctx = load_batch_data_context(cfg, synthetic=True)
    strat = gen["strategies_after_dedup"][0]
    res = evaluate_one_strategy(strat, ctx)
    assert res["strategy_id"] == strat["strategy_id"]
    assert res["status"] == "evaluated"
    assert res["n_periods_total"] >= 1
    assert "sign_selection" in res
    assert res["mass_research"] == "NO-GO"
    assert res.get("logic_id") == strat.get("logic_id")


def test_default_n_capacity_and_cf_llm_residuals():
    assert DEFAULT_N >= 100
    cfg = MassFactoryConfig()
    assert cfg.n >= 100
    cf = try_cf_minimal_mass_batch()
    assert cf["status"] == "blocked"
    assert "blocker" in cf
    assert cf["scale_deferred"] is True
    llm = llm_logic_entry_status()
    assert llm["status"] == "unconnected"
    assert "always_through_evaluator" in llm or llm.get("always_through_evaluator") is True
