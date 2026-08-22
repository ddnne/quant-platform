"""COMPLETE-21 min feature compute (pure helpers + PIT).

Calls :func:`require_feature_datasets` (permanent DEFER fail-closed) before
any PIT read. Dataset tuples are COMPLETE 21 only. No READY / Mass / GO.
"""

from __future__ import annotations

from typing import Any

from .complete21_min_parsers import (
    _as_float_or_none,
    _latest_fins_eps_bps,
    _latest_short_ratio_row,
    _parse_close_rows,
    _parse_futures_volume_rows,
    _parse_margin_interest_rows,
    _parse_volume_rows,
)
from .dataset_guard import require_feature_datasets
from .types import FeatureOutput


def volume_change_from_pairs(
    pairs: list[tuple[str, float]],
) -> tuple[float | None, dict[str, Any]]:
    """Compute 1d volume change from sorted ``(date, volume)`` pairs."""
    if len(pairs) < 2:
        return None, {
            "rows_seen": len(pairs),
            "reason": "insufficient history (need >= 2 volumes)",
        }
    (d0, v0), (d1, v1) = pairs[-2], pairs[-1]
    if v0 == 0:
        return None, {
            "rows_seen": len(pairs),
            "reason": "zero prior volume",
            "prior_date": d0,
            "last_date": d1,
        }
    return (v1 - v0) / v0, {
        "rows_seen": len(pairs),
        "prior_date": d0,
        "prior_volume": v0,
        "last_date": d1,
        "last_volume": v1,
    }


def simple_return_from_closes(
    pairs: list[tuple[str, float]],
) -> tuple[float | None, dict[str, Any]]:
    """One-session simple return from sorted ``(date, close)`` pairs."""
    if len(pairs) < 2:
        return None, {
            "rows_seen": len(pairs),
            "reason": "insufficient history (need >= 2 closes)",
        }
    (d0, c0), (d1, c1) = pairs[-2], pairs[-1]
    if c0 == 0:
        return None, {
            "rows_seen": len(pairs),
            "reason": "zero prior close",
            "prior_date": d0,
            "last_date": d1,
        }
    return (c1 - c0) / c0, {
        "rows_seen": len(pairs),
        "prior_date": d0,
        "prior_close": c0,
        "last_date": d1,
        "last_close": c1,
    }


def topix_relative_from_returns(
    equity_ret: float | None,
    topix_ret: float | None,
) -> tuple[float | None, dict[str, Any]]:
    """Equity return minus TOPIX return; None if either leg is missing."""
    if equity_ret is None or topix_ret is None:
        return None, {
            "reason": "missing equity or topix return leg",
            "equity_ret": equity_ret,
            "topix_ret": topix_ret,
        }
    return equity_ret - topix_ret, {
        "equity_ret": equity_ret,
        "topix_ret": topix_ret,
    }


def disclosure_flag_from_count(n_rows: int) -> tuple[float, dict[str, Any]]:
    """1.0 if any disclosure row is visible, else 0.0."""
    flag = 1.0 if n_rows > 0 else 0.0
    return flag, {"rows_seen": n_rows, "flag": flag}


def margin_interest_change_from_pairs(
    pairs: list[tuple[str, float]],
) -> tuple[float | None, dict[str, Any]]:
    """Session-over-session change of total margin interest (Long+Short)."""
    if len(pairs) < 2:
        return None, {
            "rows_seen": len(pairs),
            "reason": "insufficient history (need >= 2 margin observations)",
        }
    (d0, m0), (d1, m1) = pairs[-2], pairs[-1]
    if m0 == 0:
        return None, {
            "rows_seen": len(pairs),
            "reason": "zero prior margin interest",
            "prior_date": d0,
            "last_date": d1,
        }
    return (m1 - m0) / m0, {
        "rows_seen": len(pairs),
        "prior_date": d0,
        "prior_margin": m0,
        "last_date": d1,
        "last_margin": m1,
    }


