"""Offline bar-eval hold family (multi_day_hold, event_post).

Not CF SoT; no GO.
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Mapping, Sequence

from features.class_signals import (
    CLASS_EVENT_POST,
    CLASS_MULTI_DAY_HOLD,
    DEFAULT_EVENT_POST_HOLD_DAYS,
    DEFAULT_HOLD_DAYS,
    DEFAULT_TRADING_DAYS_PER_YEAR,
    EVENT_POST_ENTRY_MODE,
    SIGNAL_ID_EVENT_POST,
    SIGNAL_ID_MULTI_DAY_HOLD,
    amortized_one_way_cost,
    apply_sticky_hold,
    compute_event_post_signal,
    earnings_surprise_proxy,
    event_post_entry_bar_index,
    multi_day_forward_return,
    occurrence_rate_event_post,
    occurrence_rate_multiday,
    sign_from_numeric,
)
from research.cost_models import DEFAULT_ONE_WAY_COST
from research.eval_loaders import momentum_series
from research.offline.bar_eval_common import (
    MIN_ACTIVATION_RATE_MULTIDAY,
    MIN_EVENTS_PER_CODE_YEAR,
    MIN_EVENTS_PER_TRADING_DAY,
    _freeze,
)
from research.stats_metrics import trade_stats_report


def evaluate_multi_day_hold_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    hold_days: int = DEFAULT_HOLD_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    rebalance_mode: str = "fixed_horizon",
) -> dict[str, Any]:
    """Evaluate multi_day_hold signal on an in-memory bars panel.

    Entry = sign(momentum_n) with n=hold_days; sticky hold; gross = mean of
    sign * hold-horizon forward return on rebalance days only.
    Cost net uses amortized one-way over hold_days.
    """
    h = int(hold_days)
    if h < 1:
        raise ValueError(f"hold_days must be >= 1, got {hold_days!r}")
    am_cost = amortized_one_way_cost(one_way_cost, h)

    signed_returns: list[float] = []
    holding_records: list[dict[str, Any]] = []
    n_rebalance = 0
    n_active = 0
    per_code_stats: list[dict[str, Any]] = []

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < h + 2:
            continue
        moms = momentum_series(pairs_l, n=h)
        entry_signs = [sign_from_numeric(m) for _, m in moms]
        held = apply_sticky_hold(
            entry_signs, hold_days=h, rebalance_mode=rebalance_mode
        )
        closes = [c for _, c in pairs_l]
        dates = [d for d, _ in pairs_l]
        code_signed: list[float] = []
        for i, pos in enumerate(held):
            holding_records.append(
                {
                    "date": dates[i],
                    "code": code,
                    "sign": pos,
                }
            )
            if pos is None or pos == 0.0:
                continue
            # Only score on rebalance boundaries for fixed_horizon.
            if rebalance_mode == "fixed_horizon" and i % h != 0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_rebalance += 1
            n_active += 1
            sr = float(pos) * float(fwd)
            signed_returns.append(sr)
            code_signed.append(sr)
        if code_signed:
            per_code_stats.append(
                {
                    "code": code,
                    "n": len(code_signed),
                    "gross_mean": mean(code_signed),
                }
            )

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    # dailyized residual illustration (research only)
    net_daily = (gross - one_way_cost) if gross is not None else None
    trade_stats = trade_stats_report(
        signed_returns,
        hold_days=h,
        one_way_cost=float(one_way_cost),
        amortize_cost=True,
        trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
    )

    n_code_days = len(holding_records)
    n_codes = len(bars_by_code)
    all_dates = {r["date"] for r in holding_records}
    n_trading_days = len(all_dates)
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=n_codes,
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )

    return {
        "signal_id": SIGNAL_ID_MULTI_DAY_HOLD,
        "hypothesis_class": CLASS_MULTI_DAY_HOLD,
        "hold_days": h,
        "rebalance_mode": rebalance_mode,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "net_daily_flip_cost_illustration": net_daily,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_rebalance_events": n_rebalance,
        "n_signed_returns": len(signed_returns),
        "n_codes": n_codes,
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        "trade_stats": trade_stats,
        "per_code_sample": per_code_stats[:10],
        "holding_records": holding_records,
        "non_null": n_active,
        "non_null_rate": (
            float(n_active) / float(n_code_days) if n_code_days else None
        ),
        **_freeze(),
        "note": (
            f"Multi-day hold n={h}: sticky fixed_horizon; "
            "gross = mean(sign * R_hold); net = gross - one_way/hold_days. "
            "Occurrence = activation rate (not count alone). "
            "trade_stats = t/Sharpe/winrate on hold nets. "
            "Not READY / not Mass."
        ),
    }


def evaluate_event_post_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    post_hold_days: int = DEFAULT_EVENT_POST_HOLD_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    period_start: str | None = None,
    period_end: str | None = None,
    entry_mode: str = EVENT_POST_ENTRY_MODE,
) -> dict[str, Any]:
    """Evaluate event_post: post-disclosure multi-day hold on surprise sign.

    Scores only on disclosure events within period. Entry is **PIT-safe**:
    DiscDate+DiscTime SoT → first session close that does not look ahead
    (after-close / missing DiscTime → next trading bar). Hold is close-to-close
    over ``post_hold_days`` sessions from that entry.
    """
    h = int(post_hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    signed_returns: list[float] = []
    n_events = 0
    n_scored = 0
    n_no_surprise = 0
    n_no_bar_match = 0
    n_same_day_entry = 0
    n_next_session_entry = 0
    holding_records: list[dict[str, Any]] = []

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < h + 1:
            continue
        date_to_idx = {str(d)[:10]: i for i, (d, _) in enumerate(pairs_l)}
        closes = [c for _, c in pairs_l]
        events = list(events_by_code.get(code) or [])
        for ev in events:
            disc = str(ev.get("disc_date") or "")[:10]
            if not disc:
                continue
            if period_start and disc < str(period_start)[:10]:
                continue
            if period_end and disc > str(period_end)[:10]:
                continue
            n_events += 1
            surprise, s_meta = earnings_surprise_proxy(
                eps=ev.get("eps"),
                feps=ev.get("feps"),
                prior_eps=ev.get("prior_eps"),
            )
            # Prefer envelope available_at / event_time when present (dataset SoT)
            disc_time = ev.get("disc_time")
            event_time = ev.get("event_time") or ev.get("available_at")
            idx, entry_date, entry_meta = event_post_entry_bar_index(
                date_to_idx,
                disc_date=disc,
                disc_time=disc_time,
                event_time=str(event_time) if event_time else None,
                entry_mode=entry_mode,
            )
            if idx is None or entry_date is None:
                n_no_bar_match += 1
                holding_records.append(
                    {
                        "date": None,
                        "code": code,
                        "sign": None,
                        "disc_date": disc,
                        "disc_time": disc_time,
                        "surprise": surprise,
                        "entry_meta": entry_meta,
                        "skip": "no_eligible_entry_bar",
                    }
                )
                continue
            if entry_date == disc:
                n_same_day_entry += 1
            else:
                n_next_session_entry += 1
            rec = compute_event_post_signal(
                surprise=surprise,
                is_event_day=True,
                is_trading_day=1.0,
                post_hold_days=h,
                code=code,
                date=entry_date,
                disc_date=disc,
                as_of=entry_meta.get("available_at"),
                extra_meta={
                    "surprise_meta": s_meta,
                    "entry_meta": entry_meta,
                },
            )
            val = rec.get("value")
            holding_records.append(
                {
                    "date": entry_date,
                    "code": code,
                    "sign": val,
                    "disc_date": disc,
                    "disc_time": disc_time,
                    "surprise": surprise,
                    "entry_meta": entry_meta,
                    "available_at": entry_meta.get("available_at"),
                }
            )
            if val is None or val == 0.0:
                n_no_surprise += 1
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=idx)
            if fwd is None:
                continue
            n_scored += 1
            signed_returns.append(float(val) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    trade_stats = trade_stats_report(
        signed_returns,
        hold_days=h,
        one_way_cost=float(one_way_cost),
        amortize_cost=True,
        trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
    )
    n_codes = len(bars_by_code)
    all_bar_dates: set[str] = set()
    for pairs in bars_by_code.values():
        for d, _ in pairs:
            all_bar_dates.add(str(d)[:10])
    if period_start:
        all_bar_dates = {d for d in all_bar_dates if d >= str(period_start)[:10]}
    if period_end:
        all_bar_dates = {d for d in all_bar_dates if d <= str(period_end)[:10]}
    n_trading_days = len(all_bar_dates)
    n_code_days = n_trading_days * n_codes if n_trading_days and n_codes else 0
    occ = occurrence_rate_event_post(
        n_events=n_events,
        n_scored=n_scored,
        n_trading_days=n_trading_days,
        n_codes=n_codes,
        n_code_days=n_code_days,
        trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
        min_events_per_code_year=MIN_EVENTS_PER_CODE_YEAR,
        min_events_per_trading_day=MIN_EVENTS_PER_TRADING_DAY,
    )
    return {
        "signal_id": SIGNAL_ID_EVENT_POST,
        "hypothesis_class": CLASS_EVENT_POST,
        "post_hold_days": h,
        "entry_mode": str(entry_mode),
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_scored,
        "n_signed_returns": len(signed_returns),
        "n_events": n_events,
        "n_no_surprise": n_no_surprise,
        "n_no_bar_match": n_no_bar_match,
        "n_same_day_entry": n_same_day_entry,
        "n_next_session_entry": n_next_session_entry,
        "n_codes": n_codes,
        "n_trading_days": n_trading_days,
        "n_code_days": n_code_days,
        "occurrence": occ,
        "trade_stats": trade_stats,
        "holding_records": holding_records,
        "non_null": n_scored,
        "non_null_rate": (
            float(n_scored) / float(n_events) if n_events else None
        ),
        **_freeze(),
        "note": (
            f"Event-post hold={h}d PIT entry (mode={entry_mode}) on fins "
            "DiscDate+DiscTime surprise proxy (+ fins_earnings_date thicken "
            "when merged; no invent surprise). Entry = first session close "
            "not looking ahead of availability. Occurrence = rate not count. "
            "trade_stats = t/Sharpe/winrate on hold nets. Gaps → skip. "
            "Not READY / not Mass."
        ),
    }
