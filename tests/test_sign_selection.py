"""W86 / w0816u — sign flip both-sides + choose_sign tests."""

from __future__ import annotations

import math

import pytest

from research.sign_selection import (
    SIGN_INVERTED,
    SIGN_ORIGINAL,
    SIGN_SELECTION_VERSION,
    choose_sign,
    evaluate_and_choose_sign,
    evaluate_sign_both_sides,
    invert_period_net,
    sign_selection_from_period_rows,
)


def test_invert_period_net_from_gross_and_cost():
    # gross +100bp, cost 10bp amortized → orig net 90bp; inv = -100-10 = -110bp
    inv = invert_period_net(gross=0.01, amortized_cost=0.001)
    assert inv == pytest.approx(-0.011)


def test_invert_period_net_from_gross_and_net():
    # net = gross - cost ⇒ inv = -gross - (gross-net) = net - 2*gross
    inv = invert_period_net(gross=0.01, net=0.009)
    assert inv == pytest.approx(-0.01 - 0.001)


def test_evaluate_both_sides_prefers_original_when_positive():
    # Strong original after cost
    grosses = [0.01, 0.008, 0.012, 0.009, 0.011, 0.007]
    costs = 0.001
    both = evaluate_sign_both_sides(
        period_grosses=grosses, amortized_costs=costs, period_ids=[f"y{i}" for i in range(6)]
    )
    assert both["original"]["mean_net"] is not None
    assert both["original"]["mean_net"] > 0
    assert both["inverted"]["mean_net"] is not None
    assert both["inverted"]["mean_net"] < 0
    assert both["evidence_original"]["has_nonzero_evidence"] is True

    choice = choose_sign(both)
    assert choice["chosen_sign"] == SIGN_ORIGINAL
    assert choice["decision"] == "keep_original"
    assert choice["ready_declared"] is False
    assert choice["mass_research"] == "NO-GO"


def test_evaluate_both_sides_flips_when_original_negative_inverted_positive():
    # Original consistently negative gross → inverted positive after cost
    grosses = [-0.01, -0.008, -0.012, -0.009, -0.011, -0.007]
    both = evaluate_sign_both_sides(
        period_grosses=grosses, amortized_costs=0.001
    )
    assert both["original"]["mean_net"] < 0
    assert both["inverted"]["mean_net"] > 0

    choice = choose_sign(both, paper_mean_negative=True)
    assert choice["chosen_sign"] == SIGN_INVERTED
    assert choice["decision"] == "flip_to_inverted"
    assert "flip" in " ".join(choice["reasons"]).lower() or any(
        "inverted" in r.lower() for r in choice["reasons"]
    )


def test_both_near_zero_rejects():
    # Tiny residual after cost both sides
    grosses = [0.0002, -0.0001, 0.00015, -0.00005, 0.0001, 0.0]
    both = evaluate_sign_both_sides(
        period_grosses=grosses, amortized_costs=0.001
    )
    # after 10bp amortized, both sides deeply negative / near noise
    choice = choose_sign(both, near_zero_abs=0.0005, min_mean_net=0.002)
    assert choice["chosen_sign"] is None
    assert choice["verdict"] == "reject_or_explore_demote"
    assert choice["decision"].startswith("reject")


def test_t_is_guideline_not_hard_one_strike():
    # Positive mean but low |t| (high variance) — still eligible if mean clear
    grosses = [0.02, -0.005, 0.015, -0.004, 0.018, 0.003]
    both = evaluate_sign_both_sides(
        period_grosses=grosses, amortized_costs=0.001, t_guideline=1.5
    )
    # mean should be clearly positive
    assert both["original"]["mean_net"] is not None
    assert both["original"]["mean_net"] > 0.002
    choice = choose_sign(
        both,
        t_guideline=1.5,
        min_abs_t_hard=None,  # guideline only
        min_mean_net=0.002,
    )
    # With mean evidence, should still choose original even if |t| soft
    assert choice["chosen_sign"] == SIGN_ORIGINAL
    assert choice["policy"]["t_is_guideline_not_hard"] is True


def test_paper_mean_negative_evaluates_flip_first():
    # Original weakly positive but inverted stronger; paper_mean_negative
    # only forces flip-first when original non-positive or not eligible.
    # Case: original negative, inverted strong.
    grosses = [-0.005, -0.004, -0.006, -0.003, -0.007, -0.004]
    report = evaluate_and_choose_sign(
        period_grosses=grosses,
        amortized_costs=0.0005,
        paper_mean_negative=True,
        min_mean_net=0.002,
    )
    assert report["chosen_sign"] == SIGN_INVERTED
    assert any("paper_mean_negative" in r for r in report["reasons"])