def short_ratio_level_from_components(
    short_with_res: float | None,
    short_no_res: float | None,
    sell_ex_short: float | None,
) -> tuple[float | None, dict[str, Any]]:
    """Short ratio = (with-restriction + no-restriction) / sell-ex-short.

    Uses J-Quants short-ratio fields ``ShrtWithResVa`` / ``ShrtNoResVa`` /
    ``SellExShortVa``. Returns None when the denominator is missing or zero.
    """
    if sell_ex_short is None or sell_ex_short == 0:
        return None, {
            "reason": "missing or zero SellExShortVa denominator",
            "short_with_res": short_with_res,
            "short_no_res": short_no_res,
            "sell_ex_short": sell_ex_short,
        }
    with_r = 0.0 if short_with_res is None else float(short_with_res)
    no_r = 0.0 if short_no_res is None else float(short_no_res)
    ratio = (with_r + no_r) / float(sell_ex_short)
    return ratio, {
        "short_with_res": with_r,
        "short_no_res": no_r,
        "sell_ex_short": float(sell_ex_short),
        "ratio": ratio,
    }


def is_trading_day_from_division(
    holiday_division: str | int | None,
) -> tuple[float | None, dict[str, Any]]:
    """1.0 if holiday_division marks a trading day (\"1\"), else 0.0.

    Returns None when no calendar observation is present.
    """
    if holiday_division is None or holiday_division == "":
        return None, {
            "reason": "no calendar row / holiday_division",
            "holiday_division": holiday_division,
        }
    div = str(holiday_division).strip()
    flag = 1.0 if div == "1" else 0.0
    return flag, {"holiday_division": div, "flag": flag}


def repo_rate_level_from_rows(
    rows: list[dict[str, Any]],
) -> tuple[float | None, dict[str, Any]]:
    """Latest non-null rate from sorted repo-rate rows (by as_of_date)."""
    ranked: list[tuple[str, float, dict[str, Any]]] = []
    for r in rows:
        rate = r.get("rate")
        d = r.get("as_of_date") or r.get("date")
        if rate is None or d is None:
            continue
        try:
            ranked.append((str(d)[:10], float(rate), r))
        except (TypeError, ValueError):
            continue
    if not ranked:
        return None, {
            "rows_seen": len(rows),
            "reason": "no repo rate observations visible",
        }
    ranked.sort(key=lambda x: x[0])
    d, rate, last = ranked[-1]
    return rate, {
        "rows_seen": len(rows),
        "as_of_date": d,
        "tenor": last.get("tenor"),
        "rate_type": last.get("rate_type"),
        "rate": rate,
    }


def repo_rate_change_from_rows(
    rows: list[dict[str, Any]],
    *,
    lookback: int = 5,
) -> tuple[float | None, dict[str, Any]]:
    """Change in Tokyo repo rate over ``lookback`` distinct as_of_date steps.

    Uses the latest visible rate minus the rate ``lookback`` distinct dates
    earlier (per-date last observation). Returns None when insufficient
    history is PIT-visible.
    """
    lb = int(lookback)
    if lb < 1:
        return None, {
            "rows_seen": len(rows),
            "lookback": lb,
            "reason": "lookback must be >= 1",
        }
    by_date: dict[str, float] = {}
    for r in rows:
        rate = r.get("rate")
        d = r.get("as_of_date") or r.get("date")
        if rate is None or d is None:
            continue
        try:
            by_date[str(d)[:10]] = float(rate)
        except (TypeError, ValueError):
            continue
    dates = sorted(by_date.keys())
    if len(dates) < lb + 1:
        return None, {
            "rows_seen": len(rows),
            "n_dates": len(dates),
            "lookback": lb,
            "reason": f"insufficient repo history (need >= {lb + 1} dates)",
        }
    d_last = dates[-1]
    d_base = dates[-1 - lb]
    cur = by_date[d_last]
    base = by_date[d_base]
    return cur - base, {
        "rows_seen": len(rows),
        "n_dates": len(dates),
        "lookback": lb,
        "as_of_date": d_last,
        "base_date": d_base,
        "rate": cur,
        "base_rate": base,
        "delta": cur - base,
    }


