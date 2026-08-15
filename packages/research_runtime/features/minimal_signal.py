"""Minimal COMPLETE-21 tip signal (W52 / w0815as_g2 · T5; W53 primary promote).

One research signal built from the strongest tip-ready COMPLETE-21 min
features. Prefer approved legs when available:

* primary: ``sign(topix_relative_1d)``  →  +1 / 0 / −1  (**approved** · W53)
* filter:  ``is_trading_day == 1.0`` (non-trading → signal None) (**approved**)
* optional gate: ``volume_change_1d`` absolute threshold (**approved**)

``candidate_only=False`` after W53 primary promotion. Signal status remains
``candidate`` (not READY / not strategy-default / Mass OFF).

Hard constraints (T7):

* does **not** import ``agents.mass_research`` / mass loop
* does **not** mint READY / VerifiedResearchReadiness
* does **not** emit order intents / call paper execution

This module is pure compute over already-materialized feature values.
CF tip extraction and R2 write live in ``research.single_shot_job``.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# ---------------------------------------------------------------------------
# Identity (stable for R2 signal artifacts)
# ---------------------------------------------------------------------------

SIGNAL_ID: str = "c21_topix_relative_sign"
SIGNAL_VERSION: str = "1.0.0"
SIGNAL_STATUS: str = "candidate"  # not READY; not strategy-default
# Primary + filter + gate are all registry-approved after W53 (still no READY).
CANDIDATE_ONLY: bool = False

# Feature ids this signal consumes (all approved after W53 primary promote).
PRIMARY_FEATURE_ID: str = "topix_relative_1d"  # approved (W53)
FILTER_FEATURE_ID: str = "is_trading_day"  # approved (W52 G1)
GATE_FEATURE_ID: str = "volume_change_1d"  # approved (W52 G1)

# Registry status pins at signal-definition time (documentation; not a gate).
FEATURE_STATUS_PINS: dict[str, str] = {
    PRIMARY_FEATURE_ID: "approved",
    FILTER_FEATURE_ID: "approved",
    GATE_FEATURE_ID: "approved",
}

DEFAULT_FEATURE_IDS: tuple[str, ...] = (
    PRIMARY_FEATURE_ID,
    FILTER_FEATURE_ID,
    GATE_FEATURE_ID,
)

# Datasets sufficient for the three features (COMPLETE 21 subset).
DEFAULT_SIGNAL_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "markets_calendar",
    "indices_bars_daily_topix",
)

# Optional |volume_change_1d| gate. None = no volume gate (sign-only).
DEFAULT_VOLUME_CHANGE_ABS_MIN: float | None = None

# Freeze surface (must never arm).
MASS_RESEARCH: str = "NO-GO"
PHASE7: str = "OFF"
READY_DECLARED: bool = False
ORDER_EXECUTION: bool = False


def sign_from_topix_relative(topix_relative: float | None) -> float | None:
    """Map relative return to discrete signal: +1 / 0 / −1, or None if missing."""
    if topix_relative is None:
        return None
    try:
        v = float(topix_relative)
    except (TypeError, ValueError):
        return None
    if v > 0:
        return 1.0
    if v < 0:
        return -1.0
    return 0.0


def apply_trading_day_filter(
    signal_value: float | None,
    is_trading_day: float | None,
) -> tuple[float | None, dict[str, Any]]:
    """Zero out / null signal when calendar says non-trading or missing."""
    if is_trading_day is None:
        return None, {
            "filter": FILTER_FEATURE_ID,
            "passed": False,
            "reason": "is_trading_day missing",
        }
    try:
        td = float(is_trading_day)
    except (TypeError, ValueError):
        return None, {
            "filter": FILTER_FEATURE_ID,
            "passed": False,
            "reason": "is_trading_day not numeric",
            "raw": is_trading_day,
        }
    if td != 1.0:
        return None, {
            "filter": FILTER_FEATURE_ID,
            "passed": False,
            "reason": "non_trading_day",
            "is_trading_day": td,
        }
    return signal_value, {
        "filter": FILTER_FEATURE_ID,
        "passed": True,
        "is_trading_day": td,
    }


def apply_volume_change_gate(
    signal_value: float | None,
    volume_change: float | None,
    *,
    abs_min: float | None,
) -> tuple[float | None, dict[str, Any]]:
    """Optional |volume_change| threshold; None abs_min disables the gate."""
    if abs_min is None:
        return signal_value, {
            "gate": GATE_FEATURE_ID,
            "enabled": False,
            "passed": True,
        }
    if volume_change is None:
        return None, {
            "gate": GATE_FEATURE_ID,
            "enabled": True,
            "passed": False,
            "reason": "volume_change missing",
            "abs_min": abs_min,
        }
    try:
        vc = float(volume_change)
    except (TypeError, ValueError):
        return None, {
            "gate": GATE_FEATURE_ID,
            "enabled": True,
            "passed": False,
            "reason": "volume_change not numeric",
            "abs_min": abs_min,
        }
    if abs(vc) < float(abs_min):
        return None, {
            "gate": GATE_FEATURE_ID,
            "enabled": True,
            "passed": False,
            "reason": "below_abs_min",
            "volume_change": vc,
            "abs_min": abs_min,
        }
    return signal_value, {
        "gate": GATE_FEATURE_ID,
        "enabled": True,
        "passed": True,
        "volume_change": vc,
        "abs_min": abs_min,
    }


def compute_topix_relative_sign_signal(
    *,
    topix_relative: float | None,
    is_trading_day: float | None = 1.0,
    volume_change: float | None = None,
    volume_change_abs_min: float | None = DEFAULT_VOLUME_CHANGE_ABS_MIN,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute one minimal signal observation (no orders, no READY, no mass).

    Returns a JSON-serializable observation dict with ``value`` and metadata.
    """
    raw_sign = sign_from_topix_relative(topix_relative)
    filtered, filter_meta = apply_trading_day_filter(raw_sign, is_trading_day)
    gated, gate_meta = apply_volume_change_gate(
        filtered, volume_change, abs_min=volume_change_abs_min
    )

    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "primary_feature_id": PRIMARY_FEATURE_ID,
        "filter_feature_id": FILTER_FEATURE_ID,
        "gate_feature_id": GATE_FEATURE_ID,
        "topix_relative": topix_relative,
        "raw_sign": raw_sign,
        "filter": filter_meta,
        "gate": gate_meta,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "order_execution": ORDER_EXECUTION,
        "note": (
            "Minimal tip signal from COMPLETE-21 candidate features. "
            "Not READY. Not mass research. No order execution."
        ),
    }
    if code is not None:
        meta["code"] = str(code)
    if date is not None:
        meta["date"] = str(date)[:10]
    if as_of is not None:
        meta["as_of"] = str(as_of)
    if extra_meta:
        meta.update(dict(extra_meta))

    return {
        "signal_id": SIGNAL_ID,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "value": gated,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "metadata": meta,
    }