def test_sign_selection_from_period_rows():
    rows = [
        {
            "status": "ok",
            "period_id": "y2015",
            "gross_signed_mean_active": 0.01,
            "net_one_way_mean_active": 0.009,
            "amortized_one_way_cost": 0.001,
        },
        {
            "status": "ok",
            "period_id": "y2017",
            "gross_signed_mean_active": 0.008,
            "net_one_way_mean_active": 0.007,
            "amortized_one_way_cost": 0.001,
        },
        {
            "status": "ok",
            "period_id": "y2019",
            "gross_signed_mean_active": 0.012,
            "net_one_way_mean_active": 0.011,
            "amortized_one_way_cost": 0.001,
        },
        {
            "status": "ok",
            "period_id": "y2021",
            "gross_signed_mean_active": 0.009,
            "net_one_way_mean_active": 0.008,
            "amortized_one_way_cost": 0.001,
        },
        {
            "status": "skip",
            "period_id": "y2022",
            "gross_signed_mean_active": None,
            "net_one_way_mean_active": None,
        },
        {
            "status": "ok",
            "period_id": "y2023",
            "gross_signed_mean_active": 0.011,
            "net_one_way_mean_active": 0.010,
            "amortized_one_way_cost": 0.001,
        },
        {
            "status": "ok",
            "period_id": "y2025",
            "gross_signed_mean_active": 0.007,
            "net_one_way_mean_active": 0.006,
            "amortized_one_way_cost": 0.001,
        },
    ]
    sel = sign_selection_from_period_rows(rows, hold_days=10)
    assert sel["chosen_sign"] == SIGN_ORIGINAL
    assert sel["original"]["n_periods"] == 6
    assert sel["inverted"]["mean_net"] < 0
    assert sel["mass_research"] == "NO-GO"
    assert sel["operational_go"] is False


def test_both_eligible_picks_higher_mean():
    # Construct so both sides somehow positive? With symmetric cost, only one
    # side can be positive if |gross| > cost. Use asymmetric nets input.
    # original nets positive medium; inverted via high cost on weak gross
    # Actually with cost model both can't be strongly positive unless cost
    # is wrong. Test choose_sign directly with crafted both packs.
    both = {
        "original": {
            "sign": 1,
            "label": "original",
            "mean_net": 0.005,
            "mean_net_bp": 50.0,
            "t_stat": 1.6,
            "sharpe": 0.65,
            "win_rate": 0.67,
            "n_pos": 4,
            "n_neg": 2,
            "period_nets": [0.01, 0.008, 0.002, 0.001, 0.006, 0.003],
        },
        "inverted": {
            "sign": -1,
            "label": "inverted",
            "mean_net": 0.008,
            "mean_net_bp": 80.0,
            "t_stat": 2.1,
            "sharpe": 0.9,
            "win_rate": 0.83,
            "n_pos": 5,
            "n_neg": 1,
            "period_nets": [0.01, 0.009, 0.007, 0.006, 0.008, 0.008],
        },
        "evidence_original": {
            "has_nonzero_evidence": True,
            "near_zero": False,
        },
        "evidence_inverted": {
            "has_nonzero_evidence": True,
            "near_zero": False,
        },
    }
    choice = choose_sign(both, min_mean_net=0.002)
    assert choice["chosen_sign"] == SIGN_INVERTED
    assert "both eligible" in " ".join(choice["reasons"]).lower() or choice[
        "decision"
    ] == "flip_to_inverted"


def test_sign_selection_document_freezes():
    both = evaluate_sign_both_sides(
        period_grosses=[0.01, 0.008, 0.012, 0.009, 0.011, 0.007],
        amortized_costs=0.001,
    )
    choice = choose_sign(both)
    assert both["version"] == SIGN_SELECTION_VERSION
    assert both["simple_daily_sign"] is False
    assert choice["mass_research"] == "NO-GO"
    assert choice["ready_declared"] is False
    assert choice["phase7"] == "OFF"
    assert choice["policy"]["t_is_guideline_not_hard"] is True


def test_strategy_spec_signal_sign_round_trip():
    from strategies.spec import StrategySpec, interpret_strategy_spec

    payload = {
        "version": "strategy-spec/v3",
        "strategy_id": "xs_hold10_mom5_inv",
        "rebalance": "fixed_horizon",
        "hold_days": 10,
        "rule": {
            "type": "cross_section_rank",
            "feature": {
                "id": "momentum_n",
                "version": "1.0.0",
                "params": {"n": 5},
            },
            "long_frac": 0.3,
            "short_frac": 0.3,
            "allow_short": True,
            "signal_sign": -1,
        },
        "rationale": "W86 inverted",
    }
    spec = StrategySpec.from_dict(payload)
    assert spec.rule.signal_sign == -1
    assert spec.to_dict() == payload
    strategy = interpret_strategy_spec(spec)
    assert strategy.feature_ids == ("momentum_n",)


def test_paper_adapter_wires_chosen_sign():
    from research.paper_candidate_specs import (
        build_cross_section_hold_strategy_spec,
        build_fundamentals_hold_strategy_spec,
    )

    xs = build_cross_section_hold_strategy_spec(
        hold_days=10, momentum_n=5, signal_sign=-1
    )
    assert xs.rule.signal_sign == -1
    assert xs.to_dict()["rule"]["signal_sign"] == -1

    fund = build_fundamentals_hold_strategy_spec(
        hold_days=10, momentum_n=10, signal_sign=1
    )
    # default +1 omitted from to_dict
    assert "signal_sign" not in fund.to_dict()["rule"]
    assert fund.rule.signal_sign == 1


def test_multiyear_eval_version_w86():
    from research.offline.multiyear import (
        CLASS_HYP_EVAL_VERSION,
        CLASS_HYP_EVAL_WAVE,
    )

    assert CLASS_HYP_EVAL_VERSION == "class-hyp-eval/v7"
    assert "W86" in CLASS_HYP_EVAL_WAVE
