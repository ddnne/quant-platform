"""The core backtest engine — a trusted black box over the PIT Data API.

``run_backtest`` walks trading days (from the PIT market calendar) and, on
each decision day *D*, hands the strategy a :class:`~core.strategy_protocol.BarContext`
built entirely from facts the engine read through ``pit.get_*`` at *D*'s
decision ``as_of``. Orders become fills according to the chosen
:class:`~core.execution.ExecutionMode`; costs come from a
:class:`~core.costs.CostModel`; the result always carries reproducibility
metadata.

Hard rules enforced here and by the data boundary:

* **Facts enter only via PIT.** This module imports :mod:`pit` (and
  :mod:`ingestion.common.timeutil` for date helpers) and nothing else for
  data. No ``sqlite3`` / ``storage`` / HTTP. A static test pins this.
* **Every read is PIT-gated on the decision ``as_of``** — look-ahead is
  impossible because PIT hides rows whose ``available_at > as_of``.
* **A signal on *D* cannot fill on *D* under ``next_close``** — orders decided
  on *D* fill at the next session's close, so seeing *D*'s close is harmless.

The result is deterministic given identical inputs (no wall-clock time, no
randomness) — see :mod:`core.result`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Mapping

import features
import pit
from pit.query import resolve_db_path
from price_basis import RAW, PriceBasis, require_supported_price_basis

from .costs import (
    CostModel,
    LeverageFinancingModel,
    ShortFinancingModel,
    standard_cost,
)
from .execution import close_as_of, get_mode
from .metrics import compute_metrics
from .result import BacktestResult
from .strategy_protocol import Bar, BarContext, OrderIntent, Position
from .universe import load_master

# Bumped per Phase 3 handoff. Surfaced in every result's metadata so a consumer
# can tell which engine contract a given backtest obeys.
# 0.6.1 — W85 short-leg financing (repo + fixed spread) optional charge.
# 0.6.2 — W86 daily repo series + leverage financing (repo only; no short-spread
#         double-count) optional charge.
CORE_ENGINE_VERSION = "0.6.2"

# J-Quants HolidayDivision: "1" == trading day (exchange open).
_TRADING_HOLIDAY_DIVISION = "1"


def describe_strategy(strategy: Any) -> tuple[str, dict[str, Any]]:
    """Best-effort deterministic identity of ``strategy`` for metadata.

    A strategy may expose ``strategy_id`` (str) and ``params`` (dict); both
    default gracefully (class name / empty dict) so any object implementing
    :class:`~core.strategy_protocol.Strategy` works.
    """
    sid = getattr(strategy, "strategy_id", None) or type(strategy).__name__
    params = getattr(strategy, "params", None)
    if not isinstance(params, dict):
        params = {}
    return sid, dict(params)


def _params_hash(params: dict[str, Any]) -> str:
    """Short stable hash of a strategy params dict (JSON, sorted keys)."""
    blob = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _make_feature_accessor(as_of: str, db_path: Any):
    """Bind the trusted PIT scope used by one decision context."""
    def compute_feature(
        feature_id: str, *, version: str | None = None, **inputs: Any
    ) -> Any:
        # Declarative strategies always supply ``version``. Resolve that exact
        # definition before entering compute so a later registry addition can
        # never change a persisted StrategySpec's meaning. Hand-written local
        # strategies may continue to omit it and intentionally follow latest.
        definition = (
            features.get(feature_id, version=version)
            if version is not None
            else feature_id
        )
        return features.compute(
            definition,
            as_of=as_of,
            db_path=db_path,
            **inputs,
        )

    return compute_feature


def _bar_from_row(row: dict[str, Any]) -> Bar:
    """Map a PIT daily-bar row to the narrow :class:`Bar` the strategy sees."""
    return Bar(
        code=row.get("code") or "",
        date=row.get("date") or "",
        open=row.get("open"),
        high=row.get("high"),
        low=row.get("low"),
        close=row.get("close"),
        volume=row.get("volume"),
        adjustment_close=row.get("adjustment_close"),
    )


def _bar_price(bar: Bar, *, price_basis: PriceBasis) -> float | None:
    """Return a bar price under the runtime's explicit price-basis contract.

    Phase 6 enables ``RAW`` only.  The vendor ``adjustment_close`` column is
    retained on :class:`Bar` for inspection, but is never selected implicitly:
    an adjusted historical series can be retrospectively restated and is not
    PIT-safe until its adjustment factors are versioned as-of.
    """
    if price_basis != RAW:  # validated at entry; defensive against misuse
        raise ValueError(f"unsupported runtime price basis: {price_basis!r}")
    return bar.close


def _shift_date(date_str: str, days: int) -> str:
    """``YYYY-MM-DD`` +/- ``days`` (JST calendar arithmetic)."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (d + timedelta(days=days)).strftime("%Y-%m-%d")


