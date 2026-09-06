"""Explicit AM-session feature identities for personal AM-signal / PM-fill.

These are new versioned identities. They do not change
``retrospective_price_ratio`` / ``pit_fundamental_ratio`` v1. Ordinary
``features.compute`` without the trusted AM session capability fails closed.
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from typing import Any, Mapping

from price_basis import PERSONAL_RETROSPECTIVE_ADJUSTED

from .complete21_min_parsers import _retrospective_split_safety, _row_payload
from .dataset_guard import require_feature_datasets
from .ratio_features import (
    FUNDAMENTAL_RATIO_MODES,
    PRICE_RATIO_MODES,
    _FUNDAMENTAL_DATASETS,
    _PRICE_DATASETS,
    _adjusted_closes,
    _comparable_key,
    _finite_number,
    _pick,
    _pick_text,
    _ratio_or_none,
    _sample_volatility,
    _statement_observations,
    _validate_windows,
)
from .registry import register
from .types import FeatureDefinition, FeatureInput, FeatureOutput, FeatureVersion

AM_SESSION_PRICE_RATIO_ID = "am_session_price_ratio"
AM_SESSION_FUNDAMENTAL_RATIO_ID = "am_session_fundamental_ratio"
AM_SESSION_FEATURE_IDS = frozenset(
    {AM_SESSION_PRICE_RATIO_ID, AM_SESSION_FUNDAMENTAL_RATIO_ID}
)
AM_SESSION_VIEW = "personal_retrospective_am_signal"
LAST_RETURN_INTERVAL = "prior PM/full -> D morning"


def _decision_date(ctx: Any) -> str:
    return str(getattr(ctx, "as_of", "") or "")[:10]


def _require_am_session_bars(result: Any) -> dict[str, Any]:
    metadata = dict(getattr(result, "metadata", None) or {})
    if metadata.get("session_view") != AM_SESSION_VIEW:
        raise ValueError(
            "AM session features require bound personal retrospective AM "
            "session daily bars"
        )
    return metadata


def _positive_price(value: Any) -> float | None:
    number = _finite_number(value)
    if number is None or number <= 0.0:
        return None
    return number


def _split_decision_rows(
    rows: list[dict[str, Any]], *, decision_date: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prior: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for row in rows:
        day = str(row.get("date") or "")[:10]
        if day == decision_date:
            current.append(row)
        elif day and day < decision_date:
            prior.append(row)
    return prior, current


def _missing_d_morning(common: dict[str, Any], *, reason: str) -> FeatureOutput:
    return FeatureOutput(
        value=None,
        metadata={
            **common,
            "reason": reason,
            "last_return_interval": LAST_RETURN_INTERVAL,
            "raw_fallback": False,
        },
    )


def _am_session_price_ratio(ctx: Any) -> FeatureOutput:
    require_feature_datasets(
        _PRICE_DATASETS, context="feature am_session_price_ratio"
    )
    code = str(ctx.get_input("code")).strip()
    mode = str(ctx.get_input("mode")).strip()
    if mode not in PRICE_RATIO_MODES:
        raise ValueError(
            f"mode must be one of {sorted(PRICE_RATIO_MODES)!r}, got {mode!r}"
        )
    short_n, long_n = _validate_windows(
        ctx.get_input("short_n"), ctx.get_input("long_n")
    )
    decision_date = _decision_date(ctx)
    required = (
        2
        if mode == "market_cap"
        else long_n
        if mode == "turnover_ratio"
        else long_n + 1
    )
    result = ctx.get_equity_bars_daily(code=code, latest_n=required)
    _require_am_session_bars(result)
    rows = list(result.rows) if result is not None and result.rows else []
    rows.sort(key=lambda row: str(row.get("date") or ""))
    prior_rows, d_rows = _split_decision_rows(rows, decision_date=decision_date)
    common: dict[str, Any] = {
        "code": code,
        "mode": mode,
        "short_n": short_n,
        "long_n": long_n,
        "rows_seen": len(rows),
        "datasets": list(_PRICE_DATASETS),
        "time_semantics": "retrospective_not_point_in_time",
        "lifecycle": "DRAFT_only",
        "live_trading_eligible": False,
        "last_return_interval": LAST_RETURN_INTERVAL,
        "session_view": AM_SESSION_VIEW,
    }
    if len(rows) < required:
        return FeatureOutput(
            value=None,
            metadata={
                **common,
                "reason": f"insufficient history (need >= {required} bars)",
            },
        )

    if mode == "market_cap":
        if not prior_rows:
            return FeatureOutput(
                value=None,
                metadata={
                    **common,
                    "reason": "no strictly-prior PIT market cap",
                    "market_cap_lag": "D-1",
                    "relative_size_semantics": (
                        "level_only; relative size exists only after sector33 "
                        "percentile ranking by FactorRankRule"
                    ),
                },
            )
        size_row = prior_rows[-1]
        size_date = str(size_row.get("date") or "")[:10]
        payload = _row_payload(size_row)
        market_cap = _finite_number(size_row.get("market_cap"))
        market_cap_field = "market_cap" if market_cap is not None else None
        if market_cap is None:
            for field in ("MarketCapitalization", "MarketCap", "MktCap"):
                candidate = _finite_number(payload.get(field))
                if candidate is not None:
                    market_cap = candidate
                    market_cap_field = field
                    break
        if market_cap is None or market_cap <= 0.0:
            return FeatureOutput(
                value=None,
                metadata={
                    **common,
                    "reason": "market cap missing, zero, or invalid",
                    "market_cap_lag": "D-1",
                    "market_cap_date": size_date,
                    "relative_size_semantics": (
                        "level_only; relative size exists only after sector33 "
                        "percentile ranking by FactorRankRule"
                    ),
                },
            )
        return FeatureOutput(
            value=market_cap,
            metadata={
                **common,
                "value_field": market_cap_field,
                "value_source": (
                    "strictly_prior_PIT_visible_typed_bar"
                    if market_cap_field == "market_cap"
                    else "strictly_prior_PIT_visible_bar_payload"
                ),
                "relative_size_semantics": (
                    "level_only; relative size exists only after sector33 "
                    "percentile ranking by FactorRankRule"
                ),
                "market_cap_proxy": False,
                "market_cap_lag": "D-1",
                "market_cap_date": size_date,
                "last_date": size_date,
            },
        )

    window = rows[-required:]
    if mode == "turnover_ratio":
        if not d_rows:
            return _missing_d_morning(
                common,
                reason="missing D morning turnover_value; no volume or Va fallback",
            )
        turnovers: list[float] = []
        for row in window:
            value = _finite_number(row.get("morning_turnover_value"))
            if value is None or value < 0.0:
                return FeatureOutput(
                    value=None,
                    metadata={
                        **common,
                        "reason": (
                            "missing or invalid morning_turnover_value; "
                            "no volume or full-day Va fallback"
                        ),
                        "event_date": str(row.get("date") or "")[:10],
                        "turnover_source": "MVa_morning_turnover_value",
                    },
                )
            turnovers.append(value)
        short_value = median(turnovers[-short_n:])
        long_value = median(turnovers[-long_n:])
        if long_value == 0.0:
            return FeatureOutput(
                value=None,
                metadata={
                    **common,
                    "reason": "zero long-window median morning_turnover_value",
                    "turnover_source": "MVa_morning_turnover_value",
                },
            )
        return FeatureOutput(
            value=short_value / long_value,
            metadata={
                **common,
                "short_median": short_value,
                "long_median": long_value,
                "turnover_source": "MVa_morning_turnover_value",
                "adjusted_turnover_available": False,
                "volume_fallback": False,
                "full_day_va_fallback": False,
                "first_date": str(window[0].get("date") or "")[:10],
                "last_date": str(window[-1].get("date") or "")[:10],
            },
        )

    d_morning = _positive_price(d_rows[-1].get("adjustment_close")) if d_rows else None
    if d_morning is None:
        return _missing_d_morning(
            common,
            reason="missing D morning adjustment_close; raw/AdjC fallback disabled",
        )
    closes, close_error = _adjusted_closes(window, code=code)
    if close_error is not None:
        return FeatureOutput(
            value=None,
            metadata={
                **common,
                **close_error,
                "price_source": "prior_pm_full_and_d_morning_adjustment_close",
                "raw_fallback": False,
            },
        )
    if len(closes) < required:
        return FeatureOutput(
            value=None,
            metadata={
                **common,
                "reason": "bar date missing or invalid inside requested window",
                "price_source": "prior_pm_full_and_d_morning_adjustment_close",
                "raw_fallback": False,
            },
        )
    prices = [value for _, value in closes]
    if mode == "return_ratio":
        value = prices[-1] / prices[-long_n - 1] - 1.0
        detail = {
            "base_adjustment_close": prices[-long_n - 1],
            "last_adjustment_close": prices[-1],
        }
    elif mode == "short_long_momentum":
        recent_gross = prices[-1] / prices[-short_n - 1]
        preceding_gross = prices[-short_n - 1] / prices[-long_n - 1]
        recent_daily_gross = recent_gross ** (1.0 / short_n)
        preceding_daily_gross = preceding_gross ** (1.0 / (long_n - short_n))
        value = recent_daily_gross / preceding_daily_gross - 1.0
        detail = {
            "recent_gross_return": recent_gross,
            "preceding_gross_return": preceding_gross,
            "recent_daily_gross": recent_daily_gross,
            "preceding_daily_gross": preceding_daily_gross,
            "comparison": "recent_vs_disjoint_preceding_per_session",
        }
    else:
        short_vol = _sample_volatility(prices[-(short_n + 1) :])
        long_vol = _sample_volatility(prices[-(long_n + 1) :])
        if short_vol is None or long_vol is None or long_vol == 0.0:
            return FeatureOutput(
                value=None,
                metadata={
                    **common,
                    "reason": "invalid or zero realized-volatility denominator",
                    "short_volatility": short_vol,
                    "long_volatility": long_vol,
                    "price_source": "prior_pm_full_and_d_morning_adjustment_close",
                },
            )
        value = short_vol / long_vol
        detail = {
            "short_volatility": short_vol,
            "long_volatility": long_vol,
        }
    return FeatureOutput(
        value=value,
        metadata={
            **common,
            **detail,
            "price_source": "prior_pm_full_and_d_morning_adjustment_close",
            "first_date": closes[0][0],
            "last_date": closes[-1][0],
        },
    )


def _am_per_share_ratio(
    ctx: Any,
    *,
    code: str,
    observation: Mapping[str, Any],
    numerator: float,
    numerator_key: str,
    mode: str,
) -> FeatureOutput:
    payload = observation["payload"]
    anchor = _pick_text(payload, "period_end") or _pick_text(
        payload, "disclosed_date"
    )
    decision_date = _decision_date(ctx)
    common = {
        "code": code,
        "mode": mode,
        "numerator": numerator,
        "numerator_field": numerator_key,
        "statement_period_end": _pick_text(payload, "period_end"),
        "disclosure_date": _pick_text(payload, "disclosed_date"),
        "statement_available_at": observation.get("available_at"),
        "datasets": list(_FUNDAMENTAL_DATASETS),
        "time_semantics": "retrospective_not_point_in_time",
        "lifecycle": "DRAFT_only",
        "live_trading_eligible": False,
        "session_view": AM_SESSION_VIEW,
        "price_lag": "strictly_prior_session",
    }
    if not anchor:
        return FeatureOutput(
            value=None,
            metadata={**common, "reason": "per-share metric has no split anchor"},
        )
    latest = ctx.get_equity_bars_daily(code=code, latest_n=5)
    _require_am_session_bars(latest)
    latest_rows = list(latest.rows) if latest is not None and latest.rows else []
    prior_rows, _d_rows = _split_decision_rows(
        latest_rows, decision_date=decision_date
    )
    price_row = None
    close = None
    for row in reversed(prior_rows):
        candidate = _positive_price(row.get("close"))
        if candidate is not None:
            price_row = row
            close = candidate
            break
    if price_row is None or close is None:
        return FeatureOutput(
            value=None,
            metadata={
                **common,
                "reason": "no strictly-prior-session raw close",
            },
        )
    last_date = str(price_row.get("date") or "")[:10]
    try:
        safety_start = (
            date.fromisoformat(anchor[:10]) - timedelta(days=31)
        ).isoformat()
    except ValueError:
        return FeatureOutput(
            value=None,
            metadata={**common, "reason": "invalid split-safety anchor"},
        )
    safety = ctx.get_equity_bars_daily(
        code=code, from_event=safety_start, to_event=last_date
    )
    safety_rows = list(safety.rows) if safety is not None and safety.rows else []
    safe, evidence = _retrospective_split_safety(safety_rows, anchor=anchor[:10])
    metadata = {
        **common,
        **evidence,
        "split_safety_anchor": anchor[:10],
        "last_date": last_date,
        "raw_close": close,
        "raw_close_date": last_date,
        "price_source": "strictly_prior_session_raw_close_with_retrospective_split_blackout",
    }
    if not safe:
        metadata.setdefault("reason", "per_share_split_blackout")
        return FeatureOutput(value=None, metadata=metadata)
    return FeatureOutput(value=numerator / close, metadata=metadata)


def _am_session_fundamental_ratio(ctx: Any) -> FeatureOutput:
    require_feature_datasets(
        _FUNDAMENTAL_DATASETS, context="feature am_session_fundamental_ratio"
    )
    code = str(ctx.get_input("code")).strip()
    mode = str(ctx.get_input("mode")).strip()
    if mode not in FUNDAMENTAL_RATIO_MODES:
        raise ValueError(
            f"mode must be one of {sorted(FUNDAMENTAL_RATIO_MODES)!r}, got {mode!r}"
        )
    if mode in {"book_to_price", "earnings_to_price"}:
        probe = ctx.get_equity_bars_daily(code=code, latest_n=2)
        _require_am_session_bars(probe)
    result = ctx.get_jquants_records(dataset="fins_summary", code=code)
    rows = list(result.rows) if result is not None and result.rows else []
    observations = _statement_observations(rows)
    common: dict[str, Any] = {
        "code": code,
        "mode": mode,
        "rows_seen": len(rows),
        "statement_rows_seen": len(observations),
        "datasets": list(_FUNDAMENTAL_DATASETS),
        "time_semantics": "retrospective_not_point_in_time",
        "lifecycle": "DRAFT_only",
        "live_trading_eligible": False,
        "session_view": AM_SESSION_VIEW,
    }
    if not observations:
        return FeatureOutput(
            value=None,
            metadata={**common, "reason": "no PIT-visible financial statement"},
        )
    current = observations[-1]
    payload = current["payload"]
    current_meta = {
        **common,
        "statement_period_end": _pick_text(payload, "period_end"),
        "statement_period_type": _pick_text(payload, "period_type"),
        "statement_document_type": _pick_text(payload, "document_type"),
        "disclosure_date": _pick_text(payload, "disclosed_date"),
        "statement_available_at": current.get("available_at"),
    }

    if mode in {"book_to_price", "earnings_to_price"}:
        alias_name = (
            "book_value_per_share"
            if mode == "book_to_price"
            else "earnings_per_share"
        )
        numerator, key = _pick(payload, alias_name)
        if numerator is None or key is None:
            return FeatureOutput(
                value=None,
                metadata={**current_meta, "reason": f"{alias_name} missing"},
            )
        return _am_per_share_ratio(
            ctx,
            code=code,
            observation=current,
            numerator=numerator,
            numerator_key=key,
            mode=mode,
        )

    if mode == "roe":
        value, field = _pick(payload, "roe")
        return FeatureOutput(
            value=value,
            metadata={
                **current_meta,
                "value_field": field,
                "ratio_source": "reported",
                **({"reason": "roe missing or invalid"} if value is None else {}),
            },
        )

    if mode in {"total_assets", "net_sales"}:
        alias_name = "total_assets" if mode == "total_assets" else "sales"
        value, field = _pick(payload, alias_name)
        if value is None or value <= 0.0:
            return FeatureOutput(
                value=None,
                metadata={
                    **current_meta,
                    "reason": f"{alias_name} missing, zero, or invalid",
                    "relative_size_semantics": (
                        "level_only; relative size exists only after "
                        "sector33 percentile ranking by FactorRankRule"
                    ),
                },
            )
        return FeatureOutput(
            value=value,
            metadata={
                **current_meta,
                "value_field": field,
                "ratio_source": "same_statement_row_level",
                "relative_size_semantics": (
                    "level_only; relative size exists only after sector33 "
                    "percentile ranking by FactorRankRule"
                ),
                "market_cap_proxy": False,
            },
        )

    if mode in {"sales_growth", "assets_growth"}:
        alias_name = "sales" if mode == "sales_growth" else "total_assets"
        current_value, current_field = _pick(payload, alias_name)
        comparable = _comparable_key(payload)
        period_end = _pick_text(payload, "period_end")
        if comparable is None or not period_end:
            return FeatureOutput(
                value=None,
                metadata={
                    **current_meta,
                    "reason": "current statement lacks comparable period identity",
                },
            )
        prior: Mapping[str, Any] | None = None
        for candidate in reversed(observations[:-1]):
            prior_payload = candidate["payload"]
            if _pick_text(prior_payload, "period_end") == period_end:
                continue
            if _comparable_key(prior_payload) == comparable:
                prior = candidate
                break
        if prior is None:
            return FeatureOutput(
                value=None,
                metadata={**current_meta, "reason": "no prior comparable statement"},
            )
        prior_payload = prior["payload"]
        prior_value, prior_field = _pick(prior_payload, alias_name)
        ratio, reason = _ratio_or_none(current_value, prior_value)
        return FeatureOutput(
            value=None if ratio is None else ratio - 1.0,
            metadata={
                **current_meta,
                "current_value": current_value,
                "current_field": current_field,
                "prior_value": prior_value,
                "prior_field": prior_field,
                "prior_period_end": _pick_text(prior_payload, "period_end"),
                "prior_disclosure_date": _pick_text(
                    prior_payload, "disclosed_date"
                ),
                **({"reason": reason} if reason else {}),
            },
        )

    if mode == "net_margin":
        numerator_name, denominator_name = "profit", "sales"
    elif mode == "asset_turnover":
        numerator_name, denominator_name = "sales", "total_assets"
    else:
        direct, direct_field = _pick(payload, "equity_ratio")
        if direct is not None:
            return FeatureOutput(
                value=direct,
                metadata={
                    **current_meta,
                    "value_field": direct_field,
                    "ratio_source": "reported",
                },
            )
        numerator_name, denominator_name = "equity", "total_assets"

    numerator, numerator_field = _pick(payload, numerator_name)
    denominator, denominator_field = _pick(payload, denominator_name)
    value, reason = _ratio_or_none(numerator, denominator)
    return FeatureOutput(
        value=value,
        metadata={
            **current_meta,
            "numerator": numerator,
            "numerator_field": numerator_field,
            "denominator": denominator,
            "denominator_field": denominator_field,
            "ratio_source": "same_statement_row",
            **({"reason": reason} if reason else {}),
        },
    )


AmSessionPriceRatio: FeatureDefinition = register(
    FeatureDefinition(
        id=AM_SESSION_PRICE_RATIO_ID,
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code", "mode", "short_n", "long_n"),
            as_of_rule="morning_close",
        ),
        description=(
            "AM-session DRAFT ratio from prior PM/full vendor AdjustmentClose "
            "plus D MAdjC. Missing D MAdjC returns None for that code. "
            "Turnover uses morning_turnover_value (MVa) on every window row. "
            "Size uses strictly-prior (D-1) PIT market cap. Ordinary compute "
            "without the trusted AM session capability fails closed."
        ),
        compute=_am_session_price_ratio,
        dataset_dependencies=_PRICE_DATASETS,
        tags=(
            "price",
            "ratio",
            "volatility",
            "turnover",
            "retrospective",
            "personal",
            "am_session",
        ),
        intended_role="signal",
        status="approved",
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
    )
)


AmSessionFundamentalRatio: FeatureDefinition = register(
    FeatureDefinition(
        id=AM_SESSION_FUNDAMENTAL_RATIO_ID,
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code", "mode"),
            as_of_rule="morning_close",
        ),
        description=(
            "AM-session PIT-visible latest-statement fundamental ratio. "
            "Per-share price modes use the most recent strictly-prior-session "
            "raw close (D-1 or earlier), never D MAdjC. Ordinary compute "
            "without the trusted AM session capability fails closed."
        ),
        compute=_am_session_fundamental_ratio,
        dataset_dependencies=_FUNDAMENTAL_DATASETS,
        tags=(
            "fundamentals",
            "ratio",
            "value",
            "quality",
            "growth",
            "personal",
            "am_session",
        ),
        intended_role="signal",
        status="approved",
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
    )
)



GOVERNED_AM_SESSION_BARS_ID = "governed_am_session_bars"
AM_DATASET_ID = "equities_bars_daily_am"


def _governed_am_session_bars(ctx: Any) -> FeatureOutput:
    """Declare the AM dataset; the engine is the Controlled reader."""
    del ctx
    return FeatureOutput(
        value=None,
        metadata={"dataset": AM_DATASET_ID, "engine_owned": True},
    )


GovernedAmSessionBars: FeatureDefinition = register(
    FeatureDefinition(
        id=GOVERNED_AM_SESSION_BARS_ID,
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="morning_close",
        ),
        description=(
            "Governed Controlled AM session bars from independent "
            "equities_bars_daily_am product provenance. Not inferred from "
            "daily-close MAdjC/AAdjC timestamps. Draft AM-session features "
            "remain on equities_bars_daily."
        ),
        compute=_governed_am_session_bars,
        dataset_dependencies=(AM_DATASET_ID,),
        tags=("price", "am_session", "controlled", "governed"),
        intended_role="signal",
        status="approved",
        price_basis="RAW",
    )
)


__all__ = [
    "AM_DATASET_ID",
    "AM_SESSION_FEATURE_IDS",
    "AM_SESSION_FUNDAMENTAL_RATIO_ID",
    "AM_SESSION_PRICE_RATIO_ID",
    "GOVERNED_AM_SESSION_BARS_ID",
    "AmSessionFundamentalRatio",
    "AmSessionPriceRatio",
    "GovernedAmSessionBars",
]
