"""Safe StrategySpec interpreter targeting the narrow core protocol.

W84 / w0816s: sticky fixed-horizon hold, cross-section rank L-S, and
value×momentum agree rules. No eval/exec; approved features only.
"""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any, Mapping

import core
import features

from .schema import (
    CrossSectionRankRule,
    FactorRankRule,
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


def _master_group_key(
    ctx: core.BarContext, code: str, group: str
) -> str | None:
    """Resolve a closed grouping key; sector/scale only come from PIT master."""
    if group == "market":
        return "__market__"
    master = ctx.master.get(code)
    if master is None:
        return None
    attr = "sector_33_code" if group == "sector33" else "scale_category"
    value = getattr(master, attr, None)
    if value is None and isinstance(master, Mapping):
        value = master.get(attr)
    text = str(value).strip() if value is not None else ""
    return text or None


def _percentile_values(
    values: Mapping[str, float], *, direction: str
) -> dict[str, float]:
    """Return [0,1] average ranks; equal values receive equal percentiles."""
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    if len(ordered) == 1:
        base = {ordered[0][0]: 0.5}
    else:
        denominator = float(len(ordered) - 1)
        base: dict[str, float] = {}
        start = 0
        while start < len(ordered):
            end = start + 1
            while end < len(ordered) and ordered[end][1] == ordered[start][1]:
                end += 1
            average_rank = (start + end - 1) / 2.0
            percentile = average_rank / denominator
            for index in range(start, end):
                base[ordered[index][0]] = percentile
            start = end
    if direction == "low_good":
        return {code: 1.0 - percentile for code, percentile in base.items()}
    return base


def _factor_rank_signs(
    ctx: core.BarContext, rule: FactorRankRule
) -> tuple[dict[str, float], dict[str, Any]]:
    """Evaluate a bounded factor composite and its fail-closed coverage gates."""
    universe = tuple(sorted(set(ctx.universe)))
    leg_values: list[dict[str, float]] = []
    missing_leg_counts: dict[str, int] = {}
    for index, leg in enumerate(rule.legs):
        values: dict[str, float] = {}
        for code in universe:
            output = ctx.feature(
                leg.feature.id,
                version=leg.feature.version,
                code=code,
                **dict(leg.feature.params),
            )
            if output.value is None:
                continue
            try:
                score = float(output.value)
            except (TypeError, ValueError) as exc:
                raise StrategySpecError(
                    f"feature {leg.feature.id!r} version "
                    f"{leg.feature.version!r} returned a non-numeric score"
                ) from exc
            if math.isfinite(score):
                values[code] = score
        leg_values.append(values)
        missing_leg_counts[f"{index}:{leg.feature.id}@{leg.feature.version}"] = (
            len(universe) - len(values)
        )

    universe_group: dict[str, str] = {}
    missing_group_count = 0
    for code in universe:
        key = _master_group_key(ctx, code, rule.group)
        if key is None:
            missing_group_count += 1
        else:
            universe_group[code] = key

    candidates = [
        code
        for code in universe
        if code in universe_group and all(code in values for values in leg_values)
    ]

    universe_counts: dict[str, int] = defaultdict(int)
    eligible_counts: dict[str, int] = defaultdict(int)
    for key in universe_group.values():
        universe_counts[key] += 1
    for code in candidates:
        eligible_counts[universe_group[code]] += 1

    # A genuinely small PIT group is not evidence that the whole market is
    # unusable. Exclude that group from this rebalance. For sufficiently large
    # groups, require both the absolute and proportional coverage floors so a
    # large sector cannot pass with only a handful of populated rows.
    valid_groups = {
        key for key, count in universe_counts.items() if count >= rule.min_group_count
    }
    excluded_small_groups = tuple(sorted(set(universe_counts) - valid_groups))
    eligible = [code for code in candidates if universe_group[code] in valid_groups]
    eligible_universe_count = sum(universe_counts[key] for key in valid_groups)
    eligible_count = len(eligible)
    group_label_ratio = (
        len(universe_group) / len(universe) if universe else 0.0
    )
    eligible_ratio = (
        eligible_count / eligible_universe_count if eligible_universe_count else 0.0
    )
    failed_groups = tuple(
        sorted(
            key
            for key in valid_groups
            if (
                eligible_counts.get(key, 0) < rule.min_group_count
                or eligible_counts.get(key, 0) / universe_counts[key]
                < rule.min_eligible_ratio
            )
        )
    )

    reasons: list[str] = []
    if group_label_ratio < rule.min_eligible_ratio:
        reasons.append("group_label_coverage_below_floor")
    if eligible_count < rule.min_eligible_count:
        reasons.append("eligible_count_below_floor")
    if eligible_ratio < rule.min_eligible_ratio:
        reasons.append("eligible_ratio_below_floor")
    if failed_groups:
        reasons.append("group_coverage_below_floor")

    diagnostics: dict[str, Any] = {
        "status": "flattened" if reasons else "passed",
        "reason_codes": tuple(reasons),
        "normalization": rule.normalization,
        "group": rule.group,
        "universe_count": len(universe),
        "group_label_count": len(universe_group),
        "group_label_ratio": group_label_ratio,
        "eligible_universe_count": eligible_universe_count,
        "eligible_count": eligible_count,
        "eligible_ratio": eligible_ratio,
        "missing_group_count": missing_group_count,
        "missing_leg_counts": dict(sorted(missing_leg_counts.items())),
        "failed_groups": failed_groups,
        "excluded_small_groups": excluded_small_groups,
        "group_counts": {
            key: {
                "universe": universe_counts[key],
                "eligible": eligible_counts.get(key, 0),
                "eligible_ratio": (
                    eligible_counts.get(key, 0) / universe_counts[key]
                ),
            }
            for key in sorted(universe_counts)
        },
    }
    if reasons:
        # An empty signed book makes _signed_equal_weight_intents emit explicit
        # zero targets for every currently held position.
        return {}, diagnostics

    eligible_by_group: dict[str, list[str]] = defaultdict(list)
    for code in eligible:
        eligible_by_group[universe_group[code]].append(code)
    signed: dict[str, float] = {}
    composite_scores: dict[str, float] = {}
    weight_denominator = sum(abs(leg.weight) for leg in rule.legs)
    for key in sorted(eligible_by_group):
        codes = sorted(eligible_by_group[key])
        normalized_legs: list[dict[str, float]] = []
        for leg, values in zip(rule.legs, leg_values, strict=True):
            normalized_legs.append(
                _percentile_values(
                    {code: values[code] for code in codes},
                    direction=leg.direction,
                )
            )
        group_scores = {
            code: sum(
                leg.weight * normalized[code]
                for leg, normalized in zip(rule.legs, normalized_legs, strict=True)
            )
            / weight_denominator
            for code in codes
        }
        composite_scores.update(group_scores)
        signed.update(
            _cross_section_rank_signs(
                list(group_scores.items()),
                long_frac=rule.long_frac,
                short_frac=rule.short_frac,
                allow_short=rule.allow_short,
                neutralize_cutoff_ties=True,
            )
        )

    diagnostics["long_count"] = sum(1 for value in signed.values() if value > 0)
    diagnostics["short_count"] = sum(1 for value in signed.values() if value < 0)
    diagnostics["flat_count"] = sum(1 for value in signed.values() if value == 0)
    diagnostics["composite_min"] = min(composite_scores.values())
    diagnostics["composite_max"] = max(composite_scores.values())
    return signed, diagnostics


def _cross_section_rank_signs(
    scores: list[tuple[str, float]],
    *,
    long_frac: float,
    short_frac: float,
    allow_short: bool,
    neutralize_cutoff_ties: bool = False,
) -> dict[str, float]:
    """Top/bottom fraction signs with an opt-in tie-neutral v4 policy.

    Legacy v3 callers retain the historical code tie-break. FactorRank v4
    includes every non-overlapping cutoff tie and leaves an overlapping cutoff
    value flat, so a ticker name can never become an economic signal.
    """
    if not scores:
        return {}
    ranked = sorted(scores, key=lambda item: (-item[1], item[0]))
    n = len(ranked)
    n_long = max(1, int(round(n * float(long_frac)))) if n >= 3 else 1
    n_short = max(1, int(round(n * float(short_frac)))) if n >= 3 else 1
    if n_long + n_short > n:
        n_long = max(1, n // 3)
        n_short = max(1, n // 3)
    if neutralize_cutoff_ties:
        long_cutoff = ranked[n_long - 1][1]
        short_cutoff = ranked[n - n_short][1]
        overlap = long_cutoff <= short_cutoff
        out: dict[str, float] = {}
        for code, score in ranked:
            if (score > long_cutoff if overlap else score >= long_cutoff):
                out[code] = 1.0
            elif (score < short_cutoff if overlap else score <= short_cutoff):
                out[code] = -1.0 if allow_short else 0.0
            else:
                out[code] = 0.0
        return out
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
        definitions = resolve_strategy_features(spec)
        refs = iter_feature_refs(spec)
        self.spec = spec
        self.strategy_id = spec.strategy_id
        self.feature_ids = tuple(definition.id for definition in definitions)
        self.feature_versions = {ref.id: ref.version for ref in refs}
        self.params: dict[str, Any] = {"strategy_spec": spec.to_dict()}
        self.last_diagnostics: dict[str, Any] = {"status": "not_run"}
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
        if isinstance(rule, FactorRankRule):
            signed, diagnostics = _factor_rank_signs(ctx, rule)
            self.last_diagnostics = diagnostics
            self._last_signed = dict(signed)
            return _signed_equal_weight_intents(
                ctx, signed, note="StrategySpec factor_rank"
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
