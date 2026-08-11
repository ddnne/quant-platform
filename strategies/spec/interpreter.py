"""Safe StrategySpec interpreter targeting the narrow core protocol."""

from __future__ import annotations

from typing import Any, Mapping

import core
import features

from .schema import StrategySpec, StrategySpecError, ThresholdRule, TopKRule


def _validate_feature(spec: StrategySpec) -> None:
    """Resolve and authorize the feature, including every declared parameter."""
    try:
        definition = features.get_for_strategy(
            spec.rule.feature_id,
            allowed_statuses=("approved",),
            allowed_roles=("signal",),
        )
    except (KeyError, features.FeatureGovernanceError) as exc:
        raise StrategySpecError(str(exc)) from exc
    required = set(definition.inputs.required_kwargs) - {"code"}
    optional = set(definition.inputs.optional_kwargs)
    supplied = set(spec.rule.feature_params)
    missing = sorted(required - supplied)
    unknown = sorted(supplied - required - optional)
    if missing:
        raise StrategySpecError(
            f"feature {definition.id!r} missing parameter(s): {missing}"
        )
    if unknown:
        raise StrategySpecError(
            f"feature {definition.id!r} received unknown parameter(s): {unknown}"
        )
    for name in sorted(supplied & optional):
        default = definition.inputs.optional_kwargs[name]
        value = spec.rule.feature_params[name]
        if default is None or value is None:
            continue
        expected = type(default)
        valid = isinstance(value, expected)
        if expected is int and isinstance(value, bool):
            valid = False
        if expected is float and isinstance(value, int) and not isinstance(value, bool):
            valid = True
        if not valid:
            raise StrategySpecError(
                f"feature {definition.id!r} parameter {name!r} must have type "
                f"{expected.__name__}"
            )


def _equal_weight_intents(
    ctx: core.BarContext, selected: set[str]
) -> list[core.OrderIntent]:
    """Emit complete targets, including exits for deselected holdings."""
    weight = 1.0 / len(selected) if selected else 0.0
    codes = sorted(set(ctx.positions) | selected)
    return [
        core.OrderIntent(
            code=code,
            target_weight=weight if code in selected else 0.0,
            note="StrategySpec equal_weight",
        )
        for code in codes
    ]


class StrategySpecStrategy:
    """Core Strategy implementation produced from a validated declaration."""

    def __init__(self, spec: StrategySpec) -> None:
        _validate_feature(spec)
        self.spec = spec
        self.strategy_id = spec.strategy_id
        self.feature_ids = (spec.rule.feature_id,)
        self.params: dict[str, Any] = {"strategy_spec": spec.to_dict()}

    def _scores(self, ctx: core.BarContext) -> list[tuple[str, float]]:
        scores: list[tuple[str, float]] = []
        params: Mapping[str, Any] = self.spec.rule.feature_params
        for code in sorted(ctx.universe):
            output = ctx.feature(self.spec.rule.feature_id, code=code, **dict(params))
            if output.value is None:
                continue
            try:
                scores.append((code, float(output.value)))
            except (TypeError, ValueError) as exc:
                raise StrategySpecError(
                    f"feature {self.spec.rule.feature_id!r} returned a non-numeric score"
                ) from exc
        return scores

    def on_bar(self, ctx: core.BarContext) -> list[core.OrderIntent]:
        scores = self._scores(ctx)
        rule = self.spec.rule
        if isinstance(rule, ThresholdRule):
            selected = {code for code, score in scores if score >= rule.threshold}
        elif isinstance(rule, TopKRule):
            eligible = [
                (code, score)
                for code, score in scores
                if rule.min_score is None or score >= rule.min_score
            ]
            ranked = sorted(eligible, key=lambda item: (-item[1], item[0]))
            selected = {code for code, _ in ranked[: rule.k]}
        else:  # pragma: no cover - schema construction makes this unreachable
            raise StrategySpecError(f"unsupported rule instance: {type(rule).__name__}")
        return _equal_weight_intents(ctx, selected)


def interpret_strategy_spec(
    value: StrategySpec | Mapping[str, Any],
) -> StrategySpecStrategy:
    """Parse, validate, and compile a declaration without evaluating source."""
    spec = value if isinstance(value, StrategySpec) else StrategySpec.from_dict(value)
    return StrategySpecStrategy(spec)


__all__ = ["StrategySpecStrategy", "interpret_strategy_spec"]