def compute_signal_from_feature_observations(
    observations: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
    volume_change_abs_min: float | None = DEFAULT_VOLUME_CHANGE_ABS_MIN,
    codes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Join tip feature observations into minimal signal values per code.

    Expects feature observation records shaped like single_shot tip compute
    output: ``{feature_id, value, metadata: {code?, date?, ...}}``.
    """
    as_of_s = str(as_of).strip()
    code_filter = {str(c).strip() for c in codes} if codes else None

    # Index feature values by (feature_id, code) and calendar by date.
    by_code_feature: dict[str, dict[str, Any]] = {}
    trading_by_date: dict[str, Any] = {}
    trading_as_of: Any = None

    for obs in observations:
        fid = str(obs.get("feature_id") or "")
        md = obs.get("metadata") if isinstance(obs.get("metadata"), Mapping) else {}
        value = obs.get("value")
        if fid == FILTER_FEATURE_ID:
            d = md.get("date") or (str(as_of_s)[:10])
            trading_by_date[str(d)[:10]] = value
            if str(d)[:10] == str(as_of_s)[:10]:
                trading_as_of = value
            continue
        code = md.get("code")
        if code is None:
            continue
        code_s = str(code)
        if code_filter is not None and code_s not in code_filter:
            continue
        by_code_feature.setdefault(code_s, {})[fid] = value

    # Prefer as_of calendar day; fall back to any known trading-day flag.
    default_td = trading_as_of
    if default_td is None and trading_by_date:
        # Prefer the latest date's flag.
        last_d = sorted(trading_by_date.keys())[-1]
        default_td = trading_by_date[last_d]

    signal_obs: list[dict[str, Any]] = []
    for code in sorted(by_code_feature.keys()):
        feats = by_code_feature[code]
        rec = compute_topix_relative_sign_signal(
            topix_relative=feats.get(PRIMARY_FEATURE_ID),
            is_trading_day=default_td if default_td is not None else feats.get(FILTER_FEATURE_ID),
            volume_change=feats.get(GATE_FEATURE_ID),
            volume_change_abs_min=volume_change_abs_min,
            code=code,
            date=str(as_of_s)[:10],
            as_of=as_of_s,
        )
        signal_obs.append(rec)

    values = [r.get("value") for r in signal_obs]
    non_null = sum(1 for v in values if v is not None)
    null_n = sum(1 for v in values if v is None)
    long_n = sum(1 for v in values if v == 1.0)
    short_n = sum(1 for v in values if v == -1.0)
    flat_n = sum(1 for v in values if v == 0.0)

    return {
        "version": "minimal-signal/v1",
        "signal_id": SIGNAL_ID,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "as_of": as_of_s,
        "feature_ids": list(DEFAULT_FEATURE_IDS),
        "volume_change_abs_min": volume_change_abs_min,
        "codes": sorted(by_code_feature.keys()),
        "row_counts": {
            "computed": len(values),
            "non_null": non_null,
            "null": null_n,
            "long": long_n,
            "short": short_n,
            "flat": flat_n,
        },
        "null_counts": null_n,
        "observations": signal_obs,
        "sample_values": [
            {
                "code": r.get("code"),
                "value": r.get("value"),
                "topix_relative": (r.get("metadata") or {}).get("topix_relative"),
            }
            for r in signal_obs[:10]
        ],
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "order_execution": ORDER_EXECUTION,
        "local_sot": False,
        "note": (
            "COMPLETE-21 minimal tip signal (legs approved; signal status candidate). "
            "Not READY. Not mass research. No order execution."
        ),
    }


def signal_definition() -> dict[str, Any]:
    """Declarative signal metadata for manifests / proofs."""
    return {
        "signal_id": SIGNAL_ID,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "primary_feature_id": PRIMARY_FEATURE_ID,
        "filter_feature_id": FILTER_FEATURE_ID,
        "gate_feature_id": GATE_FEATURE_ID,
        "feature_ids": list(DEFAULT_FEATURE_IDS),
        "feature_status_pins": dict(FEATURE_STATUS_PINS),
        "datasets": list(DEFAULT_SIGNAL_DATASETS),
        "formula": (
            "value = sign(topix_relative_1d) "
            "if is_trading_day==1 "
            "and (volume_change_abs_min is None or |volume_change_1d| >= abs_min); "
            "else None"
        ),
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "order_execution": ORDER_EXECUTION,
        "note": (
            "candidate_only=False after W53 primary topix_relative_1d promote; "
            "all three legs approved (v1.0.0). Signal status remains candidate "
            "(not READY / Mass OFF / no orders)."
        ),
    }


__all__ = [
    "CANDIDATE_ONLY",
    "DEFAULT_FEATURE_IDS",
    "DEFAULT_SIGNAL_DATASETS",
    "DEFAULT_VOLUME_CHANGE_ABS_MIN",
    "FEATURE_STATUS_PINS",
    "FILTER_FEATURE_ID",
    "GATE_FEATURE_ID",
    "MASS_RESEARCH",
    "ORDER_EXECUTION",
    "PHASE7",
    "PRIMARY_FEATURE_ID",
    "READY_DECLARED",
    "SIGNAL_ID",
    "SIGNAL_STATUS",
    "SIGNAL_VERSION",
    "apply_trading_day_filter",
    "apply_volume_change_gate",
    "compute_signal_from_feature_observations",
    "compute_topix_relative_sign_signal",
    "sign_from_topix_relative",
    "signal_definition",
]
