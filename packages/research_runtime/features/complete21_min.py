"""Minimal COMPLETE-21-only features (W49 / w0815ap_g2 T6).

All features:

* declare required datasets from COMPLETE 21 only;
* call :func:`require_feature_datasets` (permanent DEFER fail-closed) before
  any PIT read;
* stay ``status="candidate"`` — no READY / strategy default claim.

Implemented:

* ``volume_change_1d`` — one-session volume change from equity daily bars.
* ``topix_relative_1d`` — equity 1d return minus TOPIX 1d return.
* ``disclosure_flag_fins`` — binary flag if any ``fins_summary`` row is visible.
"""

from __future__ import annotations

from typing import Any

from price_basis import RAW

from .dataset_guard import require_feature_datasets
from .registry import register
from .types import FeatureDefinition, FeatureInput, FeatureOutput, FeatureVersion


# ---------------------------------------------------------------------------
# pure helpers (data-free unit tests)
# ---------------------------------------------------------------------------

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


def _parse_volume_rows(rows: list[dict[str, Any]]) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for r in rows:
        v = r.get("volume")
        d = r.get("date")
        if v is None or d is None:
            continue
        try:
            out.append((str(d), float(v)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def _parse_close_rows(rows: list[dict[str, Any]]) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for r in rows:
        c = r.get("close")
        d = r.get("date")
        if c is None or d is None:
            # jquants_records payload shape
            payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
            if c is None:
                c = payload.get("Close") or payload.get("close")
            if d is None:
                d = (
                    payload.get("Date")
                    or payload.get("date")
                    or r.get("event_time")
                )
                if d is not None:
                    d = str(d)[:10]
        if c is None or d is None:
            continue
        try:
            out.append((str(d)[:10], float(c)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


# ---------------------------------------------------------------------------
# volume_change_1d
# ---------------------------------------------------------------------------

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


VolumeChange1d: FeatureDefinition = register(
    FeatureDefinition(
        id="volume_change_1d",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "One-session volume change (COMPLETE 21: equities_bars_daily only). "
            "Returns None when fewer than two volumes are visible at as_of. "
            "Permanent DEFER datasets are rejected before PIT reads."
        ),
        compute=_volume_change_1d,
        tags=("volume", "daily", "complete21"),
        intended_role="signal",
        status="candidate",
        price_basis=None,
    )
)


# ---------------------------------------------------------------------------
# topix_relative_1d
# ---------------------------------------------------------------------------

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


TopixRelative1d: FeatureDefinition = register(
    FeatureDefinition(
        id="topix_relative_1d",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "Equity 1d return minus TOPIX 1d return "
            "(COMPLETE 21: equities_bars_daily + indices_bars_daily_topix). "
            "Permanent DEFER datasets are rejected before PIT reads."
        ),
        compute=_topix_relative_1d,
        tags=("return", "relative", "topix", "complete21"),
        intended_role="signal",
        status="candidate",
        price_basis=RAW,
    )
)


# ---------------------------------------------------------------------------
# disclosure_flag_fins
# ---------------------------------------------------------------------------

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


DisclosureFlagFins: FeatureDefinition = register(
    FeatureDefinition(
        id="disclosure_flag_fins",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "Binary disclosure flag: 1.0 if any PIT-visible fins_summary row "
            "exists for code at as_of, else 0.0. COMPLETE 21 only "
            "(fins_summary). Permanent DEFER (e.g. fins_earnings_date) excluded."
        ),
        compute=_disclosure_flag_fins,
        tags=("disclosure", "fins", "flag", "complete21"),
        intended_role="signal",
        status="candidate",
        price_basis=None,
    )
)


__all__ = [
    "VolumeChange1d",
    "TopixRelative1d",
    "DisclosureFlagFins",
    "volume_change_from_pairs",
    "simple_return_from_closes",
    "topix_relative_from_returns",
    "disclosure_flag_from_count",
]
