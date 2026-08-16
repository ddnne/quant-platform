"""Hypothesis-class research signals (W78 / w0816m) — not simple daily sign.

Implements real signal logic for:

* ``multi_day_hold`` — N-day momentum entry with sticky multi-day hold
  (rebalance every ``hold_days``; not 1d flip)
* ``macro_conditioned`` — equity momentum / relative conditioned on Tokyo
  repo rate **level** or **change** from ``jsda_tokyo_repo_rates``

Hard constraints
----------------
* Does **not** import ``agents.mass_research`` / mass loop
* Does **not** mint READY / VerifiedResearchReadiness
* Does **not** emit order intents / call paper execution
* Does **not** un-reject S1–S5
* ``simple_daily_sign`` is **not** used

Status remains ``candidate`` (research). Pass ≠ READY / Mass / GO.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# ---------------------------------------------------------------------------
# Identity / freeze
# ---------------------------------------------------------------------------

CLASS_SIGNALS_VERSION: str = "class-signals/v1"
CLASS_SIGNALS_WAVE: str = "W78 / w0816m"

SIGNAL_STATUS: str = "candidate"
SIGNAL_VERSION: str = "1.0.0"
CANDIDATE_ONLY: bool = False  # legs may be approved; signal status stays candidate

MASS_RESEARCH: str = "NO-GO"
PHASE7: str = "OFF"
READY_DECLARED: bool = False
ORDER_EXECUTION: bool = False
S1_S5_UNREJECT: bool = False
SIMPLE_DAILY_SIGN: bool = False

# ---------------------------------------------------------------------------
# Class ids (align with research.hypothesis_classes)
# ---------------------------------------------------------------------------

CLASS_MULTI_DAY_HOLD: str = "multi_day_hold"
CLASS_MACRO_CONDITIONED: str = "macro_conditioned"
CLASS_CROSS_SECTION_RELATIVE: str = "cross_section_relative"

# Signal ids (stable R2 / catalog keys)
SIGNAL_ID_MULTI_DAY_HOLD: str = "c21_multi_day_momentum_hold"
SIGNAL_ID_MACRO_CONDITIONED: str = "c21_repo_conditioned_momentum"
SIGNAL_ID_CROSS_SECTION: str = "c21_cross_section_momentum_rank"

# Feature legs (prefer registry-approved)
MOMENTUM_FEATURE_ID: str = "momentum_n"
TRADING_DAY_FEATURE_ID: str = "is_trading_day"
TOPIX_REL_FEATURE_ID: str = "topix_relative_1d"
REPO_RATE_FEATURE_ID: str = "repo_rate_level"
REPO_CHANGE_FEATURE_ID: str = "repo_rate_change"

DEFAULT_HOLD_DAYS: int = 5
SUPPORTED_HOLD_DAYS: tuple[int, ...] = (5, 10, 20)
DEFAULT_MOMENTUM_N: int = 5  # match hold horizon default

# Macro regime defaults (research placeholders; disclose when overridden)
# Repo rates in local JSDA are percent-like (e.g. 0.1 = 0.1%).
DEFAULT_REPO_HIGH_THRESHOLD: float = 0.05  # level above → high
DEFAULT_REPO_LOW_THRESHOLD: float = 0.0  # level below → low
DEFAULT_REPO_CHANGE_EPS: float = 1e-6

MULTI_DAY_HOLD_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "markets_calendar",
    "indices_bars_daily_topix",
)
MACRO_CONDITIONED_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "markets_calendar",
    "indices_bars_daily_topix",
    "jsda_tokyo_repo_rates",
)
CROSS_SECTION_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "markets_calendar",
    "indices_bars_daily_topix",
)


def _freeze_meta() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "order_execution": ORDER_EXECUTION,
        "s1_s5_unreject": S1_S5_UNREJECT,
        "simple_daily_sign": SIMPLE_DAILY_SIGN,
        "class_signals_version": CLASS_SIGNALS_VERSION,
        "wave": CLASS_SIGNALS_WAVE,
    }


def sign_from_numeric(x: float | None) -> float | None:
    """Map numeric → +1 / 0 / −1, or None if missing."""
    if x is None:
        return None
    try:
        v = float(x)
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
    """Null signal on non-trading / missing calendar."""
    if is_trading_day is None:
        return None, {
            "filter": TRADING_DAY_FEATURE_ID,
            "passed": False,
            "reason": "is_trading_day missing",
        }
    try:
        td = float(is_trading_day)
    except (TypeError, ValueError):
        return None, {
            "filter": TRADING_DAY_FEATURE_ID,
            "passed": False,
            "reason": "is_trading_day not numeric",
            "raw": is_trading_day,
        }
    if td != 1.0:
        return None, {
            "filter": TRADING_DAY_FEATURE_ID,
            "passed": False,
            "reason": "non_trading_day",
            "is_trading_day": td,
        }
    return signal_value, {
        "filter": TRADING_DAY_FEATURE_ID,
        "passed": True,
        "is_trading_day": td,
    }


# ---------------------------------------------------------------------------
# multi_day_hold — sticky hold logic (not 1d sign flip)
# ---------------------------------------------------------------------------


def apply_sticky_hold(
    daily_entry_signs: Sequence[Any],
    *,
    hold_days: int = DEFAULT_HOLD_DAYS,
    rebalance_mode: str = "fixed_horizon",
) -> list[float | None]:
    """Convert daily entry signs into multi-day held positions.

    Parameters
    ----------
    daily_entry_signs:
        Chronological sequence of entry signs (+1/0/−1/None) — typically
        ``sign(momentum_n)`` each day.
    hold_days:
        Hold horizon in sessions (5 / 10 / 20). Must be >= 1.
    rebalance_mode:
        * ``fixed_horizon`` — rebalance every ``hold_days`` sessions only
          (position constant between rebalance days).
        * ``min_hold`` — allow rebalance on sign change only after
          ``hold_days`` sessions held (sticky min-hold).

    Returns
    -------
    list of held position signs (same length). None days stay flat/missing
    until a valid rebalance entry exists.
    """
    h = int(hold_days)
    if h < 1:
        raise ValueError(f"hold_days must be >= 1, got {hold_days!r}")
    mode = str(rebalance_mode or "fixed_horizon").strip().lower()
    if mode not in ("fixed_horizon", "min_hold"):
        raise ValueError(
            f"rebalance_mode must be fixed_horizon|min_hold, got {rebalance_mode!r}"
        )

    n = len(daily_entry_signs)
    out: list[float | None] = [None] * n
    if n == 0:
        return out

    held: float | None = None
    held_for = 0
    days_since_rebalance = 0

    for i, raw in enumerate(daily_entry_signs):
        entry = sign_from_numeric(raw if raw is not None else None)
        # Treat flat 0 as "no entry" for sticky hold (do not force flat mid-hold
        # under fixed_horizon — keep prior held).
        if mode == "fixed_horizon":
            if i == 0 or days_since_rebalance >= h:
                if entry is not None and entry != 0.0:
                    held = entry
                elif entry == 0.0:
                    held = 0.0
                # if entry is None, keep prior held (or None)
                days_since_rebalance = 1
            else:
                days_since_rebalance += 1
            out[i] = held
        else:  # min_hold
            if held is None:
                if entry is not None and entry != 0.0:
                    held = entry
                    held_for = 1
                elif entry == 0.0:
                    held = 0.0
                    held_for = 1
                out[i] = held
                continue
            held_for += 1
            if held_for >= h and entry is not None and entry != held:
                # allow flip / flat after min hold
                held = entry
                held_for = 1
            out[i] = held

    return out


def multi_day_forward_return(
    closes: Sequence[float | None],
    *,
    hold_days: int,
    entry_index: int,
) -> float | None:
    """Close-to-close return from ``entry_index`` over ``hold_days`` sessions.

    ``R = close[t+hold_days] / close[t] - 1`` when both ends present.
    """
    h = int(hold_days)
    if h < 1:
        raise ValueError(f"hold_days must be >= 1, got {hold_days!r}")
    i = int(entry_index)
    j = i + h
    if i < 0 or j >= len(closes):
        return None
    c0 = closes[i]
    c1 = closes[j]
    if c0 is None or c1 is None:
        return None
    try:
        a = float(c0)
        b = float(c1)
    except (TypeError, ValueError):
        return None
    if a == 0.0:
        return None
    return (b / a) - 1.0


def amortized_one_way_cost(
    one_way_cost: float,
    hold_days: int,
) -> float:
    """Research illustration: one-way cost amortized over hold horizon."""
    h = int(hold_days)
    if h < 1:
        raise ValueError(f"hold_days must be >= 1, got {hold_days!r}")
    return float(one_way_cost) / float(h)


def compute_multi_day_hold_signal(
    *,
    momentum: float | None,
    is_trading_day: float | None = 1.0,
    hold_days: int = DEFAULT_HOLD_DAYS,
    momentum_n: int | None = None,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Single-day **entry** observation for multi_day_hold class.

    Formula (entry):
        value = sign(momentum_n) if is_trading_day==1 else None

    The **hold** is applied across a time series via :func:`apply_sticky_hold`.
    This is **not** a 1-day flip primary; horizon is multi-day.
    """
    h = int(hold_days)
    if h not in SUPPORTED_HOLD_DAYS and h < 1:
        raise ValueError(f"hold_days invalid: {hold_days!r}")
    n_mom = int(momentum_n) if momentum_n is not None else h
    raw = sign_from_numeric(momentum)
    filtered, filter_meta = apply_trading_day_filter(raw, is_trading_day)
    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_MULTI_DAY_HOLD,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_MULTI_DAY_HOLD,
        "primary_feature_id": MOMENTUM_FEATURE_ID,
        "filter_feature_id": TRADING_DAY_FEATURE_ID,
        "momentum": momentum,
        "momentum_n": n_mom,
        "hold_days": h,
        "raw_entry_sign": raw,
        "filter": filter_meta,
        "formula": (
            f"entry = sign(momentum_n n={n_mom}); "
            f"hold sticky fixed_horizon={h}d (not 1d flip)"
        ),
        "not_simple_daily_sign": True,
        "note": (
            "Multi-day hold entry from momentum_n. Position held across "
            f"{h} sessions via sticky hold. Not READY. Not mass. No orders."
        ),
    }
    meta.update(_freeze_meta())
    if code is not None:
        meta["code"] = str(code)
    if date is not None:
        meta["date"] = str(date)[:10]
    if as_of is not None:
        meta["as_of"] = str(as_of)
    if extra_meta:
        meta.update(dict(extra_meta))
    return {
        "signal_id": SIGNAL_ID_MULTI_DAY_HOLD,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_MULTI_DAY_HOLD,
        "value": filtered,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "hold_days": h,
        "metadata": meta,
    }


