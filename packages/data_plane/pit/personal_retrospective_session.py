"""DRAFT personal-retrospective AM/PM session views over daily bars.

These helpers reconstruct a field-time signal view for
``am_signal_pm_close``. They compose canonical ``equities_bars_daily`` reads
and never consult tip-only ``equities_bars_daily_am``.

The D synthetic row is a mask of the official-close daily record. That is
not a claim that the full daily bar was published at 11:30 JST.
"""

from __future__ import annotations

from typing import Any

from ingestion.common.timeutil import parse_date_str
from ingestion.jquants.normalize import CLOSE_CHANGE_DATE

from .api import _result, get_equity_bars_daily
from .models import PitResult
from .query import _NOT_GIVEN, normalize_as_of

_MORNING_CLOSE_SUFFIX = "T11:30:00+09:00"

_D_SIGNAL_STRIP_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adjustment_open",
    "adjustment_high",
    "adjustment_low",
    "turnover_value",
    "market_cap",
    "afternoon_adjustment_close",
    "afternoon_turnover_value",
    "afternoon_adjustment_volume",
    "raw_payload",
)

_D_FILL_KEEP_FIELDS = ("source", "code", "date")


def _official_close_as_of(day: str) -> str:
    hhmmss = "15:30:00" if day >= CLOSE_CHANGE_DATE else "15:00:00"
    return f"{day}T{hhmmss}+09:00"


def _as_day(value: Any) -> str:
    return parse_date_str(str(value))


def _require_latest_n(
    latest_n: int | None, *, code: str | None, codes: Any
) -> None:
    if latest_n is None:
        return
    if isinstance(latest_n, bool) or not isinstance(latest_n, int) or latest_n < 1:
        raise ValueError("latest_n must be a positive integer")
    if not isinstance(code, str) or not code.strip() or codes is not None:
        raise ValueError("latest_n requires one non-empty code")


def _mask_d_am_signal_row(
    row: dict[str, Any], *, include_morning_turnover_history: bool
) -> dict[str, Any]:
    """Expose only D morning fields to a signal caller."""
    out = {key: value for key, value in row.items() if key not in _D_SIGNAL_STRIP_FIELDS}
    out["adjustment_close"] = row.get("morning_adjustment_close")
    out["adjustment_volume"] = row.get("morning_adjustment_volume")
    if include_morning_turnover_history:
        out["morning_turnover_value"] = row.get("morning_turnover_value")
        out.pop("turnover_value", None)
    else:
        out.pop("morning_turnover_value", None)
        out.pop("turnover_value", None)
    return out


def _consistent_morning_turnover_row(row: dict[str, Any]) -> dict[str, Any]:
    """Offer morning turnover without mixing in full-day ``Va``."""
    out = dict(row)
    out.pop("turnover_value", None)
    return out


def _mask_d_pm_fill_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return only the D PM adjusted price on the fill-price path."""
    aadjc = row.get("afternoon_adjustment_close")
    out = {field: row.get(field) for field in _D_FILL_KEEP_FIELDS}
    out["adjustment_close"] = aadjc
    out["afternoon_adjustment_close"] = aadjc
    return out


def get_personal_retrospective_am_signal_equity_bars_daily(
    as_of: Any = _NOT_GIVEN,
    code: str | None = None,
    from_event: Any = None,
    to_event: Any = None,
    *,
    codes: tuple[str, ...] | list[str] | set[str] | None = None,
    latest_n: int | None = None,
    db_path: Any = None,
    include_morning_turnover_history: bool = False,
) -> PitResult:
    """Prior PIT-visible full daily rows at 11:30 plus a D morning-only row.

    Prior rows are read at the decision ``as_of`` (D 11:30 JST). The exact D
    row is read no later than official D close from ``equities_bars_daily``,
    then field-masked so the signal caller cannot see D full close / AdjC /
    afternoon fields / MktCap. ``include_morning_turnover_history`` later
    offers morning turnover consistently; it is off by default so core tests
    do not mix D ``MVa`` with prior full-day ``Va``.
    """
    as_of_iso = normalize_as_of(as_of)
    if not as_of_iso.endswith(_MORNING_CLOSE_SUFFIX):
        raise ValueError(
            "personal retrospective AM signal view requires as_of at 11:30 JST"
        )
    _require_latest_n(latest_n, code=code, codes=codes)
    decision_date = as_of_iso[:10]
    include_d = True
    if from_event is not None and _as_day(from_event) > decision_date:
        include_d = False
    if to_event is not None and _as_day(to_event) < decision_date:
        include_d = False

    prior = get_equity_bars_daily(
        as_of=as_of_iso,
        code=code,
        from_event=from_event,
        to_event=to_event,
        codes=codes,
        db_path=db_path,
    )
    prior_rows = [
        row for row in prior.rows if str(row.get("date") or "") < decision_date
    ]
    if include_morning_turnover_history:
        prior_rows = [_consistent_morning_turnover_row(row) for row in prior_rows]

    d_rows: list[dict[str, Any]] = []
    if include_d:
        d_result = get_equity_bars_daily(
            as_of=_official_close_as_of(decision_date),
            code=code,
            from_event=decision_date,
            to_event=decision_date,
            codes=codes,
            db_path=db_path,
        )
        d_rows = [
            _mask_d_am_signal_row(
                row,
                include_morning_turnover_history=include_morning_turnover_history,
            )
            for row in d_result.rows
            if str(row.get("date") or "") == decision_date
        ]

    rows = [*prior_rows, *d_rows]
    rows.sort(key=lambda row: (row.get("code") or "", row.get("date") or ""))
    if latest_n is not None:
        rows = rows[-latest_n:]
    extra: dict[str, Any] = {
        "session_view": "personal_retrospective_am_signal",
        "field_time_reconstruction": True,
        "publication_claim": False,
        "historical_source": "equities_bars_daily",
        "d_row_source": "equities_bars_daily_masked_at_official_close",
        "include_morning_turnover_history": bool(include_morning_turnover_history),
    }
    if latest_n is not None:
        extra["latest_n"] = latest_n
    return _result(
        rows,
        as_of=as_of_iso,
        table="jquants_daily_bars",
        source="jquants",
        extra_metadata=extra,
    )


def get_personal_retrospective_pm_fill_equity_bars_daily(
    as_of: Any = _NOT_GIVEN,
    *,
    session_date: str,
    code: str | None = None,
    codes: tuple[str, ...] | list[str] | set[str] | None = None,
    db_path: Any = None,
) -> PitResult:
    """D PM adjusted close (AAdjC) only; no fallback to full close/AdjC."""
    day = _as_day(session_date)
    official = _official_close_as_of(day)
    as_of_iso = normalize_as_of(as_of)
    if as_of_iso > official:
        raise ValueError(
            "personal retrospective PM fill read as_of must not be later "
            "than official session close"
        )
    result = get_equity_bars_daily(
        as_of=as_of_iso,
        code=code,
        from_event=day,
        to_event=day,
        codes=codes,
        db_path=db_path,
    )
    rows = [
        _mask_d_pm_fill_row(row)
        for row in result.rows
        if str(row.get("date") or "") == day
    ]
    rows.sort(key=lambda row: (row.get("code") or "", row.get("date") or ""))
    return _result(
        rows,
        as_of=as_of_iso,
        table="jquants_daily_bars",
        source="jquants",
        extra_metadata={
            "session_view": "personal_retrospective_pm_fill",
            "field_time_reconstruction": True,
            "publication_claim": False,
            "historical_source": "equities_bars_daily",
            "fill_price_field": "afternoon_adjustment_close",
        },
    )
