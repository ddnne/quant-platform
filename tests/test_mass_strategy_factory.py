"""research.offline.factory — logic-diversity mass factory + freezes."""

from __future__ import annotations

from collections import Counter

from research.hypothesis_classes import (
    CLASS_CROSS_SECTION_RELATIVE,
    CLASS_EVENT_POST,
    CLASS_FLOW_DEMAND,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_MACRO_CONDITIONED,
    CLASS_MULTI_DAY_HOLD,
    CLASS_SIMPLE_DAILY_SIGN,
)
from research.offline.factory import (
    DEFAULT_N,
    DEFAULT_NEAR_DUP_THRESHOLD,
    FAMILY_DEFINITIONS,
    FAMILY_INDEX_VOL_REGIME,
    FAMILY_OPTIONS_VOL_REGIME,
    FAMILY_VOL_RISK_ADJUSTED,
    FACTORY_FAMILY_IDS,
    RESEARCH_UNIQUE_LOGIC_IDS,
    LOGIC_TEMPLATE_IDS,
    LOGIC_TEMPLATES,
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
    propose_profit_hypotheses,
    run_batch_eval,
    run_mass_factory,
    screen_strategy_result,
    similarity_score,
    stable_strategy_id,
    try_cf_minimal_mass_batch,
    validate_strategy_at_gen,
)
from research.offline.factory_templates import (
    FAMILY_AFTERCLOSE_EVENT_TIMING,
    FAMILY_CURVE_STEEPEN_IMPULSE_CS,
    FAMILY_DISCLOSURE_CLUSTER_GATE,
    FAMILY_EVENT_FUNDING_COMBO,
    FAMILY_EVENT_MACRO_CURVE_COMBO,
    FAMILY_EVENT_MARGIN_CROWD_COMBO,
    FAMILY_EVENT_MOM_AGREE_COMBO,
    FAMILY_FUNDING_IMPULSE_CS,
    FAMILY_IDIO_MOM_MACRO,
    FAMILY_LARGE_SURPRISE_FILTER,
    FAMILY_MULTI_FACTOR,
    FAMILY_RATE_FACTOR,
    FAMILY_SURPRISE_XS_RANK,
    FAMILY_XS_MARGIN_DELTA,
    NEAR_LOGIC_GROUPS,
    RESEARCH_FAMILY_APPEND_ID,
    RESEARCH_FAMILY_APPEND_LOGIC_IDS,
    RESEARCH_FAMILY_AUTO_RESEARCH_CANDIDATE,
    RESEARCH_FAMILY_REGISTER_ID,
    RESEARCH_FAMILY_REGISTRATION_IS_NOT_A_PASS,
    near_logic_groups_document,
    research_family_append_document,
    research_family_register_document,
)

_NKY_VOL_IDS = ("nky_vol_abs_level", "nky_vol_term_levels", "nky_vol_term_ratio")
_OPT225_IDS = (
    "opt225_basevol_abs_level",
    "opt225_basevol_term_levels",
    "opt225_basevol_term_ratio",
    "opt225_atm_iv_abs_level",
    "opt225_atm_iv_term_levels",
    "opt225_atm_iv_term_ratio",
    "opt225_iv_base_spread_abs",
    "opt225_iv_base_spread_change",
    "opt225_skew_abs_level",
    "opt225_cm_term_abs_level",
    "opt225_basevol_delta_abs",
)
_UNIQUE_NOT_GENERATED = (
    "event_funding_stress_skip",
    "curve_steep_event_confirm",
    "disclosure_cluster_mom_gate",
    "surprise_xs_rank_hold",
    "large_surprise_event_hold",
    "afterclose_only_event_hold",
    "event_pre_mom_agree_hold",
    "event_margin_crowding_skip",
    "event_funding_easy_short",
    "event_funding_stress_ls",
    "surprise_xs_rank_flip",
    "funding_impulse_cs_tilt",
    "curve_steepen_impulse_cs",
    "xs_margin_delta_rank",
    "idio_mom_macro_impulse",
)
_RESEARCH_FAMILY_IDS = (
    FAMILY_EVENT_FUNDING_COMBO,
    FAMILY_EVENT_MACRO_CURVE_COMBO,
    FAMILY_DISCLOSURE_CLUSTER_GATE,
    FAMILY_SURPRISE_XS_RANK,
    FAMILY_LARGE_SURPRISE_FILTER,
    FAMILY_AFTERCLOSE_EVENT_TIMING,
    FAMILY_EVENT_MOM_AGREE_COMBO,
    FAMILY_EVENT_MARGIN_CROWD_COMBO,
    FAMILY_FUNDING_IMPULSE_CS,
    FAMILY_CURVE_STEEPEN_IMPULSE_CS,
    FAMILY_XS_MARGIN_DELTA,
    FAMILY_IDIO_MOM_MACRO,
)


