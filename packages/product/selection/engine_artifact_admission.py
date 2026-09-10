"""Narrow selection/comparison admission for engine artifacts.

This is not a new authority and does not rewrite historic files. It rejects
AM+gross-cap artifacts whose engine identity still includes the PM quantity
resizer (core 0.8.0 and any AM+cap payload that cannot prove the frozen
morning-batch policy). Cloud inventory enumeration is a separate pending
operation.

Supported identity shapes, in order:
1. ``PaperRunResult.to_dict()`` — engine fields live in ``backtest.metadata``
2. engine ``BacktestResult.metadata`` (or a wrapper with ``metadata`` that
   already is that block)
3. personal-service evidence/summary rows with the engine fields at the top
   level
"""

from __future__ import annotations

from typing import Any, Mapping

AM_SIGNAL_PM_CLOSE = "am_signal_pm_close"
FROZEN_AM_ORDER_BATCH_POLICY = "am_frozen_order_batch/v1"
PM_RESIZE_CORE_ENGINE_VERSIONS = frozenset({"0.8.0"})
AM_PM_GROSS_CAP_PM_RESIZE_REASON = "am_pm_gross_cap_pm_resize_engine_invalidated"


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _engine_metadata(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Read the actual engine metadata block; do not search nested fields."""

    backtest = _mapping(payload.get("backtest"))
    if backtest is not None:
        nested = _mapping(backtest.get("metadata"))
        if nested is not None:
            return nested
    wrapped = _mapping(payload.get("metadata"))
    if wrapped is not None and (
        "core_engine_version" in wrapped
        or "max_gross_weight_limit" in wrapped
        or "weight_sizing_rule" in wrapped
        or "am_order_batch_policy" in wrapped
    ):
        return wrapped
    return payload


def _text(block: Mapping[str, Any], key: str) -> str:
    value = block.get(key)
    return "" if value is None else str(value)


def _execution_mode(block: Mapping[str, Any]) -> str:
    return _text(block, "execution_mode")


def _engine_version(block: Mapping[str, Any]) -> str:
    return _text(block, "core_engine_version")


def _gross_cap(block: Mapping[str, Any]) -> float | None:
    raw = block.get("max_gross_weight_limit")
    if raw is None:
        raw = block.get("max_gross_weight")
    if raw is None:
        return None
    try:
        cap = float(raw)
    except (TypeError, ValueError):
        return None
    if not (cap > 0.0):
        return None
    return cap


def _weight_sizing(block: Mapping[str, Any]) -> str:
    rule = _text(block, "weight_sizing_rule")
    if rule:
        return rule
    provenance = _mapping(block.get("price_basis_provenance"))
    if provenance is None:
        return ""
    return _text(provenance, "weight_sizing")


def _order_batch_policy(block: Mapping[str, Any]) -> str:
    return _text(block, "am_order_batch_policy")


def is_am_gross_cap_pm_resize_artifact(payload: Mapping[str, Any]) -> bool:
    """True when an AM+gross-cap artifact cannot prove frozen-AM-batch semantics."""

    if not isinstance(payload, Mapping):
        return False
    engine = _engine_metadata(payload)
    if _execution_mode(engine) != AM_SIGNAL_PM_CLOSE:
        return False
    sizing = _weight_sizing(engine)
    cap = _gross_cap(engine)
    if cap is None and "realized_pm_gross_capped" not in sizing:
        return False
    version = _engine_version(engine)
    policy = _order_batch_policy(engine)
    if version in PM_RESIZE_CORE_ENGINE_VERSIONS:
        return True
    if "realized_pm_gross_capped" in sizing:
        return True
    if policy == FROZEN_AM_ORDER_BATCH_POLICY and version not in (
        PM_RESIZE_CORE_ENGINE_VERSIONS
    ):
        return False
    return True


def admit_engine_artifact_for_selection(
    payload: Mapping[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    """Fail closed for PM-resized AM+gross-cap engine artifacts."""

    if is_am_gross_cap_pm_resize_artifact(payload):
        return False, (AM_PM_GROSS_CAP_PM_RESIZE_REASON,)
    return True, ()


__all__ = [
    "AM_PM_GROSS_CAP_PM_RESIZE_REASON",
    "FROZEN_AM_ORDER_BATCH_POLICY",
    "PM_RESIZE_CORE_ENGINE_VERSIONS",
    "admit_engine_artifact_for_selection",
    "is_am_gross_cap_pm_resize_artifact",
]
