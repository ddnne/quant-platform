"""Hypothesis-class research signals (W78–W80) — not simple daily sign.

Implements real signal logic for:

* ``multi_day_hold`` — N-day momentum entry with sticky multi-day hold
  (rebalance every ``hold_days``; not 1d flip)
* ``macro_conditioned`` — equity momentum conditioned on Tokyo repo rate
  **level** or **change** from ``jsda_tokyo_repo_rates``
* ``event_post`` — post-disclosure / post-earnings window (not continuous daily)
* ``flow_demand`` — multi-day margin/short flow pressure (not S4 daily rehash)
* ``fundamentals_price`` — PIT fundamentals × price (value / surprise)
* ``cross_section_relative`` — same-day rank L-S (optional; multi-day sticky OK)

Hard constraints
----------------
* Does **not** import ``agents.mass_research`` / mass loop
* Does **not** mint READY / VerifiedResearchReadiness
* Does **not** emit order intents / call paper execution
* Does **not** un-reject S1–S5
* ``simple_daily_sign`` is **not** used
* Mass / READY / operational GO never auto-connect from pass

Status remains ``candidate`` (research). W80 may set ``research_candidate=True``
when production criteria (economic net + occurrence rate + multi-year + risk)
are all met — still not READY / Mass / GO.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# ---------------------------------------------------------------------------
# Identity / freeze
# ---------------------------------------------------------------------------

CLASS_SIGNALS_VERSION: str = "class-signals/v6"
CLASS_SIGNALS_WAVE: str = "W83 / w0816r"

SIGNAL_STATUS: str = "candidate"
SIGNAL_VERSION: str = "1.4.0"
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
CLASS_EVENT_POST: str = "event_post"
CLASS_FLOW_DEMAND: str = "flow_demand"
CLASS_FUNDAMENTALS_PRICE: str = "fundamentals_price"

# Signal ids (stable R2 / catalog keys)
SIGNAL_ID_MULTI_DAY_HOLD: str = "c21_multi_day_momentum_hold"
SIGNAL_ID_MACRO_CONDITIONED: str = "c21_repo_conditioned_momentum"
SIGNAL_ID_CROSS_SECTION: str = "c21_cross_section_momentum_rank"
SIGNAL_ID_EVENT_POST: str = "c21_event_post_disclosure_hold"
SIGNAL_ID_FLOW_DEMAND: str = "c21_margin_flow_multiday"
SIGNAL_ID_FUNDAMENTALS_PRICE: str = "c21_fundamentals_price_value"

# Feature legs (prefer registry-approved)
MOMENTUM_FEATURE_ID: str = "momentum_n"
TRADING_DAY_FEATURE_ID: str = "is_trading_day"
TOPIX_REL_FEATURE_ID: str = "topix_relative_1d"
REPO_RATE_FEATURE_ID: str = "repo_rate_level"
REPO_CHANGE_FEATURE_ID: str = "repo_rate_change"
DISCLOSURE_FEATURE_ID: str = "disclosure_flag_fins"
MARGIN_CHANGE_FEATURE_ID: str = "margin_interest_change_1d"
SHORT_RATIO_FEATURE_ID: str = "short_ratio_level"
FUNDAMENTAL_RATIO_FEATURE_ID: str = "fundamental_ratio"

DEFAULT_HOLD_DAYS: int = 5
SUPPORTED_HOLD_DAYS: tuple[int, ...] = (5, 10, 20)
DEFAULT_MOMENTUM_N: int = 5  # match hold horizon default
DEFAULT_EVENT_POST_HOLD_DAYS: int = 5
DEFAULT_FLOW_HOLD_DAYS: int = 5
DEFAULT_FUND_HOLD_DAYS: int = 20
DEFAULT_FUND_MOMENTUM_N: int = 20
# PIT event_post entry: first session close that is knowable after disclosure.
# "same_day_close_if_pre_close" = trade event-day close only when DiscTime is
# present and strictly before that day's session close; otherwise next bar.
# Never invent DiscTime; missing time → next trading session (conservative).
EVENT_POST_ENTRY_MODE: str = "same_day_close_if_pre_close"
# TSE cash close moved 15:00 → 15:30 JST on 2024-11-05 (dataset / exchange SoT).
SESSION_CLOSE_CHANGE_DATE: str = "2024-11-05"
# Candidate bar helper: residual after costs must clear this for "economic"
# meaningfulness discussion (research only).
DEFAULT_MIN_ECONOMIC_NET: float = 0.002  # 20bp per scored hold

# ---------------------------------------------------------------------------
# W80 occurrence-rate / production-candidate bar (rate-based, not count alone)
# ---------------------------------------------------------------------------
# multi_day_hold: scored rebalances / code-days. fixed_horizon expect ~1/hold.
# Floor at half expected for hold=10 → 0.05; use 0.04 research buffer.
DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY: float = 0.04
# event_post: annualized scored events per code (earnings ~4/yr typical).
# 0.5 = at least half an event / code / year average across multi-year.
DEFAULT_MIN_EVENTS_PER_CODE_YEAR: float = 0.5
# event_post panel intensity: scored events / trading days (not code-days).
DEFAULT_MIN_EVENTS_PER_TRADING_DAY: float = 0.05
# multi-year: single-year share of sum(max(net,0)) must stay below this.
DEFAULT_MAX_YEAR_POS_NET_SHARE: float = 0.75
# research_candidate requires enough independent years (not count of events).
DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE: int = 4
DEFAULT_TRADING_DAYS_PER_YEAR: int = 245

# ---------------------------------------------------------------------------
# W81 statistical bar (raise beyond mean bp) — period-net metrics
# ---------------------------------------------------------------------------
# |t| of period mean nets vs 0 (sample std). Below ~1.0 is noise with n≈6.
DEFAULT_MIN_ABS_T_STAT: float = 1.5
# Period Sharpe = mean/std of period nets (periods_per_year=1).
DEFAULT_MIN_SHARPE_PERIOD: float = 0.50
# Share of periods with net > 0 (yearly sign stability).
DEFAULT_MIN_PERIOD_WIN_RATE: float = 0.60
# Absolute positive-net year count.
DEFAULT_MIN_POSITIVE_PERIODS: int = 4

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
EVENT_POST_DATASETS: tuple[str, ...] = (
    "fins_summary",
    "fins_earnings_date",  # W80 thicken event calendar when available
    "equities_bars_daily",
    "markets_calendar",
)
FLOW_DEMAND_DATASETS: tuple[str, ...] = (
    "markets_margin_interest",
    "markets_short_ratio",
    "equities_bars_daily",
    "markets_calendar",
)
FUNDAMENTALS_PRICE_DATASETS: tuple[str, ...] = (
    "fins_summary",
    "equities_bars_daily",
    "markets_calendar",
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


def session_close_hhmmss(date_yyyy_mm_dd: str) -> str:
    """Cash-session close clock for ``date`` (JST). No invent beyond TSE cutover."""
    d = str(date_yyyy_mm_dd)[:10]
    if d < SESSION_CLOSE_CHANGE_DATE:
        return "15:00:00"
    return "15:30:00"


def parse_disc_time_hhmmss(disc_time: Any) -> str | None:
    """Normalize DiscTime-like field to HH:MM:SS. None if missing/unparseable.

    Does **not** invent a time when the field is absent.
    """
    if disc_time is None or disc_time == "":
        return None
    s = str(disc_time).strip()
    if not s:
        return None
    # Accept HH:MM, HH:MM:SS, or embedded in ISO timestamp
    if "T" in s:
        s = s.split("T", 1)[1]
    s = s.replace("Z", "").split("+", 1)[0].split("-", 1)[0].strip()
    parts = s.split(":")
    if len(parts) < 2:
        return None
    try:
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(float(parts[2])) if len(parts) >= 3 else 0
    except (TypeError, ValueError):
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        return None
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def event_post_available_at_from_fields(
    *,
    disc_date: str | None,
    disc_time: Any = None,
    event_time: str | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Build disclosure availability instant from dataset fields only.

    Source of truth priority (no invented timestamps):
    1. Full ``event_time`` ISO when present (ingest usually stamps DiscDate+DiscTime)
    2. ``DiscDate`` + ``DiscTime`` when both present
    3. ``DiscDate`` alone → date known, **time unknown** (``available_at=None``;
       caller must use conservative next-session entry — do not invent 00:00/09:00)
    """
    d = str(disc_date or "")[:10]
    et = str(event_time).strip() if event_time else ""
    if et and "T" in et:
        # Prefer explicit full timestamp already on the row
        return et, {
            "mode": "event_time",
            "disc_date": d or et[:10],
            "available_at": et,
            "time_known": True,
        }
    hhmmss = parse_disc_time_hhmmss(disc_time)
    if d and hhmmss:
        aa = f"{d}T{hhmmss}+09:00"
        return aa, {
            "mode": "disc_date_plus_disc_time",
            "disc_date": d,
            "disc_time": hhmmss,
            "available_at": aa,
            "time_known": True,
        }
    if d:
        return None, {
            "mode": "disc_date_only_time_unknown",
            "disc_date": d,
            "available_at": None,
            "time_known": False,
            "reason": "DiscTime missing — no invent; force next-session entry",
        }
    return None, {
        "mode": "unavailable",
        "disc_date": None,
        "available_at": None,
        "time_known": False,
        "reason": "no DiscDate / event_time",
    }


