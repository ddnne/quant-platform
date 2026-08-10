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
from typing import Any

import pit
from pit.query import resolve_db_path

from .costs import CostModel, standard_cost
from .execution import close_as_of, get_mode
from .metrics import compute_metrics
from .result import BacktestResult
from .strategy_protocol import Bar, BarContext, OrderIntent, Position
from .universe import load_master

# Bumped per Phase 3 handoff. Surfaced in every result's metadata so a consumer
# can tell which engine contract a given backtest obeys.
CORE_ENGINE_VERSION = "0.3.0"

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


def _bar_price(bar: Bar) -> float | None:
    """Return the split-adjusted price used by the portfolio share ledger.

    J-Quants supplies adjusted OHLC values when a corporate action changes the
    number of shares.  Using ``adjustment_close`` for sizing, fills, and marks
    keeps the engine's stored share quantities in the same adjusted units and
    prevents a split from appearing as investment P&L.  Older/minimal rows may
    omit adjusted values, in which case the raw close remains the fallback.
    """
    if bar.adjustment_close is not None and bar.adjustment_close > 0:
        return bar.adjustment_close
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
) -> dict[str, dict[str, Any]]:
    """PIT-visible recent bars per code at ``as_of``, via ``get_equity_bars_daily``.

    Returns ``{code: {"close": float|None, "bars": [Bar, ...]}}``. PIT returns
    rows ordered by ``(code, date)``; ``close`` is the most recent visible
    split-adjusted close (or raw fallback, ``None`` if no bar is visible in the
    window). Only the requested universe + held codes are read and exposed.
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
        entry["close"] = _bar_price(bars[-1]) if bars else None
    return snapshot


def _session_prices(
    snapshot: dict[str, dict[str, Any]], session_date: str
) -> dict[str, float]:
    """Adjusted closes backed by a bar from exactly ``session_date``.

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
            price = _bar_price(bar)
            if price is not None and price > 0:
                prices[code] = price
            break
    return prices


def _mark_equity(
    shares: dict[str, float], closes: dict[str, float | None], cash: float
) -> float:
    """Total equity = cash + positions marked at last visible close.

    A held code with no visible close in the window is marked at 0 (the engine
    cannot invent a price); for continuous data this never triggers.
    """
    positions_value = 0.0
    for code, qty in shares.items():
        if not qty:
            continue
        px = closes.get(code)
        positions_value += qty * (px if px is not None else 0.0)
    return cash + positions_value


def _resolve_targets(
    intents: list[OrderIntent],
    equity: float,
    prices: dict[str, float | None],
) -> dict[str, float]:
    """Convert target weights to target shares at the decision ``as_of``.

    Codes without a visible positive price are skipped (cannot size). Shorts
    are clipped to flat — shorting is out of scope for the minimal engine.
    """
    targets: dict[str, float] = {}
    for intent in intents:
        price = prices.get(intent.code)
        if price is None or price <= 0:
            continue
        weight = intent.target_weight
        if weight < 0:
            weight = 0.0
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


def run_backtest(
    strategy: Any,
    start: str,
    end: str,
    *,
    db_path: Any = None,
    execution_mode: str = "next_close",
    cost_model: CostModel | None = None,
    universe: tuple[str, ...] | list[str] | None = None,
    starting_capital: float = 1_000_000.0,
    lookback_days: int = 30,
    calendar_as_of: str | None = None,
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
        universe: Optional fixed code list; otherwise built per decision day
            from the PIT equity master as-of (anti-survivorship).
        starting_capital: Initial cash (defaults to 1,000,000 JPY).
        lookback_days: Bar-history window handed to the strategy each day.
        calendar_as_of: Override the PIT ``as_of`` used to read the calendar.

    Returns:
        A :class:`BacktestResult` with equity curve, trade log, metrics, and
        reproducibility metadata.
    """
    mode = get_mode(execution_mode)
    cost_model = cost_model or standard_cost()
    fixed_universe = (
        tuple(sorted(universe)) if universe is not None else None
    )

    days = _trading_days(start, end, db_path=db_path, calendar_as_of=calendar_as_of)
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
    # next_close only: orders decided on day D fill on day D+1.
    pending: dict[str, Any] | None = None

    for d in days:
        # --- universe + held set for this day --------------------------------
        decision_as_of = mode.decision_as_of(d)
        master_d = load_master(decision_as_of, db_path=db_path)
        universe_d = fixed_universe if fixed_universe is not None else tuple(
            sorted(master_d.keys())
        )
        held = set(shares) | set(universe_d)

        # --- close snapshot at close(d): used for marking and fills ----------
        snap_close = _load_snapshot(
            close_as_of(d), held, d, lookback_days, db_path=db_path
        )
        closes = {
            c: snap_close[c]["close"]
            for c in held
            if snap_close[c]["close"] is not None
        }
        fill_closes = _session_prices(snap_close, d)

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
            decision_equity = _mark_equity(shares, closes, cash)
            # The next-close decision occurs after this close's fills and mark.
            equity_curve.append(
                {
                    "date": d,
                    "cash": cash,
                    "positions_value": decision_equity - cash,
                    "equity": decision_equity,
                }
            )
        else:
            # same_day_close decides at open(d): d's close is NOT yet visible.
            snap_dec = _load_snapshot(
                mode.decision_as_of(d), held, d, lookback_days, db_path=db_path
            )
            decision_closes = {
                c: snap_dec[c]["close"]
                for c in held
                if snap_dec[c]["close"] is not None
            }
            decision_equity = _mark_equity(shares, decision_closes, cash)
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
            # The published curve is a post-fill, post-cost close-time mark.
            close_equity = _mark_equity(shares, closes, cash)
            equity_curve.append(
                {
                    "date": d,
                    "cash": cash,
                    "positions_value": close_equity - cash,
                    "equity": close_equity,
                }
            )

    metrics = compute_metrics(equity_curve=equity_curve, trades=trades)

    strategy_id, strategy_params = describe_strategy(strategy)
    metadata = {
        "core_engine_version": CORE_ENGINE_VERSION,
        "pit_api_version": pit.PIT_API_VERSION,
        "start": start,
        "end": end,
        "execution_mode": mode.name,
        "as_of_rule": mode.as_of_rule,
        "cost_model": cost_model.describe(),
        "universe_rule": (
            "fixed: " + ",".join(fixed_universe)
            if fixed_universe is not None
            else "pit_equity_master_latest_as_of_per_decision_day"
        ),
        "lookback_days": lookback_days,
        "starting_capital": starting_capital,
        "strategy_id": strategy_id,
        "strategy_params": strategy_params,
        "strategy_params_hash": _params_hash(strategy_params),
        "db_path": str(resolve_db_path(db_path)),
        "trading_days": len(days),
    }

    return BacktestResult(
        equity_curve=equity_curve,
        trades=trades,
        metrics=metrics,
        metadata=metadata,
    )
