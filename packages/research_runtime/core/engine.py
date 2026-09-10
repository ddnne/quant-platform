"""PIT-only backtest engine.

Facts enter via ``pit.get_*`` at the decision ``as_of`` (a static test pins
the import boundary). Fills follow :class:`~core.execution.ExecutionMode`;
costs follow :class:`~core.costs.CostModel`. Under ``next_close``, a signal
on *D* cannot fill on *D*. Deterministic given identical inputs.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

import features
import pit
from features.runtime import (
    bind_personal_retrospective_am_session_daily_bars,
    bind_verified_controlled_am_session_daily_bars,
    compute_with_engine_daily_bars_capability,
)
from paper_runtime.code_fingerprints import feature_definition_hashes
from paper_runtime.personal_prepared_frame import (
    PreparedFeatureValue,
    PreparedPriceRows,
    _active_personal_prepared_frame,
    _is_cache_miss,
)
from pit.personal_retrospective_session import (
    INFORMATION_CUTOFF,
    OPERATIONAL_USABLE_BY,
    am_session_view_digest,
    personal_retrospective_am_signal_from_source_rows,
)
from pit.errors import SnapshotObservationClockError
from pit.governed_am_view import (
    GovernedAmSessionDataView,
    OfflineFixtureAmSessionDataView,
    VerifiedControlledSnapshotHandle,
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
from .execution import (
    AM_SIGNAL_PM_CLOSE,
    NEXT_CLOSE,
    close_as_of,
    get_mode,
    morning_close_as_of,
)
from .metrics import compute_metrics
from .result import BacktestResult, GrossLimitObservation
from .strategy_protocol import (
    Bar,
    BarContext,
    FrozenMorningOrder,
    FrozenMorningOrderBatch,
    OrderIntent,
    Position,
    encode_am_cost_basis,
)
from .universe import ResolvedDailyUniverse, load_master, resolve_injected_universe

# Result metadata. 0.9.0: AM OrderBatch freeze; PM measures, does not resize.
CORE_ENGINE_VERSION = "0.9.0"
AM_FROZEN_ORDER_BATCH_POLICY = "am_frozen_order_batch/v1"
GOVERNED_AM_DATASET_ID = "equities_bars_daily_am"

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
_ADJUSTMENT_VALIDATION_PURPOSE = "retrospective-adjustment-validation"


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


def _make_feature_accessor(
    as_of: str,
    db_path: Any,
    *,
    daily_bars_capability: Any = None,
):
    """Bind the trusted PIT scope used by one decision context."""

    prepared_frame = _active_personal_prepared_frame(db_path)
    session_view_digest = getattr(daily_bars_capability, "session_view_digest", None)

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
                    session_view_digest=session_view_digest,
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

        compute_kw = dict(inputs)
        target = definition if version is not None else feature_id
        if daily_bars_capability is not None:
            completed = compute_with_engine_daily_bars_capability(
                target,
                as_of=as_of,
                db_path=db_path,
                daily_bars_capability=daily_bars_capability,
                **compute_kw,
            )
        else:
            completed = features.compute(
                target,
                as_of=as_of,
                db_path=db_path,
                **compute_kw,
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
                    session_view_digest=session_view_digest,
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
    if not math.isfinite(price) or price <= 0.0:
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


def _positive_finite_price(value: Any) -> float | None:
    """Return a usable price, or None without substituting another field."""
    if value is None:
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price <= 0.0:
        return None
    return price


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


def _load_am_signal_snapshot(
    as_of: str,
    codes: set[str],
    to_date: str,
    lookback_days: int,
    *,
    db_path: Any,
    price_basis: PriceBasis,
) -> dict[str, dict[str, Any]]:
    """AM signal snapshot: D decision prices are exact-session MAdjC only.

    A missing D morning row or non-positive MAdjC leaves that code unpriced.
    ``lookback_days`` bounds historical bars placed on ``ctx.bars``. Zero
    queries the current session only. Prior bars, when requested, must not
    become ``prices_d`` and must not abort a multi-name run.
    """
    snapshot: dict[str, dict[str, Any]] = {
        code: {"close": None, "bars": []} for code in codes
    }
    if not codes:
        return snapshot
    from_date = _shift_date(to_date, -lookback_days)
    result = pit.get_personal_retrospective_am_signal_equity_bars_daily(
        as_of=as_of,
        from_event=from_date,
        to_event=to_date,
        codes=tuple(sorted(codes)),
        db_path=db_path,
    )
    return _am_snapshot_from_session_rows(
        result.rows, codes=codes, to_date=to_date, price_basis=price_basis
    )


def _am_snapshot_from_session_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    codes: set[str],
    to_date: str,
    price_basis: PriceBasis,
) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {
        code: {"close": None, "bars": []} for code in codes
    }
    for row in rows:
        code = row.get("code")
        if code not in snapshot:
            continue
        day = str(row.get("date") or "")
        if day == to_date:
            morning = _positive_finite_price(row.get("adjustment_close"))
            if morning is None:
                snapshot[code]["bars"].append(
                    Bar(
                        code=str(code),
                        date=day,
                        open=None,
                        high=None,
                        low=None,
                        close=None,
                        volume=None,
                        adjustment_close=None,
                    )
                )
            else:
                snapshot[code]["bars"].append(
                    _bar_from_row(row, price_basis=price_basis)
                )
        else:
            snapshot[code]["bars"].append(
                _bar_from_row(row, price_basis=price_basis)
            )
    for entry in snapshot.values():
        morning = None
        for bar in reversed(entry["bars"]):
            if bar.date != to_date:
                continue
            morning = _positive_finite_price(bar.adjustment_close)
            break
        entry["close"] = morning
    return snapshot


def _am_payload_digest(payload: Mapping[str, Any]) -> str:
    body = {key: payload[key] for key in payload if key != "am_row_identity"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _am_row_identity(row: Mapping[str, Any]) -> str:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    receipt = str(
        row.get("trusted_receipt_digest")
        or payload.get("trusted_receipt_digest")
        or payload.get("receipt_proof_digest")
        or ""
    )
    product = str(
        row.get("product_snapshot_id")
        or payload.get("product_snapshot_id")
        or payload.get("product_digest")
        or ""
    )
    body = {
        "dataset": GOVERNED_AM_DATASET_ID,
        "source": str(row.get("source") or ""),
        "natural_key": str(row.get("natural_key") or ""),
        "date": str(payload.get("Date") or payload.get("date") or "")[:10],
        "event_time": str(row.get("event_time") or ""),
        "available_at": str(row.get("available_at") or ""),
        "ingested_at": str(row.get("ingested_at") or ""),
        "trusted_receipt_digest": receipt,
        "receipt_proof_digest": str(payload.get("receipt_proof_digest") or receipt),
        "product_snapshot_id": product,
        "product_digest": str(payload.get("product_digest") or product),
        "payload_digest": _am_payload_digest(payload),
        "snapshot_id": str(payload.get("snapshot_id") or row.get("snapshot_id") or ""),
        "profile_digest": str(payload.get("profile_digest") or row.get("profile_digest") or ""),
        "dependency_closure_digest": str(
            payload.get("dependency_closure_digest")
            or row.get("dependency_closure_digest")
            or ""
        ),
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load_governed_am_signal_snapshot(
    as_of: str,
    codes: set[str],
    to_date: str,
    lookback_days: int,
    *,
    db_path: Any,
    price_basis: PriceBasis,
    data_view: GovernedAmSessionDataView,
) -> dict[str, dict[str, Any]]:
    """As-of-safe AM snapshot from a verifier-minted data-view capability.

    Public digest-shaped receipt/product fields and row self-hashes are not
    authority. The closed verifier already bound rows to sealed product
    materialization and the immutable snapshot observation clock.
    """
    del price_basis
    if type(data_view) is OfflineFixtureAmSessionDataView:
        raise TypeError("fixture AM view cannot enter the Controlled path")
    if type(data_view) is not GovernedAmSessionDataView:
        raise TypeError("Controlled AM snapshot requires a verifier-minted data view")
    data_view.assert_pinned_artifact()
    snapshot: dict[str, dict[str, Any]] = {
        code: {
            "close": None,
            "bars": [],
            "authentic_am_session_evidence": False,
            "unauthorized_am_dates": [],
        }
        for code in codes
    }
    if not codes:
        return snapshot
    from_date = _shift_date(to_date, -lookback_days)
    unauthorized = data_view.unauthorized_dates(
        codes=codes, from_date=from_date, to_date=to_date
    )
    for code, days in unauthorized.items():
        snapshot[code]["unauthorized_am_dates"].extend(days)
    for row in data_view.authorized_rows(
        as_of=as_of,
        codes=codes,
        from_date=from_date,
        to_date=to_date,
    ):
        code = str(row["code"])
        day = str(row["date"])
        morning = _positive_finite_price(row.get("close"))
        if morning is None:
            snapshot[code]["unauthorized_am_dates"].append(day)
            continue
        snapshot[code]["bars"].append(
            Bar(
                code=code,
                date=day,
                open=None,
                high=None,
                low=None,
                close=morning,
                volume=None,
                adjustment_close=None,
            )
        )
        if day == to_date:
            snapshot[code]["authentic_am_session_evidence"] = True
            snapshot[code]["am_row_identity"] = str(row.get("row_identity") or "")
    for entry in snapshot.values():
        morning = None
        for bar in reversed(entry["bars"]):
            if bar.date != to_date:
                continue
            morning = _positive_finite_price(bar.close)
            break
        entry["close"] = morning
    return snapshot


def _governed_pm_fill_closes(
    *, session_date: str, codes: set[str], db_path: Any,
    data_view: GovernedAmSessionDataView,
) -> dict[str, float]:
    """PIT-visible afternoon session field. No retrospective reconstruction."""
    del db_path
    if type(data_view) is not GovernedAmSessionDataView:
        raise TypeError("Controlled PM fill requires the verified AM capability")
    data_view.assert_pinned_artifact()
    return data_view.pm_fill_closes(session_date=session_date, codes=codes)


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

    if price_basis == PERSONAL_RETROSPECTIVE_ADJUSTED:
        _validate_prepared_adjustment_window(
            as_of=as_of,
            codes=codes,
            from_event=_shift_date(to_date, -lookback_days),
            to_event=to_date,
            db_path=db_path,
        )

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


def _validate_prepared_adjustment_window(
    *,
    as_of: str,
    codes: set[str],
    from_event: str,
    to_event: str,
    db_path: Any,
) -> None:
    """Retain the original lookback-wide adjusted-close fail-closed check."""

    ordered_codes = tuple(sorted(codes))
    frame = _active_personal_prepared_frame(db_path)
    if frame is not None:
        prepared = frame.load_price_rows(
            as_of=as_of,
            from_event=from_event,
            to_event=to_event,
            codes=ordered_codes,
            purpose=_ADJUSTMENT_VALIDATION_PURPOSE,
        )
        if not _is_cache_miss(prepared):
            if not isinstance(prepared, PreparedPriceRows) or prepared.rows:
                raise RuntimeError("invalid prepared adjustment validation marker")
            return

    invalid_row = pit.first_invalid_adjusted_close(
        as_of=as_of,
        from_event=from_event,
        to_event=to_event,
        codes=ordered_codes,
        db_path=db_path,
    )
    if invalid_row is not None:
        # Keep the public error contract centralized in the exact same helper
        # used for consumed bars.  The probe only identifies the offending
        # PIT-visible row; it never manufactures a validation message.
        _required_adjusted_close(invalid_row)

    if frame is not None:
        frame.store_price_rows(
            as_of=as_of,
            from_event=from_event,
            to_event=to_event,
            codes=ordered_codes,
            rows=(),
            purpose=_ADJUSTMENT_VALIDATION_PURPOSE,
        )


def _pm_fill_closes(
    *, session_date: str, codes: set[str], db_path: Any
) -> dict[str, float]:
    """D afternoon adjustment close only. Missing AAdjC blocks that code's fill."""
    if not codes:
        return {}
    result = pit.get_personal_retrospective_pm_fill_equity_bars_daily(
        as_of=close_as_of(session_date),
        session_date=session_date,
        codes=tuple(sorted(codes)),
        db_path=db_path,
    )
    prices: dict[str, float] = {}
    for row in result.rows:
        code = row.get("code")
        if not code:
            continue
        price = _positive_finite_price(row.get("adjustment_close"))
        if price is None:
            continue
        prices[str(code)] = price
    return prices


