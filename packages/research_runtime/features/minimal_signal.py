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

from features.research_freezes import (
    MASS_RESEARCH,
    ORDER_EXECUTION,
    PHASE7,
    READY_DECLARED,
)

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


# ---------------------------------------------------------------------------
# Multi-signal research catalog (W58 / w0815ay_g2 · T4)
# All legs registry-approved. Signal status remains candidate.
# ---------------------------------------------------------------------------

# S2 defaults: |volume_change_1d| >= 10% to emit sign(volume_change).
DEFAULT_VOLUME_SIGN_ABS_MIN: float = 0.10

# S3 secondary filter feature (disclosure binary; margin is documented alt).
DISCLOSURE_FEATURE_ID: str = "disclosure_flag_fins"
MARGIN_CHANGE_FEATURE_ID: str = "margin_interest_change_1d"

MULTI_SIGNAL_FEATURE_IDS: tuple[str, ...] = (
    "topix_relative_1d",
    "is_trading_day",
    "volume_change_1d",
    DISCLOSURE_FEATURE_ID,
    MARGIN_CHANGE_FEATURE_ID,
)

MULTI_SIGNAL_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "markets_calendar",
    "indices_bars_daily_topix",
    "fins_summary",
    "markets_margin_interest",
)

# Research signal ids (candidate; not READY).
SIGNAL_ID_TOPIX_REL: str = SIGNAL_ID  # c21_topix_relative_sign
SIGNAL_ID_VOLUME_SIGN: str = "c21_volume_change_sign"
SIGNAL_ID_TOPIX_DISC: str = "c21_topix_rel_disclosure_filter"


def sign_from_numeric(x: float | None) -> float | None:
    """Map any numeric feature to discrete +1 / 0 / −1, or None if missing."""
    return sign_from_topix_relative(x)


def apply_disclosure_filter(
    signal_value: float | None,
    disclosure_flag: float | None,
    *,
    require_flag: float = 1.0,
) -> tuple[float | None, dict[str, Any]]:
    """Keep signal only when disclosure_flag_fins equals require_flag (default 1.0)."""
    if disclosure_flag is None:
        return None, {
            "filter": DISCLOSURE_FEATURE_ID,
            "passed": False,
            "reason": "disclosure_flag missing",
        }
    try:
        flag = float(disclosure_flag)
    except (TypeError, ValueError):
        return None, {
            "filter": DISCLOSURE_FEATURE_ID,
            "passed": False,
            "reason": "disclosure_flag not numeric",
            "raw": disclosure_flag,
        }
    if flag != float(require_flag):
        return None, {
            "filter": DISCLOSURE_FEATURE_ID,
            "passed": False,
            "reason": "disclosure_flag_not_set",
            "disclosure_flag": flag,
            "require_flag": require_flag,
        }
    return signal_value, {
        "filter": DISCLOSURE_FEATURE_ID,
        "passed": True,
        "disclosure_flag": flag,
        "require_flag": require_flag,
    }


def _index_feature_observations(
    observations: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
    codes: Sequence[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], Any]:
    """Index tip feature obs by code → feature_id, plus trading-day default."""
    as_of_s = str(as_of).strip()
    code_filter = {str(c).strip() for c in codes} if codes else None
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

    default_td = trading_as_of
    if default_td is None and trading_by_date:
        last_d = sorted(trading_by_date.keys())[-1]
        default_td = trading_by_date[last_d]
    return by_code_feature, default_td


def _signal_row_envelope(
    *,
    signal_id: str,
    value: float | None,
    code: str,
    date: str,
    as_of: str,
    candidate_only: bool,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": candidate_only,
        "value": value,
        "code": code,
        "date": date,
        "as_of": as_of,
        "metadata": dict(metadata),
    }