def _tpl_proposal(lid: str) -> dict:
    tpl = LOGIC_TEMPLATES[lid]
    return {
        "logic_id": lid,
        "thesis": tpl.thesis,
        "signal_definition": tpl.signal_definition,
        "position_rule": tpl.position_rule,
        "datasets_used": list(tpl.datasets_used),
    }


def _eval_vol_family(
    lids,
    family_id,
    *,
    seed: int,
    panel_key: str,
    dataset: str,
    bad_params: dict,
    bad_logic_id: str,
):
    for lid in lids:
        assert dataset in LOGIC_TEMPLATES[lid].datasets_used
    cfg = MassFactoryConfig(seed=seed, n=5, max_codes=4)
    ctx = load_batch_data_context(cfg, synthetic=True)
    assert all(p.get(panel_key) for p in ctx.panels)
    for lid in lids:
        _eval_template(lid, family_id, ctx)
    ok_bad, reason_bad = validate_strategy_at_gen(
        family_id, bad_params, logic_id=bad_logic_id
    )
    assert ok_bad is False
    assert reason_bad is not None


def _eval_template(lid: str, family_id: str, ctx) -> None:
    tpl = LOGIC_TEMPLATES[lid]
    assert tpl.family_id == family_id
    ok, reason = validate_strategy_at_gen(family_id, dict(tpl.base_params), logic_id=lid)
    assert ok is True, reason
    res = evaluate_one_strategy(
        {
            "strategy_id": f"test_{lid}",
            "logic_id": lid,
            "family_id": family_id,
            "params": dict(tpl.base_params),
            "thesis": tpl.thesis,
            "signal_definition": tpl.signal_definition,
            "position_rule": tpl.position_rule,
            "datasets_used": list(tpl.datasets_used),
        },
        ctx,
    )
    assert res["status"] == "evaluated"
    assert res["n_periods_total"] >= 1
    assert res.get("logic_id") == lid
    assert res["mass_research"] == "NO-GO"