def _load_snapshot(
    as_of: str,
    codes: set[str],
    to_date: str,
    lookback_days: int,
    *,
    db_path: Any,
    price_basis: PriceBasis,
) -> dict[str, dict[str, Any]]:
    """PIT-visible recent bars per code at ``as_of``, via ``get_equity_bars_daily``.

    Returns ``{code: {"close": float|None, "bars": [Bar, ...]}}``. PIT returns
    rows ordered by ``(code, date)``; ``close`` is the most recent visible
    raw close (``None`` if no bar is visible in the signal window). Only the
    requested universe + held codes are read and exposed. Portfolio valuation
    does not depend on this window; it uses the independent mark ledger.
    """
    snapshot: dict[str, dict[str, Any]] = {
        c: {"close": None, "bars": []} for c in codes
    }
    if not codes:
        return snapshot
    from_date = _shift_date(to_date, -lookback_days)
    result = pit.get_equity_bars_daily(
        as_of=as_of,
        from_event=from_date,
        to_event=to_date,
        codes=tuple(sorted(codes)),
        db_path=db_path,
    )
    for row in result.rows:
        code = row.get("code")
        if code not in snapshot:
            continue
        snapshot[code]["bars"].append(_bar_from_row(row))
    for entry in snapshot.values():
        bars = entry["bars"]
        entry["close"] = (
            _bar_price(bars[-1], price_basis=price_basis) if bars else None
        )
    return snapshot


def _session_prices(
    snapshot: dict[str, dict[str, Any]], session_date: str, *, price_basis: PriceBasis
) -> dict[str, float]:
    """Prices backed by a PIT-visible bar from exactly ``session_date``.

    A snapshot's general ``close`` is intentionally the latest visible mark,
    which can be older than the requested session during a suspension or data
    delay.  Execution must be stricter: an order can fill only when the actual
    fill session has a visible, positive price.
    """
    prices: dict[str, float] = {}
    for code, entry in snapshot.items():
        for bar in reversed(entry["bars"]):
            if bar.date != session_date:
                continue
            price = _bar_price(bar, price_basis=price_basis)
            if price is not None and price > 0:
                prices[code] = price
            break
    return prices


def _mark_equity(
    shares: dict[str, float], marks: dict[str, tuple[float, str]], cash: float
) -> float:
    """Total equity using the last PIT-safe valuation mark for each holding.

    The mark ledger is independent of the signal lookback window. A session
    without a bar carries the last mark; the engine never fabricates a price.
    A position normally cannot exist without a prior exact-session fill price,
    so the zero fallback is only a fail-closed defensive case.
    """
    positions_value = 0.0
    for code, qty in shares.items():
        if not qty:
            continue
        mark = marks.get(code)
        positions_value += qty * (mark[0] if mark is not None else 0.0)
    return cash + positions_value


def _update_marks(
    marks: dict[str, tuple[float, str]],
    session_prices: dict[str, float],
    session_date: str,
) -> None:
    """Advance valuation marks only from actual bars in ``session_date``."""
    for code, price in session_prices.items():
        marks[code] = (price, session_date)