def _session_prices(
    snapshot: dict[str, dict[str, Any]], session_date: str, *, price_basis: PriceBasis
) -> dict[str, float]:
    """Exact-session prices only. Snapshot ``close`` may be an older visible mark."""
    prices: dict[str, float] = {}
    for code, entry in snapshot.items():
        for bar in reversed(entry["bars"]):
            if bar.date != session_date:
                continue
            if (
                price_basis == PERSONAL_RETROSPECTIVE_ADJUSTED
                and bar.adjustment_close is None
            ):
                # Exact-session row is present but unusable; do not walk back.
                break
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


def _causal_morning_equity(
    shares: dict[str, float],
    morning_prices: dict[str, float],
    cash: float,
    *,
    missing_held: Sequence[str],
) -> float | None:
    """Value the book from D MAdjC only. Prior PM/full AdjC is never a fallback."""

    if missing_held:
        return None
    equity = float(cash)
    for code, qty in shares.items():
        if not qty:
            continue
        price = morning_prices.get(code)
        if price is None:
            return None
        equity += qty * float(price)
    return equity


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


def _apply_gross_cap(
    intents: Sequence[OrderIntent],
    max_gross_weight: float | None,
) -> list[OrderIntent]:
    """Scale target weights so abs-weight gross cannot exceed the governed cap."""

    rows = list(intents)
    if max_gross_weight is None:
        return rows
    gross = 0.0
    for intent in rows:
        weight = float(intent.target_weight)
        if weight == weight:
            gross += abs(weight)
    if gross <= max_gross_weight + 1e-12 or gross <= 0.0:
        return rows
    scale = max_gross_weight / gross
    capped: list[OrderIntent] = []
    for intent in rows:
        capped.append(
            OrderIntent(
                code=intent.code,
                target_weight=float(intent.target_weight) * scale,
            )
        )
    return capped