def test_logic_templates_distinct_economic_logic():
    doc = logic_templates_document()
    assert doc["n_logic_templates"] >= 20
    assert len(LOGIC_TEMPLATE_IDS) == len(set(LOGIC_TEMPLATE_IDS))
    fps = {tpl.to_dict()["logic_fingerprint"] for lid, tpl in LOGIC_TEMPLATES.items()}
    for lid, tpl in LOGIC_TEMPLATES.items():
        d = tpl.to_dict()
        assert d["thesis"] and d["signal_definition"] and d["position_rule"]
        assert d["datasets_used"] and d["logic_id"] == lid and d["logic_fingerprint"]
    assert len(fps) == len(LOGIC_TEMPLATES)
    assert all(
        CLASS_SIMPLE_DAILY_SIGN not in (t.family_id, t.logic_id)
        for t in LOGIC_TEMPLATES.values()
    )
    for lid in ("rate_abs_level_xs", "rate_curve_shape_xs"):
        assert LOGIC_TEMPLATES[lid].family_id == FAMILY_RATE_FACTOR
    for lid in ("mf_value_mom_rate", "mf_flow_price"):
        assert LOGIC_TEMPLATES[lid].family_id == FAMILY_MULTI_FACTOR
    for lid in _NKY_VOL_IDS:
        assert LOGIC_TEMPLATES[lid].family_id == FAMILY_INDEX_VOL_REGIME
    assert "nky_vol_abs_level" in doc.get("w91_index_vol_logic_ids", [])
    for lid in _OPT225_IDS:
        assert LOGIC_TEMPLATES[lid].family_id == FAMILY_OPTIONS_VOL_REGIME
    assert "opt225_basevol_abs_level" in doc.get("w92_options_vol_logic_ids", [])
    assert "opt225_skew_abs_level" in doc.get("w94_options_vol_logic_ids", [])
    assert doc.get("opt225_canonical_level") == "basevol"
    assert doc.get("opt225_atm_iv_role") == "compare_only"
    assert LOGIC_TEMPLATES["opt225_atm_iv_abs_level"].base_params.get("compare_only") is True
    for lid in _UNIQUE_NOT_GENERATED:
        assert lid in RESEARCH_UNIQUE_LOGIC_IDS
        assert lid not in LOGIC_TEMPLATES
    assert "event_funding_stress_skip" in doc.get("unique_logic_ids", [])
    assert "overnight_level_cs_tilt" in doc.get("unique_logic_append_logic_ids", [])
    assert "w105_research_unique_logic_ids" not in doc
    assert "w104_w105" not in str(
        doc.get("research_family_registration", {}).get("register_id", "")
    )
    rules = doc["diversity_rules"]
    assert "hold_days only" in str(rules["does_not_count"])
    assert "info source" in str(rules["counts_as_different"]).lower() or any(
        "info" in x.lower() for x in rules["counts_as_different"]
    )
    ng = near_logic_groups_document()
    assert len(ng["groups"]) >= 5
    assert len(NEAR_LOGIC_GROUPS) >= 5
    group_ids = {g["group_id"] for g in NEAR_LOGIC_GROUPS}
    assert {
        "vol_family_name_vs_index",
        "index_vol_regime_family",
        "options_vol_regime_family",
        "nky_vol_proxy_vs_options_sot",
    } <= group_ids


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
    for fid in (
        FAMILY_VOL_RISK_ADJUSTED,
        FAMILY_RATE_FACTOR,
        FAMILY_MULTI_FACTOR,
        FAMILY_INDEX_VOL_REGIME,
        FAMILY_OPTIONS_VOL_REGIME,
    ):
        assert fid in FAMILY_DEFINITIONS
    for fid in _RESEARCH_FAMILY_IDS:
        assert fid in FAMILY_DEFINITIONS
        assert FAMILY_DEFINITIONS[fid].generation_enabled is False
    assert CLASS_SIMPLE_DAILY_SIGN not in FAMILY_DEFINITIONS
    reg = research_family_register_document()
    assert reg["register_id"] == RESEARCH_FAMILY_REGISTER_ID
    assert reg["registration"] == "recognition"
    assert reg["registration_is_not_a_pass"] is True
    assert RESEARCH_FAMILY_REGISTRATION_IS_NOT_A_PASS is True
    assert RESEARCH_FAMILY_AUTO_RESEARCH_CANDIDATE is False
    assert reg["auto_research_candidate"] is False
    assert reg["promote_as_main"] is False
    assert reg["go"] is False
    append = research_family_append_document()
    assert append["append_id"] == RESEARCH_FAMILY_APPEND_ID
    assert append["registration"] == "recognition"
    assert append["registration_is_not_a_pass"] is True
    assert append["registration_is_not_promotion"] is True
    assert append["generation_enabled"] is False
    assert append["this_wave_only"] is True
    assert append["did_not_kill_funding_surprise"] is True
    assert set(append["appended_logic_ids"]) == set(RESEARCH_FAMILY_APPEND_LOGIC_IDS)


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
    assert gen["n_unique_logic"] < 40
    assert gen["n_after_dedup"] < 40
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
    assert cf["status"] == "available"
    assert cf["version"] != "research-mass-eval/v6"
    assert cf["version"].startswith("research-mass-eval/")
    assert cf["worker"] == "quant-platform-research-mass-eval"
    assert "POST /v1/mass-eval" in str(cf.get("endpoint") or "")
    assert cf.get("r2_prefix", "").startswith("research/mass_eval/")
    assert cf.get("r2_bucket") == "quant-structured"
    assert cf.get("n_survivors_are_not_a_pass") is True
    assert cf.get("candidate_grade") is False
    assert isinstance(cf.get("not_yet_implemented"), list)
    assert cf.get("scale_queue_fanout") is False
    assert int(cf.get("n_cf_batch_cap") or 0) >= 1
    llm = llm_logic_entry_status()
    assert llm["status"] == "connected"
    assert llm.get("always_through_evaluator") is True
    assert "propose_profit_hypotheses" in str(llm.get("entry_fn") or "")