def _equity_point(
    *,
    date: str,
    shares: dict[str, float],
    marks: dict[str, tuple[float, str]],
    cash: float,
) -> dict[str, Any]:
    """Build an auditable close-time equity row, including stale mark state."""
    equity = _mark_equity(shares, marks, cash)
    held = sorted(code for code, qty in shares.items() if qty)
    mark_dates = {code: marks[code][1] for code in held if code in marks}
    return {
        "date": date,
        "cash": cash,
        "positions_value": equity - cash,
        "equity": equity,
        "mark_dates": mark_dates,
        "stale_mark_codes": [
            code for code in held if code in marks and marks[code][1] != date
        ],
        "unpriced_codes": [code for code in held if code not in marks],
    }


def _resolve_targets(
    intents: list[OrderIntent],
    equity: float,
    prices: dict[str, float | None],
) -> dict[str, float]:
    """Convert target weights to target shares at the decision ``as_of``.

    Codes without a visible positive price are skipped (cannot size).
    Negative weights are permitted (simple short book for paper L-S).
    Gross |weight| is not hard-capped here — StrategySpec signed equal-weight
    keeps long and short books at ~50% each when both sides are present.
    """
    targets: dict[str, float] = {}
    for intent in intents:
        price = prices.get(intent.code)
        if price is None or price <= 0:
            continue
        weight = float(intent.target_weight)
        if not (weight == weight):  # NaN guard
            continue
        targets[intent.code] = weight * equity / price
    return targets


def _apply_fills(
    targets: dict[str, float],
    *,
    decision_date: str,
    fill_date: str,
    closes: dict[str, float],
    cost_model: CostModel,
    shares: dict[str, float],
    cash: float,
    trades: list[dict[str, Any]],
) -> tuple[dict[str, float], float, dict[str, float]]:
    """Trade each target to its desired shares at ``fill_date``'s close.

    Returns ``(shares, cash, leftover)`` where ``leftover`` holds target codes
    whose fill price was not (yet) visible — the caller carries them forward
    to a later session under ``next_close``. A target equal to the current
    position produces no trade (so a buy & hold strategy incurs no cost after
    its first fill).
    """
    leftover: dict[str, float] = {}
    for code, target_shares in targets.items():
        price = closes.get(code)
        if price is None or price <= 0:
            leftover[code] = target_shares
            continue
        current = shares.get(code, 0.0)
        delta = target_shares - current
        if abs(delta) < 1e-12:
            continue
        notional = delta * price
        cost = cost_model.one_way_cost(notional)
        new_shares = current + delta
        if abs(new_shares) < 1e-12:
            new_shares = 0.0
        shares[code] = new_shares
        cash -= notional + cost
        trades.append(
            {
                "decision_date": decision_date,
                "fill_date": fill_date,
                "code": code,
                "side": "buy" if delta > 0 else "sell",
                "shares": delta,
                "price": price,
                "notional": notional,
                "cost": cost,
            }
        )
    return shares, cash, leftover


def _trading_days(
    start: str, end: str, *, db_path: Any, calendar_as_of: str | None
) -> list[str]:
    """Trading days in ``[start, end]`` from the PIT market calendar.

    A day is a trading day when ``holiday_division == "1"`` (exchange open).
    The calendar is read at ``close_as_of(end)`` (or an explicit override); the
    calendar is published in advance, so it is visible by then. Non-trading
    days are skipped by construction.
    """
    as_of = calendar_as_of or close_as_of(end)
    result = pit.get_market_calendar(
        as_of=as_of, from_date=start, to_date=end, db_path=db_path
    )
    days = sorted(
        row["date"]
        for row in result.rows
        if row.get("holiday_division") == _TRADING_HOLIDAY_DIVISION
        and start <= row.get("date", "") <= end
    )
    return days


