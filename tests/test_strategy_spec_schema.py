"""Closed-schema and governance tests for declarative StrategySpec."""

from __future__ import annotations

import features
import pytest

from strategies.spec import (
    FeatureRef,
    StrategySpec,
    StrategySpecError,
    ThresholdRule,
    TopKRule,
    interpret_strategy_spec,
)
# v3 rules imported via from_dict in new tests


def test_strategy_spec_round_trip_supports_only_whitelisted_rules():
    payload = {
        "version": "strategy-spec/v2",
        "strategy_id": "approved_momentum",
        "rebalance": "daily",
        "rule": {
            "type": "top_k",
            "feature": {
                "id": "momentum_n",
                "version": "1.0.0",
                "params": {"n": 5},
            },
            "k": 3,
            "min_score": 0.0,
        },
        "rationale": "fixture",
    }

    spec = StrategySpec.from_dict(payload)

    assert isinstance(spec.rule, TopKRule)
    assert spec.to_dict() == payload
    strategy = interpret_strategy_spec(spec)
    assert strategy.feature_ids == ("momentum_n",)
    assert strategy.feature_versions == {"momentum_n": "1.0.0"}
    assert strategy.params == {"strategy_spec": payload}


def test_strategy_spec_v3_cross_section_rank_sticky_round_trip():
    payload = {
        "version": "strategy-spec/v3",
        "strategy_id": "xs_hold10_mom5",
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
        },
        "rationale": "W84 xs sticky",
    }
    spec = StrategySpec.from_dict(payload)
    assert spec.rebalance == "fixed_horizon"
    assert spec.hold_days == 10
    assert spec.to_dict() == payload
    strategy = interpret_strategy_spec(spec)
    assert strategy.feature_ids == ("momentum_n",)


def test_strategy_spec_v3_value_momentum_agree_round_trip():
    payload = {
        "version": "strategy-spec/v3",
        "strategy_id": "fund_hold10_mom10",
        "rebalance": "fixed_horizon",
        "hold_days": 10,
        "rule": {
            "type": "value_momentum_agree",
            "value_feature": {
                "id": "fundamental_value_score",
                "version": "1.0.0",
                "params": {},
            },
            "momentum_feature": {
                "id": "momentum_n",
                "version": "1.0.0",
                "params": {"n": 10},
            },
            "mode": "value_momentum_agree",
            "allow_short": True,
        },
        "rationale": "W84 fund sticky",
    }
    spec = StrategySpec.from_dict(payload)
    assert spec.to_dict() == payload
    strategy = interpret_strategy_spec(spec)
    assert set(strategy.feature_ids) == {
        "fundamental_value_score",
        "momentum_n",
    }


def test_strategy_spec_v2_rejects_fixed_horizon_and_new_rules():
    with pytest.raises(StrategySpecError, match="unsupported rebalance|fixed_horizon"):
        StrategySpec.from_dict(
            {
                "version": "strategy-spec/v2",
                "strategy_id": "bad",
                "rebalance": "fixed_horizon",
                "hold_days": 10,
                "rule": {
                    "type": "top_k",
                    "feature": {
                        "id": "momentum_n",
                        "version": "1.0.0",
                        "params": {"n": 5},
                    },
                    "k": 1,
                },
            }
        )
    with pytest.raises(StrategySpecError, match="requires strategy-spec/v3|unknown rule"):
        StrategySpec.from_dict(
            {
                "version": "strategy-spec/v2",
                "strategy_id": "bad",
                "rebalance": "daily",
                "rule": {
                    "type": "cross_section_rank",
                    "feature": {
                        "id": "momentum_n",
                        "version": "1.0.0",
                        "params": {"n": 5},
                    },
                },
            }
        )


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
                    "feature": {
                        "id": "return_1d",
                        "version": "1.0.0",
                        "params": {},
                    },
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
                    "feature": {
                        "id": "return_1d",
                        "version": "1.0.0",
                        "params": {"db_path": "facts.sqlite"},
                    },
                    "threshold": 0,
                },
            },
            "runtime-owned",
        ),
        (
            {
                "strategy_id": "bad",
                "rule": {
                    "type": "top_k",
                    "feature": {
                        "id": "momentum_n",
                        "version": "1.0.0",
                        "params": {"unknown": 1},
                    },
                    "k": 1,
                },
            },
            "unknown parameter",
        ),
        (
            {
                "strategy_id": "bad",
                "rule": {
                    "type": "top_k",
                    "feature": {
                        "id": "momentum_n",
                        "version": "1.0.0",
                        "params": {"n": "five"},
                    },
                    "k": 1,
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
            rule=ThresholdRule(
                FeatureRef(feature.id, str(feature.version)),
                0.0,
            ),
        )
        with pytest.raises(StrategySpecError, match="candidate"):
            interpret_strategy_spec(spec)
    finally:
        features.FEATURES_REGISTRY.pop((feature.id, str(feature.version)))


def test_persisted_spec_requires_nested_exact_feature_ref():
    with pytest.raises(StrategySpecError, match="unsupported StrategySpec version"):
        StrategySpec.from_dict(
            {
                "version": "strategy-spec/v1",
                "strategy_id": "legacy_unpinned",
                "rule": {
                    "type": "threshold",
                    "feature_id": "return_1d",
                    "threshold": 0,
                },
            }
        )

    with pytest.raises(StrategySpecError, match="missing field.*version"):
        StrategySpec.from_dict(
            {
                "version": "strategy-spec/v2",
                "strategy_id": "missing_pin",
                "rule": {
                    "type": "threshold",
                    "feature": {"id": "return_1d", "params": {}},
                    "threshold": 0,
                },
            }
        )


def test_interpreter_uses_pinned_version_even_when_newer_exists():
    feature_id = "phase6_exact_pin_fixture"
    v1 = features.FeatureDefinition(
        id=feature_id,
        version=features.FeatureVersion(1),
        inputs=features.FeatureInput(required_kwargs=("code",)),
        description="pinned",
        compute=lambda _ctx: features.FeatureOutput(value=1.0),
        intended_role="signal",
        status="approved",
    )
    v2 = features.FeatureDefinition(
        id=feature_id,
        version=features.FeatureVersion(2),
        inputs=features.FeatureInput(required_kwargs=("code",)),
        description="newer",
        compute=lambda _ctx: features.FeatureOutput(value=2.0),
        intended_role="signal",
        status="approved",
    )
    features.register(v1)
    features.register(v2)
    calls: list[tuple[str, str | None]] = []

    class Context:
        universe = ("1332",)
        positions = {}

        def feature(self, feature_id, *, version=None, **_inputs):
            calls.append((feature_id, version))
            return features.FeatureOutput(value=1.0)

    try:
        strategy = interpret_strategy_spec(
            StrategySpec(
                strategy_id="pinned",
                rule=ThresholdRule(FeatureRef(feature_id, "1.0.0"), 0.0),
            )
        )
        strategy.on_bar(Context())
        assert calls == [(feature_id, "1.0.0")]
        assert strategy.feature_versions == {feature_id: "1.0.0"}
        assert features.get(feature_id).version == features.FeatureVersion(2)
    finally:
        features.FEATURES_REGISTRY.pop((feature_id, "1.0.0"), None)
        features.FEATURES_REGISTRY.pop((feature_id, "2.0.0"), None)


def test_strategy_spec_source_contains_no_dynamic_code_execution():
    import ast
    from pathlib import Path

    import strategies as _strategies_pkg

    root = Path(_strategies_pkg.__file__).resolve().parent / "spec"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert not ({"eval", "exec", "compile", "__import__"} & called), path