def _requested_gross(intents: Sequence[OrderIntent]) -> float:
    gross = 0.0
    for intent in intents:
        weight = float(intent.target_weight)
        if weight == weight:
            gross += abs(weight)
    return gross


def _share_book(shares: Mapping[str, float]) -> dict[str, float]:
    return {code: qty for code, qty in shares.items() if abs(qty) >= 1e-12}


def _price_map_gross(
    shares: Mapping[str, float],
    prices: Mapping[str, float],
    cash: float,
) -> tuple[float | None, float, float, list[str]]:
    """Gross weight from an explicit price map. Missing held marks stay incomplete."""

    missing = [
        code
        for code, qty in shares.items()
        if abs(qty) >= 1e-12 and prices.get(code) is None
    ]
    equity = float(cash)
    gross_notional = 0.0
    for code, qty in shares.items():
        if abs(qty) < 1e-12:
            continue
        price = prices.get(code)
        if price is None:
            continue
        equity += float(qty) * float(price)
        gross_notional += abs(float(qty)) * float(price)
    if missing:
        return None, equity, gross_notional, missing
    if equity <= 0.0:
        return None, equity, gross_notional, []
    return gross_notional / equity, equity, gross_notional, []


def _finite_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _project_am_post_cost(
    *,
    current_shares: Mapping[str, float],
    desired: Mapping[str, float],
    morning_prices: Mapping[str, float],
    cash: float,
    cost_model: CostModel,
) -> tuple[float | None, float, float, list[str]]:
    """AM-only fill+cost projection. PM prices never enter."""

    shares = dict(current_shares)
    sim_cash = float(cash)
    for code, target_shares in desired.items():
        price = morning_prices.get(code)
        if price is None or price <= 0:
            continue
        current = float(shares.get(code, 0.0))
        delta = float(target_shares) - current
        if abs(delta) < 1e-12:
            continue
        notional = delta * float(price)
        cost = cost_model.one_way_cost(notional)
        new_shares = current + delta
        shares[code] = 0.0 if abs(new_shares) < 1e-12 else new_shares
        sim_cash -= notional + cost
    return _price_map_gross(shares, morning_prices, sim_cash)


