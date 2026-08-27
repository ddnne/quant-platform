"""Closed, declarative schema for agent-proposed strategies.

Only the rule types defined here are executable.  The parser rejects unknown
keys as well as unknown rule types, so a memo or model response cannot smuggle
Python source, database arguments, or an unreviewed execution primitive into
the trusted paper runtime.

Version history
---------------
* ``strategy-spec/v2`` — daily rebalance; ``threshold`` / ``top_k`` only.
* ``strategy-spec/v3`` (W84 / w0816s) — adds sticky ``fixed_horizon`` rebalance
  with ``hold_days``, plus research-aligned rules:
  ``cross_section_rank`` (CS L-S) and ``value_momentum_agree`` (fund value×mom).
  v2 payloads remain parseable and interpretable.
* W86 / w0816u — optional ``signal_sign`` (+1 original / −1 inverted) on
  ``cross_section_rank`` and ``value_momentum_agree`` for reproducibility of
  research sign-selection. Default +1; omitted from to_dict when +1.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


STRATEGY_SPEC_VERSION = "strategy-spec/v3"
STRATEGY_SPEC_VERSION_V2 = "strategy-spec/v2"
SUPPORTED_STRATEGY_SPEC_VERSIONS = frozenset(
    {STRATEGY_SPEC_VERSION, STRATEGY_SPEC_VERSION_V2}
)

REBALANCE_DAILY = "daily"
REBALANCE_FIXED_HORIZON = "fixed_horizon"
SUPPORTED_REBALANCES_V2 = frozenset({REBALANCE_DAILY})
SUPPORTED_REBALANCES_V3 = frozenset({REBALANCE_DAILY, REBALANCE_FIXED_HORIZON})

_RESERVED_FEATURE_PARAMS = frozenset({"code", "as_of", "db_path", "version"})


class StrategySpecError(ValueError):
    """Raised when a StrategySpec violates the closed schema."""


def _strict_keys(payload: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise StrategySpecError(f"unknown {where} field(s): {unknown}")


def _identifier(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise StrategySpecError(f"{where} must be a string")
    text = value.strip()
    if not text or not all(ch.isalnum() or ch in "._-" for ch in text):
        raise StrategySpecError(f"{where} must be a non-empty safe identifier")
    return text


def _feature_params(value: Any) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise StrategySpecError("FeatureRef.params must be an object")
    params = dict(value)
    reserved = sorted(_RESERVED_FEATURE_PARAMS.intersection(params))
    if reserved:
        raise StrategySpecError(
            f"FeatureRef.params may not set runtime-owned field(s): {reserved}"
        )
    for key, item in params.items():
        if not isinstance(key, str) or not key:
            raise StrategySpecError("feature parameter names must be non-empty strings")
        if isinstance(item, (dict, list, tuple, set)) or not isinstance(
            item, (str, int, float, bool, type(None))
        ):
            raise StrategySpecError(
                f"feature parameter {key!r} must be a JSON scalar"
            )
        if isinstance(item, float) and not math.isfinite(item):
            raise StrategySpecError(f"feature parameter {key!r} must be finite")
    return MappingProxyType(params)


def _finite_float(value: Any, where: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise StrategySpecError(f"{where} must be numeric") from exc
    if not math.isfinite(out):
        raise StrategySpecError(f"{where} must be finite")
    return out


def _frac(value: Any, where: str) -> float:
    out = _finite_float(value, where)
    if out <= 0.0 or out > 1.0:
        raise StrategySpecError(f"{where} must be in (0, 1]")
    return out


@dataclass(frozen=True)
class FeatureRef:
    """An immutable, exact reference to one governed feature definition."""

    id: str
    version: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "FeatureRef.id"))
        object.__setattr__(
            self, "version", _identifier(self.version, "FeatureRef.version")
        )
        object.__setattr__(self, "params", _feature_params(self.params))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FeatureRef":
        if not isinstance(payload, Mapping):
            raise StrategySpecError("rule.feature must be a FeatureRef object")
        _strict_keys(payload, {"id", "version", "params"}, "FeatureRef")
        missing = {"id", "version"} - set(payload)
        if missing:
            raise StrategySpecError(f"FeatureRef missing field(s): {sorted(missing)}")
        return cls(
            id=payload["id"],
            version=payload["version"],
            params=payload.get("params", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "params": dict(self.params),
        }


@dataclass(frozen=True)
class ThresholdRule:
    """Equal-weight every code whose approved feature is at least ``threshold``."""

    feature: FeatureRef
    threshold: float
    type: str = field(default="threshold", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.feature, FeatureRef):
            raise StrategySpecError("threshold.feature must be a FeatureRef")
        object.__setattr__(self, "threshold", _finite_float(self.threshold, "threshold"))

    @property
    def feature_id(self) -> str:
        return self.feature.id

    @property
    def feature_version(self) -> str:
        return self.feature.version

    @property
    def feature_params(self) -> Mapping[str, Any]:
        return self.feature.params

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "feature": self.feature.to_dict(),
            "threshold": self.threshold,
        }


@dataclass(frozen=True)
class TopKRule:
    """Equal-weight the highest-scoring ``k`` codes from an approved feature."""

    feature: FeatureRef
    k: int
    min_score: float | None = None
    type: str = field(default="top_k", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.feature, FeatureRef):
            raise StrategySpecError("top_k.feature must be a FeatureRef")
        if isinstance(self.k, bool) or not isinstance(self.k, int):
            raise StrategySpecError("top_k.k must be an integer")
        if self.k < 1:
            raise StrategySpecError("top_k.k must be >= 1")
        if self.min_score is not None:
            object.__setattr__(
                self, "min_score", _finite_float(self.min_score, "top_k.min_score")
            )

    @property
    def feature_id(self) -> str:
        return self.feature.id

    @property
    def feature_version(self) -> str:
        return self.feature.version

    @property
    def feature_params(self) -> Mapping[str, Any]:
        return self.feature.params

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "feature": self.feature.to_dict(),
            "k": self.k,
            "min_score": self.min_score,
        }


def _signal_sign(value: Any, where: str) -> int:
    """+1 original / −1 inverted (W86 sign selection). Default +1."""
    if value is None:
        return 1
    try:
        s = int(value)
    except (TypeError, ValueError) as exc:
        raise StrategySpecError(f"{where} must be +1 or -1") from exc
    if s not in (1, -1):
        raise StrategySpecError(f"{where} must be +1 or -1, got {s!r}")
    return s


@dataclass(frozen=True)
class CrossSectionRankRule:
    """Same-day rank long/short from one approved feature (research CS L-S).

    Top ``long_frac`` → long equal weight; bottom ``short_frac`` → short equal
    weight (when ``allow_short``). Middle band is flat. Sticky hold is expressed
    via StrategySpec ``rebalance=fixed_horizon`` + ``hold_days``.

    ``signal_sign``: +1 keep rank direction; −1 invert (short winners / long
    losers) after research sign-selection (W86).
    """

    feature: FeatureRef
    long_frac: float = 0.3
    short_frac: float = 0.3
    allow_short: bool = True
    signal_sign: int = 1
    type: str = field(default="cross_section_rank", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.feature, FeatureRef):
            raise StrategySpecError("cross_section_rank.feature must be a FeatureRef")
        object.__setattr__(
            self, "long_frac", _frac(self.long_frac, "cross_section_rank.long_frac")
        )
        object.__setattr__(
            self, "short_frac", _frac(self.short_frac, "cross_section_rank.short_frac")
        )
        if not isinstance(self.allow_short, bool):
            raise StrategySpecError("cross_section_rank.allow_short must be a boolean")
        object.__setattr__(
            self,
            "signal_sign",
            _signal_sign(self.signal_sign, "cross_section_rank.signal_sign"),
        )

    @property
    def feature_id(self) -> str:
        return self.feature.id

    @property
    def feature_version(self) -> str:
        return self.feature.version

    @property
    def feature_params(self) -> Mapping[str, Any]:
        return self.feature.params

    def to_dict(self) -> dict[str, Any]:
        out = {
            "type": self.type,
            "feature": self.feature.to_dict(),
            "long_frac": self.long_frac,
            "short_frac": self.short_frac,
            "allow_short": self.allow_short,
        }
        # Omit default +1 so legacy payloads still round-trip equal.
        if int(self.signal_sign) != 1:
            out["signal_sign"] = int(self.signal_sign)
        return out


@dataclass(frozen=True)
class ValueMomentumAgreeRule:
    """Fundamentals value × price-momentum agree (research fund path).

    Long when value_score > CS median (or 0 when no CS) AND momentum > 0;
    short when value_score < median AND momentum < 0; else flat. Sticky hold
    via ``rebalance=fixed_horizon`` + ``hold_days``.

    ``signal_sign``: +1 keep; −1 invert after research sign-selection (W86).
    """

    value_feature: FeatureRef
    momentum_feature: FeatureRef
    mode: str = "value_momentum_agree"
    allow_short: bool = True
    signal_sign: int = 1
    type: str = field(default="value_momentum_agree", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.value_feature, FeatureRef):
            raise StrategySpecError(
                "value_momentum_agree.value_feature must be a FeatureRef"
            )
        if not isinstance(self.momentum_feature, FeatureRef):
            raise StrategySpecError(
                "value_momentum_agree.momentum_feature must be a FeatureRef"
            )
        mode = str(self.mode or "value_momentum_agree").strip().lower()
        if mode not in {"value_momentum_agree", "value_only"}:
            raise StrategySpecError(
                "value_momentum_agree.mode must be "
                "value_momentum_agree|value_only"
            )
        object.__setattr__(self, "mode", mode)
        if not isinstance(self.allow_short, bool):
            raise StrategySpecError(
                "value_momentum_agree.allow_short must be a boolean"
            )
        object.__setattr__(
            self,
            "signal_sign",
            _signal_sign(self.signal_sign, "value_momentum_agree.signal_sign"),
        )

    def to_dict(self) -> dict[str, Any]:
        out = {
            "type": self.type,
            "value_feature": self.value_feature.to_dict(),
            "momentum_feature": self.momentum_feature.to_dict(),
            "mode": self.mode,
            "allow_short": self.allow_short,
        }
        if int(self.signal_sign) != 1:
            out["signal_sign"] = int(self.signal_sign)
        return out


Rule = ThresholdRule | TopKRule | CrossSectionRankRule | ValueMomentumAgreeRule
_V2_RULE_TYPES = frozenset({"threshold", "top_k"})
_V3_RULE_TYPES = frozenset(
    {"threshold", "top_k", "cross_section_rank", "value_momentum_agree"}
)


def _parse_rule(payload: Any, *, version: str) -> Rule:
    if not isinstance(payload, Mapping):
        raise StrategySpecError("rule must be an object")
    rule_type = payload.get("type")
    allowed = _V2_RULE_TYPES if version == STRATEGY_SPEC_VERSION_V2 else _V3_RULE_TYPES
    if rule_type == "threshold":
        _strict_keys(
            payload,
            {"type", "feature", "threshold"},
            "threshold rule",
        )
        required = {"feature", "threshold"} - set(payload)
        if required:
            raise StrategySpecError(f"threshold rule missing field(s): {sorted(required)}")
        return ThresholdRule(
            feature=FeatureRef.from_dict(payload["feature"]),
            threshold=payload["threshold"],
        )
    if rule_type == "top_k":
        _strict_keys(
            payload,
            {"type", "feature", "k", "min_score"},
            "top_k rule",
        )
        required = {"feature", "k"} - set(payload)
        if required:
            raise StrategySpecError(f"top_k rule missing field(s): {sorted(required)}")
        return TopKRule(
            feature=FeatureRef.from_dict(payload["feature"]),
            k=payload["k"],
            min_score=payload.get("min_score"),
        )
    if rule_type == "cross_section_rank":
        if rule_type not in allowed:
            raise StrategySpecError(
                f"rule type {rule_type!r} requires strategy-spec/v3"
            )
        _strict_keys(
            payload,
            {
                "type",
                "feature",
                "long_frac",
                "short_frac",
                "allow_short",
                "signal_sign",
            },
            "cross_section_rank rule",
        )
        required = {"feature"} - set(payload)
        if required:
            raise StrategySpecError(
                f"cross_section_rank rule missing field(s): {sorted(required)}"
            )
        return CrossSectionRankRule(
            feature=FeatureRef.from_dict(payload["feature"]),
            long_frac=payload.get("long_frac", 0.3),
            short_frac=payload.get("short_frac", 0.3),
            allow_short=payload.get("allow_short", True),
            signal_sign=payload.get("signal_sign", 1),
        )
    if rule_type == "value_momentum_agree":
        if rule_type not in allowed:
            raise StrategySpecError(
                f"rule type {rule_type!r} requires strategy-spec/v3"
            )
        _strict_keys(
            payload,
            {
                "type",
                "value_feature",
                "momentum_feature",
                "mode",
                "allow_short",
                "signal_sign",
            },
            "value_momentum_agree rule",
        )
        required = {"value_feature", "momentum_feature"} - set(payload)
        if required:
            raise StrategySpecError(
                f"value_momentum_agree rule missing field(s): {sorted(required)}"
            )
        return ValueMomentumAgreeRule(
            value_feature=FeatureRef.from_dict(payload["value_feature"]),
            momentum_feature=FeatureRef.from_dict(payload["momentum_feature"]),
            mode=payload.get("mode", "value_momentum_agree"),
            allow_short=payload.get("allow_short", True),
            signal_sign=payload.get("signal_sign", 1),
        )
    raise StrategySpecError(
        f"unknown rule type {rule_type!r}; allowed: {sorted(allowed)}"
    )


@dataclass(frozen=True)
class StrategySpec:
    """A complete, versioned paper strategy declaration.

    ``rebalance``:
      * ``daily`` — recompute selection every bar (v2 default).
      * ``fixed_horizon`` — sticky hold: recompute only every ``hold_days``
        sessions (v3; research multi-day / CS sticky / fund sticky).
    """

    strategy_id: str
    rule: Rule
    rationale: str = ""
    version: str = STRATEGY_SPEC_VERSION
    rebalance: str = REBALANCE_DAILY
    hold_days: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_id", _identifier(self.strategy_id, "strategy_id"))
        if self.version not in SUPPORTED_STRATEGY_SPEC_VERSIONS:
            raise StrategySpecError(
                f"unsupported StrategySpec version {self.version!r}; "
                f"expected one of {sorted(SUPPORTED_STRATEGY_SPEC_VERSIONS)}"
            )
        allowed_reb = (
            SUPPORTED_REBALANCES_V2
            if self.version == STRATEGY_SPEC_VERSION_V2
            else SUPPORTED_REBALANCES_V3
        )
        reb = str(self.rebalance or REBALANCE_DAILY).strip().lower()
        if reb not in allowed_reb:
            raise StrategySpecError(
                f"unsupported rebalance {self.rebalance!r} for {self.version}; "
                f"allowed: {sorted(allowed_reb)}"
            )
        object.__setattr__(self, "rebalance", reb)
        if reb == REBALANCE_FIXED_HORIZON:
            if self.hold_days is None:
                raise StrategySpecError(
                    "hold_days is required when rebalance=fixed_horizon"
                )
            if isinstance(self.hold_days, bool) or not isinstance(self.hold_days, int):
                raise StrategySpecError("hold_days must be an integer")
            if self.hold_days < 1:
                raise StrategySpecError("hold_days must be >= 1")
        elif self.hold_days is not None:
            # allow documenting hold intent on daily specs only when explicit None
            if isinstance(self.hold_days, bool) or not isinstance(self.hold_days, int):
                raise StrategySpecError("hold_days must be an integer")
            if self.hold_days < 1:
                raise StrategySpecError("hold_days must be >= 1")
        if not isinstance(
            self.rule,
            (ThresholdRule, TopKRule, CrossSectionRankRule, ValueMomentumAgreeRule),
        ):
            raise StrategySpecError("rule must be a whitelisted StrategySpec rule")
        if self.version == STRATEGY_SPEC_VERSION_V2 and not isinstance(
            self.rule, (ThresholdRule, TopKRule)
        ):
            raise StrategySpecError(
                f"rule type {self.rule.type!r} requires strategy-spec/v3"
            )
        if not isinstance(self.rationale, str):
            raise StrategySpecError("rationale must be a string")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StrategySpec":
        if not isinstance(payload, Mapping):
            raise StrategySpecError("StrategySpec must be an object")
        _strict_keys(
            payload,
            {
                "version",
                "strategy_id",
                "rule",
                "rationale",
                "rebalance",
                "hold_days",
            },
            "StrategySpec",
        )
        missing = {"strategy_id", "rule"} - set(payload)
        if missing:
            raise StrategySpecError(f"StrategySpec missing field(s): {sorted(missing)}")
        version = payload.get("version", STRATEGY_SPEC_VERSION)
        if version not in SUPPORTED_STRATEGY_SPEC_VERSIONS:
            raise StrategySpecError(
                f"unsupported StrategySpec version {version!r}; "
                f"expected one of {sorted(SUPPORTED_STRATEGY_SPEC_VERSIONS)}"
            )
        return cls(
            version=version,
            strategy_id=payload["strategy_id"],
            rule=_parse_rule(payload["rule"], version=str(version)),
            rationale=payload.get("rationale", ""),
            rebalance=payload.get("rebalance", REBALANCE_DAILY),
            hold_days=payload.get("hold_days"),
        )

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "version": self.version,
            "strategy_id": self.strategy_id,
            "rebalance": self.rebalance,
            "rule": self.rule.to_dict(),
            "rationale": self.rationale,
        }
        if self.hold_days is not None:
            body["hold_days"] = self.hold_days
        return body


def iter_feature_refs(spec: StrategySpec) -> tuple[FeatureRef, ...]:
    """Return every governed feature reference in semantic rule order."""
    if not isinstance(spec, StrategySpec):
        raise TypeError("StrategySpec required")
    rule = spec.rule
    if isinstance(rule, ValueMomentumAgreeRule):
        return (rule.value_feature, rule.momentum_feature)
    return (rule.feature,)


def strategy_spec_digest(spec: StrategySpec) -> str:
    """Canonical digest for an exact StrategySpec body."""
    if not isinstance(spec, StrategySpec):
        raise TypeError("StrategySpec required")
    raw = json.dumps(
        spec.to_dict(),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


__all__ = [
    "CrossSectionRankRule",
    "FeatureRef",
    "REBALANCE_DAILY",
    "REBALANCE_FIXED_HORIZON",
    "STRATEGY_SPEC_VERSION",
    "STRATEGY_SPEC_VERSION_V2",
    "SUPPORTED_STRATEGY_SPEC_VERSIONS",
    "StrategySpec",
    "StrategySpecError",
    "ThresholdRule",
    "TopKRule",
    "ValueMomentumAgreeRule",
    "iter_feature_refs",
    "strategy_spec_digest",
]
