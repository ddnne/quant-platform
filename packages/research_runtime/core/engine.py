"""PIT-only backtest engine.

Facts enter via ``pit.get_*`` at the decision ``as_of`` (a static test pins
the import boundary). Fills follow :class:`~core.execution.ExecutionMode`;
costs follow :class:`~core.costs.CostModel`. Under ``next_close``, a signal
on *D* cannot fill on *D*. Deterministic given identical inputs.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Mapping

import features
import pit
from paper_runtime.code_fingerprints import feature_definition_hashes
from paper_runtime.personal_prepared_frame import (
    PreparedFeatureValue,
    PreparedPriceRows,
    _active_personal_prepared_frame,
    _is_cache_miss,
)
from pit.query import resolve_db_path
from price_basis import (
    PERSONAL_RETROSPECTIVE_ADJUSTED,
    RAW,
    PriceBasis,
    require_supported_price_basis,
)

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
from .universe import ResolvedDailyUniverse, load_master, resolve_injected_universe

# Result metadata. 0.6.3: fixed candidates are PIT-gated on every decision day.
CORE_ENGINE_VERSION = "0.7.0"

# J-Quants HolidayDivision: "1" == trading day (exchange open).
_TRADING_HOLIDAY_DIVISION = "1"

_PREPARED_BAR_FIELDS = (
    "source",
    "code",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adjustment_open",
    "adjustment_high",
    "adjustment_low",
    "adjustment_close",
    "adjustment_volume",
)


def describe_strategy(strategy: Any) -> tuple[str, dict[str, Any]]:
    """``strategy_id`` / ``params`` for metadata; class name / {} if omitted."""
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

    prepared_frame = _active_personal_prepared_frame(db_path)

    def compute_feature(
        feature_id: str, *, version: str | None = None, **inputs: Any
    ) -> Any:
        # Pin ``version`` when given so a later registry add cannot change a
        # persisted StrategySpec. Omit version = follow latest (hand-written).
        definition = features.get(feature_id, version=version)
        definition_digest: str | None = None
        if prepared_frame is not None:
            try:
                def _exact_definition_digest() -> str:
                    metadata_digest = features.feature_definition_digest(definition)
                    implementation_digest = feature_definition_hashes(
                        {definition.id: str(definition.version)}
                    )[definition.id]
                    payload = (
                        metadata_digest + "\0" + implementation_digest
                    ).encode("ascii")
                    return "sha256:" + hashlib.sha256(payload).hexdigest()

                definition_digest = prepared_frame.definition_digest(
                    definition,
                    _exact_definition_digest,
                )
                prepared = prepared_frame.load_feature(
                    as_of=as_of,
                    feature_id=definition.id,
                    feature_version=str(definition.version),
                    definition_digest=definition_digest,
                    inputs=inputs,
                )
            except (KeyError, TypeError, ValueError):
                # A future feature may accept a non-JSON input. The prepared
                # frame is only an optimization; such a feature must retain
                # the public live-compute behavior unchanged.
                definition_digest = None
            else:
                if not _is_cache_miss(prepared):
                    if not isinstance(prepared, PreparedFeatureValue):
                        raise RuntimeError("invalid personal prepared feature value")
                    return features.FeatureOutput(
                        value=prepared.value,
                        metadata=dict(prepared.metadata),
                    )

        completed = features.compute(
            definition if version is not None else feature_id,
            as_of=as_of,
            db_path=db_path,
            **inputs,
        )
        if prepared_frame is not None and definition_digest is not None:
            try:
                prepared_frame.store_feature(
                    as_of=as_of,
                    feature_id=definition.id,
                    feature_version=str(definition.version),
                    definition_digest=definition_digest,
                    inputs=inputs,
                    value=completed.value,
                    metadata=completed.metadata,
                )
            except (TypeError, ValueError):
                # Key encoding is best effort for the same reason as above.
                pass
        return completed

    return compute_feature


def _required_adjusted_close(row: Mapping[str, Any]) -> float:
    """Return one vendor adjusted close without silently mixing price units."""
    value = row.get("adjustment_close")
    if value is None:
        raise ValueError(
            "PERSONAL_RETROSPECTIVE_ADJUSTED requires adjustment_close for "
            f"every consumed bar; missing for {row.get('code')} {row.get('date')}"
        )
    try:
        price = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "PERSONAL_RETROSPECTIVE_ADJUSTED received a non-numeric "
            f"adjustment_close for {row.get('code')} {row.get('date')}"
        ) from exc
    if price <= 0.0:
        raise ValueError(
            "PERSONAL_RETROSPECTIVE_ADJUSTED requires a positive "
            f"adjustment_close for {row.get('code')} {row.get('date')}"
        )
    return price


def _bar_from_row(row: dict[str, Any], *, price_basis: PriceBasis) -> Bar:
    """Map a PIT daily-bar row to the narrow :class:`Bar` the strategy sees."""
    close = row.get("close")
    open_price = row.get("open")
    high = row.get("high")
    low = row.get("low")
    volume = row.get("volume")
    if price_basis == PERSONAL_RETROSPECTIVE_ADJUSTED:
        # Deliberately replace the strategy-visible close.  Keeping RAW here
        # while fills and marks use adjusted units would make target weights
        # internally inconsistent.
        close = _required_adjusted_close(row)
        # Never present raw OHLCV beside an adjusted close as though the units
        # matched. Non-close adjusted fields are optional because this engine
        # does not use them for fills or marks; absence stays explicit None.
        open_price = row.get("adjustment_open")
        high = row.get("adjustment_high")
        low = row.get("adjustment_low")
        volume = row.get("adjustment_volume")
    return Bar(
        code=row.get("code") or "",
        date=row.get("date") or "",
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        adjustment_close=row.get("adjustment_close"),
    )


def _bar_price(bar: Bar, *, price_basis: PriceBasis) -> float | None:
    """Return a price in the explicitly selected unit system."""
    if price_basis == RAW:
        return bar.close
    if price_basis == PERSONAL_RETROSPECTIVE_ADJUSTED:
        if bar.adjustment_close is None:
            raise ValueError(
                "PERSONAL_RETROSPECTIVE_ADJUSTED cannot fall back to RAW close"
            )
        return float(bar.adjustment_close)
    raise ValueError(f"unsupported runtime price basis: {price_basis!r}")


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
    """PIT-visible recent bars per code at ``as_of``. Valuation uses the mark ledger, not this window."""
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
        snapshot[code]["bars"].append(
            _bar_from_row(row, price_basis=price_basis)
        )
    for entry in snapshot.values():
        bars = entry["bars"]
        entry["close"] = (
            _bar_price(bars[-1], price_basis=price_basis) if bars else None
        )
    return snapshot


def _prepared_bar_rows(
    *,
    as_of: str,
    codes: set[str],
    from_event: str,
    to_event: str,
    db_path: Any,
) -> tuple[dict[str, Any], ...]:
    """Read one bounded bar window and reuse it inside the active job frame."""

    ordered_codes = tuple(sorted(codes))
    if not ordered_codes:
        return ()
    frame = _active_personal_prepared_frame(db_path)
    if frame is not None:
        prepared = frame.load_price_rows(
            as_of=as_of,
            from_event=from_event,
            to_event=to_event,
            codes=ordered_codes,
        )
        if not _is_cache_miss(prepared):
            if not isinstance(prepared, PreparedPriceRows):
                raise RuntimeError("invalid personal prepared price rows")
            return prepared.rows

    result = pit.get_equity_bars_daily(
        as_of=as_of,
        from_event=from_event,
        to_event=to_event,
        codes=ordered_codes,
        db_path=db_path,
    )
    rows = tuple(
        {
            field: row.get(field)
            for field in _PREPARED_BAR_FIELDS
            if field in row
        }
        for row in result.rows
    )
    if frame is not None:
        frame.store_price_rows(
            as_of=as_of,
            from_event=from_event,
            to_event=to_event,
            codes=ordered_codes,
            rows=rows,
        )
    return rows


def _load_prepared_strategy_snapshot(
    as_of: str,
    codes: set[str],
    to_date: str,
    lookback_days: int,
    *,
    db_path: Any,
    price_basis: PriceBasis,
) -> dict[str, dict[str, Any]]:
    """Compact snapshot for a StrategySpec that never consumes ``ctx.bars``.

    Exact-session bars cover fills, marks, and almost every decision price.
    Only codes missing an exact-session bar pay for the original historical
    fallback needed to preserve ``last close within lookback`` behavior.
    """

    snapshot: dict[str, dict[str, Any]] = {
        code: {"close": None, "bars": []} for code in codes
    }
    if not codes:
        return snapshot

    exact_rows = _prepared_bar_rows(
        as_of=as_of,
        codes=codes,
        from_event=to_date,
        to_event=to_date,
        db_path=db_path,
    )
    exact_codes: set[str] = set()
    for row in exact_rows:
        code = str(row.get("code") or "")
        if code not in snapshot:
            continue
        exact_codes.add(code)
        snapshot[code]["bars"].append(
            _bar_from_row(row, price_basis=price_basis)
        )

    missing = codes - exact_codes
    if missing:
        from_date = _shift_date(to_date, -lookback_days)
        for row in _prepared_bar_rows(
            as_of=as_of,
            codes=missing,
            from_event=from_date,
            to_event=to_date,
            db_path=db_path,
        ):
            code = str(row.get("code") or "")
            if code not in snapshot:
                continue
            snapshot[code]["bars"].append(
                _bar_from_row(row, price_basis=price_basis)
            )

    for entry in snapshot.values():
        bars = entry["bars"]
        entry["close"] = (
            _bar_price(bars[-1], price_basis=price_basis) if bars else None
        )
    return snapshot


def _session_prices(
    snapshot: dict[str, dict[str, Any]], session_date: str, *, price_basis: PriceBasis
) -> dict[str, float]:
    """Exact-session prices only. Snapshot ``close`` may be an older visible mark."""
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
    """Equity from last PIT-safe mark; never fabricates a price. Zero is fail-closed."""
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
    """Target weights → shares. Skip unpriced codes; negative weights allowed (no gross cap)."""
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
    """Fill targets at ``fill_date`` close. Unpriced codes go to leftover; no-op if already at target."""
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
    """Trading days in ``[start, end]`` (``holiday_division == "1"``). Calendar is read at close(end)."""
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
    """Absolute market value of short (negative share) positions."""
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
    """Charge short (repo+spread) then leverage (repo only on excess); return (cash, short_gap, lev_gap)."""
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
    universe: Any = None,
    starting_capital: float = 1_000_000.0,
    lookback_days: int = 30,
    calendar_as_of: str | None = None,
    price_basis: str = RAW,
) -> BacktestResult:
    """PIT-only backtest of ``strategy`` over ``[start, end]``.

    Each trading day *D*: read PIT at the mode's decision ``as_of``, call
    ``strategy.on_bar(ctx)``, fill per execution mode. Valuation marks are
    independent of ``lookback_days``. ``RAW`` remains the default;
    ``PERSONAL_RETROSPECTIVE_ADJUSTED`` uses vendor-restated split-adjusted
    closes for local DRAFT research only, while ``PIT_ADJUSTED`` fails closed.

    ``universe`` is None (PIT master per decision day) or a candidate
    fixed allowlist supplied as an
    :class:`~core.universe.EquityMasterMap` from :func:`core.universe.load_master`
    / :func:`core.universe.membership_at` carrying ``pit_as_of``.  Candidate
    codes are intersected with the PIT master at every decision instant. A
    raw code list is rejected unless ``QP_ALLOW_FIXED_UNIVERSE=1``
    (research-only; not GO).
    """
    mode = get_mode(execution_mode)
    resolved_price_basis = require_supported_price_basis(price_basis)
    resolved_db_path = resolve_db_path(db_path)
    cost_model = cost_model or standard_cost()
    resolved_candidates = resolve_injected_universe(
        universe, db_path=resolved_db_path
    )
    daily_resolved = (
        resolved_candidates
        if isinstance(resolved_candidates, ResolvedDailyUniverse)
        else None
    )
    fixed_allowlist = (
        None if daily_resolved is not None else resolved_candidates
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
    # (last PIT-visible exact-session price, that session's date)
    marks: dict[str, tuple[float, str]] = {}
    # next_close only: orders decided on day D fill on day D+1.
    pending: dict[str, Any] | None = None
    prepared_strategy_frame = bool(
        mode.fill_offset == 1
        and _active_personal_prepared_frame(resolved_db_path) is not None
        and getattr(strategy, "personal_prepared_frame_eligible", False) is True
    )

    for d in days:
        decision_as_of = mode.decision_as_of(d)
        master_all_d = load_master(decision_as_of, db_path=resolved_db_path)
        if daily_resolved is not None:
            daily_candidates = daily_resolved.codes_for(d)
            universe_d = tuple(
                code for code in daily_candidates if code in master_all_d
            )
        elif fixed_allowlist is None:
            universe_d = tuple(sorted(master_all_d.keys()))
        else:
            universe_d = tuple(
                code for code in fixed_allowlist if code in master_all_d
            )
        master_d = type(master_all_d)(
            {code: master_all_d[code] for code in universe_d},
            pit_as_of=master_all_d.pit_as_of,
        )
        held = set(shares) | set(universe_d)

        snapshot_loader = (
            _load_prepared_strategy_snapshot
            if prepared_strategy_frame
            else _load_snapshot
        )
        snap_close = snapshot_loader(
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

        # next_close: close is in the decision set, so marks may advance before fills.
        if mode.fill_offset == 1:
            _update_marks(marks, fill_closes, d)

        if mode.fill_offset == 1 and pending is not None:
            # A prior-day order cannot fill after its code leaves today's
            # PIT membership.  Dropped targets are cancelled permanently;
            # existing holdings remain subject to the stale-mark policy.
            eligible_targets = {
                code: target
                for code, target in pending["targets"].items()
                if code in master_d
            }
            shares, cash, leftover = _apply_fills(
                eligible_targets,
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

        if mode.fill_offset == 1:
            snap_dec = snap_close  # next_close decides at close(d)
            decision_equity = _mark_equity(shares, marks, cash)
            # next_close: financing on post-fill end-of-day book.
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
        # Private PIT-scoped closure; BarContext stays facts + ctx.feature(...).
        object.__setattr__(
            ctx,
            "_feature_accessor",
            _make_feature_accessor(decision_as_of, resolved_db_path),
        )

        intents = strategy.on_bar(ctx)
        targets = _resolve_targets(intents, decision_equity, prices_d)

        if mode.fill_offset == 1:
            # Non-empty targets replace any carried leftover.
            if targets:
                pending = {"targets": targets, "decision_date": d}
        else:
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
            "resolved_daily_membership_intersect_pit_equity_master_per_decision_day"
            if daily_resolved is not None
            else (
                "fixed_allowlist_intersect_pit_equity_master_per_decision_day"
                if fixed_allowlist is not None
                else "pit_equity_master_latest_as_of_per_decision_day"
            )
        ),
        "fixed_allowlist": (
            list(fixed_allowlist) if fixed_allowlist is not None else None
        ),
        "universe_rule_digest": (
            daily_resolved.rule_digest if daily_resolved is not None else None
        ),
        "resolved_universe_digest": (
            daily_resolved.resolved_membership_digest
            if daily_resolved is not None
            else None
        ),
        "lookback_days": lookback_days,
        "signal_lookback_days": lookback_days,
        "valuation_mark_policy": (
            "last_retrospective_adjusted_exact_session_bar"
            if resolved_price_basis == PERSONAL_RETROSPECTIVE_ADJUSTED
            else "last_pit_safe_exact_session_bar"
        ),
        "price_basis": resolved_price_basis,
        "price_basis_provenance": (
            {
                "source": "vendor_adjustment_close",
                "adjusted_fields_consumed": [
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ],
                "required_adjusted_fields": ["close"],
                "optional_adjusted_fields_missing_policy": "expose_null",
                "adjustment_scope": "vendor_supported_splits_and_reverse_splits",
                "time_semantics": "retrospective_not_point_in_time",
                "position_units": "synthetic_split_adjusted_units",
                "lifecycle": "DRAFT_only",
                "live_trading_eligible": False,
            }
            if resolved_price_basis == PERSONAL_RETROSPECTIVE_ADJUSTED
            else {
                "source": "vendor_raw_close",
                "time_semantics": "point_in_time_observed",
            }
        ),
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