def _position_price(
    code: str,
    marks: Mapping[str, tuple[float, str]],
    closes: Mapping[str, float] | None = None,
) -> float | None:
    """Same-session close when available; else last PIT mark."""
    px = None
    if closes is not None:
        px = closes.get(code)
    if px is None or px <= 0:
        mark = marks.get(code)
        if mark is not None:
            px = mark[0]
    if px is None or px <= 0:
        return None
    return float(px)


def _short_market_value(
    shares: Mapping[str, float],
    marks: Mapping[str, tuple[float, str]],
    closes: Mapping[str, float] | None = None,
) -> float:
    """Absolute market value of short (negative share) positions.

    Prefers same-session ``closes`` when available; else last PIT mark.
    """
    total = 0.0
    for code, qty in shares.items():
        if qty >= 0:
            continue
        px = _position_price(code, marks, closes)
        if px is None:
            continue
        total += abs(float(qty)) * float(px)
    return total


def _long_market_value(
    shares: Mapping[str, float],
    marks: Mapping[str, tuple[float, str]],
    closes: Mapping[str, float] | None = None,
) -> float:
    """Market value of long (positive share) positions."""
    total = 0.0
    for code, qty in shares.items():
        if qty <= 0:
            continue
        px = _position_price(code, marks, closes)
        if px is None:
            continue
        total += float(qty) * float(px)
    return total