def test_propose_profit_hypotheses_rejects_window_tweaks_and_evals():
    # window tweak only → reject
    bad = propose_profit_hypotheses(
        [
            {
                "logic_id": "xs_rank_ls_sticky",
                "params": {"hold_days": 15, "momentum_n": 3},
            }
        ],
        evaluate=False,
    )
    assert bad["n_rejected"] >= 1
    assert bad["n_accepted"] == 0

    # full thesis rate factor → accept + evaluate synthetic
    good = propose_profit_hypotheses(
        [
            _tpl_proposal("rate_abs_level_xs"),
            _tpl_proposal("mf_flow_price"),
        ],
        evaluate=True,
        synthetic=True,
    )
    assert good["n_accepted"] == 2
    assert good["n_rejected"] == 0
    assert good.get("eval") is not None
    assert good["eval"].get("n_strategies_evaluated") == 2
    assert good["mass_research"] == "NO-GO"
    assert good["continuous_paper"] == "UNARMED"


def test_nky_vol_logics_templates_and_eval_synthetic():
    name_fps = {
        LOGIC_TEMPLATES["vol_risk_adjusted_mom"].logic_fingerprint(),
        LOGIC_TEMPLATES["vol_breakout_expand"].logic_fingerprint(),
    }
    for lid in _NKY_VOL_IDS:
        tpl = LOGIC_TEMPLATES[lid]
        assert "CS" in tpl.signal_definition or "rank" in tpl.signal_definition
        assert LOGIC_TEMPLATES[lid].logic_fingerprint() not in name_fps
    _eval_vol_family(
        _NKY_VOL_IDS,
        FAMILY_INDEX_VOL_REGIME,
        seed=91,
        panel_key="nky_vol_series",
        dataset="derivatives_bars_daily_futures",
        bad_params={
            "mode": "not_a_mode",
            "vol_short_n": 10,
            "vol_long_n": 60,
            "hold_days": 10,
            "momentum_n": 5,
        },
        bad_logic_id="nky_vol_abs_level",
    )


def test_opt225_vol_logics_templates_and_eval_synthetic():
    _eval_vol_family(
        _OPT225_IDS,
        FAMILY_OPTIONS_VOL_REGIME,
        seed=92,
        panel_key="opt225_regime",
        dataset="derivatives_bars_daily_options_225",
        bad_params={
            "mode": "not_a_mode",
            "series_kind": "basevol",
            "vol_short_n": 10,
            "vol_long_n": 60,
            "hold_days": 10,
            "momentum_n": 5,
        },
        bad_logic_id="opt225_basevol_abs_level",
    )


