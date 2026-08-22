"""Minimal-signal registry (identity, pins, catalog dumps).

Declarative manifests for COMPLETE-21 tip signals S1–S5. Value compute lives
in ``minimal_signal``. This module does not evaluate feature observations.

Mass / READY / GO closed. No S1–S5 un-reject. Signal status remains candidate.
"""

from __future__ import annotations

from typing import Any

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


def _freeze_meta() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "order_execution": ORDER_EXECUTION,
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
        **_freeze_meta(),
        "note": (
            "candidate_only=False after W53 primary topix_relative_1d promote; "
            "all three legs approved (v1.0.0). Signal status remains candidate "
            "(not READY / Mass OFF / no orders)."
        ),
    }


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
