"""Narrow selection/comparison admission for engine artifacts.

This is not a new authority and does not rewrite historic files.

- Known AM + positive cap + old PM-resize identity is invalidated.
- Explicit ``max_gross_weight_limit: null`` on full engine metadata is uncapped.
- An AM summary that omits or malforms the cap is UNKNOWN/unproven, not proof
  that the run was uncapped or that cloud inventory was PM-resized.
"""

from __future__ import annotations

from typing import Any, Mapping

AM_SIGNAL_PM_CLOSE = "am_signal_pm_close"
FROZEN_AM_ORDER_BATCH_POLICY = "am_frozen_order_batch/v1"
PM_RESIZE_CORE_ENGINE_VERSIONS = frozenset({"0.8.0"})
AM_PM_GROSS_CAP_PM_RESIZE_REASON = "am_pm_gross_cap_pm_resize_engine_invalidated"
AM_GROSS_CAP_EVIDENCE_UNPROVEN_REASON = "am_gross_cap_evidence_unproven"


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


def _cap_field(block: Mapping[str, Any]) -> tuple[str, float | None]:
    """Return (absent|explicit_none|invalid|value, parsed cap)."""

    if "max_gross_weight_limit" in block:
        raw = block["max_gross_weight_limit"]
    elif "max_gross_weight" in block:
        raw = block["max_gross_weight"]
    else:
        return "absent", None
    if raw is None:
        return "explicit_none", None
    if type(raw) is bool:
        return "invalid", None
    try:
        cap = float(raw)
    except (TypeError, ValueError):
        return "invalid", None
    if cap != cap or cap in (float("inf"), float("-inf")) or not (cap > 0.0):
        return "invalid", None
    return "value", cap


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


def _is_full_engine_metadata(block: Mapping[str, Any]) -> bool:
    version = block.get("core_engine_version")
    return isinstance(version, str) and bool(version) and (
        "max_gross_weight_limit" in block
    )


def is_am_gross_cap_pm_resize_artifact(payload: Mapping[str, Any]) -> bool:
    """True only when AM+positive-cap evidence shows the old PM resizer."""

    if not isinstance(payload, Mapping):
        return False
    engine = _engine_metadata(payload)
    if _execution_mode(engine) != AM_SIGNAL_PM_CLOSE:
        return False
    sizing = _weight_sizing(engine)
    state, cap = _cap_field(engine)
    if state != "value" and "realized_pm_gross_capped" not in sizing:
        return False
    version = _engine_version(engine)
    if version in PM_RESIZE_CORE_ENGINE_VERSIONS:
        return True
    if "realized_pm_gross_capped" in sizing:
        return True
    return False


def admit_engine_artifact_for_selection(
    payload: Mapping[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    """Fail closed for PM-resized or unproven AM gross-cap evidence."""

    if not isinstance(payload, Mapping):
        return False, (AM_GROSS_CAP_EVIDENCE_UNPROVEN_REASON,)
    if is_am_gross_cap_pm_resize_artifact(payload):
        return False, (AM_PM_GROSS_CAP_PM_RESIZE_REASON,)
    engine = _engine_metadata(payload)
    if _execution_mode(engine) != AM_SIGNAL_PM_CLOSE:
        return True, ()
    state, cap = _cap_field(engine)
    if state == "explicit_none":
        if _is_full_engine_metadata(engine):
            return True, ()
        return False, (AM_GROSS_CAP_EVIDENCE_UNPROVEN_REASON,)
    if state == "value":
        policy = _order_batch_policy(engine)
        version = _engine_version(engine)
        if (
            policy == FROZEN_AM_ORDER_BATCH_POLICY
            and version
            and version not in PM_RESIZE_CORE_ENGINE_VERSIONS
        ):
            return True, ()
        return False, (AM_GROSS_CAP_EVIDENCE_UNPROVEN_REASON,)
    return False, (AM_GROSS_CAP_EVIDENCE_UNPROVEN_REASON,)


__all__ = [
    "AM_GROSS_CAP_EVIDENCE_UNPROVEN_REASON",
    "AM_PM_GROSS_CAP_PM_RESIZE_REASON",
    "FROZEN_AM_ORDER_BATCH_POLICY",
    "PM_RESIZE_CORE_ENGINE_VERSIONS",
    "admit_engine_artifact_for_selection",
    "is_am_gross_cap_pm_resize_artifact",
]