# ---------------------------------------------------------------------------
# macro_conditioned — condition on repo rate level / change
# ---------------------------------------------------------------------------


def repo_regime_from_level(
    repo_rate: float | None,
    *,
    high_threshold: float = DEFAULT_REPO_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_REPO_LOW_THRESHOLD,
) -> tuple[str | None, dict[str, Any]]:
    """Label rate level regime: high / mid / low (or None if missing)."""
    if repo_rate is None:
        return None, {"reason": "repo_rate missing"}
    try:
        r = float(repo_rate)
    except (TypeError, ValueError):
        return None, {"reason": "repo_rate not numeric", "raw": repo_rate}
    if r >= float(high_threshold):
        label = "high"
    elif r <= float(low_threshold):
        label = "low"
    else:
        label = "mid"
    return label, {
        "repo_rate": r,
        "high_threshold": float(high_threshold),
        "low_threshold": float(low_threshold),
        "regime": label,
    }


def repo_regime_from_change(
    repo_rate: float | None,
    prev_repo_rate: float | None,
    *,
    eps: float = DEFAULT_REPO_CHANGE_EPS,
) -> tuple[str | None, dict[str, Any]]:
    """Label rate change regime: rate_up / rate_down / flat (or None)."""
    if repo_rate is None or prev_repo_rate is None:
        return None, {
            "reason": "repo_rate or prev missing",
            "repo_rate": repo_rate,
            "prev_repo_rate": prev_repo_rate,
        }
    try:
        cur = float(repo_rate)
        prev = float(prev_repo_rate)
    except (TypeError, ValueError):
        return None, {"reason": "repo_rate not numeric"}
    delta = cur - prev
    if delta > float(eps):
        label = "rate_up"
    elif delta < -float(eps):
        label = "rate_down"
    else:
        label = "flat"
    return label, {
        "repo_rate": cur,
        "prev_repo_rate": prev,
        "delta": delta,
        "eps": float(eps),
        "regime": label,
    }