def event_post_entry_bar_index(
    date_to_idx: Mapping[str, int],
    *,
    disc_date: str,
    disc_time: Any = None,
    event_time: str | None = None,
    entry_mode: str = EVENT_POST_ENTRY_MODE,
) -> tuple[int | None, str | None, dict[str, Any]]:
    """Resolve PIT-safe entry bar index for event_post (close-to-close hold).

    Rules
    -----
    * Signal becomes available at DiscDate+DiscTime (dataset SoT). No invent.
    * Position opens at the **first trading bar close** that does not look ahead
      of availability:
      - If DiscTime present and **strictly before** that day's session close,
        entry = that day's bar if it exists, else next bar on/after disc_date.
      - If DiscTime ≥ session close, missing, or unparseable → entry = **next**
        trading bar **after** disc_date (conservative; matches after-hours).
    * Hold horizon is applied from that entry index via
      :func:`multi_day_forward_return` (close[t+hold]/close[t]-1).

    Returns ``(entry_index, entry_date, meta)``. ``entry_index is None`` when
    no eligible bar exists (gap → skip, no invent).
    """
    d = str(disc_date)[:10]
    aa, aa_meta = event_post_available_at_from_fields(
        disc_date=d, disc_time=disc_time, event_time=event_time
    )
    mode = str(entry_mode or EVENT_POST_ENTRY_MODE)
    time_known = bool(aa_meta.get("time_known"))
    pre_close = False
    if time_known and aa:
        day = str(aa)[:10]
        close_clock = session_close_hhmmss(day)
        # Compare time portion only (JST assumed on both)
        t_part = str(aa).split("T", 1)[1][:8] if "T" in str(aa) else ""
        # Normalize to HH:MM:SS
        if len(t_part) == 5:
            t_part = t_part + ":00"
        pre_close = bool(t_part and t_part < close_clock)
    else:
        close_clock = session_close_hhmmss(d) if d else None

    allow_same_day = bool(
        mode == "same_day_close_if_pre_close" and time_known and pre_close
    )
    # Candidate entry dates among bar calendar
    later_or_eq = sorted(x for x in date_to_idx if x >= d)
    later_strict = sorted(x for x in date_to_idx if x > d)
    if allow_same_day:
        candidates = later_or_eq
        entry_reason = "same_day_close_pre_session_close"
    else:
        candidates = later_strict if later_strict else []
        if not time_known:
            entry_reason = "next_session_close_time_unknown_no_invent"
        elif not pre_close:
            entry_reason = "next_session_close_after_or_at_session_close"
        else:
            entry_reason = "next_session_close"
        # Fallback: if disc_date is non-trading and no later bars for after-close
        # case with only same-day missing — still use later_or_eq only when
        # disc_date itself is not a bar (non-trading disclosure day).
        if not candidates and d not in date_to_idx and later_or_eq:
            # Disclosure on weekend/holiday: first trading bar after calendar day
            # is not look-ahead of the disclosure day close.
            candidates = later_or_eq
            entry_reason = "first_trading_bar_after_non_trading_disc_date"

    meta: dict[str, Any] = {
        "disc_date": d,
        "available_at": aa,
        "available_at_meta": aa_meta,
        "entry_mode": mode,
        "session_close_clock": close_clock,
        "pre_session_close": pre_close if time_known else None,
        "time_known": time_known,
        "entry_reason": entry_reason,
        "look_ahead": False,
    }
    if not candidates:
        meta["reason"] = "no_eligible_entry_bar"
        return None, None, meta
    entry_date = candidates[0]
    # Hard no look-ahead: entry calendar day must be >= disc_date; if time was
    # at/after close on a trading disc_date, entry must be > disc_date.
    if entry_date < d:
        meta["reason"] = "entry_before_disc_date_blocked"
        meta["look_ahead"] = True
        return None, None, meta
    if (not allow_same_day) and entry_date == d and d in date_to_idx:
        meta["reason"] = "same_day_entry_blocked_for_post_close_or_unknown_time"
        meta["look_ahead"] = True
        return None, None, meta
    idx = int(date_to_idx[entry_date])
    meta["entry_date"] = entry_date
    meta["entry_index"] = idx
    meta["reason"] = entry_reason
    return idx, entry_date, meta


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
# event_post — post-disclosure / post-earnings (not continuous daily sign)
# ---------------------------------------------------------------------------


