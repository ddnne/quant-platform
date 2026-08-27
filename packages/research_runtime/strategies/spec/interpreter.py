"""Safe StrategySpec interpreter targeting the narrow core protocol.

W84 / w0816s: sticky fixed-horizon hold, cross-section rank L-S, and
value×momentum agree rules. No eval/exec; approved features only.
"""

from __future__ import annotations

from statistics import median
from typing import Any, Mapping

import core
import features

from .schema import (
    CrossSectionRankRule,
    FeatureRef,
    REBALANCE_FIXED_HORIZON,
    StrategySpec,
    StrategySpecError,
    ThresholdRule,
    TopKRule,
    ValueMomentumAgreeRule,
    iter_feature_refs,
)


def resolve_feature_ref(ref: FeatureRef) -> features.FeatureDefinition:
    """Resolve and authorize one feature, including every declared parameter."""
    try:
        definition = features.get_for_strategy(
            ref.id,
            version=ref.version,
            allowed_statuses=("approved",),
            allowed_roles=("signal",),
        )
    except (KeyError, features.FeatureGovernanceError) as exc:
        raise StrategySpecError(str(exc)) from exc
    required = set(definition.inputs.required_kwargs) - {"code"}
    optional = set(definition.inputs.optional_kwargs)
    supplied = set(ref.params)
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
        value = ref.params[name]
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
    return definition


def resolve_strategy_features(
    spec: StrategySpec,
) -> tuple[features.FeatureDefinition, ...]:
    """Resolve every exact FeatureRef without a latest-version fallback."""
    if not isinstance(spec, StrategySpec):
        raise TypeError("StrategySpec required")
    return tuple(resolve_feature_ref(ref) for ref in iter_feature_refs(spec))


def _resolve_features(spec: StrategySpec) -> dict[str, features.FeatureDefinition]:
    """Resolve all FeatureRefs referenced by the rule."""
    rule = spec.rule
    if isinstance(rule, ValueMomentumAgreeRule):
        return {
            "value": resolve_feature_ref(rule.value_feature),
            "momentum": resolve_feature_ref(rule.momentum_feature),
        }
    return {"primary": resolve_feature_ref(rule.feature)}


def _score_feature(
    ctx: core.BarContext, ref: FeatureRef
) -> list[tuple[str, float]]:
    scores: list[tuple[str, float]] = []
    params: Mapping[str, Any] = ref.params
    for code in sorted(ctx.universe):
        output = ctx.feature(
            ref.id,
            version=ref.version,
            code=code,
            **dict(params),
        )
        if output.value is None:
            continue
        try:
            scores.append((code, float(output.value)))
        except (TypeError, ValueError) as exc:
            raise StrategySpecError(
                f"feature {ref.id!r} version {ref.version!r} returned a "
                "non-numeric score"
            ) from exc
    return scores