def condition_signal_on_regime(
    entry_sign: float | None,
    regime: str | None,
    *,
    mode: str = "rate_change",
) -> tuple[float | None, dict[str, Any]]:
    """Apply macro condition to an entry sign.

    Modes
    -----
    rate_change (default):
        * rate_down → keep long only (entry +1 kept; −1 zeroed)
        * rate_up → keep short only (entry −1 kept; +1 zeroed)
        * flat → None (no trade)
    rate_level:
        * low → keep long only
        * high → keep short only
        * mid → None
    """
    m = str(mode or "rate_change").strip().lower()
    if entry_sign is None or regime is None:
        return None, {
            "conditioned": False,
            "reason": "missing entry or regime",
            "mode": m,
            "regime": regime,
            "entry_sign": entry_sign,
        }
    try:
        e = float(entry_sign)
    except (TypeError, ValueError):
        return None, {
            "conditioned": False,
            "reason": "entry not numeric",
            "mode": m,
        }

    if m == "rate_change":
        if regime == "rate_down":
            out = e if e > 0 else (0.0 if e == 0.0 else None)
            rule = "rate_down → long_only"
        elif regime == "rate_up":
            out = e if e < 0 else (0.0 if e == 0.0 else None)
            rule = "rate_up → short_only"
        elif regime == "flat":
            out = None
            rule = "flat → no_trade"
        else:
            out = None
            rule = f"unknown regime {regime!r}"
    elif m == "rate_level":
        if regime == "low":
            out = e if e > 0 else (0.0 if e == 0.0 else None)
            rule = "low_rate → long_only"
        elif regime == "high":
            out = e if e < 0 else (0.0 if e == 0.0 else None)
            rule = "high_rate → short_only"
        elif regime == "mid":
            out = None
            rule = "mid_rate → no_trade"
        else:
            out = None
            rule = f"unknown regime {regime!r}"
    else:
        raise ValueError(f"mode must be rate_change|rate_level, got {mode!r}")

    return out, {
        "conditioned": True,
        "mode": m,
        "regime": regime,
        "entry_sign": e,
        "rule": rule,
        "value": out,
    }