def margin_alert_flag_from_count(n_rows: int) -> tuple[float, dict[str, Any]]:
    """1.0 if any margin-alert row is visible, else 0.0."""
    flag = 1.0 if n_rows > 0 else 0.0
    return flag, {"rows_seen": n_rows, "flag": flag}


def futures_activity_from_volume_pairs(
    pairs: list[tuple[str, float]],
) -> tuple[float | None, dict[str, Any]]:
    """Sum volumes on the latest date as a futures activity proxy.

    ``pairs`` are sorted ``(date, volume)`` observations (any contract).
    Returns None when no volume observations are present.
    """
    if not pairs:
        return None, {
            "rows_seen": 0,
            "reason": "no futures volume observations visible",
        }
    last_date = pairs[-1][0]
    total = 0.0
    n_on_date = 0
    for d, v in pairs:
        if d == last_date:
            total += v
            n_on_date += 1
    return total, {
        "rows_seen": len(pairs),
        "activity_date": last_date,
        "contracts_on_date": n_on_date,
        "volume_sum": total,
    }


_VOLUME_DATASETS = ("equities_bars_daily",)


def _volume_change_1d(ctx) -> FeatureOutput:
    require_feature_datasets(
        _VOLUME_DATASETS, context="feature volume_change_1d"
    )
    code = ctx.get_input("code")
    res = ctx.get_equity_bars_daily(code=code)
    pairs = _parse_volume_rows(res.rows)
    value, meta = volume_change_from_pairs(pairs)
    meta = {**meta, "code": code, "datasets": list(_VOLUME_DATASETS)}
    return FeatureOutput(value=value, metadata=meta)


_TOPIX_REL_DATASETS = ("equities_bars_daily", "indices_bars_daily_topix")


def _topix_relative_1d(ctx) -> FeatureOutput:
    require_feature_datasets(
        _TOPIX_REL_DATASETS, context="feature topix_relative_1d"
    )
    code = ctx.get_input("code")
    bar_res = ctx.get_equity_bars_daily(code=code)
    eq_pairs = _parse_close_rows(bar_res.rows)
    equity_ret, eq_meta = simple_return_from_closes(eq_pairs)

    topix_res = ctx.get_jquants_records(dataset="indices_bars_daily_topix")
    tx_pairs = _parse_close_rows(topix_res.rows)
    topix_ret, tx_meta = simple_return_from_closes(tx_pairs)

    value, rel_meta = topix_relative_from_returns(equity_ret, topix_ret)
    meta = {
        "code": code,
        "datasets": list(_TOPIX_REL_DATASETS),
        "equity": eq_meta,
        "topix": tx_meta,
        **rel_meta,
    }
    return FeatureOutput(value=value, metadata=meta)


_DISC_DATASETS = ("fins_summary",)


def _disclosure_flag_fins(ctx) -> FeatureOutput:
    require_feature_datasets(
        _DISC_DATASETS, context="feature disclosure_flag_fins"
    )
    code = ctx.get_input("code")
    res = ctx.get_jquants_records(dataset="fins_summary", code=code)
    n = len(res.rows) if res is not None and getattr(res, "rows", None) is not None else 0
    value, meta = disclosure_flag_from_count(n)
    meta = {**meta, "code": code, "datasets": list(_DISC_DATASETS)}
    return FeatureOutput(value=value, metadata=meta)


_MARGIN_DATASETS = ("markets_margin_interest",)


def _margin_interest_change_1d(ctx) -> FeatureOutput:
    require_feature_datasets(
        _MARGIN_DATASETS, context="feature margin_interest_change_1d"
    )
    code = ctx.get_input("code")
    res = ctx.get_jquants_records(dataset="markets_margin_interest", code=code)
    pairs = _parse_margin_interest_rows(res.rows)
    value, meta = margin_interest_change_from_pairs(pairs)
    meta = {
        **meta,
        "code": code,
        "datasets": list(_MARGIN_DATASETS),
        "metric": "LongVol+ShrtVol",
    }
    return FeatureOutput(value=value, metadata=meta)