def _apply_daily_financing(
    *,
    date: str,
    shares: dict[str, float],
    marks: dict[str, tuple[float, str]],
    closes: dict[str, float],
    cash: float,
    short_financing: ShortFinancingModel | None,
    leverage_financing: LeverageFinancingModel | None,
    financing_events: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> tuple[float, int, int]:
    """Charge short + leverage financing; return (cash, short_gap, lev_gap).

    Short uses (repo + spread); leverage uses **repo only** on excess gross
    notional above equity — never re-applies short spread (no double-count).
    Both use pre-charge marks for notionals; cash is reduced after both costs
    are computed so order of application does not change bases.
    """
    short_gap = 0
    lev_gap = 0
    short_nv = _short_market_value(shares, marks, closes)
    long_nv = _long_market_value(shares, marks, closes)
    gross_nv = float(long_nv) + float(short_nv)
    equity = _mark_equity(shares, marks, cash)

    short_cost = 0.0
    if short_financing is not None and short_financing.enabled and short_nv > 0:
        short_cost, is_gap = short_financing.daily_cost(short_nv, date=date)
        financing_events.append(
            {
                "date": date,
                "short_notional": short_nv,
                "cost": float(short_cost),
                "is_gap": bool(is_gap),
                "side": "short_financing",
            }
        )
        if is_gap:
            short_gap = 1
        if short_cost > 0:
            trades.append(
                {
                    "decision_date": date,
                    "fill_date": date,
                    "code": "_short_financing",
                    "side": "short_financing",
                    "shares": 0.0,
                    "price": 0.0,
                    "notional": 0.0,
                    "cost": float(short_cost),
                    "short_notional": short_nv,
                }
            )

    lev_cost = 0.0
    if leverage_financing is not None and leverage_financing.enabled:
        lev_cost, is_gap = leverage_financing.daily_cost(
            gross_notional=gross_nv,
            equity=equity,
            date=date,
        )
        # Record only when there is excess leverage (gross > equity).
        excess = max(gross_nv - float(equity), 0.0) if equity > 0 else 0.0
        if excess > 0:
            financing_events.append(
                {
                    "date": date,
                    "gross_notional": gross_nv,
                    "equity": equity,
                    "excess_notional": excess,
                    "cost": float(lev_cost),
                    "is_gap": bool(is_gap),
                    "side": "leverage_financing",
                }
            )
            if is_gap:
                lev_gap = 1
        if lev_cost > 0:
            trades.append(
                {
                    "decision_date": date,
                    "fill_date": date,
                    "code": "_leverage_financing",
                    "side": "leverage_financing",
                    "shares": 0.0,
                    "price": 0.0,
                    "notional": 0.0,
                    "cost": float(lev_cost),
                    "gross_notional": gross_nv,
                    "excess_notional": excess,
                }
            )

    cash -= float(short_cost) + float(lev_cost)
    return cash, short_gap, lev_gap


def run_backtest(
    strategy: Any,
    start: str,
    end: str,
    *,
    db_path: Any = None,
    execution_mode: str = "next_close",
    cost_model: CostModel | None = None,
    short_financing: ShortFinancingModel | None = None,
    leverage_financing: LeverageFinancingModel | None = None,
    universe: tuple[str, ...] | list[str] | None = None,
    starting_capital: float = 1_000_000.0,
    lookback_days: int = 30,
    calendar_as_of: str | None = None,
    price_basis: str = RAW,
) -> BacktestResult:
    """Run a minimal PIT-only backtest of ``strategy`` over ``[start, end]``.

    Daily loop: on each trading day *D* the engine reads decision information
    via PIT at *D*'s decision ``as_of`` (session close for ``next_close``,
    session open for ``same_day_close``), builds a :class:`BarContext`, calls
    ``strategy.on_bar(ctx)``, and fills the resulting orders per the execution
    mode. See module docstring for the data-boundary and look-ahead guarantees.

    Args:
        strategy: Anything implementing ``on_bar(ctx) -> list[OrderIntent]``.
        start, end: Period bounds, ``YYYY-MM-DD`` (inclusive trading days).
        db_path: Structured DB path (defaults to PIT's default location).
        execution_mode: ``"next_close"`` (default) or ``"same_day_close"``.
        cost_model: :class:`CostModel` (defaults to 5 bps one-way standard).
        short_financing: Optional :class:`ShortFinancingModel` charging daily
            borrow on short market value = f(repo[t] + fixed spread). ``None``
            keeps prior long-only / no-borrow behaviour (default).
        leverage_financing: Optional :class:`LeverageFinancingModel` charging
            daily repo on excess gross leverage above 1× (repo only — does
            **not** re-apply short spread). ``None`` keeps prior behaviour.
        universe: Optional fixed code list; otherwise built per decision day
            from the PIT equity master as-of (anti-survivorship).
        starting_capital: Initial cash (defaults to 1,000,000 JPY).
        lookback_days: Signal bar-history window handed to the strategy each
            day. Portfolio valuation is independent and carries its last
            PIT-safe mark across sessions without a bar.
        calendar_as_of: Override the PIT ``as_of`` used to read the calendar.
        price_basis: Explicit price convention. Phase 6 enables ``"RAW"``.
            ``"PIT_ADJUSTED"`` fails closed until adjustment provenance is
            versioned and demonstrably PIT-safe.

    Returns:
        A :class:`BacktestResult` with equity curve, trade log, metrics, and
        reproducibility metadata.
    """
    mode = get_mode(execution_mode)
    resolved_price_basis = require_supported_price_basis(price_basis)
    resolved_db_path = resolve_db_path(db_path)
    cost_model = cost_model or standard_cost()
    fixed_universe = (
        tuple(sorted(universe)) if universe is not None else None
    )

    days = _trading_days(
        start,
        end,
        db_path=resolved_db_path,
        calendar_as_of=calendar_as_of,
    )
    if not days:
        raise ValueError(
            f"no trading days in [{start}, {end}] from the PIT market calendar "
            f"(read as_of={calendar_as_of or close_as_of(end)}); seed the "
            "calendar with holiday_division='1' rows first."
        )

    shares: dict[str, float] = {}
    cash = float(starting_capital)
    equity_curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    financing_events: list[dict[str, Any]] = []
    n_short_financing_gaps = 0
    n_leverage_financing_gaps = 0
    # Portfolio valuation is independent of the rolling signal window. Each
    # entry is (last PIT-visible exact-session price, that session's date).
    marks: dict[str, tuple[float, str]] = {}
    # next_close only: orders decided on day D fill on day D+1.
    pending: dict[str, Any] | None = None

    for d in days:
        # --- universe + held set for this day --------------------------------
        decision_as_of = mode.decision_as_of(d)
        master_d = load_master(decision_as_of, db_path=resolved_db_path)
        universe_d = fixed_universe if fixed_universe is not None else tuple(
            sorted(master_d.keys())
        )
        held = set(shares) | set(universe_d)

        # --- close snapshot at close(d): used for marking and fills ----------
        snap_close = _load_snapshot(
            close_as_of(d),
            held,
            d,
            lookback_days,
            db_path=resolved_db_path,
            price_basis=resolved_price_basis,
        )
        fill_closes = _session_prices(
            snap_close, d, price_basis=resolved_price_basis
        )

        # Under next_close the session close is inside the decision information
        # set, so exact-bar marks may advance before fills and valuation. Under
        # same_day_close the decision occurs at the open; marks advance only
        # after that decision and its close-time fills below.
        if mode.fill_offset == 1:
            _update_marks(marks, fill_closes, d)

        # --- apply pending next_close orders at d's close --------------------
        if mode.fill_offset == 1 and pending is not None:
            shares, cash, leftover = _apply_fills(
                pending["targets"],
                decision_date=pending["decision_date"],
                fill_date=d,
                closes=fill_closes,
                cost_model=cost_model,
                shares=shares,
                cash=cash,
                trades=trades,
            )
            pending = (
                {"targets": leftover, "decision_date": pending["decision_date"]}
                if leftover
                else None
            )

        # --- decision information set at decision_as_of ----------------------
        if mode.fill_offset == 1:
            snap_dec = snap_close  # next_close decides at close(d)
            decision_equity = _mark_equity(shares, marks, cash)
            # The next-close decision occurs after this close's fills and mark.
            # Short + leverage financing accrues on end-of-day book (post-fill).
            cash, s_gap, l_gap = _apply_daily_financing(
                date=d,
                shares=shares,
                marks=marks,
                closes=fill_closes,
                cash=cash,
                short_financing=short_financing,
                leverage_financing=leverage_financing,
                financing_events=financing_events,
                trades=trades,
            )
            n_short_financing_gaps += s_gap
            n_leverage_financing_gaps += l_gap
            equity_curve.append(
                _equity_point(
                    date=d, shares=shares, marks=marks, cash=cash
                )
            )
        else:
            # same_day_close decides at open(d): d's close is NOT yet visible.
            snap_dec = _load_snapshot(
                mode.decision_as_of(d),
                held,
                d,
                lookback_days,
                db_path=resolved_db_path,
                price_basis=resolved_price_basis,
            )
            decision_equity = _mark_equity(shares, marks, cash)
        prices_d = {c: snap_dec[c]["close"] for c in universe_d}
        bars_d = {c: tuple(snap_dec[c]["bars"]) for c in universe_d}
        positions = {
            c: Position(code=c, shares=qty) for c, qty in shares.items() if qty
        }
        ctx = BarContext(
            as_of=decision_as_of,
            date=d,
            universe=universe_d,
            positions=positions,
            cash=cash,
            equity=decision_equity,
            prices=prices_d,
            bars=bars_d,
            master=master_d,
        )
        # Bind a private callable rather than exposing a database field.  The
        # public BarContext shape remains facts + ctx.feature(...), while this
        # trusted closure owns both PIT scope inputs.
        object.__setattr__(
            ctx,
            "_feature_accessor",
            _make_feature_accessor(decision_as_of, resolved_db_path),
        )

        # --- ask the strategy -----------------------------------------------
        intents = strategy.on_bar(ctx)
        targets = _resolve_targets(intents, decision_equity, prices_d)

        # --- fill -----------------------------------------------------------
        if mode.fill_offset == 1:
            # A non-empty target set replaces any carried order.  With no new
            # replacement, preserve targets that could not fill this session.
            if targets:
                pending = {"targets": targets, "decision_date": d}
        else:
            # same_day_close fills immediately at d's close.
            shares, cash, _ = _apply_fills(
                targets,
                decision_date=d,
                fill_date=d,
                closes=fill_closes,
                cost_model=cost_model,
                shares=shares,
                cash=cash,
                trades=trades,
            )
            _update_marks(marks, fill_closes, d)
            cash, s_gap, l_gap = _apply_daily_financing(
                date=d,
                shares=shares,
                marks=marks,
                closes=fill_closes,
                cash=cash,
                short_financing=short_financing,
                leverage_financing=leverage_financing,
                financing_events=financing_events,
                trades=trades,
            )
            n_short_financing_gaps += s_gap
            n_leverage_financing_gaps += l_gap
            # The published curve is a post-fill, post-cost close-time mark.
            equity_curve.append(
                _equity_point(
                    date=d, shares=shares, marks=marks, cash=cash
                )
            )

    metrics = compute_metrics(equity_curve=equity_curve, trades=trades)
    short_events = [
        e for e in financing_events if e.get("side") == "short_financing"
    ]
    lev_events = [
        e for e in financing_events if e.get("side") == "leverage_financing"
    ]
    short_fin_total = float(
        sum(float(e.get("cost") or 0.0) for e in short_events)
    )
    lev_fin_total = float(
        sum(float(e.get("cost") or 0.0) for e in lev_events)
    )
    metrics["short_financing_cost"] = short_fin_total
    metrics["n_short_financing_days"] = len(short_events)
    metrics["n_short_financing_gaps"] = int(n_short_financing_gaps)
    metrics["leverage_financing_cost"] = lev_fin_total
    metrics["n_leverage_financing_days"] = len(lev_events)
    metrics["n_leverage_financing_gaps"] = int(n_leverage_financing_gaps)
    metrics["repo_financing_cost"] = short_fin_total + lev_fin_total

    strategy_id, strategy_params = describe_strategy(strategy)
    metadata = {
        "core_engine_version": CORE_ENGINE_VERSION,
        "pit_api_version": pit.PIT_API_VERSION,
        "start": start,
        "end": end,
        "execution_mode": mode.name,
        "as_of_rule": mode.as_of_rule,
        "cost_model": cost_model.describe(),
        "short_financing": (
            short_financing.describe() if short_financing is not None else None
        ),
        "short_financing_applied": bool(
            short_financing is not None and short_financing.enabled
        ),
        "n_short_financing_gaps": int(n_short_financing_gaps),
        "short_financing_total_cost": short_fin_total,
        "leverage_financing": (
            leverage_financing.describe()
            if leverage_financing is not None
            else None
        ),
        "leverage_financing_applied": bool(
            leverage_financing is not None and leverage_financing.enabled
        ),
        "n_leverage_financing_gaps": int(n_leverage_financing_gaps),
        "leverage_financing_total_cost": lev_fin_total,
        "repo_financing_total_cost": short_fin_total + lev_fin_total,
        "universe_rule": (
            "fixed: " + ",".join(fixed_universe)
            if fixed_universe is not None
            else "pit_equity_master_latest_as_of_per_decision_day"
        ),
        "lookback_days": lookback_days,
        "signal_lookback_days": lookback_days,
        "valuation_mark_policy": "last_pit_safe_exact_session_bar",
        "price_basis": resolved_price_basis,
        "starting_capital": starting_capital,
        "strategy_id": strategy_id,
        "strategy_params": strategy_params,
        "strategy_params_hash": _params_hash(strategy_params),
        "db_path": str(resolved_db_path),
        "trading_days": len(days),
    }

    return BacktestResult(
        equity_curve=equity_curve,
        trades=trades,
        metrics=metrics,
        metadata=metadata,
    )
