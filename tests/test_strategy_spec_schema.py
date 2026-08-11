"""Closed-schema and governance tests for declarative StrategySpec."""

from __future__ import annotations

import features
import pytest

from strategies.spec import (
    StrategySpec,
    StrategySpecError,
    ThresholdRule,
    TopKRule,
    interpret_strategy_spec,
)


def test_strategy_spec_round_trip_supports_only_whitelisted_rules():
    payload = {
        "version": "strategy-spec/v1",
        "strategy_id": "approved_momentum",
        "rebalance": "daily",
        "rule": {
            "type": "top_k",
            "feature_id": "momentum_n",
            "k": 3,
            "min_score": 0.0,
            "feature_params": {"n": 5},
        },
        "rationale": "fixture",
    }

    spec = StrategySpec.from_dict(payload)

    assert isinstance(spec.rule, TopKRule)
    assert spec.to_dict() == payload
    strategy = interpret_strategy_spec(spec)
    assert strategy.feature_ids == ("momentum_n",)
    assert strategy.params == {"strategy_spec": payload}


@pytest.mark.parametrize(
    "payload, match",
    [
        (
            {
                "strategy_id": "bad",
                "rule": {"type": "python", "source": "pass"},
            },
            "unknown rule type",
        ),
        (
            {
                "strategy_id": "bad",
                "rule": {
                    "type": "threshold",
                    "feature_id": "return_1d",
                    "threshold": 0,
                    "source": "pass",
                },
            },
            "unknown threshold rule field",
        ),
        (
            {
                "strategy_id": "bad",
                "rule": {
                    "type": "threshold",
                    "feature_id": "return_1d",
                    "threshold": 0,
                    "feature_params": {"db_path": "facts.sqlite"},
                },
            },
            "runtime-owned",
        ),
        (
            {
                "strategy_id": "bad",
                "rule": {
                    "type": "top_k",
                    "feature_id": "momentum_n",
                    "k": 1,
                    "feature_params": {"unknown": 1},
                },
            },
            "unknown parameter",
        ),
        (
            {
                "strategy_id": "bad",
                "rule": {
                    "type": "top_k",
                    "feature_id": "momentum_n",
                    "k": 1,
                    "feature_params": {"n": "five"},
                },
            },
            "must have type int",
        ),
    ],
)
def test_strategy_spec_rejects_unknown_types_fields_and_params(payload, match):
    with pytest.raises(StrategySpecError, match=match):
        interpret_strategy_spec(payload)


def test_strategy_spec_rejects_unapproved_feature_by_default():
    feature = features.FeatureDefinition(
        id="phase6_candidate_fixture",
        version=features.FeatureVersion(1),
        inputs=features.FeatureInput(required_kwargs=("code",)),
        description="candidate test feature",
        compute=lambda _ctx: features.FeatureOutput(value=1.0),
        intended_role="signal",
    )
    features.register(feature)
    try:
        spec = StrategySpec(
            strategy_id="candidate_rejected",
            rule=ThresholdRule(feature.id, 0.0),
        )
        with pytest.raises(StrategySpecError, match="candidate"):
            interpret_strategy_spec(spec)
    finally:
        features.FEATURES_REGISTRY.pop((feature.id, str(feature.version)))


def test_strategy_spec_source_contains_no_dynamic_code_execution():
    import ast
    from pathlib import Path

    root = Path(__file__).parents[1] / "strategies" / "spec"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert not ({"eval", "exec", "compile", "__import__"} & called), path
