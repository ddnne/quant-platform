"""W80 / w0816o Task D — paper candidate adapter stays UNARMED.

Covers:
* class_hyp / research candidate → paper-readable StrategySpec envelope
* arm / live / GO flags never set (and hostile input is stripped)
* multi_day_hold 10d + event_post examples
* no live order path / continuous paper scheduler
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from research.paper_candidate_adapt import (
    PAPER_CANDIDATE_SPEC_VERSION,
    PaperCandidateReceptacle,
    adapt_class_hyp_candidate,
    adapt_from_class_hyp_bundle,
    assert_unarmed,
    emit_example_paper_specs,
    example_event_post_payload,
    example_multi_day_hold_10d_payload,
)
from research.paper_candidate_specs import (
    build_cross_section_hold_strategy_spec,
    build_event_post_strategy_spec,
    build_fundamentals_hold_strategy_spec,
    build_multi_day_hold_strategy_spec,
)
from strategies.spec import STRATEGY_SPEC_VERSION, StrategySpec, interpret_strategy_spec
REPO = Path(__file__).resolve().parents[1]
RESEARCH_DIR = REPO / "packages" / "product" / "research"
ADAPTER_PATH = RESEARCH_DIR / "paper_candidate_adapt.py"
ADAPTER_IMPL_PATHS = (
    ADAPTER_PATH,
    RESEARCH_DIR / "paper_candidate_specs.py",
)


def test_multi_day_hold_10d_strategy_spec_is_closed_and_interpretable():
    spec = build_multi_day_hold_strategy_spec(hold_days=10, top_k=5)
    assert isinstance(spec, StrategySpec)
    assert spec.version == STRATEGY_SPEC_VERSION
    assert spec.rebalance == "fixed_horizon"
    assert spec.hold_days == 10
    assert spec.rule.type == "top_k"
    assert spec.rule.feature.id == "momentum_n"
    assert spec.rule.feature.params["n"] == 10
    # approved feature → interpreter accepts
    strategy = interpret_strategy_spec(spec)
    assert strategy.feature_ids == ("momentum_n",)
    assert strategy.feature_versions["momentum_n"] == "1.0.0"


def test_event_post_strategy_spec_is_closed_and_interpretable():
    spec = build_event_post_strategy_spec(post_hold_days=5)
    assert spec.rule.type == "threshold"
    assert spec.rule.feature.id == "disclosure_flag_fins"
    strategy = interpret_strategy_spec(spec)
    assert strategy.feature_ids == ("disclosure_flag_fins",)


def test_adapt_multi_day_hold_10d_aligns_horizon_costs_universe_rebalance():
    rec = adapt_class_hyp_candidate(example_multi_day_hold_10d_payload())
    body = rec.to_dict()
    assert body["version"] == PAPER_CANDIDATE_SPEC_VERSION
    assert body["hypothesis_class"] == "multi_day_hold"
    assert body["horizon"] == "10d_hold"
    assert body["hold_days"] == 10
    assert body["rebalance"] == "fixed_horizon_10d"
    assert "tse_prime_liquid" in body["universe"] or body["universe"]
    assert body["costs"]["one_way_cost"] == pytest.approx(0.001)
    assert body["costs"]["cost_bps"] == pytest.approx(10.0)
    assert body["costs"]["amortization"] == "hold_days"
    assert body["strategy_spec"]["rebalance"] == "fixed_horizon"
    assert body["strategy_spec"]["hold_days"] == 10
    assert body["strategy_spec"]["rule"]["feature"]["params"]["n"] == 10
    assert body["strategy_spec_fidelity"] in {"aligned", "aligned_with_residuals"}
    assert body["status"] == "paper_receptacle_unarmed"
    assert body["discussion_only"] is True
    # nested StrategySpec round-trip
    StrategySpec.from_dict(body["strategy_spec"])


def test_adapt_event_post_discussion_only_proxy():
    rec = adapt_class_hyp_candidate(example_event_post_payload())
    body = rec.to_dict()
    assert body["hypothesis_class"] == "event_post"
    assert body["horizon"] == "1d_to_5d_post_event"
    assert body["rebalance"] == "event_entry_hold_5d_sticky"
    assert body["strategy_spec_fidelity"] == "proxy"
    assert body["discussion_only"] is True
    assert body["signal_id"] == "c21_event_post_disclosure_hold"
    StrategySpec.from_dict(body["strategy_spec"])


def test_adapter_strips_hostile_arm_live_go_flags():
    """Even if input claims arm/live/go, output stays closed."""
    hostile = example_multi_day_hold_10d_payload()
    assert hostile["paper_scheduler_armed"] is True
    assert hostile["live_orders"] is True
    assert hostile["operational_go"] is True
    assert hostile["ready_declared"] is True
    assert hostile["mass_research"] == "GO"
    assert hostile["phase7"] == "ON"

    body = adapt_class_hyp_candidate(hostile).to_dict()
    assert body["paper_scheduler_armed"] is False
    assert body["paper_continuous"] is False
    assert body["live_orders"] is False
    assert body["live_order_path_enabled"] is False
    assert body["live_order_path"] is False
    assert body["ready_declared"] is False
    assert body["operational_go"] is False
    assert body["mass_research"] == "NO-GO"
    assert body["phase7"] == "OFF"
    assert body["connected_to_ready"] is False
    assert body["connected_to_mass"] is False
    assert body["research_candidate"] is False
    assert body["source_candidate"]["research_candidate"] is False
    assert body["arm"]["paper_scheduler_armed"] is False
    assert body["arm"]["live_orders"] is False
    assert body["arm"]["operational_go"] is False
    assert body["paper_run_hints"]["scheduler_armed"] is False
    assert body["paper_run_hints"]["run_now"] is False
    assert body["paper_run_hints"]["continuous"] is False
    assert "require_ready_snapshot" not in body["paper_run_hints"]
    assert_unarmed(body)


def test_assert_unarmed_rejects_armed_payload():
    with pytest.raises(ValueError, match="unarmed"):
        assert_unarmed({"paper_scheduler_armed": True})
    with pytest.raises(ValueError, match="unarmed"):
        assert_unarmed({"live_orders": True})
    with pytest.raises(ValueError, match="unarmed"):
        assert_unarmed({"operational_go": True})
    with pytest.raises(ValueError, match="unarmed"):
        assert_unarmed({"ready_declared": True})
    with pytest.raises(ValueError, match="mass_research"):
        assert_unarmed({"mass_research": "GO"})
    with pytest.raises(ValueError, match="phase7"):
        assert_unarmed({"phase7": "ON"})
    with pytest.raises(ValueError, match="unarmed"):
        assert_unarmed({"arm": {"live_orders": True}})
    with pytest.raises(ValueError, match="status"):
        assert_unarmed({"status": "armed"})


def test_never_auto_promotes_research_candidate():
    payload = example_multi_day_hold_10d_payload()
    payload["candidate"] = {
        "research_candidate": True,  # hostile
        "research_candidate_allowed": True,
        "verdict": "should_not_matter",
    }
    body = adapt_class_hyp_candidate(payload).to_dict()
    assert body["research_candidate"] is False
    assert body["source_candidate"]["research_candidate"] is False


def test_adapt_from_class_hyp_bundle_keys():
    bundle = {
        "one_way_cost": 0.001,
        "codes": ["13010", "72030"],
        "multi_day_hold_10": {
            "signal_id": "c21_multi_day_momentum_hold",
            "hypothesis_class": "multi_day_hold",
            "variant": "hold_10",
            "hold_days": 10,
            "candidate": {
                "research_candidate": False,
                "research_candidate_allowed": True,
                "gate_passed": True,
                "economic_net_ok": True,
                "verdict": "discussion_only_not_auto_promoted",
            },
        },
        "event_post": {
            "signal_id": "c21_event_post_disclosure_hold",
            "hypothesis_class": "event_post",
            "post_hold_days": 5,
            "candidate": {
                "research_candidate": False,
                "research_candidate_allowed": True,
                "gate_passed": True,
                "economic_net_ok": True,
                "verdict": "discussion_only_not_auto_promoted",
            },
        },
        "candidate_summary": {
            "multi_day_hold_10": {
                "candidate_yes_no": "no_discussion_only",
                "research_candidate": False,
                "research_candidate_allowed": True,
                "verdict": "discussion_only_not_auto_promoted",
                "signal_id": "c21_multi_day_momentum_hold",
            },
            "event_post": {
                "candidate_yes_no": "no_discussion_only",
                "research_candidate": False,
                "research_candidate_allowed": True,
                "verdict": "discussion_only_not_auto_promoted",
                "signal_id": "c21_event_post_disclosure_hold",
            },
        },
    }
    mdh = adapt_from_class_hyp_bundle(bundle, "multi_day_hold_10")
    ep = adapt_from_class_hyp_bundle(bundle, "event_post")
    assert mdh.hold_days == 10
    assert mdh.hypothesis_class == "multi_day_hold"
    assert ep.hypothesis_class == "event_post"
    assert mdh.to_dict()["paper_scheduler_armed"] is False
    assert ep.to_dict()["live_orders"] is False


def test_emit_example_paper_specs(tmp_path: Path):
    paths = emit_example_paper_specs(tmp_path)
    assert (tmp_path / "multi_day_hold_10d.json").is_file()
    assert (tmp_path / "event_post.json").is_file()
    assert (tmp_path / "index.json").is_file()
    assert (tmp_path / "multi_day_hold_10d_strategy_spec.json").is_file()
    assert (tmp_path / "event_post_strategy_spec.json").is_file()

    mdh = json.loads((tmp_path / "multi_day_hold_10d.json").read_text(encoding="utf-8"))
    ep = json.loads((tmp_path / "event_post.json").read_text(encoding="utf-8"))
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))

    for body in (mdh, ep, index):
        assert_unarmed(body)
        assert body["paper_scheduler_armed"] is False
        assert body["live_orders"] is False
        assert body["ready_declared"] is False
        assert body["operational_go"] is False
        assert body["mass_research"] == "NO-GO"

    assert mdh["horizon"] == "10d_hold"
    assert mdh["strategy_spec"]["rule"]["feature"]["params"]["n"] == 10
    assert ep["hypothesis_class"] == "event_post"
    StrategySpec.from_dict(mdh["strategy_spec"])
    StrategySpec.from_dict(ep["strategy_spec"])
    assert set(paths) >= {
        "multi_day_hold_10d.json",
        "event_post.json",
        "index.json",
    }


def test_adapter_source_has_no_run_paper_or_live_order_calls():
    """Static guard: receptacle must not invoke paper runner or live path."""
    imported: set[str] = set()
    called: set[str] = set()
    srcs: list[str] = []
    for path in ADAPTER_IMPL_PATHS:
        src = path.read_text(encoding="utf-8")
        srcs.append(src)
        tree = ast.parse(src, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                for alias in node.names:
                    imported.add(f"{node.module}.{alias.name}")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called.add(node.func.attr)

    forbidden_roots = {
        "execution",
        "agents.trader",
        "agents.pipeline",
        "strategies.paper.runner",
        "strategies.paper",
    }
    for mod in imported:
        root = mod.split(".", 1)[0]
        if mod in forbidden_roots or root in {"execution"}:
            # strategies.spec is allowed; strategies.paper is not
            if mod.startswith("strategies.spec"):
                continue
            if mod == "strategies" or mod.startswith("strategies.paper"):
                pytest.fail(f"adapter must not import paper runner: {mod}")
            if root == "execution":
                pytest.fail(f"adapter must not import execution: {mod}")

    for name in ("run_paper", "PaperExecutionService", "prepare", "place_order"):
        assert name not in called, f"adapter must not call {name}"

    joined = "\n".join(srcs)
    assert "live_order_path_enabled: bool = True" not in joined
    assert "PAPER_SCHEDULER_ARMED: bool = True" not in joined
    assert "LIVE_ORDERS: bool = True" not in joined
    assert "OPERATIONAL_GO: bool = True" not in joined
    assert "READY_DECLARED: bool = True" not in joined


def test_paper_candidate_receptacle_type():
    rec = adapt_class_hyp_candidate(example_multi_day_hold_10d_payload())
    assert isinstance(rec, PaperCandidateReceptacle)
    assert rec.status == "paper_receptacle_unarmed"


def test_cross_section_hold_10_strategy_spec_aligned_v3():
    """W84: xs hold=10 mom=5 sticky CS L-S expressible in StrategySpec v3."""
    spec = build_cross_section_hold_strategy_spec(
        hold_days=10, momentum_n=5, long_frac=0.3, short_frac=0.3
    )
    assert spec.version == STRATEGY_SPEC_VERSION
    assert spec.rebalance == "fixed_horizon"
    assert spec.hold_days == 10
    assert spec.rule.type == "cross_section_rank"
    assert spec.rule.feature.params["n"] == 5
    strategy = interpret_strategy_spec(spec)
    assert strategy.feature_ids == ("momentum_n",)

    rec = adapt_class_hyp_candidate(
        {
            "hypothesis_class": "cross_section_relative",
            "variant": "hold_10",
            "hold_days": 10,
            "momentum_n": 5,
            "one_way_cost": 0.001,
            "signal_id": "c21_cross_section_momentum_rank",
        }
    )
    body = rec.to_dict()
    assert body["strategy_spec"]["rebalance"] == "fixed_horizon"
    assert body["strategy_spec"]["hold_days"] == 10
    assert body["strategy_spec"]["rule"]["type"] == "cross_section_rank"
    assert body["strategy_spec"]["rule"]["feature"]["params"]["n"] == 5
    assert body["strategy_spec_fidelity"] == "aligned_with_residuals"
    assert_unarmed(body)


def test_fundamentals_hold_10_strategy_spec_aligned_v3():
    """W84: fund hold=10 mom=10 value×mom agree expressible in StrategySpec v3."""
    spec = build_fundamentals_hold_strategy_spec(hold_days=10, momentum_n=10)
    assert spec.rebalance == "fixed_horizon"
    assert spec.hold_days == 10
    assert spec.rule.type == "value_momentum_agree"
    assert spec.rule.momentum_feature.params["n"] == 10
    strategy = interpret_strategy_spec(spec)
    assert set(strategy.feature_ids) == {"fundamental_value_score", "momentum_n"}

    rec = adapt_class_hyp_candidate(
        {
            "hypothesis_class": "fundamentals_price",
            "variant": "hold_10",
            "hold_days": 10,
            "momentum_n": 10,
            "mode": "value_momentum_agree",
            "one_way_cost": 0.001,
            "signal_id": "c21_fundamentals_price_value",
        }
    )
    body = rec.to_dict()
    assert body["strategy_spec"]["rule"]["type"] == "value_momentum_agree"
    assert body["strategy_spec"]["rule"]["momentum_feature"]["params"]["n"] == 10
    assert body["strategy_spec"]["hold_days"] == 10
    assert body["strategy_spec_fidelity"] == "aligned_with_residuals"
    assert_unarmed(body)