def test_nky_vol_signal_helpers_pure():
    from features.class_signals import (
        compute_nky_vol_abs_level_signal,
        compute_nky_vol_term_levels_signal,
        compute_nky_vol_term_ratio_signal,
        nky_vol_regime_from_abs_level,
        nky_vol_regime_from_term_levels,
        nky_vol_regime_from_term_ratio,
    )

    assert nky_vol_regime_from_abs_level(0.05)[0] == "low"
    assert nky_vol_regime_from_abs_level(0.30)[0] == "high"
    assert nky_vol_regime_from_abs_level(0.15)[0] == "mid"
    assert nky_vol_regime_from_term_levels(0.05, 0.08)[0] == "low"
    assert nky_vol_regime_from_term_levels(0.30, 0.25)[0] == "high"
    assert nky_vol_regime_from_term_levels(0.05, 0.25)[0] == "mid"  # disagree
    assert nky_vol_regime_from_term_ratio(0.30, 0.20)[0] == "expanding"
    assert nky_vol_regime_from_term_ratio(0.10, 0.20)[0] == "compressing"

    abs_s = compute_nky_vol_abs_level_signal(cs_sign=1.0, vol_level=0.05)
    assert abs_s["value"] == 1.0  # low → keep
    abs_h = compute_nky_vol_abs_level_signal(cs_sign=1.0, vol_level=0.30)
    assert abs_h["value"] == -1.0  # high → reverse
    abs_m = compute_nky_vol_abs_level_signal(cs_sign=1.0, vol_level=0.15)
    assert abs_m["value"] is None  # mid → flat

    term = compute_nky_vol_term_levels_signal(
        cs_sign=1.0, short_vol=0.05, long_vol=0.08
    )
    assert term["value"] == 1.0
    ratio = compute_nky_vol_term_ratio_signal(
        cs_sign=1.0, short_vol=0.30, long_vol=0.20
    )
    assert ratio["value"] == -1.0  # expanding → reverse
    assert ratio["hypothesis_class"] == FAMILY_INDEX_VOL_REGIME


def test_opt225_signal_helpers_pure():
    from features.class_signals import (
        CLASS_OPTIONS_VOL_REGIME,
        compute_opt225_basevol_abs_level_signal,
        compute_opt225_basevol_delta_abs_signal,
        compute_opt225_cm_term_abs_level_signal,
        compute_opt225_iv_base_spread_abs_signal,
        compute_opt225_skew_abs_level_signal,
        compute_opt225_vol_signal,
    )

    low = compute_opt225_basevol_abs_level_signal(cs_sign=1.0, vol_level=10.0)
    assert low["hypothesis_class"] == CLASS_OPTIONS_VOL_REGIME
    assert low["value"] == 1.0
    high = compute_opt225_basevol_abs_level_signal(cs_sign=1.0, vol_level=30.0)
    assert high["value"] == -1.0
    mid = compute_opt225_basevol_abs_level_signal(cs_sign=1.0, vol_level=18.0)
    assert mid["value"] is None
    sp = compute_opt225_iv_base_spread_abs_signal(cs_sign=1.0, vol_level=2.0)
    assert sp["value"] == -1.0
    ratio = compute_opt225_vol_signal(
        mode="term_ratio",
        cs_sign=1.0,
        short_vol=20.0,
        long_vol=10.0,
        series_kind="atm_iv",
    )
    assert ratio["regime"] == "expanding"
    assert ratio["value"] == -1.0
    skew_hi = compute_opt225_skew_abs_level_signal(cs_sign=1.0, vol_level=4.0)
    assert skew_hi["value"] == -1.0
    skew_lo = compute_opt225_skew_abs_level_signal(cs_sign=1.0, vol_level=0.2)
    assert skew_lo["value"] == 1.0
    term_hi = compute_opt225_cm_term_abs_level_signal(cs_sign=1.0, vol_level=3.0)
    assert term_hi["value"] == -1.0
    dlt_hi = compute_opt225_basevol_delta_abs_signal(cs_sign=1.0, vol_level=2.0)
    assert dlt_hi["value"] == -1.0
    dlt_lo = compute_opt225_basevol_delta_abs_signal(cs_sign=1.0, vol_level=-2.0)
    assert dlt_lo["value"] == 1.0