def _fit_am_desired_to_cap(
    desired: Mapping[str, float],
    *,
    current_shares: Mapping[str, float],
    morning_prices: Mapping[str, float],
    cash: float,
    cost_model: CostModel,
    max_gross_weight: float,
) -> tuple[dict[str, float], bool, dict[str, Any]]:
    """Scale the AM desired book so known AM costs still fit the unchanged cap."""

    unscaled = dict(desired)
    gross, equity, notional, missing = _project_am_post_cost(
        current_shares=current_shares,
        desired=unscaled,
        morning_prices=morning_prices,
        cash=cash,
        cost_model=cost_model,
    )
    basis = {
        "prices": "am_morning_prices",
        "pm_prices_used": False,
        "cost_model": cost_model.describe(),
        "unscaled_post_cost_gross_weight": _finite_or_none(gross),
        "unscaled_post_cost_equity": _finite_or_none(equity),
        "unscaled_post_cost_gross_notional": _finite_or_none(notional),
    }
    if missing:
        basis["incomplete_held_marks"] = list(missing)
        return unscaled, False, basis
    if gross is not None and gross <= max_gross_weight + 1e-12:
        return unscaled, False, basis
    fitted = {code: 0.0 for code in unscaled}
    lo = 0.0
    hi = 1.0
    for _ in range(48):
        mid = 0.5 * (lo + hi)
        candidate = {code: qty * mid for code, qty in unscaled.items()}
        fitted_gross, _, _, fitted_missing = _project_am_post_cost(
            current_shares=current_shares,
            desired=candidate,
            morning_prices=morning_prices,
            cash=cash,
            cost_model=cost_model,
        )
        if fitted_missing:
            hi = mid
            continue
        if fitted_gross is not None and fitted_gross <= max_gross_weight + 1e-12:
            fitted = candidate
            lo = mid
        else:
            hi = mid
    fitted_gross, fitted_equity, fitted_notional, _ = _project_am_post_cost(
        current_shares=current_shares,
        desired=fitted,
        morning_prices=morning_prices,
        cash=cash,
        cost_model=cost_model,
    )
    basis["fitted_post_cost_gross_weight"] = _finite_or_none(fitted_gross)
    basis["fitted_post_cost_equity"] = _finite_or_none(fitted_equity)
    basis["fitted_post_cost_gross_notional"] = _finite_or_none(fitted_notional)
    return fitted, True, basis


def _flatten_held_morning_batch(
    *,
    decision_timestamp: str,
    session_date: str,
    current_shares: Mapping[str, float],
    morning_prices: Mapping[str, float],
    price_basis: str,
    max_gross_weight: float | None,
) -> FrozenMorningOrderBatch:
    """AM risk-correction: flatten the observable priced book. No strategy orders."""

    orders: list[FrozenMorningOrder] = []
    for code in sorted(_share_book(current_shares)):
        price = morning_prices.get(code)
        if price is None or price <= 0:
            continue
        current = float(current_shares[code])
        orders.append(
            FrozenMorningOrder(
                code=code,
                target_shares=0.0,
                delta_shares=-current,
                target_weight=0.0,
                intent_target_weight=None,
                morning_price=float(price),
                origin="risk_correction",
            )
        )
    return FrozenMorningOrderBatch(
        decision_timestamp=decision_timestamp,
        session_date=session_date,
        orders=tuple(orders),
        morning_price_basis=price_basis,
        risk_policy_id=AM_FROZEN_ORDER_BATCH_POLICY,
        max_gross_weight_limit=max_gross_weight,
        origin="risk_correction" if orders else "empty",
        am_cost_basis_json=encode_am_cost_basis(
            {
                "prices": "am_morning_prices",
                "pm_prices_used": False,
                "policy": "flatten_nonpositive_am_equity",
            }
        ),
    )


def _freeze_morning_order_batch(
    *,
    decision_timestamp: str,
    session_date: str,
    current_shares: Mapping[str, float],
    strategy_targets: Mapping[str, float],
    strategy_weights: Mapping[str, float],
    morning_prices: Mapping[str, float],
    cash: float,
    decision_equity: float,
    price_basis: str,
    max_gross_weight: float | None,
    cost_model: CostModel,
) -> FrozenMorningOrderBatch:
    """Freeze AM quantities. PM prices and fill costs never enter this step."""

    desired = _share_book(current_shares)
    desired.update(dict(strategy_targets))
    cost_basis: dict[str, Any] | None = None
    scaled_to_cap = False
    if max_gross_weight is not None and decision_equity > 0.0:
        desired, scaled_to_cap, cost_basis = _fit_am_desired_to_cap(
            desired,
            current_shares=current_shares,
            morning_prices=morning_prices,
            cash=cash,
            cost_model=cost_model,
            max_gross_weight=max_gross_weight,
        )
    retained_without_intent = any(
        abs(float(qty)) >= 1e-12 and code not in strategy_targets
        for code, qty in current_shares.items()
    )
    orders: list[FrozenMorningOrder] = []
    for code in sorted(set(desired) | set(strategy_targets)):
        target_shares = float(
            desired[code] if code in desired else strategy_targets[code]
        )
        current = float(current_shares.get(code, 0.0))
        delta = target_shares - current
        if abs(delta) < 1e-12 and code not in strategy_targets:
            continue
        price = morning_prices.get(code)
        if price is None or price <= 0:
            continue
        intent_weight = strategy_weights.get(code)
        if decision_equity > 0.0:
            final_weight = target_shares * float(price) / float(decision_equity)
        else:
            final_weight = 0.0 if abs(target_shares) < 1e-12 else None
        if code not in strategy_targets:
            origin = "risk_correction"
        elif scaled_to_cap and retained_without_intent:
            origin = "risk_correction"
        else:
            origin = "strategy"
        orders.append(
            FrozenMorningOrder(
                code=code,
                target_shares=target_shares,
                delta_shares=delta,
                target_weight=final_weight,
                intent_target_weight=(
                    None if intent_weight is None else float(intent_weight)
                ),
                morning_price=float(price),
                origin=origin,
            )
        )
    if any(order.origin == "risk_correction" for order in orders):
        batch_origin = "risk_correction"
    elif orders:
        batch_origin = "strategy"
    else:
        batch_origin = "empty"
    return FrozenMorningOrderBatch(
        decision_timestamp=decision_timestamp,
        session_date=session_date,
        orders=tuple(orders),
        morning_price_basis=price_basis,
        risk_policy_id=AM_FROZEN_ORDER_BATCH_POLICY,
        max_gross_weight_limit=max_gross_weight,
        origin=batch_origin,
        am_cost_basis_json=encode_am_cost_basis(cost_basis),
    )


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


