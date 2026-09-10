"""Narrow selection/comparison admission for engine artifacts.

This is not a new authority and does not rewrite historic files. It rejects
AM+gross-cap artifacts whose engine identity still includes the PM quantity
resizer (core 0.8.0 and any AM+cap payload that cannot prove the frozen
morning-batch policy). Cloud inventory enumeration is a separate pending
operation.
"""

from __future__ import annotations

from typing import Any, Mapping

AM_SIGNAL_PM_CLOSE = "am_signal_pm_close"
FROZEN_AM_ORDER_BATCH_POLICY = "am_frozen_order_batch/v1"
PM_RESIZE_CORE_ENGINE_VERSIONS = frozenset({"0.8.0"})
AM_PM_GROSS_CAP_PM_RESIZE_REASON = "am_pm_gross_cap_pm_resize_engine_invalidated"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_present(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
        quality = _mapping(payload.get("data_quality"))
        if key in quality and quality[key] is not None:
            return quality[key]
        metadata = _mapping(payload.get("metadata"))
        if key in metadata and metadata[key] is not None:
            return metadata[key]
        reproduction = _mapping(payload.get("reproducibility"))
        if key in reproduction and reproduction[key] is not None:
            return reproduction[key]
        provenance = _mapping(
            metadata.get("price_basis_provenance")
            or reproduction.get("price_basis_provenance")
        )
        if key in provenance and provenance[key] is not None:
            return provenance[key]
    return None


def _execution_mode(payload: Mapping[str, Any]) -> str:
    return str(_first_present(payload, "execution_mode") or "")


def _engine_version(payload: Mapping[str, Any]) -> str:
    runtime = _mapping(_first_present(payload, "runtime_versions"))
    version = runtime.get("core_engine") or _first_present(
        payload, "core_engine_version", "core_engine"
    )
    return "" if version is None else str(version)


def _gross_cap(payload: Mapping[str, Any]) -> float | None:
    raw = _first_present(
        payload,
        "max_gross_weight_limit",
        "max_gross_weight",
    )
    if raw is None:
        return None
    try:
        cap = float(raw)
    except (TypeError, ValueError):
        return None
    if not (cap > 0.0):
        return None
    return cap


def _weight_sizing(payload: Mapping[str, Any]) -> str:
    return str(
        _first_present(payload, "weight_sizing_rule", "weight_sizing") or ""
    )


def _order_batch_policy(payload: Mapping[str, Any]) -> str:
    return str(_first_present(payload, "am_order_batch_policy") or "")


def is_am_gross_cap_pm_resize_artifact(payload: Mapping[str, Any]) -> bool:
    """True when an AM+gross-cap artifact cannot prove frozen-AM-batch semantics."""

    if not isinstance(payload, Mapping):
        return False
    if _execution_mode(payload) != AM_SIGNAL_PM_CLOSE:
        return False
    sizing = _weight_sizing(payload)
    cap = _gross_cap(payload)
    if cap is None and "realized_pm_gross_capped" not in sizing:
        return False
    version = _engine_version(payload)
    policy = _order_batch_policy(payload)
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
