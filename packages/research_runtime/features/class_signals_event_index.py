"""Event-post entry-index helpers: disc_time, bar index, compute_event_post_signal.

Not simple daily sign. Mass / READY / GO closed. No S1–S5 un-reject.
"""

from __future__ import annotations

from typing import Any, Mapping

from .class_signals import (
    CLASS_EVENT_POST,
    DEFAULT_EVENT_POST_HOLD_DAYS,
    DISCLOSURE_FEATURE_ID,
    EVENT_POST_DATASETS,
    EVENT_POST_ENTRY_MODE,
    SESSION_CLOSE_CHANGE_DATE,
    SIGNAL_ID_EVENT_POST,
    SIGNAL_STATUS,
    SIGNAL_VERSION,
    TRADING_DAY_FEATURE_ID,
    _freeze_meta,
)
from .class_signals_hold import (
    _as_float_or_none,
    apply_trading_day_filter,
    sign_from_numeric,
)


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
    """Disclosure availability from dataset fields only. Missing DiscTime → no invent."""
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
    """PIT-safe event_post entry bar: pre-close same day, else next session. No invent."""
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


def earnings_surprise_proxy(
    *,
    eps: float | None = None,
    feps: float | None = None,
    prior_eps: float | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """Surprise proxy: FEPS−EPS, else EPS−prior, else None (no invent)."""
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
    """Post-event entry on disclosure day only: sign(surprise); non-event → None."""
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
        "entry_mode": EVENT_POST_ENTRY_MODE,
        "not_simple_daily_sign": True,
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