def _cross_section_rank_signs(
    scores: list[tuple[str, float]],
    *,
    long_frac: float,
    short_frac: float,
    allow_short: bool,
) -> dict[str, float]:
    """Top long_frac → +1, bottom short_frac → −1 (or 0 if shorts disallowed)."""
    if not scores:
        return {}
    ranked = sorted(scores, key=lambda item: (-item[1], item[0]))
    n = len(ranked)
    n_long = max(1, int(round(n * float(long_frac)))) if n >= 3 else 1
    n_short = max(1, int(round(n * float(short_frac)))) if n >= 3 else 1
    if n_long + n_short > n:
        n_long = max(1, n // 3)
        n_short = max(1, n // 3)
    out: dict[str, float] = {}
    for i, (code, _) in enumerate(ranked):
        if i < n_long:
            out[code] = 1.0
        elif i >= n - n_short:
            out[code] = -1.0 if allow_short else 0.0
        else:
            out[code] = 0.0
    return out


def _signed_equal_weight_intents(
    ctx: core.BarContext,
    signed: Mapping[str, float],
    *,
    note: str,
) -> list[core.OrderIntent]:
    """Convert signed positions (+1 long / −1 short / 0 flat) to target weights.

    Long book and short book are each equal-weight and each gross 50% of equity
    when both sides are present (dollar-neutral-ish). Long-only uses full 100%.
    """
    longs = sorted(c for c, s in signed.items() if s > 0)
    shorts = sorted(c for c, s in signed.items() if s < 0)
    weights: dict[str, float] = {}
    if longs and shorts:
        w_long = 0.5 / len(longs)
        w_short = -0.5 / len(shorts)
        for c in longs:
            weights[c] = w_long
        for c in shorts:
            weights[c] = w_short
    elif longs:
        w = 1.0 / len(longs)
        for c in longs:
            weights[c] = w
    elif shorts:
        # pure short book (rare): -100% equal weight
        w = -1.0 / len(shorts)
        for c in shorts:
            weights[c] = w
    codes = sorted(set(ctx.positions) | set(weights) | set(signed))
    return [
        core.OrderIntent(
            code=code,
            target_weight=float(weights.get(code, 0.0)),
            note=note,
        )
        for code in codes
    ]


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
    """Core Strategy implementation produced from a validated declaration.

    Sticky ``fixed_horizon`` hold: selection is recomputed only every
    ``hold_days`` sessions (session counter starts at 0). Between rebalance
    bars the previous target weights are re-emitted so the engine keeps
    positions (no daily churn).
    """

    def __init__(self, spec: StrategySpec) -> None:
        definitions = _resolve_features(spec)
        self.spec = spec
        self.strategy_id = spec.strategy_id
        if isinstance(spec.rule, ValueMomentumAgreeRule):
            self.feature_ids = (
                definitions["value"].id,
                definitions["momentum"].id,
            )
            self.feature_versions = {
                definitions["value"].id: str(definitions["value"].version),
                definitions["momentum"].id: str(definitions["momentum"].version),
            }
        else:
            primary = definitions["primary"]
            self.feature_ids = (primary.id,)
            self.feature_versions = {primary.id: str(primary.version)}
        self.params: dict[str, Any] = {"strategy_spec": spec.to_dict()}
        # sticky hold state
        self._bars_seen = 0
        self._last_intents: list[core.OrderIntent] | None = None
        self._last_signed: dict[str, float] | None = None

    def _compute_fresh_intents(self, ctx: core.BarContext) -> list[core.OrderIntent]:
        rule = self.spec.rule
        if isinstance(rule, ThresholdRule):
            scores = _score_feature(ctx, rule.feature)
            selected = {code for code, score in scores if score >= rule.threshold}
            return _equal_weight_intents(ctx, selected)
        if isinstance(rule, TopKRule):
            scores = _score_feature(ctx, rule.feature)
            eligible = [
                (code, score)
                for code, score in scores
                if rule.min_score is None or score >= rule.min_score
            ]
            ranked = sorted(eligible, key=lambda item: (-item[1], item[0]))
            selected = {code for code, _ in ranked[: rule.k]}
            return _equal_weight_intents(ctx, selected)
        if isinstance(rule, CrossSectionRankRule):
            scores = _score_feature(ctx, rule.feature)
            signed = _cross_section_rank_signs(
                scores,
                long_frac=rule.long_frac,
                short_frac=rule.short_frac,
                allow_short=rule.allow_short,
            )
            # W86: optional signal_sign invert (−1) after research sign-selection.
            sig = int(getattr(rule, "signal_sign", 1) or 1)
            if sig == -1:
                signed = {c: (-s if s else s) for c, s in signed.items()}
                # after invert, shorts may become longs; allow_short already applied
            self._last_signed = dict(signed)
            return _signed_equal_weight_intents(
                ctx, signed, note="StrategySpec cross_section_rank"
            )
        if isinstance(rule, ValueMomentumAgreeRule):
            value_scores = dict(_score_feature(ctx, rule.value_feature))
            mom_scores = dict(_score_feature(ctx, rule.momentum_feature))
            vals = [v for v in value_scores.values() if v is not None]
            bench = float(median(vals)) if vals else 0.0
            signed: dict[str, float] = {}
            codes = sorted(set(value_scores) | set(mom_scores) | set(ctx.universe))
            for code in codes:
                v = value_scores.get(code)
                m = mom_scores.get(code)
                if v is None:
                    signed[code] = 0.0
                    continue
                value_sign = 1.0 if v > bench else (-1.0 if v < bench else 0.0)
                if rule.mode == "value_only":
                    s = value_sign
                else:
                    if m is None or m == 0.0 or value_sign == 0.0:
                        s = 0.0
                    elif (value_sign > 0 and m > 0) or (value_sign < 0 and m < 0):
                        s = value_sign
                    else:
                        s = 0.0
                if s < 0 and not rule.allow_short:
                    s = 0.0
                signed[code] = s
            sig = int(getattr(rule, "signal_sign", 1) or 1)
            if sig == -1:
                flipped: dict[str, float] = {}
                for c, s in signed.items():
                    ns = -s if s else s
                    if ns < 0 and not rule.allow_short:
                        ns = 0.0
                    flipped[c] = ns
                signed = flipped
            self._last_signed = dict(signed)
            return _signed_equal_weight_intents(
                ctx, signed, note="StrategySpec value_momentum_agree"
            )
        raise StrategySpecError(f"unsupported rule instance: {type(rule).__name__}")

    def _should_rebalance(self) -> bool:
        if self.spec.rebalance != REBALANCE_FIXED_HORIZON:
            return True
        h = int(self.spec.hold_days or 1)
        if self._last_intents is None:
            return True
        # rebalance on bar 0, h, 2h, ...
        return self._bars_seen % h == 0

    def on_bar(self, ctx: core.BarContext) -> list[core.OrderIntent]:
        if self._should_rebalance():
            intents = self._compute_fresh_intents(ctx)
            self._last_intents = list(intents)
            self._bars_seen += 1
            return intents
        # Sticky hold: omit intents so the engine leaves shares untouched
        # (re-emitting constant *weights* would still rebalance as prices move).
        self._bars_seen += 1
        return []


def interpret_strategy_spec(
    value: StrategySpec | Mapping[str, Any],
) -> StrategySpecStrategy:
    """Parse, validate, and compile a declaration without evaluating source."""
    spec = value if isinstance(value, StrategySpec) else StrategySpec.from_dict(value)
    return StrategySpecStrategy(spec)


__all__ = [
    "StrategySpecStrategy",
    "interpret_strategy_spec",
    "resolve_feature_ref",
    "resolve_strategy_features",
]
