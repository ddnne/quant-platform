"""Small, parameterized ratio-factor atoms for personal DRAFT research.

The two definitions in this module deliberately stay below the strategy
layer.  They return one numeric observation (or ``None``) and leave
cross-sectional ranking, industry neutralization, and portfolio construction
to the closed StrategySpec DSL.

``retrospective_price_ratio`` uses the vendor-restated ``AdjustmentClose``
series.  It never falls back to raw close.  Its turnover mode uses the
vendor's unadjusted ``TurnoverValue`` field because no adjusted turnover-value
field exists; it never substitutes volume.

``pit_fundamental_ratio`` selects one latest PIT-visible statement payload and
never mixes numerator and denominator from different rows.  The only second
row it may use is the prior comparable statement for a growth calculation.
Per-share value modes retain the existing retrospective split blackout, so
the combined feature is personal DRAFT only even though statement visibility
is PIT-gated.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import median
from typing import Any, Mapping

from price_basis import PERSONAL_RETROSPECTIVE_ADJUSTED

from .complete21_min_parsers import _retrospective_split_safety, _row_payload
from .dataset_guard import require_feature_datasets
from .registry import register
from .types import FeatureDefinition, FeatureInput, FeatureOutput, FeatureVersion


PRICE_RATIO_MODES = frozenset(
    {
        "return_ratio",
        "short_long_momentum",
        "realized_vol_ratio",
        "turnover_ratio",
        "market_cap",
    }
)
FUNDAMENTAL_RATIO_MODES = frozenset(
    {
        "book_to_price",
        "earnings_to_price",
        "roe",
        "net_margin",
        "asset_turnover",
        "equity_ratio",
        "sales_growth",
        "assets_growth",
        "total_assets",
        "net_sales",
    }
)

_PRICE_DATASETS = ("equities_bars_daily",)
_FUNDAMENTAL_DATASETS = ("equities_bars_daily", "fins_summary")

_FINS_ALIASES: dict[str, tuple[str, ...]] = {
    # J-Quants v2 short names followed by v1 long names.
    "book_value_per_share": ("BPS", "BookValuePerShare"),
    "earnings_per_share": ("EPS", "EarningsPerShare"),
    "roe": ("ROE", "ReturnOnEquity"),
    "sales": ("Sales", "NetSales"),
    "profit": ("NP", "Profit"),
    "total_assets": ("TA", "TotalAssets"),
    "equity": ("Eq", "Equity"),
    "equity_ratio": ("EqAR", "EquityToAssetRatio"),
    "period_type": ("CurPerType", "TypeOfCurrentPeriod"),
    "period_end": ("CurPerEn", "CurrentPeriodEndDate"),
    "document_type": ("DocType", "TypeOfDocument"),
    "disclosed_date": ("DiscDate", "DisclosedDate"),
    "disclosed_time": ("DiscTime", "DisclosedTime"),
}

_STATEMENT_VALUE_KEYS = tuple(
    key
    for name in (
        "book_value_per_share",
        "earnings_per_share",
        "roe",
        "sales",
        "profit",
        "total_assets",
        "equity",
        "equity_ratio",
    )
    for key in _FINS_ALIASES[name]
)


def _finite_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _pick(
    payload: Mapping[str, Any], alias_name: str
) -> tuple[float | None, str | None]:
    for key in _FINS_ALIASES[alias_name]:
        if key not in payload:
            continue
        value = _finite_number(payload.get(key))
        if value is not None:
            return value, key
    return None, None


def _pick_text(payload: Mapping[str, Any], alias_name: str) -> str | None:
    for key in _FINS_ALIASES[alias_name]:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _validate_windows(short_n: Any, long_n: Any) -> tuple[int, int]:
    if type(short_n) is not int or type(long_n) is not int:
        raise ValueError("short_n and long_n must be JSON integers")
    short = short_n
    long = long_n
    if short < 2 or long < 3 or short >= long:
        raise ValueError("ratio windows require 2 <= short_n < long_n")
    return short, long


def _bar_rows(ctx: Any, *, code: str, required: int) -> list[dict[str, Any]]:
    result = ctx.get_equity_bars_daily(code=code, latest_n=required)
    rows = list(result.rows) if result is not None and result.rows else []
    rows.sort(key=lambda row: str(row.get("date") or ""))
    return rows


def _adjusted_closes(
    rows: list[dict[str, Any]], *, code: str
) -> tuple[list[tuple[str, float]], dict[str, Any] | None]:
    parsed: list[tuple[str, float]] = []
    for row in rows:
        day = str(row.get("date") or "")[:10]
        if not day:
            continue
        value = row.get("adjustment_close")
        if value is None:
            return [], {
                "reason": "adjustment_close missing; raw fallback disabled",
                "event_date": day,
                "event_code": str(row.get("code") or code),
            }
        close = _finite_number(value)
        if close is None or close <= 0.0:
            return [], {
                "reason": "adjustment_close non-positive or invalid",
                "event_date": day,
                "event_code": str(row.get("code") or code),
            }
        parsed.append((day, close))
    return parsed, None


def _sample_volatility(prices: list[float]) -> float | None:
    returns = [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices))]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (
        len(returns) - 1
    )
    return math.sqrt(variance) * math.sqrt(252.0)


def _retrospective_price_ratio(ctx: Any) -> FeatureOutput:
    require_feature_datasets(
        _PRICE_DATASETS, context="feature retrospective_price_ratio"
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
    required = (
        1
        if mode == "market_cap"
        else long_n
        if mode == "turnover_ratio"
        else long_n + 1
    )
    rows = _bar_rows(ctx, code=code, required=required)
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
    }
    if len(rows) < required:
        return FeatureOutput(
            value=None,
            metadata={
                **common,
                "reason": f"insufficient history (need >= {required} bars)",
            },
        )

    rows = rows[-required:]
    if mode == "market_cap":
        payload = _row_payload(rows[-1])
        market_cap = _finite_number(rows[-1].get("market_cap"))
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
                    "latest_PIT_visible_typed_bar"
                    if market_cap_field == "market_cap"
                    else "latest_PIT_visible_bar_payload"
                ),
                "relative_size_semantics": (
                    "level_only; relative size exists only after sector33 "
                    "percentile ranking by FactorRankRule"
                ),
                "market_cap_proxy": False,
                "last_date": str(rows[-1].get("date") or "")[:10],
            },
        )

    if mode == "turnover_ratio":
        turnovers: list[float] = []
        for row in rows:
            value = _finite_number(row.get("turnover_value"))
            if value is None or value < 0.0:
                return FeatureOutput(
                    value=None,
                    metadata={
                        **common,
                        "reason": (
                            "missing or invalid TurnoverValue; no volume fallback"
                        ),
                        "event_date": str(row.get("date") or "")[:10],
                        "turnover_source": "TurnoverValue_unadjusted",
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
                    "reason": "zero long-window median TurnoverValue",
                    "turnover_source": "TurnoverValue_unadjusted",
                },
            )
        return FeatureOutput(
            value=short_value / long_value,
            metadata={
                **common,
                "short_median": short_value,
                "long_median": long_value,
                "turnover_source": "TurnoverValue_unadjusted",
                "adjusted_turnover_available": False,
                "volume_fallback": False,
                "first_date": str(rows[0].get("date") or "")[:10],
                "last_date": str(rows[-1].get("date") or "")[:10],
            },
        )

    closes, close_error = _adjusted_closes(rows, code=code)
    if close_error is not None:
        return FeatureOutput(
            value=None,
            metadata={
                **common,
                **close_error,
                "price_source": "vendor_adjustment_close",
                "raw_fallback": False,
            },
        )
    if len(closes) < required:
        return FeatureOutput(
            value=None,
            metadata={
                **common,
                "reason": "bar date missing or invalid inside requested window",
                "price_source": "vendor_adjustment_close",
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
        # Compare disjoint recent and preceding horizons on the same
        # per-session scale.  Dividing two trailing gross returns directly
        # would cancel today's price and accidentally measure only the older
        # sub-period.
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
                    "price_source": "vendor_adjustment_close",
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
            "price_source": "vendor_adjustment_close",
            "first_date": closes[0][0],
            "last_date": closes[-1][0],
        },
    )


def _statement_sort_key(
    row: Mapping[str, Any], payload: Mapping[str, Any]
) -> tuple[str, str, str, str]:
    disclosed_date = _pick_text(payload, "disclosed_date") or str(
        row.get("event_time") or ""
    )[:10]
    disclosed_time = _pick_text(payload, "disclosed_time") or ""
    return (
        disclosed_date[:10],
        disclosed_time,
        str(row.get("available_at") or row.get("event_time") or ""),
        str(row.get("natural_key") or ""),
    )


def _statement_observations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for row in rows:
        payload = _row_payload(row)
        if not payload or not any(
            _finite_number(payload.get(key)) is not None
            for key in _STATEMENT_VALUE_KEYS
        ):
            continue
        observations.append(
            {
                "payload": payload,
                "sort_key": _statement_sort_key(row, payload),
                "available_at": str(row.get("available_at") or "") or None,
            }
        )
    observations.sort(key=lambda item: item["sort_key"])
    return observations


def _consolidation_kind(payload: Mapping[str, Any]) -> str:
    value = (_pick_text(payload, "document_type") or "").lower().replace("-", "")
    if "nonconsolidated" in value:
        return "nonconsolidated"
    if "consolidated" in value:
        return "consolidated"
    return "unspecified"


def _comparable_key(payload: Mapping[str, Any]) -> tuple[str, str] | None:
    period_type = _pick_text(payload, "period_type")
    if not period_type:
        return None
    return period_type.lower(), _consolidation_kind(payload)


def _ratio_or_none(
    numerator: float | None, denominator: float | None
) -> tuple[float | None, str | None]:
    if numerator is None:
        return None, "numerator missing or invalid"
    if denominator is None or denominator <= 0.0:
        return None, "denominator missing, zero, or invalid"
    return numerator / denominator, None


def _per_share_ratio(
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
    }
    if not anchor:
        return FeatureOutput(
            value=None,
            metadata={**common, "reason": "per-share metric has no split anchor"},
        )
    latest = ctx.get_equity_bars_daily(code=code, latest_n=1)
    latest_rows = list(latest.rows) if latest is not None and latest.rows else []
    if not latest_rows:
        return FeatureOutput(
            value=None, metadata={**common, "reason": "no PIT close"}
        )
    latest_row = latest_rows[-1]
    last_date = str(latest_row.get("date") or "")[:10]
    close = _finite_number(latest_row.get("close"))
    if not last_date or close is None or close <= 0.0:
        return FeatureOutput(
            value=None,
            metadata={**common, "reason": "raw close missing, zero, or invalid"},
        )
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
        "price_source": "raw_close_with_retrospective_split_blackout",
    }
    if not safe:
        metadata.setdefault("reason", "per_share_split_blackout")
        return FeatureOutput(value=None, metadata=metadata)
    return FeatureOutput(value=numerator / close, metadata=metadata)


def _pit_fundamental_ratio(ctx: Any) -> FeatureOutput:
    require_feature_datasets(
        _FUNDAMENTAL_DATASETS, context="feature pit_fundamental_ratio"
    )
    code = str(ctx.get_input("code")).strip()
    mode = str(ctx.get_input("mode")).strip()
    if mode not in FUNDAMENTAL_RATIO_MODES:
        raise ValueError(
            f"mode must be one of {sorted(FUNDAMENTAL_RATIO_MODES)!r}, got {mode!r}"
        )
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
        return _per_share_ratio(
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


RetrospectivePriceRatio: FeatureDefinition = register(
    FeatureDefinition(
        id="retrospective_price_ratio",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code", "mode", "short_n", "long_n"),
            as_of_rule="session_close",
        ),
        description=(
            "Parameterized DRAFT-only ratio from vendor AdjustmentClose: "
            "long return, short/long gross momentum, realized-vol ratio, or "
            "short/long median TurnoverValue. TurnoverValue is unadjusted "
            "because J-Quants has no adjusted turnover-value field; no volume "
            "fallback. Market-cap mode prefers the positive typed market_cap "
            "field, with official payload aliases as compatibility input, "
            "from the latest PIT-visible bar for later sector33 ranking."
        ),
        compute=_retrospective_price_ratio,
        dataset_dependencies=_PRICE_DATASETS,
        tags=(
            "price",
            "ratio",
            "volatility",
            "turnover",
            "retrospective",
            "personal",
        ),
        intended_role="signal",
        status="approved",
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
    )
)


PitFundamentalRatio: FeatureDefinition = register(
    FeatureDefinition(
        id="pit_fundamental_ratio",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code", "mode"),
            as_of_rule="session_close",
        ),
        description=(
            "PIT-visible latest-statement fundamental ratio using J-Quants "
            "v1/v2 long/short aliases without cross-row field mixing. Growth "
            "alone uses one prior comparable row. Per-share price modes use "
            "the personal retrospective split blackout, so v1 is DRAFT-only. "
            "Total-assets and net-sales modes are positive levels for later "
            "sector33 percentile FactorRankRule ranking, never market-cap proxies."
        ),
        compute=_pit_fundamental_ratio,
        dataset_dependencies=_FUNDAMENTAL_DATASETS,
        tags=("fundamentals", "ratio", "value", "quality", "growth", "personal"),
        intended_role="signal",
        status="approved",
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
    )
)


__all__ = [
    "FUNDAMENTAL_RATIO_MODES",
    "PRICE_RATIO_MODES",
    "PitFundamentalRatio",
    "RetrospectivePriceRatio",
]
