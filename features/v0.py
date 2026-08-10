"""Built-in features: return_1d, momentum_n, volatility_n.

All three are pure functions of PIT daily bars at ``as_of``. Each requires
``code`` and reads bars through the context's PIT-scoped getter. They NEVER
see a row whose ``available_at > as_of`` — PIT guarantees it.

* :class:`Return1d` — one-session simple return (close-to-close).
* :class:`MomentumN` — N-session cumulative return (default N=20).
* :class:`VolatilityN` — N-session realized volatility of one-session returns
  (sample stdev, default N=20, annualized by sqrt(252)).

Each feature's ``compute`` returns ``FeatureOutput(value=None, ...)`` when
there isn't enough history at ``as_of`` — distinct from an exception.
"""

from __future__ import annotations

from typing import Any

from .registry import register
from .types import FeatureDefinition, FeatureInput, FeatureOutput, FeatureVersion


def _parse_close_rows(rows: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """Extract ``(date, close)`` pairs from PIT bar rows, dropping nulls."""
    out: list[tuple[str, float]] = []
    for r in rows:
        c = r.get("close")
        d = r.get("date")
        if c is None or d is None:
            continue
        try:
            out.append((str(d), float(c)))
        except (TypeError, ValueError):
            continue
    # PIT rows are already ordered by date ascending; sort defensively.
    out.sort(key=lambda x: x[0])
    return out


# --- return_1d --------------------------------------------------------------

def _return_1d(ctx) -> FeatureOutput:
    code = ctx.inputs["code"]
    res = ctx.get_equity_bars_daily(code=code)
    rows = _parse_close_rows(res.rows)
    if len(rows) < 2:
        return FeatureOutput(
            value=None,
            metadata={
                "code": code,
                "rows_seen": len(rows),
                "reason": "insufficient history (need >= 2 closes)",
            },
        )
    (d0, c0), (d1, c1) = rows[-2], rows[-1]
    if c0 == 0:
        return FeatureOutput(
            value=None,
            metadata={
                "code": code, "rows_seen": len(rows),
                "reason": "zero prior close",
            },
        )
    r = (c1 - c0) / c0
    return FeatureOutput(
        value=r,
        metadata={
            "code": code,
            "rows_seen": len(rows),
            "prior_date": d0,
            "prior_close": c0,
            "last_date": d1,
            "last_close": c1,
        },
    )


Return1d: FeatureDefinition = register(
    FeatureDefinition(
        id="return_1d",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "One-session simple return (close-to-close) observable at as_of. "
            "Returns None when fewer than two closes are visible."
        ),
        compute=_return_1d,
        tags=("price", "daily", "return"),
    )
)


# --- momentum_n -------------------------------------------------------------

def _momentum_n(ctx) -> FeatureOutput:
    code = ctx.inputs["code"]
    n = int(ctx.inputs.get("n", 20))
    if n < 1:
        return FeatureOutput(
            value=None, metadata={"code": code, "reason": "n must be >= 1"},
        )
    res = ctx.get_equity_bars_daily(code=code)
    rows = _parse_close_rows(res.rows)
    if len(rows) < n + 1:
        return FeatureOutput(
            value=None,
            metadata={
                "code": code, "rows_seen": len(rows),
                "n": n,
                "reason": f"insufficient history (need >= {n + 1} closes)",
            },
        )
    base_close = rows[-n - 1][1]
    last_close = rows[-1][1]
    last_date = rows[-1][0]
    base_date = rows[-n - 1][0]
    if base_close == 0:
        return FeatureOutput(
            value=None,
            metadata={"code": code, "rows_seen": len(rows), "reason": "zero base close"},
        )
    m = (last_close - base_close) / base_close
    return FeatureOutput(
        value=m,
        metadata={
            "code": code,
            "rows_seen": len(rows),
            "n": n,
            "base_date": base_date,
            "base_close": base_close,
            "last_date": last_date,
            "last_close": last_close,
        },
    )


MomentumN: FeatureDefinition = register(
    FeatureDefinition(
        id="momentum_n",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            optional_kwargs={"n": 20},
            as_of_rule="session_close",
        ),
        description=(
            "N-session cumulative return (close-to-close). Default N=20. "
            "Returns None when fewer than N+1 closes are visible at as_of."
        ),
        compute=_momentum_n,
        tags=("price", "daily", "momentum"),
    )
)


# --- volatility_n -----------------------------------------------------------

def _volatility_n(ctx) -> FeatureOutput:
    import math
    code = ctx.inputs["code"]
    n = int(ctx.inputs.get("n", 20))
    if n < 2:
        return FeatureOutput(
            value=None,
            metadata={"code": code, "reason": "n must be >= 2 for stdev"},
        )
    res = ctx.get_equity_bars_daily(code=code)
    rows = _parse_close_rows(res.rows)
    if len(rows) < n + 1:
        return FeatureOutput(
            value=None,
            metadata={
                "code": code, "rows_seen": len(rows), "n": n,
                "reason": f"insufficient history (need >= {n + 1} closes)",
            },
        )
    # Take the last n+1 closes -> n one-session returns.
    tail = [c for _, c in rows[-(n + 1):]]
    rets = [(tail[i] - tail[i - 1]) / tail[i - 1]
            for i in range(1, len(tail)) if tail[i - 1] != 0]
    if len(rets) < 2:
        return FeatureOutput(
            value=None,
            metadata={"code": code, "rows_seen": len(rows), "reason": "zero base"},
        )
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)  # sample stdev
    sd = math.sqrt(var)
    ann = sd * math.sqrt(252)
    return FeatureOutput(
        value=ann,
        metadata={
            "code": code,
            "rows_seen": len(rows),
            "n": n,
            "sample_stdev": sd,
            "annualized": ann,
            "first_date": rows[-(n + 1)][0],
            "last_date": rows[-1][0],
        },
    )


VolatilityN: FeatureDefinition = register(
    FeatureDefinition(
        id="volatility_n",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            optional_kwargs={"n": 20},
            as_of_rule="session_close",
        ),
        description=(
            "N-session realized volatility (sample stdev of one-session "
            "returns, annualized by sqrt(252)). Default N=20. Returns None "
            "when fewer than N+1 closes are visible at as_of."
        ),
        compute=_volatility_n,
        tags=("price", "daily", "volatility"),
    )
)


__all__ = ["Return1d", "MomentumN", "VolatilityN"]
