"""Closed, declarative schema for agent-proposed strategies.

Only the rule types defined here are executable.  The parser rejects unknown
keys as well as unknown rule types, so a memo or model response cannot smuggle
Python source, database arguments, or an unreviewed execution primitive into
the trusted paper runtime.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


STRATEGY_SPEC_VERSION = "strategy-spec/v2"
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
        try:
            threshold = float(self.threshold)
        except (TypeError, ValueError) as exc:
            raise StrategySpecError("threshold must be numeric") from exc
        if not math.isfinite(threshold):
            raise StrategySpecError("threshold must be finite")
        object.__setattr__(self, "threshold", threshold)

    @property
    def feature_id(self) -> str:
        """Compatibility read for metadata consumers; never loses the pin."""
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
            try:
                min_score = float(self.min_score)
            except (TypeError, ValueError) as exc:
                raise StrategySpecError("top_k.min_score must be numeric") from exc
            if not math.isfinite(min_score):
                raise StrategySpecError("top_k.min_score must be finite")
            object.__setattr__(self, "min_score", min_score)

    @property
    def feature_id(self) -> str:
        """Compatibility read for metadata consumers; never loses the pin."""
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


Rule = ThresholdRule | TopKRule


def _parse_rule(payload: Any) -> Rule:
    if not isinstance(payload, Mapping):
        raise StrategySpecError("rule must be an object")
    rule_type = payload.get("type")
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
    raise StrategySpecError(
        f"unknown rule type {rule_type!r}; allowed: ['threshold', 'top_k']"
    )


@dataclass(frozen=True)
class StrategySpec:
    """A complete, versioned, daily-rebalanced paper strategy declaration."""

    strategy_id: str
    rule: Rule
    rationale: str = ""
    version: str = STRATEGY_SPEC_VERSION
    rebalance: str = "daily"

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_id", _identifier(self.strategy_id, "strategy_id"))
        if self.version != STRATEGY_SPEC_VERSION:
            raise StrategySpecError(
                f"unsupported StrategySpec version {self.version!r}; "
                f"expected {STRATEGY_SPEC_VERSION!r}"
            )
        if self.rebalance != "daily":
            raise StrategySpecError("only daily rebalancing is supported")
        if not isinstance(self.rule, (ThresholdRule, TopKRule)):
            raise StrategySpecError("rule must be a whitelisted StrategySpec rule")
        if not isinstance(self.rationale, str):
            raise StrategySpecError("rationale must be a string")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StrategySpec":
        if not isinstance(payload, Mapping):
            raise StrategySpecError("StrategySpec must be an object")
        _strict_keys(
            payload,
            {"version", "strategy_id", "rule", "rationale", "rebalance"},
            "StrategySpec",
        )
        missing = {"strategy_id", "rule"} - set(payload)
        if missing:
            raise StrategySpecError(f"StrategySpec missing field(s): {sorted(missing)}")
        version = payload.get("version", STRATEGY_SPEC_VERSION)
        if version != STRATEGY_SPEC_VERSION:
            raise StrategySpecError(
                f"unsupported StrategySpec version {version!r}; "
                f"expected {STRATEGY_SPEC_VERSION!r}"
            )
        return cls(
            version=version,
            strategy_id=payload["strategy_id"],
            rule=_parse_rule(payload["rule"]),
            rationale=payload.get("rationale", ""),
            rebalance=payload.get("rebalance", "daily"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "strategy_id": self.strategy_id,
            "rebalance": self.rebalance,
            "rule": self.rule.to_dict(),
            "rationale": self.rationale,
        }