def _as_float_or_none(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def earnings_surprise_proxy(
    *,
    eps: float | None = None,
    feps: float | None = None,
    prior_eps: float | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """Research surprise proxy from fins_summary fields (not audited PEAD).

    Priority
    --------
    1. ``FEPS - EPS`` when both numeric (forward vs reported snapshot)
    2. ``EPS - prior_eps`` when prior disclosure EPS present
    3. else None (no invent)
    """
    e = _as_float_or_none(eps)
    f = _as_float_or_none(feps)
    p = _as_float_or_none(prior_eps)
    if e is not None and f is not None:
        delta = f - e
        return delta, {
            "mode": "feps_minus_eps",
            "eps": e,
            "feps": f,
            "delta": delta,
        }
    if e is not None and p is not None:
        delta = e - p
        return delta, {
            "mode": "eps_minus_prior",
            "eps": e,
            "prior_eps": p,
            "delta": delta,
        }
    return None, {
        "mode": "unavailable",
        "reason": "need FEPS+EPS or EPS+prior_EPS",
        "eps": e,
        "feps": f,
        "prior_eps": p,
    }


def fundamental_value_score(
    *,
    close: float | None,
    eps: float | None = None,
    bps: float | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """Cheap value score: prefer BPS/price, else EPS/price. None if missing."""
    c = _as_float_or_none(close)
    if c is None or c == 0.0:
        return None, {"reason": "close missing or zero", "close": c}
    b = _as_float_or_none(bps)
    e = _as_float_or_none(eps)
    if b is not None:
        score = b / c
        return score, {"mode": "bps_over_price", "bps": b, "close": c, "score": score}
    if e is not None:
        score = e / c
        return score, {"mode": "eps_over_price", "eps": e, "close": c, "score": score}
    return None, {"reason": "no BPS or EPS", "close": c}


def economic_net_meaningful(
    net_values: Sequence[float | None],
    *,
    min_mean_net: float = DEFAULT_MIN_ECONOMIC_NET,
    require_positive_majority: bool = True,
) -> dict[str, Any]:
    """Research bar: net residual after costs must be economically meaningful.

    Weak consistent-negative (or tiny residual << cost) is **not** candidate.
    """
    vals = [float(v) for v in net_values if v is not None]
    if not vals:
        return {
            "meaningful": False,
            "reason": "no_net_values",
            "min_mean_net": float(min_mean_net),
            "require_positive_majority": bool(require_positive_majority),
        }
    n_pos = sum(1 for v in vals if v > 0)
    n_neg = sum(1 for v in vals if v < 0)
    mean_net = sum(vals) / float(len(vals))
    majority_pos = n_pos > n_neg
    majority_neg = n_neg > n_pos
    if require_positive_majority and not majority_pos:
        return {
            "meaningful": False,
            "reason": (
                "net_majority_not_positive"
                if majority_neg
                else "net_majority_tied_or_flat"
            ),
            "mean_net": mean_net,
            "n_pos": n_pos,
            "n_neg": n_neg,
            "n": len(vals),
            "min_mean_net": float(min_mean_net),
            "weak_consistent_negative": bool(majority_neg and mean_net < 0),
        }
    if mean_net < float(min_mean_net):
        return {
            "meaningful": False,
            "reason": "mean_net_below_economic_threshold",
            "mean_net": mean_net,
            "n_pos": n_pos,
            "n_neg": n_neg,
            "n": len(vals),
            "min_mean_net": float(min_mean_net),
        }
    return {
        "meaningful": True,
        "reason": "positive_majority_and_mean_net_above_threshold",
        "mean_net": mean_net,
        "n_pos": n_pos,
        "n_neg": n_neg,
        "n": len(vals),
        "min_mean_net": float(min_mean_net),
    }


def occurrence_rate_multiday(
    *,
    n_active: int | None,
    n_code_days: int | None,
    n_trading_days: int | None = None,
    n_codes: int | None = None,
    hold_days: int = DEFAULT_HOLD_DAYS,
    min_activation_rate: float = DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY,
) -> dict[str, Any]:
    """Occurrence / activation rate for multi_day_hold (rate, not count alone).

    ``activation_rate = n_active / n_code_days`` when code-days known.
    Absolute ``n_active`` alone is **not** used to reject.
    """
    n_a = int(n_active or 0)
    n_cd = int(n_code_days or 0)
    n_td = int(n_trading_days or 0)
    n_c = int(n_codes or 0)
    rate = (float(n_a) / float(n_cd)) if n_cd > 0 else None
    expected = 1.0 / float(max(int(hold_days), 1))
    sufficient = bool(rate is not None and rate >= float(min_activation_rate))
    return {
        "kind": "occurrence_rate_multiday",
        "n_active": n_a,
        "n_code_days": n_cd if n_cd > 0 else None,
        "n_trading_days": n_td if n_td > 0 else None,
        "n_codes": n_c if n_c > 0 else None,
        "activation_rate": rate,
        "activation_rate_per_code_day": rate,
        "expected_activation_rate": expected,
        "min_activation_rate": float(min_activation_rate),
        "sufficient": sufficient,
        "reject_on_count_alone": False,
        "reason": (
            "activation_rate_ok"
            if sufficient
            else (
                "activation_rate_below_min"
                if rate is not None
                else "no_code_days_for_rate"
            )
        ),
        "note": (
            "Sufficiency uses rate (events or rebalances / code-days), "
            "not absolute n_active. Short window with OK rate → extend."
        ),
    }


def occurrence_rate_event_post(
    *,
    n_events: int | None,
    n_scored: int | None = None,
    n_trading_days: int | None = None,
    n_codes: int | None = None,
    n_code_days: int | None = None,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
    min_events_per_code_year: float = DEFAULT_MIN_EVENTS_PER_CODE_YEAR,
    min_events_per_trading_day: float = DEFAULT_MIN_EVENTS_PER_TRADING_DAY,
) -> dict[str, Any]:
    """Occurrence rate for event_post — rate-based, multi-year friendly.

    Primary metrics:
    * events_per_trading_day = n_scored / n_trading_days
    * events_per_code_year   = annualized n_scored / n_codes
    * events_per_code_day    = n_scored / n_code_days

    Absolute event count alone must **not** reject when rates are OK.
    """
    n_ev = int(n_events or 0)
    n_sc = int(n_scored if n_scored is not None else n_ev)
    n_td = int(n_trading_days or 0)
    n_c = int(n_codes or 0)
    n_cd = int(n_code_days or 0)
    if n_cd <= 0 and n_td > 0 and n_c > 0:
        n_cd = n_td * n_c

    per_td = (float(n_sc) / float(n_td)) if n_td > 0 else None
    per_cd = (float(n_sc) / float(n_cd)) if n_cd > 0 else None
    per_code_year = None
    if n_c > 0 and n_td > 0:
        # annualize from window length
        years_frac = float(n_td) / float(max(int(trading_days_per_year), 1))
        if years_frac > 0:
            per_code_year = (float(n_sc) / float(n_c)) / years_frac

    rate_ok_td = bool(
        per_td is not None and per_td >= float(min_events_per_trading_day)
    )
    rate_ok_year = bool(
        per_code_year is not None
        and per_code_year >= float(min_events_per_code_year)
    )
    # either panel intensity or annualized per-code rate is enough
    sufficient = bool(rate_ok_td or rate_ok_year)
    if per_td is None and per_code_year is None:
        sufficient = False
        reason = "no_days_or_codes_for_rate"
    elif sufficient:
        reason = "occurrence_rate_ok"
    else:
        reason = "occurrence_rate_below_min"

    return {
        "kind": "occurrence_rate_event_post",
        "n_events": n_ev,
        "n_scored": n_sc,
        "n_trading_days": n_td if n_td > 0 else None,
        "n_codes": n_c if n_c > 0 else None,
        "n_code_days": n_cd if n_cd > 0 else None,
        "events_per_trading_day": per_td,
        "events_per_code_day": per_cd,
        "events_per_code_year_annualized": per_code_year,
        "min_events_per_trading_day": float(min_events_per_trading_day),
        "min_events_per_code_year": float(min_events_per_code_year),
        "rate_ok_trading_day": rate_ok_td,
        "rate_ok_code_year": rate_ok_year,
        "sufficient": sufficient,
        "reject_on_count_alone": False,
        "reason": reason,
        "note": (
            "Event sufficiency = occurrence rate (events/trading day or "
            "annualized per code), multi-year coverage. Do not reject on "
            "absolute n_events alone. Short window with OK rate → extend."
        ),
    }


def multi_year_skew_check(
    net_by_period: Mapping[str, float | None] | Sequence[tuple[str, float | None]],
    *,
    max_pos_share: float = DEFAULT_MAX_YEAR_POS_NET_SHARE,
) -> dict[str, Any]:
    """Detect extreme single-year dominance of positive net mass."""
    if isinstance(net_by_period, Mapping):
        items = [(str(k), v) for k, v in net_by_period.items()]
    else:
        items = [(str(k), v) for k, v in net_by_period]
    pos = [(k, float(v)) for k, v in items if v is not None and float(v) > 0]
    pos_sum = sum(v for _, v in pos)
    if pos_sum <= 0:
        return {
            "ok": False,
            "reason": "no_positive_net_years",
            "max_pos_share": float(max_pos_share),
            "shares": {},
            "dominant_period": None,
            "dominant_share": None,
        }
    shares = {k: float(v) / pos_sum for k, v in pos}
    dom_k, dom_s = max(shares.items(), key=lambda kv: kv[1])
    ok = bool(dom_s <= float(max_pos_share))
    return {
        "ok": ok,
        "reason": "no_extreme_skew" if ok else "extreme_single_year_skew",
        "max_pos_share": float(max_pos_share),
        "shares": shares,
        "dominant_period": dom_k,
        "dominant_share": dom_s,
        "n_positive_years": len(pos),
        "pos_net_sum": pos_sum,
    }


def production_candidate_bar(
    *,
    checklist_complete: bool,
    gate_passed: bool,
    risk_ok: bool,
    economic_net_ok: bool,
    occurrence_ok: bool,
    multi_year_ok: bool,
    skew_ok: bool,
    n_ok_periods: int,
    min_years: int = DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE,
    economic_net: Mapping[str, Any] | None = None,
    occurrence: Mapping[str, Any] | None = None,
    skew: Mapping[str, Any] | None = None,
    stats_ok: bool = True,
    stats: Mapping[str, Any] | None = None,
    stats_bar: Mapping[str, Any] | None = None,
    require_stats: bool = True,
) -> dict[str, Any]:
    """W81 production research_candidate bar (still not READY / Mass / GO).

    All must pass:
    1. checklist v2 complete (caller-supplied)
    2. robustness gate pass
    3. risk scenarios not catastrophic
    4. economic net meaningful (positive majority + mean ≥ min)
    5. occurrence / activation rate sufficient (rate, not count alone)
    6. multi-year coverage (≥ min_years ok periods) without extreme skew
    7. **W81 statistical bar**: |t|, Sharpe, period win-rate / pos years
       (when ``require_stats``; default True)

    When all pass → ``research_candidate=True`` (research only).
    Weak consistent-negative → not_candidate (via economic_net_ok=False).
    Low t/Sharpe / unstable yearly signs → demote to discussion_only
    (gate+econ ok) or not_candidate.
    """
    years_ok = bool(multi_year_ok and int(n_ok_periods) >= int(min_years))
    stats_required_ok = bool(stats_ok) if require_stats else True
    all_ok = bool(
        checklist_complete
        and gate_passed
        and risk_ok
        and economic_net_ok
        and occurrence_ok
        and years_ok
        and skew_ok
        and stats_required_ok
    )
    fails: list[str] = []
    if not checklist_complete:
        fails.append("checklist_incomplete")
    if not gate_passed:
        fails.append("gate_failed")
    if not risk_ok:
        fails.append("risk_catastrophic_or_blocked")
    if not economic_net_ok:
        fails.append("economic_net_not_meaningful")
    if not occurrence_ok:
        fails.append("occurrence_rate_insufficient")
    if not years_ok:
        fails.append("multi_year_coverage_insufficient")
    if not skew_ok:
        fails.append("extreme_multi_year_skew")
    if require_stats and not stats_ok:
        fails.append("stats_bar_failed")

    w80_core_ok = bool(
        checklist_complete
        and gate_passed
        and risk_ok
        and economic_net_ok
        and occurrence_ok
        and years_ok
        and skew_ok
    )
    noisy = bool((stats_bar or {}).get("noisy")) if stats_bar else False

    if all_ok:
        verdict = "research_candidate"
        yes_no = "yes"
    elif (
        gate_passed
        and risk_ok
        and economic_net_ok
        and (
            not occurrence_ok
            or not years_ok
            or not skew_ok
            or not checklist_complete
            or (require_stats and not stats_ok)
        )
    ):
        # gate+econ ok but production rate/year/checklist/stats incomplete
        if require_stats and not stats_ok and w80_core_ok:
            verdict = (
                "discussion_only_noisy_stats"
                if noisy
                else "discussion_only_stats_bar"
            )
        else:
            verdict = "discussion_only"
        yes_no = "no_discussion_only"
    elif gate_passed and risk_ok and not economic_net_ok:
        verdict = "not_candidate_economic_net_not_meaningful"
        yes_no = "no"
    else:
        verdict = "not_candidate"
        yes_no = "no"

    return {
        "research_candidate": bool(all_ok),
        "research_candidate_allowed": bool(
            gate_passed and risk_ok and economic_net_ok
        ),
        "candidate_yes_no": yes_no,
        "verdict": verdict,
        "production_criteria": {
            "checklist_complete": bool(checklist_complete),
            "gate_passed": bool(gate_passed),
            "risk_ok": bool(risk_ok),
            "economic_net_ok": bool(economic_net_ok),
            "occurrence_ok": bool(occurrence_ok),
            "multi_year_ok": bool(years_ok),
            "skew_ok": bool(skew_ok),
            "stats_ok": bool(stats_required_ok),
            "stats_required": bool(require_stats),
            "n_ok_periods": int(n_ok_periods),
            "min_years": int(min_years),
            "all_ok": all_ok,
            "w80_core_ok": w80_core_ok,
            "fails": fails,
        },
        "economic_net": dict(economic_net) if economic_net else None,
        "occurrence": dict(occurrence) if occurrence else None,
        "skew": dict(skew) if skew else None,
        "stats": dict(stats) if stats else None,
        "stats_bar": dict(stats_bar) if stats_bar else None,
        "ready_declared": False,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "operational_go": False,
        "connected_to_ready": False,
        "connected_to_mass": False,
        "note": (
            "W81 production research_candidate bar. All criteria required "
            "including statistical bar (|t|, Sharpe, period win-rate). "
            "research_candidate=True is research-only; never auto-connects "
            "READY / Mass / operational GO / Phase7 / orders. "
            "Occurrence uses rates not absolute counts. "
            "Noisy low t/Sharpe / unstable yearly signs → demote."
        ),
    }


def compute_event_post_signal(
    *,
    surprise: float | None,
    is_event_day: bool,
    is_trading_day: float | None = 1.0,
    post_hold_days: int = DEFAULT_EVENT_POST_HOLD_DAYS,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    disc_date: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Post-event entry: only on disclosure day; sign(surprise); hold multi-day.

    Not continuous daily sign. Non-event days → value None (no trade).
    """
    h = int(post_hold_days)
    if h < 1:
        raise ValueError(f"post_hold_days must be >= 1, got {post_hold_days!r}")
    raw = sign_from_numeric(surprise)
    filtered, filter_meta = apply_trading_day_filter(raw, is_trading_day)
    if not is_event_day:
        value = None
        event_meta = {"is_event_day": False, "reason": "not_disclosure_day"}
    elif filtered is None or filtered == 0.0:
        value = None if filtered is None else 0.0
        event_meta = {
            "is_event_day": True,
            "reason": "surprise_flat_or_missing",
            "raw_sign": raw,
        }
    else:
        value = filtered
        event_meta = {"is_event_day": True, "raw_sign": raw}

    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_EVENT_POST,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_EVENT_POST,
        "primary_feature_id": DISCLOSURE_FEATURE_ID,
        "filter_feature_id": TRADING_DAY_FEATURE_ID,
        "datasets_required": list(EVENT_POST_DATASETS),
        "surprise": surprise,
        "post_hold_days": h,
        "disc_date": disc_date,
        "filter": filter_meta,
        "event": event_meta,
        "formula": (
            f"on fins DiscDate(+DiscTime): available_at from dataset fields; "
            f"entry=sign(surprise_proxy) at first non-look-ahead session close; "
            f"sticky hold={h}d close-to-close; non-event → no trade"
        ),
        "entry_mode": EVENT_POST_ENTRY_MODE,
        "not_simple_daily_sign": True,
        "note": (
            "Post-disclosure hold from fins_summary DiscDate/DiscTime SoT. "
            "Missing DiscTime → next session (no invent). Not READY. Not mass."
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
        "signal_id": SIGNAL_ID_EVENT_POST,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_EVENT_POST,
        "value": value,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "post_hold_days": h,
        "metadata": meta,
    }


def compute_flow_demand_signal(
    *,
    margin_change: float | None,
    short_ratio_change: float | None = None,
    is_trading_day: float | None = 1.0,
    hold_days: int = DEFAULT_FLOW_HOLD_DAYS,
    require_short_confirm: bool = False,
    short_confirm_mode: str | None = None,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Multi-day flow/demand from margin interest change (not S4 1d flip).

    Entry = sign(margin_change). Optional short_ratio_change confirmation:

    * ``short_confirm_mode="off"`` (default) — margin only
    * ``"hard"`` / ``require_short_confirm=True`` — same-sign required;
      missing short → no entry
    * ``"soft"`` (W85) — same-sign when short present; margin-only on short
      gap (cheap occurrence improve; no look-ahead)

    Hold via sticky multi-day structure at the eval layer — this returns the
    **entry** sign.
    """
    h = int(hold_days)
    if short_confirm_mode is None:
        mode_s = "hard" if require_short_confirm else "off"
    else:
        mode_s = str(short_confirm_mode).strip().lower()
        if mode_s in {"true", "1", "yes", "on", "require"}:
            mode_s = "hard"
        elif mode_s in {"false", "0", "no", "none"}:
            mode_s = "off"
        elif mode_s not in {"off", "hard", "soft"}:
            raise ValueError(
                f"short_confirm_mode must be off|hard|soft, got "
                f"{short_confirm_mode!r}"
            )
    raw = sign_from_numeric(margin_change)
    filtered, filter_meta = apply_trading_day_filter(raw, is_trading_day)
    short_sign = sign_from_numeric(short_ratio_change)
    confirmed = True
    confirm_meta: dict[str, Any] = {
        "require_short_confirm": mode_s == "hard",
        "short_confirm_mode": mode_s,
        "short_ratio_change": short_ratio_change,
        "short_sign": short_sign,
    }
    value = filtered
    if mode_s == "hard":
        if short_sign is None or filtered is None:
            value = None
            confirmed = False
            confirm_meta["reason"] = "short_or_margin_missing"
        elif short_sign == 0.0 or filtered == 0.0:
            value = 0.0
            confirm_meta["reason"] = "flat_leg"
        elif (short_sign > 0) != (filtered > 0):
            value = None
            confirmed = False
            confirm_meta["reason"] = "short_margin_sign_conflict"
        else:
            confirm_meta["reason"] = "confirmed_same_sign"
    elif mode_s == "soft":
        # Soft (W85 cheap near-miss improve):
        # * same-sign short when available → preferred entry
        # * short gap → margin-only
        # * sign conflict → keep margin entry (confirmation optional, not a hard gate)
        # Distinct from hard confirm (conflict → no entry) and from S4 daily flip.
        if filtered is None:
            value = None
            confirmed = False
            confirm_meta["reason"] = "margin_missing"
        elif short_sign is None:
            value = filtered
            confirmed = True
            confirm_meta["reason"] = "soft_margin_only_short_gap"
        elif short_sign == 0.0 or filtered == 0.0:
            value = 0.0
            confirm_meta["reason"] = "flat_leg"
        elif (short_sign > 0) != (filtered > 0):
            value = filtered
            confirmed = False
            confirm_meta["reason"] = "soft_conflict_keep_margin"
        else:
            confirm_meta["reason"] = "soft_confirmed_same_sign"
    confirm_meta["confirmed"] = confirmed

    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_FLOW_DEMAND,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_FLOW_DEMAND,
        "primary_feature_id": MARGIN_CHANGE_FEATURE_ID,
        "short_feature_id": SHORT_RATIO_FEATURE_ID,
        "filter_feature_id": TRADING_DAY_FEATURE_ID,
        "datasets_required": list(FLOW_DEMAND_DATASETS),
        "margin_change": margin_change,
        "hold_days": h,
        "raw_entry_sign": raw,
        "filter": filter_meta,
        "confirm": confirm_meta,
        "formula": (
            f"entry=sign(margin_interest_change); sticky hold={h}d "
            f"(not S4 daily); short_confirm_mode={mode_s}"
        ),
        "not_simple_daily_sign": True,
        "not_s4_rehash": True,
        "note": (
            "Multi-day margin flow demand. Distinct from rejected S4 daily "
            "margin_change_sign. Not READY. Not mass."
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
        "signal_id": SIGNAL_ID_FLOW_DEMAND,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_FLOW_DEMAND,
        "value": value,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "hold_days": h,
        "metadata": meta,
    }


def compute_fundamentals_price_signal(
    *,
    value_score: float | None,
    momentum: float | None,
    value_benchmark: float | None = None,
    is_trading_day: float | None = 1.0,
    hold_days: int = DEFAULT_FUND_HOLD_DAYS,
    mode: str = "value_momentum_agree",
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fundamentals × price: value vs benchmark conditioned on momentum.

    Modes
    -----
    value_momentum_agree (default):
        long only when value_score > benchmark AND momentum > 0;
        short only when value_score < benchmark AND momentum < 0;
        else None.
    value_only:
        entry = sign(value_score - benchmark)
    """
    h = int(hold_days)
    m = str(mode or "value_momentum_agree").strip().lower()
    _, filter_meta = apply_trading_day_filter(1.0, is_trading_day)
    if filter_meta.get("passed") is not True:
        value = None
        rule = "non_trading_day"
    elif value_score is None:
        value = None
        rule = "value_score_missing"
    else:
        bench = 0.0 if value_benchmark is None else float(value_benchmark)
        value_sign = sign_from_numeric(float(value_score) - bench)
        mom_sign = sign_from_numeric(momentum)
        if m == "value_only":
            value = value_sign
            rule = "value_only"
        elif m == "value_momentum_agree":
            if value_sign is None or mom_sign is None or value_sign == 0.0:
                value = None if value_sign is None else 0.0
                rule = "flat_or_missing"
            elif mom_sign == 0.0:
                value = None
                rule = "momentum_flat_no_trade"
            elif (value_sign > 0 and mom_sign > 0) or (
                value_sign < 0 and mom_sign < 0
            ):
                value = value_sign
                rule = "value_and_momentum_agree"
            else:
                value = None
                rule = "value_momentum_disagree"
        else:
            raise ValueError(
                f"mode must be value_momentum_agree|value_only, got {mode!r}"
            )

    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_FUNDAMENTALS_PRICE,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_FUNDAMENTALS_PRICE,
        "primary_feature_id": FUNDAMENTAL_RATIO_FEATURE_ID,
        "momentum_feature_id": MOMENTUM_FEATURE_ID,
        "filter_feature_id": TRADING_DAY_FEATURE_ID,
        "datasets_required": list(FUNDAMENTALS_PRICE_DATASETS),
        "value_score": value_score,
        "value_benchmark": value_benchmark,
        "momentum": momentum,
        "hold_days": h,
        "mode": m,
        "rule": rule,
        "filter": filter_meta,
        "formula": (
            f"value_score (BPS/P or EPS/P) vs benchmark; mode={m}; "
            f"sticky hold={h}d (PIT fins)"
        ),
        "not_simple_daily_sign": True,
        "note": (
            "Fundamentals vs price with PIT fins_summary. Not READY. Not mass."
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
        "signal_id": SIGNAL_ID_FUNDAMENTALS_PRICE,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_FUNDAMENTALS_PRICE,
        "value": value,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "hold_days": h,
        "metadata": meta,
    }


# ---------------------------------------------------------------------------
# Catalog / definitions
# ---------------------------------------------------------------------------


def class_signal_definitions(
    *,
    hold_days: int = DEFAULT_HOLD_DAYS,
    macro_mode: str = "rate_change",
    event_hold_days: int = DEFAULT_EVENT_POST_HOLD_DAYS,
    flow_hold_days: int = DEFAULT_FLOW_HOLD_DAYS,
    fund_hold_days: int = DEFAULT_FUND_HOLD_DAYS,
) -> list[dict[str, Any]]:
    """Declarative catalog for W79 class-based research signals."""
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
            "signal_id": SIGNAL_ID_EVENT_POST,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_EVENT_POST,
            "horizon": f"1d_to_{int(event_hold_days)}d_post_event",
            "primary_feature_id": DISCLOSURE_FEATURE_ID,
            "filter_feature_id": TRADING_DAY_FEATURE_ID,
            "feature_kinds": [
                "disclosure_flag",
                "event_window",
                "post_event_drift",
                "earnings_surprise_proxy",
            ],
            "datasets_required": list(EVENT_POST_DATASETS),
            "post_hold_days": int(event_hold_days),
            "formula": (
                f"on fins DiscDate+DiscTime (SoT): PIT entry at first session "
                f"close not looking ahead; sign(surprise_proxy); "
                f"hold={int(event_hold_days)}d close-to-close; non-event no trade"
            ),
            "entry_mode": EVENT_POST_ENTRY_MODE,
            "not_simple_daily_sign": True,
            "role": "event_post",
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
            "formula": (
                "rank(momentum) L-S within day; optional sticky multi-day hold"
            ),
            "not_simple_daily_sign": True,
            "role": "cross_section_relative",
            "optional": True,
        },
        {
            "signal_id": SIGNAL_ID_FLOW_DEMAND,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_FLOW_DEMAND,
            "horizon": f"{int(flow_hold_days)}d_to_20d_flow",
            "primary_feature_id": MARGIN_CHANGE_FEATURE_ID,
            "feature_kinds": [
                "flow_delta",
                "demand_pressure",
                "positioning_level",
            ],
            "datasets_required": list(FLOW_DEMAND_DATASETS),
            "hold_days": int(flow_hold_days),
            "formula": (
                f"entry=sign(margin_change); sticky hold={int(flow_hold_days)}d; "
                "not S4 daily rehash; optional short_ratio confirm"
            ),
            "not_simple_daily_sign": True,
            "not_s4_rehash": True,
            "role": "flow_demand",
        },
        {
            "signal_id": SIGNAL_ID_FUNDAMENTALS_PRICE,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_FUNDAMENTALS_PRICE,
            "horizon": f"{int(fund_hold_days)}d_to_60d_fundamental",
            "primary_feature_id": FUNDAMENTAL_RATIO_FEATURE_ID,
            "feature_kinds": [
                "fundamental_ratio",
                "earnings_surprise_proxy",
                "value_score",
            ],
            "datasets_required": list(FUNDAMENTALS_PRICE_DATASETS),
            "hold_days": int(fund_hold_days),
            "formula": (
                f"value_score=BPS/P|EPS/P (PIT); agree with momentum; "
                f"hold={int(fund_hold_days)}d"
            ),
            "not_simple_daily_sign": True,
            "role": "fundamentals_price",
        },
    ]


def class_signals_document() -> dict[str, Any]:
    """Public document for class signal surface."""
    return {
        "version": CLASS_SIGNALS_VERSION,
        "wave": CLASS_SIGNALS_WAVE,
        "signals": class_signal_definitions(),
        "supported_hold_days": list(SUPPORTED_HOLD_DAYS),
        "min_economic_net": DEFAULT_MIN_ECONOMIC_NET,
        "min_activation_rate_multiday": DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY,
        "min_events_per_code_year": DEFAULT_MIN_EVENTS_PER_CODE_YEAR,
        "min_years_research_candidate": DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE,
        "min_abs_t_stat": DEFAULT_MIN_ABS_T_STAT,
        "min_sharpe_period": DEFAULT_MIN_SHARPE_PERIOD,
        "min_period_win_rate": DEFAULT_MIN_PERIOD_WIN_RATE,
        "min_positive_periods": DEFAULT_MIN_POSITIVE_PERIODS,
        "not_simple_daily_sign": True,
        "s1_s5_unreject": S1_S5_UNREJECT,
        **_freeze_meta(),
        "note": (
            "W82 class-based research signals. multi_day_hold + event_post + "
            "macro_conditioned + flow_demand + fundamentals_price "
            "(+ optional cross_section). Production research_candidate only "
            "if economic net + occurrence rate + multi-year no extreme skew + "
            "risk OK + statistical bar (|t|≥1.5, Sharpe≥0.5, win-rate≥0.6, "
            "≥4 positive periods). Weak consistent-negative is not_candidate. "
            "Noisy low t/Sharpe → demote to discussion_only. "
            "READY/Mass never auto-connect. No S1–S5 un-reject."
        ),
    }


__all__ = [
    "CANDIDATE_ONLY",
    "CLASS_CROSS_SECTION_RELATIVE",
    "CLASS_EVENT_POST",
    "CLASS_FLOW_DEMAND",
    "CLASS_FUNDAMENTALS_PRICE",
    "CLASS_MACRO_CONDITIONED",
    "CLASS_MULTI_DAY_HOLD",
    "CLASS_SIGNALS_VERSION",
    "CLASS_SIGNALS_WAVE",
    "CROSS_SECTION_DATASETS",
    "DEFAULT_EVENT_POST_HOLD_DAYS",
    "DEFAULT_FLOW_HOLD_DAYS",
    "EVENT_POST_ENTRY_MODE",
    "SESSION_CLOSE_CHANGE_DATE",
    "DEFAULT_FUND_HOLD_DAYS",
    "DEFAULT_FUND_MOMENTUM_N",
    "DEFAULT_HOLD_DAYS",
    "DEFAULT_MAX_YEAR_POS_NET_SHARE",
    "DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY",
    "DEFAULT_MIN_ECONOMIC_NET",
    "DEFAULT_MIN_ABS_T_STAT",
    "DEFAULT_MIN_EVENTS_PER_CODE_YEAR",
    "DEFAULT_MIN_EVENTS_PER_TRADING_DAY",
    "DEFAULT_MIN_PERIOD_WIN_RATE",
    "DEFAULT_MIN_POSITIVE_PERIODS",
    "DEFAULT_MIN_SHARPE_PERIOD",
    "DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE",
    "DEFAULT_MOMENTUM_N",
    "DEFAULT_REPO_CHANGE_EPS",
    "DEFAULT_REPO_HIGH_THRESHOLD",
    "DEFAULT_REPO_LOW_THRESHOLD",
    "DEFAULT_TRADING_DAYS_PER_YEAR",
    "DISCLOSURE_FEATURE_ID",
    "EVENT_POST_DATASETS",
    "FLOW_DEMAND_DATASETS",
    "FUNDAMENTALS_PRICE_DATASETS",
    "FUNDAMENTAL_RATIO_FEATURE_ID",
    "MACRO_CONDITIONED_DATASETS",
    "MARGIN_CHANGE_FEATURE_ID",
    "MASS_RESEARCH",
    "MOMENTUM_FEATURE_ID",
    "MULTI_DAY_HOLD_DATASETS",
    "ORDER_EXECUTION",
    "PHASE7",
    "READY_DECLARED",
    "REPO_CHANGE_FEATURE_ID",
    "REPO_RATE_FEATURE_ID",
    "SHORT_RATIO_FEATURE_ID",
    "SIGNAL_ID_CROSS_SECTION",
    "SIGNAL_ID_EVENT_POST",
    "SIGNAL_ID_FLOW_DEMAND",
    "SIGNAL_ID_FUNDAMENTALS_PRICE",
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
    "compute_event_post_signal",
    "compute_flow_demand_signal",
    "compute_fundamentals_price_signal",
    "compute_macro_conditioned_signal",
    "compute_multi_day_hold_signal",
    "condition_signal_on_regime",
    "cross_section_rank_signs",
    "earnings_surprise_proxy",
    "economic_net_meaningful",
    "event_post_available_at_from_fields",
    "event_post_entry_bar_index",
    "fundamental_value_score",
    "multi_day_forward_return",
    "multi_year_skew_check",
    "occurrence_rate_event_post",
    "occurrence_rate_multiday",
    "parse_disc_time_hhmmss",
    "production_candidate_bar",
    "repo_regime_from_change",
    "repo_regime_from_level",
    "session_close_hhmmss",
    "sign_from_numeric",
]