def _run_backtest_impl(
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
    max_gross_weight: float | None = None,
    am_session_data_view: Any = None,
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
    am_pm_mode = mode.name == AM_SIGNAL_PM_CLOSE.name
    draft_am_pm = (
        am_pm_mode and resolved_price_basis == PERSONAL_RETROSPECTIVE_ADJUSTED
    )
    governed_am_pm = False
    if am_pm_mode and resolved_price_basis == RAW:
        governed_am_pm = True
    if am_pm_mode and not governed_am_pm and not draft_am_pm:
        raise ValueError(
            "am_signal_pm_close requires PERSONAL_RETROSPECTIVE_ADJUSTED "
            "historical reconstruction, or RAW only as a fail-closed skip"
        )
    gross_cap = None if max_gross_weight is None else float(max_gross_weight)
    if gross_cap is not None and not (gross_cap > 0.0):
        raise ValueError("max_gross_weight must be positive")
    resolved_db_path = resolve_db_path(db_path)
    cost_model = cost_model or standard_cost()

    governed_am_view: GovernedAmSessionDataView | None = None
    controlled_hold_reason: str | None = None
    if type(am_session_data_view) is OfflineFixtureAmSessionDataView:
        raise TypeError("fixture AM view cannot enter the Controlled path")
    if am_pm_mode and am_session_data_view is not None:
        candidate = am_session_data_view
        if type(candidate) is VerifiedControlledSnapshotHandle:
            try:
                candidate = candidate.am_session_data_view()
            except SnapshotObservationClockError as exc:
                candidate = None
                controlled_hold_reason = str(exc) or (
                    "pinned snapshot observation clock is missing"
                )
        if type(candidate) is not GovernedAmSessionDataView:
            if controlled_hold_reason is None:
                controlled_hold_reason = "missing_verified_production_am_capability"
        else:
            try:
                candidate.assert_pinned_artifact()
                candidate.bind_engine_reads()
                governed_am_view = candidate
            except SnapshotObservationClockError as exc:
                controlled_hold_reason = str(exc) or (
                    "pinned snapshot observation clock is missing"
                )
    if governed_am_pm and governed_am_view is None and controlled_hold_reason is None:
        controlled_hold_reason = "missing_verified_production_am_capability"

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

    if controlled_hold_reason is not None:
        days: list[str] = []
    else:
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
        mode.name == NEXT_CLOSE.name
        and not am_pm_mode
        and _active_personal_prepared_frame(resolved_db_path) is not None
        and getattr(strategy, "personal_prepared_frame_eligible", False) is True
    )
    # AM ctx.bars window only. Features still use their own declared history.
    # Explicit False opts out; missing/True keeps the requested lookback.
    context_bar_lookback_days = lookback_days
    if (
        am_pm_mode
        and getattr(strategy, "consumes_rolling_bars", True) is False
    ):
        context_bar_lookback_days = 0
    am_skipped_decisions: list[dict[str, Any]] = []
    am_incomplete_valuations: list[dict[str, Any]] = []
    am_unfilled_orders: list[dict[str, Any]] = []
    am_missing_session_evidence: list[dict[str, Any]] = []
    morning_order_batches: list[dict[str, Any]] = []
    gross_limit_events: list[dict[str, Any]] = []
    am_policy_holds: list[dict[str, Any]] = []
    requested_gross_obs: list[float] = []
    realized_gross_obs: list[float] = []
    if controlled_hold_reason is not None:
        hold_event = {
            "date": start,
            "reason": controlled_hold_reason,
            "codes": [],
        }
        am_skipped_decisions.append(dict(hold_event))
        am_missing_session_evidence.append(dict(hold_event))

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

        daily_bars_capability = None
        skip_am_decision = False
        signal_equity: float | None = None
        if am_pm_mode:
            historical_session = (
                draft_am_pm or governed_am_view is not None
            ) and resolved_price_basis == PERSONAL_RETROSPECTIVE_ADJUSTED
            if historical_session:
                if governed_am_view is not None:
                    from_date = _shift_date(d, -context_bar_lookback_days)
                    source_rows = governed_am_view.sealed_daily_source_bars(
                        codes=held,
                        from_date=from_date,
                        to_date=d,
                    )
                    am_result = personal_retrospective_am_signal_from_source_rows(
                        source_rows,
                        as_of=decision_as_of,
                        observed_through=governed_am_view.observed_through,
                        codes=tuple(sorted(held)),
                        from_event=from_date,
                        to_event=d,
                        include_morning_turnover_history=True,
                    )
                    snap_dec = _am_snapshot_from_session_rows(
                        am_result.rows,
                        codes=held,
                        to_date=d,
                        price_basis=resolved_price_basis,
                    )
                    fill_closes = _governed_pm_fill_closes(
                        session_date=d,
                        codes=held,
                        db_path=resolved_db_path,
                        data_view=governed_am_view,
                    )
                else:
                    snap_dec = _load_am_signal_snapshot(
                        decision_as_of,
                        held,
                        d,
                        context_bar_lookback_days,
                        db_path=resolved_db_path,
                        price_basis=resolved_price_basis,
                    )
                    fill_closes = _pm_fill_closes(
                        session_date=d,
                        codes=held,
                        db_path=resolved_db_path,
                    )
            elif governed_am_pm:
                snap_dec = {
                    code: {
                        "close": None,
                        "bars": [],
                        "authentic_am_session_evidence": False,
                    }
                    for code in held
                }
                fill_closes = {}
            else:
                snap_dec = _load_am_signal_snapshot(
                    decision_as_of,
                    held,
                    d,
                    context_bar_lookback_days,
                    db_path=resolved_db_path,
                    price_basis=resolved_price_basis,
                )
                fill_closes = _pm_fill_closes(
                    session_date=d,
                    codes=held,
                    db_path=resolved_db_path,
                )
            morning_prices = _session_prices(
                snap_dec, d, price_basis=resolved_price_basis
            )
            if governed_am_pm and not historical_session:
                skip_am_decision = True
                missing_evidence = sorted(universe_d)
                am_missing_session_evidence.append(
                    {
                        "date": d,
                        "reason": "historical_reconstruction_requires_adjusted_basis",
                        "codes": missing_evidence,
                    }
                )
                am_skipped_decisions.append(
                    {
                        "date": d,
                        "reason": "historical_reconstruction_requires_adjusted_basis",
                        "codes": missing_evidence,
                    }
                )
            held_positions = sorted(
                code for code, qty in shares.items() if qty
            )
            held_missing_m = [
                code
                for code in held_positions
                if morning_prices.get(code) is None
            ]
            if held_missing_m:
                skip_am_decision = True
                am_skipped_decisions.append(
                    {
                        "date": d,
                        "reason": "held_missing_morning_adjustment_close",
                        "codes": held_missing_m,
                    }
                )
            signal_equity = _causal_morning_equity(
                shares,
                morning_prices,
                cash,
                missing_held=held_missing_m,
            )
            decision_equity = (
                float(signal_equity) if signal_equity is not None else float(cash)
            )
            daily_bars_capability = (
                bind_verified_controlled_am_session_daily_bars(
                    as_of=decision_as_of,
                    db_path=resolved_db_path,
                    data_view=governed_am_view,
                )
                if historical_session and governed_am_view is not None
                else (
                    bind_personal_retrospective_am_session_daily_bars(
                        as_of=decision_as_of, db_path=resolved_db_path
                    )
                    if historical_session
                    else None
                )
            )
        else:
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
        morning_batch: FrozenMorningOrderBatch | None = None
        if skip_am_decision:
            targets = {}
            if am_pm_mode:
                morning_batch = FrozenMorningOrderBatch(
                    decision_timestamp=decision_as_of,
                    session_date=d,
                    orders=(),
                    morning_price_basis=resolved_price_basis,
                    risk_policy_id=AM_FROZEN_ORDER_BATCH_POLICY,
                    max_gross_weight_limit=gross_cap,
                    origin="empty",
                )
        elif am_pm_mode and decision_equity <= 0.0:
            am_policy_holds.append(
                {
                    "date": d,
                    "reason": "nonpositive_decision_equity",
                    "decision_equity": float(decision_equity),
                    "action": "flatten_priced_holdings",
                }
            )
            morning_batch = _flatten_held_morning_batch(
                decision_timestamp=decision_as_of,
                session_date=d,
                current_shares=shares,
                morning_prices=morning_prices,
                price_basis=resolved_price_basis,
                max_gross_weight=gross_cap,
            )
            targets = morning_batch.target_shares()
        else:
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
                _make_feature_accessor(
                    decision_as_of,
                    resolved_db_path,
                    daily_bars_capability=daily_bars_capability,
                ),
            )

            intents = strategy.on_bar(ctx)
            requested_gross_obs.append(_requested_gross(intents))
            intents = _apply_gross_cap(intents, gross_cap)
            strategy_weights = {
                intent.code: float(intent.target_weight) for intent in intents
            }
            targets = _resolve_targets(intents, decision_equity, prices_d)
            if am_pm_mode:
                morning_batch = _freeze_morning_order_batch(
                    decision_timestamp=decision_as_of,
                    session_date=d,
                    current_shares=shares,
                    strategy_targets=targets,
                    strategy_weights=strategy_weights,
                    morning_prices=morning_prices,
                    cash=cash,
                    decision_equity=float(decision_equity),
                    price_basis=resolved_price_basis,
                    max_gross_weight=gross_cap,
                    cost_model=cost_model,
                )
                targets = morning_batch.target_shares()

        if morning_batch is not None:
            morning_order_batches.append(morning_batch.to_dict())

        if mode.fill_offset == 1:
            # Non-empty targets replace any carried leftover.
            if targets:
                pending = {"targets": targets, "decision_date": d}
        else:
            shares, cash, leftover = _apply_fills(
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
            if am_pm_mode:
                observed_gross, observed_equity, observed_notional, unpriced_gross = (
                    _price_map_gross(shares, fill_closes, cash)
                )
                finite_gross = _finite_or_none(observed_gross)
                if finite_gross is not None:
                    realized_gross_obs.append(finite_gross)
                if gross_cap is not None:
                    undefined_reason = None
                    if unpriced_gross:
                        status = "INCOMPLETE"
                    elif observed_equity <= 0.0 or finite_gross is None:
                        status = "HOLD"
                        undefined_reason = "nonpositive_equity"
                    elif finite_gross > gross_cap + 1e-12:
                        status = "BREACH"
                    else:
                        status = "OK"
                    complete = status != "INCOMPLETE"
                    event = GrossLimitObservation(
                        date=d,
                        decision_timestamp=decision_as_of,
                        limit=gross_cap,
                        observed_gross_weight=finite_gross if complete else None,
                        observed_equity=(
                            _finite_or_none(observed_equity) if complete else None
                        ),
                        observed_gross_notional=(
                            _finite_or_none(observed_notional) if complete else None
                        ),
                        status=status,
                        undefined_ratio_reason=undefined_reason,
                        partial_marked_equity=(
                            _finite_or_none(observed_equity)
                            if status == "INCOMPLETE"
                            else None
                        ),
                        partial_marked_gross_notional=(
                            _finite_or_none(observed_notional)
                            if status == "INCOMPLETE"
                            else None
                        ),
                        unpriced_held_codes=tuple(unpriced_gross),
                    )
                    gross_limit_events.append(event.to_dict())
                if leftover:
                    held_now = {
                        code for code, qty in shares.items() if qty
                    }
                    am_unfilled_orders.append(
                        {
                            "date": d,
                            "decision_date": d,
                            "fill_date": d,
                            "reason": "missing_afternoon_adjustment_close",
                            "codes": sorted(leftover),
                            "unfilled_target_shares": {
                                code: leftover[code] for code in sorted(leftover)
                            },
                            "new_target_codes": sorted(
                                code for code in leftover if code not in held_now
                            ),
                            "held_codes": sorted(
                                code for code in leftover if code in held_now
                            ),
                            "fallback": False,
                            "fill_substituted": False,
                        }
                    )
                held_after = sorted(
                    code for code, qty in shares.items() if qty
                )
                held_missing_a = [
                    code for code in held_after if fill_closes.get(code) is None
                ]
                if held_missing_a:
                    am_incomplete_valuations.append(
                        {
                            "date": d,
                            "reason": "held_missing_afternoon_adjustment_close",
                            "codes": held_missing_a,
                        }
                    )
            point = _equity_point(
                date=d, shares=shares, marks=marks, cash=cash
            )
            if am_pm_mode:
                point["signal_equity"] = signal_equity
            equity_curve.append(point)

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
                "lifecycle": "Paper" if governed_am_view is not None else "DRAFT",
                "price_evidence_mode": "historical_daily_reconstruction",
                "contemporaneous_observation_unproven": True,
                "live_trading_eligible": False,
            }
            if resolved_price_basis == PERSONAL_RETROSPECTIVE_ADJUSTED
            else {
                "source": "vendor_raw_close",
                "time_semantics": "point_in_time_observed",
            }
        ),
        "starting_capital": starting_capital,
        "max_gross_weight_limit": gross_cap,
        "am_order_batch_policy": (
            AM_FROZEN_ORDER_BATCH_POLICY if am_pm_mode else None
        ),
        "requested_gross_weight": (
            max(requested_gross_obs) if requested_gross_obs else 0.0
        ),
        "realized_gross_weight": (
            max(realized_gross_obs) if realized_gross_obs else 0.0
        ),
        "daily_requested_gross_weights": list(requested_gross_obs),
        "daily_realized_gross_weights": list(realized_gross_obs),
        "morning_order_batches": list(morning_order_batches),
        "gross_limit_events": list(gross_limit_events),
        "strategy_id": strategy_id,
        "strategy_params": strategy_params,
        "strategy_params_hash": _params_hash(strategy_params),
        "db_path": str(resolved_db_path),
        "trading_days": len(days),
    }
    if am_pm_mode:
        metadata["context_bar_lookback_days"] = context_bar_lookback_days
        metadata["valuation_mark_policy"] = (
            "decision_marks_d_morning_adjustment_close;"
            "pm_valuation_afternoon_adjustment_close_only"
        )
        metadata["execution_field_time_semantics"] = (
            "historical_daily_reconstruction_from_equities_bars_daily; "
            "not contemporaneous tip-only AM observation; "
            "not a claim that the full daily record was published at 11:30"
        )
        metadata["weight_sizing_rule"] = (
            "frozen_am_order_batch; "
            "pm_executes_and_measures; "
            "realized_weights_may_drift_by_pm_close; "
            "no_pm_quantity_resize"
        )
        provenance = dict(metadata["price_basis_provenance"])
        provenance["signal_fields"] = [
            "morning_adjustment_close",
            "morning_adjustment_volume",
        ]
        provenance["fill_fields"] = ["afternoon_adjustment_close"]
        provenance["field_time_semantics"] = (
            "historical_daily_reconstruction_not_11:30_publication"
        )
        provenance["weight_sizing"] = (
            "causal_morning_frozen_quantity_pm_fill_may_drift"
        )
        metadata["price_basis_provenance"] = provenance
        session_digest = am_session_view_digest(
            include_morning_turnover_history=True
        )
        gross_breaches = [
            event
            for event in gross_limit_events
            if event.get("status") == "BREACH"
        ]
        incomplete_gross = [
            event
            for event in gross_limit_events
            if event.get("status") == "INCOMPLETE"
        ]
        undefined_gross = [
            event
            for event in gross_limit_events
            if event.get("status") == "HOLD"
        ]
        comparable = (
            not am_skipped_decisions
            and not am_incomplete_valuations
            and not am_unfilled_orders
            and not am_policy_holds
            and not gross_breaches
            and not incomplete_gross
            and not undefined_gross
        )
        skipped_dates = [event["date"] for event in am_skipped_decisions]
        incomplete_dates = [event["date"] for event in am_incomplete_valuations]
        missing_fill_dates = [event["date"] for event in am_unfilled_orders]
        incomplete_codes = sorted(
            {
                code
                for event in am_incomplete_valuations
                for code in event.get("codes") or ()
            }
        )
        missing_fill_codes = sorted(
            {
                code
                for event in am_unfilled_orders
                for code in event.get("codes") or ()
            }
        )
        breach_dates = [event["date"] for event in gross_breaches]
        incomplete_gross_dates = [event["date"] for event in incomplete_gross]
        undefined_gross_dates = [event["date"] for event in undefined_gross]
        policy_hold_dates = [event["date"] for event in am_policy_holds]
        non_comparable_session_dates = sorted(
            set(skipped_dates)
            | set(incomplete_dates)
            | set(missing_fill_dates)
            | set(breach_dates)
            | set(incomplete_gross_dates)
            | set(undefined_gross_dates)
            | set(policy_hold_dates)
        )
        production_eligible = False
        # Completeness may authorize research comparison/selection. It is not
        # Live authority, production eligibility, or automatic promotion.
        selection_eligible = comparable
        comparison_eligible = comparable
        data_quality = {
            "comparable": comparable,
            "selection_eligible": selection_eligible,
            "comparison_eligible": comparison_eligible,
            "production_eligible": production_eligible,
            "incomplete_valuation": bool(am_incomplete_valuations),
            "skipped_decision_count": len(am_skipped_decisions),
            "incomplete_valuation_count": len(am_incomplete_valuations),
            "unfilled_order_count": len(am_unfilled_orders),
            "skipped_decision_dates": skipped_dates,
            "incomplete_valuation_dates": incomplete_dates,
            "incomplete_valuation_codes": incomplete_codes,
            "missing_fill_dates": missing_fill_dates,
            "missing_fill_codes": missing_fill_codes,
            "non_comparable_session_dates": non_comparable_session_dates,
            "held_missing_morning_adjustment_close": am_skipped_decisions,
            "held_missing_afternoon_adjustment_close": am_incomplete_valuations,
            "missing_afternoon_adjustment_close_unfilled": am_unfilled_orders,
            "gross_limit_events": list(gross_limit_events),
            "gross_breach_dates": breach_dates,
            "incomplete_gross_dates": incomplete_gross_dates,
            "undefined_gross_dates": undefined_gross_dates,
            "am_policy_holds": list(am_policy_holds),
            "pm_quantity_resized": False,
        }
        metadata["authentic_am_session_evidence"] = False
        metadata["price_evidence_mode"] = "historical_daily_reconstruction"
        metadata["contemporaneous_observation_unproven"] = True
        metadata["historical_reconstruction"] = True
        if governed_am_pm:
            metadata["am_session_evidence_reason"] = (
                controlled_hold_reason
                if controlled_hold_reason is not None
                else "historical_daily_reconstruction_not_contemporaneous_am_evidence"
            )
        metadata["information_cutoff"] = INFORMATION_CUTOFF
        metadata["operational_usable_by"] = OPERATIONAL_USABLE_BY
        metadata["non_price_information_cutoff"] = INFORMATION_CUTOFF
        metadata["am_observation_acquisition_deadline"] = OPERATIONAL_USABLE_BY
        metadata["session_view_digest"] = session_digest
        metadata["data_quality"] = data_quality
        metadata["comparable"] = comparable
        metadata["selection_eligible"] = selection_eligible
        metrics["comparable"] = comparable
        metrics["selection_eligible"] = selection_eligible
        metrics["comparison_eligible"] = comparison_eligible
        metrics["incomplete_valuation"] = bool(am_incomplete_valuations)
        metrics["skipped_decision_count"] = len(am_skipped_decisions)
        metrics["incomplete_valuation_count"] = len(am_incomplete_valuations)
        metrics["unfilled_order_count"] = len(am_unfilled_orders)
        metrics["skipped_decision_dates"] = skipped_dates
        metrics["incomplete_valuation_dates"] = incomplete_dates
        metrics["incomplete_valuation_codes"] = incomplete_codes
        metrics["missing_fill_dates"] = missing_fill_dates
        metrics["missing_fill_codes"] = missing_fill_codes
        metrics["non_comparable_session_dates"] = non_comparable_session_dates
        metrics["gross_breach_dates"] = breach_dates
        metrics["incomplete_gross_dates"] = incomplete_gross_dates
        metrics["undefined_gross_dates"] = undefined_gross_dates
        if gross_breaches:
            metrics["gross_limit_gate"] = "hold_max_gross_weight_breach"
        elif undefined_gross or am_policy_holds:
            metrics["gross_limit_gate"] = "hold_undefined_or_nonpositive_equity"
        if not comparable:
            metrics["data_quality_gate"] = "hard_fail_not_selection_eligible"

    return BacktestResult(
        equity_curve=equity_curve,
        trades=trades,
        metrics=metrics,
        metadata=metadata,
    )


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
    max_gross_weight: float | None = None,
    am_session_data_view: Any = None,
) -> BacktestResult:
    """Run a backtest and always release a pinned Controlled read binding."""

    try:
        return _run_backtest_impl(
            strategy,
            start,
            end,
            db_path=db_path,
            execution_mode=execution_mode,
            cost_model=cost_model,
            short_financing=short_financing,
            leverage_financing=leverage_financing,
            universe=universe,
            starting_capital=starting_capital,
            lookback_days=lookback_days,
            calendar_as_of=calendar_as_of,
            price_basis=price_basis,
            max_gross_weight=max_gross_weight,
            am_session_data_view=am_session_data_view,
        )
    finally:
        release = getattr(am_session_data_view, "release_engine_reads", None)
        if callable(release):
            release()