_SHORT_RATIO_DATASETS = ("markets_short_ratio",)


def _short_ratio_level(ctx) -> FeatureOutput:
    require_feature_datasets(
        _SHORT_RATIO_DATASETS, context="feature short_ratio_level"
    )
    section = ctx.get_input("section")
    res = ctx.get_jquants_records(dataset="markets_short_ratio")
    row = _latest_short_ratio_row(res.rows, section=str(section))
    if row is None:
        return FeatureOutput(
            value=None,
            metadata={
                "section": section,
                "datasets": list(_SHORT_RATIO_DATASETS),
                "rows_seen": len(res.rows) if res is not None else 0,
                "reason": "no short_ratio row for section at as_of",
            },
        )
    value, ratio_meta = short_ratio_level_from_components(
        row.get("ShrtWithResVa"),
        row.get("ShrtNoResVa"),
        row.get("SellExShortVa"),
    )
    meta = {
        "section": section,
        "datasets": list(_SHORT_RATIO_DATASETS),
        "date": row.get("Date") or row.get("date"),
        **ratio_meta,
    }
    return FeatureOutput(value=value, metadata=meta)


_CALENDAR_DATASETS = ("markets_calendar",)


def _is_trading_day(ctx) -> FeatureOutput:
    require_feature_datasets(
        _CALENDAR_DATASETS, context="feature is_trading_day"
    )
    # Optional override; default is calendar date of as_of.
    date = ctx.get_input("date", None)
    if date is None:
        date = str(ctx.as_of)[:10]
    else:
        date = str(date)[:10]
    res = ctx.get_market_calendar(from_date=date, to_date=date)
    rows = res.rows if res is not None and getattr(res, "rows", None) else []
    if not rows:
        value, meta = is_trading_day_from_division(None)
    else:
        # Prefer an explicit trading-day hit if multiple rows exist.
        divisions = [r.get("holiday_division") for r in rows]
        if any(str(d).strip() == "1" for d in divisions if d is not None):
            value, meta = is_trading_day_from_division("1")
        else:
            value, meta = is_trading_day_from_division(divisions[0])
    meta = {
        **meta,
        "date": date,
        "datasets": list(_CALENDAR_DATASETS),
        "rows_seen": len(rows),
    }
    return FeatureOutput(value=value, metadata=meta)


_REPO_DATASETS = ("jsda_tokyo_repo_rates",)


def _repo_rate_level(ctx) -> FeatureOutput:
    require_feature_datasets(
        _REPO_DATASETS, context="feature repo_rate_level"
    )
    tenor = ctx.get_input("tenor", None)
    rate_type = ctx.get_input("rate_type", None)
    kwargs: dict[str, Any] = {}
    if tenor is not None:
        kwargs["tenor"] = tenor
    if rate_type is not None:
        kwargs["rate_type"] = rate_type
    res = ctx.get_jsda_repo_rates(**kwargs)
    rows = res.rows if res is not None and getattr(res, "rows", None) else []
    value, meta = repo_rate_level_from_rows(rows)
    meta = {
        **meta,
        "datasets": list(_REPO_DATASETS),
        "tenor_filter": tenor,
        "rate_type_filter": rate_type,
    }
    return FeatureOutput(value=value, metadata=meta)


def _repo_rate_change(ctx) -> FeatureOutput:
    require_feature_datasets(
        _REPO_DATASETS, context="feature repo_rate_change"
    )
    lookback = int(ctx.get_input("lookback", 5) or 5)
    tenor = ctx.get_input("tenor", None)
    rate_type = ctx.get_input("rate_type", None)
    kwargs: dict[str, Any] = {}
    if tenor is not None:
        kwargs["tenor"] = tenor
    if rate_type is not None:
        kwargs["rate_type"] = rate_type
    res = ctx.get_jsda_repo_rates(**kwargs)
    rows = res.rows if res is not None and getattr(res, "rows", None) else []
    value, meta = repo_rate_change_from_rows(rows, lookback=lookback)
    meta = {
        **meta,
        "datasets": list(_REPO_DATASETS),
        "tenor_filter": tenor,
        "rate_type_filter": rate_type,
    }
    return FeatureOutput(value=value, metadata=meta)