def compute_macro_conditioned_signal(
    *,
    momentum: float | None,
    repo_rate: float | None,
    prev_repo_rate: float | None = None,
    is_trading_day: float | None = 1.0,
    mode: str = "rate_change",
    high_threshold: float = DEFAULT_REPO_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_REPO_LOW_THRESHOLD,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Macro-conditioned research signal (repo rate level or change).

    Primary entry = sign(momentum_n) (or caller-supplied momentum value).
    Conditioned on JSDA Tokyo repo rate regime — **not** unconditional daily sign.
    """
    m = str(mode or "rate_change").strip().lower()
    raw = sign_from_numeric(momentum)
    filtered, filter_meta = apply_trading_day_filter(raw, is_trading_day)

    if m == "rate_change":
        regime, regime_meta = repo_regime_from_change(
            repo_rate, prev_repo_rate
        )
    else:
        regime, regime_meta = repo_regime_from_level(
            repo_rate,
            high_threshold=high_threshold,
            low_threshold=low_threshold,
        )

    conditioned, cond_meta = condition_signal_on_regime(
        filtered, regime, mode=m
    )

    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_MACRO_CONDITIONED,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_MACRO_CONDITIONED,
        "primary_feature_id": MOMENTUM_FEATURE_ID,
        "macro_feature_id": REPO_RATE_FEATURE_ID,
        "filter_feature_id": TRADING_DAY_FEATURE_ID,
        "datasets_required": list(MACRO_CONDITIONED_DATASETS),
        "momentum": momentum,
        "repo_rate": repo_rate,
        "prev_repo_rate": prev_repo_rate,
        "mode": m,
        "raw_entry_sign": raw,
        "filter": filter_meta,
        "regime": regime_meta,
        "condition": cond_meta,
        "formula": (
            f"entry=sign(momentum); regime=repo_{m}; "
            "condition long_only on rate_down/low, short_only on rate_up/high"
        ),
        "not_simple_daily_sign": True,
        "note": (
            "Macro-conditioned momentum on jsda_tokyo_repo_rates. "
            "Not READY. Not mass. No orders."
        ),
    }
    meta.update(_freeze_meta())
    if code is not None:
        meta["code"] = str(code)
    if date is not None:
        meta["date"] = str(date)[:10]
    if as_of is not None:
        meta["as_of"] = str(as_of)
    if extra_meta:
        meta.update(dict(extra_meta))

    return {
        "signal_id": SIGNAL_ID_MACRO_CONDITIONED,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_MACRO_CONDITIONED,
        "value": conditioned,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "regime": regime,
        "metadata": meta,
    }


# ---------------------------------------------------------------------------
# optional third: cross_section_relative (rank within day)
# ---------------------------------------------------------------------------


def cross_section_rank_signs(
    values_by_code: Mapping[str, float | None],
    *,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
) -> dict[str, float | None]:
    """Rank codes by value; top long_frac → +1, bottom short_frac → −1.

    Remaining middle / missing → 0 or None.
    """
    scored: list[tuple[str, float]] = []
    missing: list[str] = []
    for code, v in values_by_code.items():
        if v is None:
            missing.append(str(code))
            continue
        try:
            scored.append((str(code), float(v)))
        except (TypeError, ValueError):
            missing.append(str(code))
    scored.sort(key=lambda x: (-x[1], x[0]))
    n = len(scored)
    out: dict[str, float | None] = {c: None for c in missing}
    if n == 0:
        return out
    n_long = max(1, int(round(n * float(long_frac)))) if n >= 3 else 1
    n_short = max(1, int(round(n * float(short_frac)))) if n >= 3 else 1
    if n_long + n_short > n:
        n_long = max(1, n // 3)
        n_short = max(1, n // 3)
    for i, (code, _) in enumerate(scored):
        if i < n_long:
            out[code] = 1.0
        elif i >= n - n_short:
            out[code] = -1.0
        else:
            out[code] = 0.0
    return out


def compute_cross_section_signal(
    *,
    momentum_by_code: Mapping[str, float | None],
    is_trading_day: float | None = 1.0,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    date: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Cross-section relative L-S from same-day momentum ranks (optional third)."""
    filtered_td, filter_meta = apply_trading_day_filter(1.0, is_trading_day)
    if filtered_td is None:
        obs = [
            {
                "signal_id": SIGNAL_ID_CROSS_SECTION,
                "value": None,
                "code": str(c),
                "date": str(date)[:10] if date else None,
                "as_of": as_of,
                "metadata": {"filter": filter_meta},
            }
            for c in momentum_by_code
        ]
        return {
            "signal_id": SIGNAL_ID_CROSS_SECTION,
            "hypothesis_class": CLASS_CROSS_SECTION_RELATIVE,
            "status": SIGNAL_STATUS,
            "observations": obs,
            "filter": filter_meta,
            **_freeze_meta(),
        }

    ranks = cross_section_rank_signs(
        momentum_by_code, long_frac=long_frac, short_frac=short_frac
    )
    obs = []
    for code, val in sorted(ranks.items()):
        obs.append(
            {
                "signal_id": SIGNAL_ID_CROSS_SECTION,
                "version": SIGNAL_VERSION,
                "status": SIGNAL_STATUS,
                "hypothesis_class": CLASS_CROSS_SECTION_RELATIVE,
                "value": val,
                "code": code,
                "date": str(date)[:10] if date else None,
                "as_of": as_of,
                "metadata": {
                    "primary_feature_id": MOMENTUM_FEATURE_ID,
                    "momentum": momentum_by_code.get(code),
                    "long_frac": long_frac,
                    "short_frac": short_frac,
                    "filter": filter_meta,
                    "not_simple_daily_sign": True,
                    **_freeze_meta(),
                },
            }
        )
    return {
        "signal_id": SIGNAL_ID_CROSS_SECTION,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_CROSS_SECTION_RELATIVE,
        "observations": obs,
        "n_codes": len(obs),
        "filter": filter_meta,
        "formula": (
            f"rank(momentum) within day; top {long_frac:.0%} +1 / "
            f"bottom {short_frac:.0%} -1"
        ),
        **_freeze_meta(),
    }


# ---------------------------------------------------------------------------
# Catalog / definitions
# ---------------------------------------------------------------------------


def class_signal_definitions(
    *,
    hold_days: int = DEFAULT_HOLD_DAYS,
    macro_mode: str = "rate_change",
) -> list[dict[str, Any]]:
    """Declarative catalog for W78 class-based research signals."""
    return [
        {
            "signal_id": SIGNAL_ID_MULTI_DAY_HOLD,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_MULTI_DAY_HOLD,
            "horizon": f"{int(hold_days)}d_hold",
            "primary_feature_id": MOMENTUM_FEATURE_ID,
            "filter_feature_id": TRADING_DAY_FEATURE_ID,
            "feature_kinds": [
                "multi_day_return",
                "momentum_n",
                "hold_period_score",
                "turnover_aware_signal",
            ],
            "datasets_required": list(MULTI_DAY_HOLD_DATASETS),
            "hold_days": int(hold_days),
            "formula": (
                f"entry=sign(momentum_n n={int(hold_days)}); "
                f"sticky fixed_horizon hold={int(hold_days)}d; "
                "forward return over hold (not 1d nextday primary)"
            ),
            "not_simple_daily_sign": True,
            "role": "multi_day_hold",
        },
        {
            "signal_id": SIGNAL_ID_MACRO_CONDITIONED,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_MACRO_CONDITIONED,
            "horizon": "20d_to_60d_regime_conditioned",
            "primary_feature_id": MOMENTUM_FEATURE_ID,
            "macro_feature_id": REPO_RATE_FEATURE_ID,
            "filter_feature_id": TRADING_DAY_FEATURE_ID,
            "feature_kinds": [
                "regime_label",
                "macro_state",
                "conditioned_signal",
                "rate_environment",
            ],
            "datasets_required": list(MACRO_CONDITIONED_DATASETS),
            "macro_mode": str(macro_mode),
            "formula": (
                f"entry=sign(momentum); regime from repo_rate_{macro_mode}; "
                "long_only on rate_down/low; short_only on rate_up/high"
            ),
            "not_simple_daily_sign": True,
            "role": "macro_conditioned",
        },
        {
            "signal_id": SIGNAL_ID_CROSS_SECTION,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_CROSS_SECTION_RELATIVE,
            "horizon": "5d_to_20d_cross_section",
            "primary_feature_id": MOMENTUM_FEATURE_ID,
            "feature_kinds": [
                "cross_section_rank",
                "relative_value",
                "dispersion_signal",
            ],
            "datasets_required": list(CROSS_SECTION_DATASETS),
            "formula": "rank(momentum) L-S within day (optional third)",
            "not_simple_daily_sign": True,
            "role": "cross_section_relative",
            "optional": True,
        },
    ]


def class_signals_document() -> dict[str, Any]:
    """Public document for class signal surface."""
    return {
        "version": CLASS_SIGNALS_VERSION,
        "wave": CLASS_SIGNALS_WAVE,
        "signals": class_signal_definitions(),
        "supported_hold_days": list(SUPPORTED_HOLD_DAYS),
        "not_simple_daily_sign": True,
        "s1_s5_unreject": S1_S5_UNREJECT,
        **_freeze_meta(),
        "note": (
            "W78 class-based research signals. multi_day_hold + "
            "macro_conditioned (+ optional cross_section). "
            "Not READY. Not Mass. No S1–S5 un-reject."
        ),
    }


__all__ = [
    "CANDIDATE_ONLY",
    "CLASS_CROSS_SECTION_RELATIVE",
    "CLASS_MACRO_CONDITIONED",
    "CLASS_MULTI_DAY_HOLD",
    "CLASS_SIGNALS_VERSION",
    "CLASS_SIGNALS_WAVE",
    "CROSS_SECTION_DATASETS",
    "DEFAULT_HOLD_DAYS",
    "DEFAULT_MOMENTUM_N",
    "DEFAULT_REPO_CHANGE_EPS",
    "DEFAULT_REPO_HIGH_THRESHOLD",
    "DEFAULT_REPO_LOW_THRESHOLD",
    "MACRO_CONDITIONED_DATASETS",
    "MASS_RESEARCH",
    "MOMENTUM_FEATURE_ID",
    "MULTI_DAY_HOLD_DATASETS",
    "ORDER_EXECUTION",
    "PHASE7",
    "READY_DECLARED",
    "REPO_CHANGE_FEATURE_ID",
    "REPO_RATE_FEATURE_ID",
    "SIGNAL_ID_CROSS_SECTION",
    "SIGNAL_ID_MACRO_CONDITIONED",
    "SIGNAL_ID_MULTI_DAY_HOLD",
    "SIGNAL_STATUS",
    "SIGNAL_VERSION",
    "SUPPORTED_HOLD_DAYS",
    "TOPIX_REL_FEATURE_ID",
    "TRADING_DAY_FEATURE_ID",
    "amortized_one_way_cost",
    "apply_sticky_hold",
    "apply_trading_day_filter",
    "class_signal_definitions",
    "class_signals_document",
    "compute_cross_section_signal",
    "compute_macro_conditioned_signal",
    "compute_multi_day_hold_signal",
    "condition_signal_on_regime",
    "cross_section_rank_signs",
    "multi_day_forward_return",
    "repo_regime_from_change",
    "repo_regime_from_level",
    "sign_from_numeric",
]
