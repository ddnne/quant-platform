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


STRATEGY_SPEC_VERSION = "strategy-spec/v1"
_RESERVED_FEATURE_PARAMS = frozenset({"code", "as_of", "db_path"})


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
        raise StrategySpecError("rule.feature_params must be an object")
    params = dict(value)
    reserved = sorted(_RESERVED_FEATURE_PARAMS.intersection(params))
    if reserved:
        raise StrategySpecError(
            f"rule.feature_params may not set runtime-owned field(s): {reserved}"
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
class ThresholdRule:
    """Equal-weight every code whose approved feature is at least ``threshold``."""

    feature_id: str
    threshold: float
    feature_params: Mapping[str, Any] = field(default_factory=dict)
    type: str = field(default="threshold", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature_id", _identifier(self.feature_id, "feature_id"))
        try:
            threshold = float(self.threshold)
        except (TypeError, ValueError) as exc:
            raise StrategySpecError("threshold must be numeric") from exc
        if not math.isfinite(threshold):
            raise StrategySpecError("threshold must be finite")
        object.__setattr__(self, "threshold", threshold)
        object.__setattr__(self, "feature_params", _feature_params(self.feature_params))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "feature_id": self.feature_id,
            "threshold": self.threshold,
            "feature_params": dict(self.feature_params),
        }


@dataclass(frozen=True)
class TopKRule:
    """Equal-weight the highest-scoring ``k`` codes from an approved feature."""

    feature_id: str
    k: int
    min_score: float | None = None
    feature_params: Mapping[str, Any] = field(default_factory=dict)
    type: str = field(default="top_k", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature_id", _identifier(self.feature_id, "feature_id"))
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
        object.__setattr__(self, "feature_params", _feature_params(self.feature_params))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "feature_id": self.feature_id,
            "k": self.k,
            "min_score": self.min_score,
            "feature_params": dict(self.feature_params),
        }


Rule = ThresholdRule | TopKRule


def _parse_rule(payload: Any) -> Rule:
    if not isinstance(payload, Mapping):
        raise StrategySpecError("rule must be an object")
    rule_type = payload.get("type")
    if rule_type == "threshold":
        _strict_keys(
            payload,
            {"type", "feature_id", "threshold", "feature_params"},
            "threshold rule",
        )
        required = {"feature_id", "threshold"} - set(payload)
        if required:
            raise StrategySpecError(f"threshold rule missing field(s): {sorted(required)}")
        return ThresholdRule(
            feature_id=payload["feature_id"],
            threshold=payload["threshold"],
            feature_params=payload.get("feature_params", {}),
        )
    if rule_type == "top_k":
        _strict_keys(
            payload,
            {"type", "feature_id", "k", "min_score", "feature_params"},
            "top_k rule",
        )
        required = {"feature_id", "k"} - set(payload)
        if required:
            raise StrategySpecError(f"top_k rule missing field(s): {sorted(required)}")
        return TopKRule(
            feature_id=payload["feature_id"],
            k=payload["k"],
            min_score=payload.get("min_score"),
            feature_params=payload.get("feature_params", {}),
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
        return cls(
            version=payload.get("version", STRATEGY_SPEC_VERSION),
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