_RETURN_C21_DATASETS = ("equities_bars_daily",)


def _return_1d_c21(ctx) -> FeatureOutput:
    require_feature_datasets(
        _RETURN_C21_DATASETS, context="feature return_1d_c21"
    )
    code = ctx.get_input("code")
    res = ctx.get_equity_bars_daily(code=code)
    pairs = _parse_close_rows(res.rows)
    value, meta = simple_return_from_closes(pairs)
    meta = {
        **meta,
        "code": code,
        "datasets": list(_RETURN_C21_DATASETS),
        "export_of": "return_1d",
        "path": "complete21_min",
    }
    return FeatureOutput(value=value, metadata=meta)


_MARGIN_ALERT_DATASETS = ("markets_margin_alert",)


def _margin_alert_flag(ctx) -> FeatureOutput:
    require_feature_datasets(
        _MARGIN_ALERT_DATASETS, context="feature margin_alert_flag"
    )
    code = ctx.get_input("code")
    res = ctx.get_jquants_records(dataset="markets_margin_alert", code=code)
    n = len(res.rows) if res is not None and getattr(res, "rows", None) is not None else 0
    value, meta = margin_alert_flag_from_count(n)
    meta = {**meta, "code": code, "datasets": list(_MARGIN_ALERT_DATASETS)}
    return FeatureOutput(value=value, metadata=meta)


_FUTURES_DATASETS = ("derivatives_bars_daily_futures",)


def _futures_activity_proxy(ctx) -> FeatureOutput:
    require_feature_datasets(
        _FUTURES_DATASETS, context="feature futures_activity_proxy"
    )
    code = ctx.get_input("code", None)
    kwargs: dict[str, Any] = {"dataset": "derivatives_bars_daily_futures"}
    if code is not None:
        kwargs["code"] = code
    res = ctx.get_jquants_records(**kwargs)
    rows = res.rows if res is not None and getattr(res, "rows", None) else []
    pairs = _parse_futures_volume_rows(rows)
    value, meta = futures_activity_from_volume_pairs(pairs)
    meta = {
        **meta,
        "code": code,
        "datasets": list(_FUTURES_DATASETS),
        "metric": "volume_sum_latest_date",
    }
    return FeatureOutput(value=value, metadata=meta)


_FUND_VALUE_DATASETS = ("fins_summary", "equities_bars_daily")


def fundamental_value_score_from_parts(
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


def _fundamental_value_score(ctx) -> FeatureOutput:
    require_feature_datasets(
        _FUND_VALUE_DATASETS, context="feature fundamental_value_score"
    )
    code = ctx.get_input("code")
    bar_res = ctx.get_equity_bars_daily(code=code)
    closes = _parse_close_rows(
        list(bar_res.rows) if bar_res is not None and bar_res.rows else []
    )
    if not closes:
        return FeatureOutput(
            value=None,
            metadata={"code": code, "reason": "no PIT close"},
        )
    last_date, last_close = closes[-1]
    fins_res = ctx.get_jquants_records(dataset="fins_summary", code=code)
    rows = list(fins_res.rows) if fins_res is not None and fins_res.rows else []
    eps, bps, fins_meta = _latest_fins_eps_bps(rows)
    value, meta = fundamental_value_score_from_parts(
        close=last_close, eps=eps, bps=bps
    )
    meta = {
        **meta,
        **fins_meta,
        "code": code,
        "last_date": last_date,
        "datasets": list(_FUND_VALUE_DATASETS),
    }
    return FeatureOutput(value=value, metadata=meta)