def _aggregate_signal_obs(
    signal_obs: Sequence[Mapping[str, Any]],
    *,
    signal_id: str,
    as_of: str,
    feature_ids: Sequence[str],
    volume_change_abs_min: float | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    values = [r.get("value") for r in signal_obs]
    non_null = sum(1 for v in values if v is not None)
    null_n = sum(1 for v in values if v is None)
    long_n = sum(1 for v in values if v == 1.0)
    short_n = sum(1 for v in values if v == -1.0)
    flat_n = sum(1 for v in values if v == 0.0)
    body: dict[str, Any] = {
        "version": "minimal-signal/v1",
        "signal_id": signal_id,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": False,
        "as_of": as_of,
        "feature_ids": list(feature_ids),
        "volume_change_abs_min": volume_change_abs_min,
        "codes": [r.get("code") for r in signal_obs],
        "row_counts": {
            "computed": len(values),
            "non_null": non_null,
            "null": null_n,
            "long": long_n,
            "short": short_n,
            "flat": flat_n,
        },
        "null_counts": null_n,
        "observations": list(signal_obs),
        "sample_values": [
            {
                "code": r.get("code"),
                "value": r.get("value"),
            }
            for r in list(signal_obs)[:10]
        ],
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "order_execution": ORDER_EXECUTION,
        "local_sot": False,
        "note": (
            "COMPLETE-21 multi-signal research observation (legs approved; "
            "signal status candidate). Not READY. Not mass research. No orders."
        ),
    }
    if extra:
        body.update(dict(extra))
    return body


def compute_volume_change_sign_signal(
    *,
    volume_change: float | None,
    is_trading_day: float | None = 1.0,
    volume_change_abs_min: float = DEFAULT_VOLUME_SIGN_ABS_MIN,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """S2: sign(volume_change_1d) when |volume_change| >= abs_min and trading day.

    Approved legs only. Research candidate signal — not READY.
    """
    raw_sign = sign_from_numeric(volume_change)
    filtered, filter_meta = apply_trading_day_filter(raw_sign, is_trading_day)
    # Abs threshold on the primary itself (not a separate gate feature).
    gated, gate_meta = apply_volume_change_gate(
        filtered, volume_change, abs_min=volume_change_abs_min
    )
    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_VOLUME_SIGN,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": False,
        "primary_feature_id": GATE_FEATURE_ID,
        "filter_feature_id": FILTER_FEATURE_ID,
        "gate_feature_id": GATE_FEATURE_ID,
        "volume_change": volume_change,
        "raw_sign": raw_sign,
        "filter": filter_meta,
        "gate": gate_meta,
        "volume_change_abs_min": volume_change_abs_min,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "order_execution": ORDER_EXECUTION,
        "note": (
            "Research signal: sign(volume_change_1d) with abs threshold. "
            "Not READY. Not mass research. No order execution."
        ),
    }
    if code is not None:
        meta["code"] = str(code)
    if date is not None:
        meta["date"] = str(date)[:10]
    if as_of is not None:
        meta["as_of"] = str(as_of)
    return _signal_row_envelope(
        signal_id=SIGNAL_ID_VOLUME_SIGN,
        value=gated,
        code=str(code) if code is not None else "",
        date=str(date)[:10] if date is not None else "",
        as_of=str(as_of) if as_of is not None else "",
        candidate_only=False,
        metadata=meta,
    )


def compute_topix_rel_disclosure_signal(
    *,
    topix_relative: float | None,
    is_trading_day: float | None = 1.0,
    disclosure_flag: float | None = None,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """S3: sign(topix_relative_1d) filtered by trading day + disclosure_flag==1.

    Approved legs only. Research candidate signal — not READY.
    """
    raw_sign = sign_from_topix_relative(topix_relative)
    filtered, filter_meta = apply_trading_day_filter(raw_sign, is_trading_day)
    disc_filtered, disc_meta = apply_disclosure_filter(filtered, disclosure_flag)
    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_TOPIX_DISC,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": False,
        "primary_feature_id": PRIMARY_FEATURE_ID,
        "filter_feature_id": FILTER_FEATURE_ID,
        "secondary_filter_feature_id": DISCLOSURE_FEATURE_ID,
        "topix_relative": topix_relative,
        "disclosure_flag": disclosure_flag,
        "raw_sign": raw_sign,
        "filter": filter_meta,
        "secondary_filter": disc_meta,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "order_execution": ORDER_EXECUTION,
        "note": (
            "Research signal: sign(topix_relative_1d) + disclosure_flag_fins==1. "
            "Not READY. Not mass research. No order execution."
        ),
    }
    if code is not None:
        meta["code"] = str(code)
    if date is not None:
        meta["date"] = str(date)[:10]
    if as_of is not None:
        meta["as_of"] = str(as_of)
    return _signal_row_envelope(
        signal_id=SIGNAL_ID_TOPIX_DISC,
        value=disc_filtered,
        code=str(code) if code is not None else "",
        date=str(date)[:10] if date is not None else "",
        as_of=str(as_of) if as_of is not None else "",
        candidate_only=False,
        metadata=meta,
    )


def compute_volume_sign_from_feature_observations(
    observations: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
    volume_change_abs_min: float = DEFAULT_VOLUME_SIGN_ABS_MIN,
    codes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Join tip features into S2 volume-change-sign signal per code."""
    as_of_s = str(as_of).strip()
    by_code, default_td = _index_feature_observations(
        observations, as_of=as_of_s, codes=codes
    )
    signal_obs: list[dict[str, Any]] = []
    for code in sorted(by_code.keys()):
        feats = by_code[code]
        rec = compute_volume_change_sign_signal(
            volume_change=feats.get(GATE_FEATURE_ID),
            is_trading_day=(
                default_td
                if default_td is not None
                else feats.get(FILTER_FEATURE_ID)
            ),
            volume_change_abs_min=volume_change_abs_min,
            code=code,
            date=str(as_of_s)[:10],
            as_of=as_of_s,
        )
        signal_obs.append(rec)
    return _aggregate_signal_obs(
        signal_obs,
        signal_id=SIGNAL_ID_VOLUME_SIGN,
        as_of=as_of_s,
        feature_ids=(GATE_FEATURE_ID, FILTER_FEATURE_ID),
        volume_change_abs_min=volume_change_abs_min,
        extra={
            "formula": (
                f"value = sign(volume_change_1d) if is_trading_day==1 "
                f"and |volume_change_1d| >= {volume_change_abs_min}; else None"
            ),
        },
    )


def compute_topix_disc_from_feature_observations(
    observations: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
    codes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Join tip features into S3 topix-relative + disclosure filter per code."""
    as_of_s = str(as_of).strip()
    by_code, default_td = _index_feature_observations(
        observations, as_of=as_of_s, codes=codes
    )
    signal_obs: list[dict[str, Any]] = []
    for code in sorted(by_code.keys()):
        feats = by_code[code]
        rec = compute_topix_rel_disclosure_signal(
            topix_relative=feats.get(PRIMARY_FEATURE_ID),
            is_trading_day=(
                default_td
                if default_td is not None
                else feats.get(FILTER_FEATURE_ID)
            ),
            disclosure_flag=feats.get(DISCLOSURE_FEATURE_ID),
            code=code,
            date=str(as_of_s)[:10],
            as_of=as_of_s,
        )
        signal_obs.append(rec)
    return _aggregate_signal_obs(
        signal_obs,
        signal_id=SIGNAL_ID_TOPIX_DISC,
        as_of=as_of_s,
        feature_ids=(PRIMARY_FEATURE_ID, FILTER_FEATURE_ID, DISCLOSURE_FEATURE_ID),
        extra={
            "formula": (
                "value = sign(topix_relative_1d) if is_trading_day==1 "
                "and disclosure_flag_fins==1; else None"
            ),
        },
    )


# ---------------------------------------------------------------------------
# W62 extra research hypotheses (not S1 rehash)
# S4: sign(margin_interest_change_1d)
# S5: sign(Δ short_ratio_level) for a fixed section (broadcast to codes)
# ---------------------------------------------------------------------------

SHORT_RATIO_FEATURE_ID: str = "short_ratio_level"
SIGNAL_ID_MARGIN_CHANGE: str = "c21_margin_change_sign"
SIGNAL_ID_SHORT_RATIO_DELTA: str = "c21_short_ratio_delta_sign"
DEFAULT_SHORT_RATIO_SECTION: str = "0050"  # research pin (TSE 33 sector code)

EXTRA_HYP_FEATURE_IDS: tuple[str, ...] = (
    "is_trading_day",
    MARGIN_CHANGE_FEATURE_ID,
    SHORT_RATIO_FEATURE_ID,
)

EXTRA_HYP_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "markets_calendar",
    "indices_bars_daily_topix",
    "markets_margin_interest",
    "markets_short_ratio",
)


def compute_margin_change_sign_signal(
    *,
    margin_change: float | None,
    is_trading_day: float | None = 1.0,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """S4 research: sign(margin_interest_change_1d) on trading days.

    Approved legs only. Candidate status — not READY.
    """
    raw_sign = sign_from_numeric(margin_change)
    filtered, filter_meta = apply_trading_day_filter(raw_sign, is_trading_day)
    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_MARGIN_CHANGE,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": False,
        "primary_feature_id": MARGIN_CHANGE_FEATURE_ID,
        "filter_feature_id": FILTER_FEATURE_ID,
        "margin_interest_change_1d": margin_change,
        "raw_sign": raw_sign,
        "filter": filter_meta,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "order_execution": ORDER_EXECUTION,
        "note": (
            "Research signal: sign(margin_interest_change_1d). "
            "Not READY. Not mass research. No order execution."
        ),
    }
    if code is not None:
        meta["code"] = str(code)
    if date is not None:
        meta["date"] = str(date)[:10]
    if as_of is not None:
        meta["as_of"] = str(as_of)
    return _signal_row_envelope(
        signal_id=SIGNAL_ID_MARGIN_CHANGE,
        value=filtered,
        code=str(code) if code is not None else "",
        date=str(date)[:10] if date is not None else "",
        as_of=str(as_of) if as_of is not None else "",
        candidate_only=False,
        metadata=meta,
    )


def compute_short_ratio_delta_sign_signal(
    *,
    short_ratio_level: float | None,
    prev_short_ratio_level: float | None,
    is_trading_day: float | None = 1.0,
    section: str | None = None,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """S5 research: sign(short_ratio_level − prev) on trading days.

    Sector-level Δ broadcast to each code (research convenience). Not READY.
    Missing prev or level → None (honest empty).
    """
    delta: float | None
    if short_ratio_level is None or prev_short_ratio_level is None:
        delta = None
    else:
        try:
            delta = float(short_ratio_level) - float(prev_short_ratio_level)
        except (TypeError, ValueError):
            delta = None
    raw_sign = sign_from_numeric(delta)
    filtered, filter_meta = apply_trading_day_filter(raw_sign, is_trading_day)
    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_SHORT_RATIO_DELTA,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": False,
        "primary_feature_id": SHORT_RATIO_FEATURE_ID,
        "filter_feature_id": FILTER_FEATURE_ID,
        "section": section,
        "short_ratio_level": short_ratio_level,
        "prev_short_ratio_level": prev_short_ratio_level,
        "delta": delta,
        "raw_sign": raw_sign,
        "filter": filter_meta,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "order_execution": ORDER_EXECUTION,
        "note": (
            "Research signal: sign(Δ short_ratio_level) for fixed section, "
            "broadcast per code. Not READY. Not mass. No orders."
        ),
    }
    if code is not None:
        meta["code"] = str(code)
    if date is not None:
        meta["date"] = str(date)[:10]
    if as_of is not None:
        meta["as_of"] = str(as_of)
    return _signal_row_envelope(
        signal_id=SIGNAL_ID_SHORT_RATIO_DELTA,
        value=filtered,
        code=str(code) if code is not None else "",
        date=str(date)[:10] if date is not None else "",
        as_of=str(as_of) if as_of is not None else "",
        candidate_only=False,
        metadata=meta,
    )


def compute_margin_sign_from_feature_observations(
    observations: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
    codes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Batch S4 from tip/R2 feature observations."""
    as_of_s = str(as_of).strip()
    by_code, default_td = _index_feature_observations(
        observations, as_of=as_of_s, codes=codes
    )
    code_list = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes
        else sorted(by_code.keys())
    )
    signal_obs: list[dict[str, Any]] = []
    for code in code_list:
        feats = by_code.get(code) or {}
        td = feats.get(FILTER_FEATURE_ID, default_td)
        rec = compute_margin_change_sign_signal(
            margin_change=feats.get(MARGIN_CHANGE_FEATURE_ID),
            is_trading_day=td,
            code=code,
            date=str(as_of_s)[:10],
            as_of=as_of_s,
        )
        signal_obs.append(rec)
    return _aggregate_signal_obs(
        signal_obs,
        signal_id=SIGNAL_ID_MARGIN_CHANGE,
        as_of=as_of_s,
        feature_ids=(MARGIN_CHANGE_FEATURE_ID, FILTER_FEATURE_ID),
        extra={
            "formula": (
                "value = sign(margin_interest_change_1d) if is_trading_day==1; "
                "else None"
            ),
        },
    )


def compute_short_delta_from_feature_observations(
    observations: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
    prev_short_ratio_level: float | None,
    codes: Sequence[str] | None = None,
    section: str = DEFAULT_SHORT_RATIO_SECTION,
) -> dict[str, Any]:
    """Batch S5: broadcast sector Δ short_ratio to each code."""
    as_of_s = str(as_of).strip()
    by_code, default_td = _index_feature_observations(
        observations, as_of=as_of_s, codes=codes
    )
    # short_ratio_level is section-keyed (metadata may omit code)
    level: float | None = None
    for obs in observations:
        if str(obs.get("feature_id") or "") != SHORT_RATIO_FEATURE_ID:
            continue
        v = obs.get("value")
        if v is not None:
            try:
                level = float(v)
            except (TypeError, ValueError):
                level = None
            break
    code_list = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes
        else sorted(by_code.keys()) or [""]
    )
    signal_obs: list[dict[str, Any]] = []
    for code in code_list:
        feats = by_code.get(code) or {}
        td = feats.get(FILTER_FEATURE_ID, default_td)
        rec = compute_short_ratio_delta_sign_signal(
            short_ratio_level=level,
            prev_short_ratio_level=prev_short_ratio_level,
            is_trading_day=td,
            section=section,
            code=code,
            date=str(as_of_s)[:10],
            as_of=as_of_s,
        )
        signal_obs.append(rec)
    return _aggregate_signal_obs(
        signal_obs,
        signal_id=SIGNAL_ID_SHORT_RATIO_DELTA,
        as_of=as_of_s,
        feature_ids=(SHORT_RATIO_FEATURE_ID, FILTER_FEATURE_ID),
        extra={
            "formula": (
                "value = sign(short_ratio_level - prev) if is_trading_day==1 "
                f"and section={section!r}; else None (broadcast to codes)"
            ),
            "section": section,
            "short_ratio_level": level,
            "prev_short_ratio_level": prev_short_ratio_level,
        },
    )


def extra_hyp_definitions(
    *,
    section: str = DEFAULT_SHORT_RATIO_SECTION,
) -> list[dict[str, Any]]:
    """Declarative catalog for W62 S4/S5 research hypotheses."""
    return [
        {
            "signal_id": SIGNAL_ID_MARGIN_CHANGE,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": False,
            "approved_legs_only": True,
            "primary_feature_id": MARGIN_CHANGE_FEATURE_ID,
            "filter_feature_id": FILTER_FEATURE_ID,
            "feature_status_pins": {
                MARGIN_CHANGE_FEATURE_ID: "approved",
                FILTER_FEATURE_ID: "approved",
            },
            "formula": (
                "value = sign(margin_interest_change_1d) if is_trading_day==1"
            ),
            "role": "margin_change_sign",
            "not_s1_rehash": True,
        },
        {
            "signal_id": SIGNAL_ID_SHORT_RATIO_DELTA,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": False,
            "approved_legs_only": True,
            "primary_feature_id": SHORT_RATIO_FEATURE_ID,
            "filter_feature_id": FILTER_FEATURE_ID,
            "section": section,
            "feature_status_pins": {
                SHORT_RATIO_FEATURE_ID: "approved",
                FILTER_FEATURE_ID: "approved",
            },
            "formula": (
                f"value = sign(Δ short_ratio_level[{section}]) "
                "if is_trading_day==1; broadcast to codes"
            ),
            "role": "short_ratio_delta_sign",
            "not_s1_rehash": True,
        },
    ]


def multi_signal_definitions(
    *,
    volume_sign_abs_min: float = DEFAULT_VOLUME_SIGN_ABS_MIN,
) -> list[dict[str, Any]]:
    """Declarative catalog for the three W58 research signals (T4)."""
    return [
        {
            "signal_id": SIGNAL_ID_TOPIX_REL,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": False,
            "approved_legs_only": True,
            "primary_feature_id": PRIMARY_FEATURE_ID,
            "filter_feature_id": FILTER_FEATURE_ID,
            "gate_feature_id": GATE_FEATURE_ID,
            "feature_ids": list(DEFAULT_FEATURE_IDS),
            "feature_status_pins": {
                PRIMARY_FEATURE_ID: "approved",
                FILTER_FEATURE_ID: "approved",
                GATE_FEATURE_ID: "approved",
            },
            "formula": (
                "value = sign(topix_relative_1d) if is_trading_day==1 "
                "(volume gate off by default)"
            ),
            "role": "baseline",
        },
        {
            "signal_id": SIGNAL_ID_VOLUME_SIGN,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": False,
            "approved_legs_only": True,
            "primary_feature_id": GATE_FEATURE_ID,
            "filter_feature_id": FILTER_FEATURE_ID,
            "gate_feature_id": GATE_FEATURE_ID,
            "feature_ids": [GATE_FEATURE_ID, FILTER_FEATURE_ID],
            "feature_status_pins": {
                GATE_FEATURE_ID: "approved",
                FILTER_FEATURE_ID: "approved",
            },
            "volume_change_abs_min": volume_sign_abs_min,
            "formula": (
                f"value = sign(volume_change_1d) if is_trading_day==1 "
                f"and |volume_change_1d| >= {volume_sign_abs_min}; else None"
            ),
            "role": "volume_sign_abs_threshold",
        },
        {
            "signal_id": SIGNAL_ID_TOPIX_DISC,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": False,
            "approved_legs_only": True,
            "primary_feature_id": PRIMARY_FEATURE_ID,
            "filter_feature_id": FILTER_FEATURE_ID,
            "secondary_filter_feature_id": DISCLOSURE_FEATURE_ID,
            "feature_ids": [
                PRIMARY_FEATURE_ID,
                FILTER_FEATURE_ID,
                DISCLOSURE_FEATURE_ID,
            ],
            "feature_status_pins": {
                PRIMARY_FEATURE_ID: "approved",
                FILTER_FEATURE_ID: "approved",
                DISCLOSURE_FEATURE_ID: "approved",
            },
            "formula": (
                "value = sign(topix_relative_1d) if is_trading_day==1 "
                "and disclosure_flag_fins==1; else None"
            ),
            "alt_filter_documented": (
                f"{MARGIN_CHANGE_FEATURE_ID} non-null filter "
                "(approved; not selected for primary S3 in this wave)"
            ),
            "role": "topix_rel_disclosure_filter",
        },
    ]


__all__ = [
    "CANDIDATE_ONLY",
    "DEFAULT_FEATURE_IDS",
    "DEFAULT_SHORT_RATIO_SECTION",
    "DEFAULT_SIGNAL_DATASETS",
    "DEFAULT_VOLUME_CHANGE_ABS_MIN",
    "DEFAULT_VOLUME_SIGN_ABS_MIN",
    "DISCLOSURE_FEATURE_ID",
    "EXTRA_HYP_DATASETS",
    "EXTRA_HYP_FEATURE_IDS",
    "FEATURE_STATUS_PINS",
    "FILTER_FEATURE_ID",
    "GATE_FEATURE_ID",
    "MARGIN_CHANGE_FEATURE_ID",
    "MASS_RESEARCH",
    "MULTI_SIGNAL_DATASETS",
    "MULTI_SIGNAL_FEATURE_IDS",
    "ORDER_EXECUTION",
    "PHASE7",
    "PRIMARY_FEATURE_ID",
    "READY_DECLARED",
    "SHORT_RATIO_FEATURE_ID",
    "SIGNAL_ID",
    "SIGNAL_ID_MARGIN_CHANGE",
    "SIGNAL_ID_SHORT_RATIO_DELTA",
    "SIGNAL_ID_TOPIX_DISC",
    "SIGNAL_ID_TOPIX_REL",
    "SIGNAL_ID_VOLUME_SIGN",
    "SIGNAL_STATUS",
    "SIGNAL_VERSION",
    "apply_disclosure_filter",
    "apply_trading_day_filter",
    "apply_volume_change_gate",
    "compute_margin_change_sign_signal",
    "compute_margin_sign_from_feature_observations",
    "compute_short_delta_from_feature_observations",
    "compute_short_ratio_delta_sign_signal",
    "compute_signal_from_feature_observations",
    "compute_topix_disc_from_feature_observations",
    "compute_topix_rel_disclosure_signal",
    "compute_topix_relative_sign_signal",
    "compute_volume_change_sign_signal",
    "compute_volume_sign_from_feature_observations",
    "extra_hyp_definitions",
    "multi_signal_definitions",
    "sign_from_numeric",
    "sign_from_topix_relative",
    "signal_definition",
]
