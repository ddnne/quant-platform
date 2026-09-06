"""DRAFT personal-retrospective AM/PM session views over daily bars.

These helpers reconstruct a field-time signal view for
``am_signal_pm_close``. They compose canonical ``equities_bars_daily`` reads
and never consult tip-only ``equities_bars_daily_am``.

The D AM row is an allowlisted synthetic session row, not a canonical PIT
publication at 11:30 JST. Source-close evidence stays in result metadata.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping
from collections.abc import Sequence

from ingestion.common.timeutil import parse_date_str
from ingestion.jquants.normalize import CLOSE_CHANGE_DATE

from .api import get_equity_bars_daily
from .models import PIT_API_VERSION
from .query import _NOT_GIVEN, normalize_as_of, snapshot_observed_through
from ops.receipt_product import _aware_instant

_MORNING_CLOSE_SUFFIX = "T11:30:00+09:00"
INFORMATION_CUTOFF = "11:30:00+09:00"
OPERATIONAL_USABLE_BY = "12:30:00+09:00"
AM_SIGNAL_SESSION_VIEW = "personal_retrospective_am_signal"
PM_FILL_SESSION_VIEW = "personal_retrospective_pm_fill"

_D_AM_IDENTITY_FIELDS = ("source", "code", "date")
_D_AM_VALUE_FIELDS = ("close", "adjustment_close", "adjustment_volume")
_D_AM_TURNOVER_FIELD = "morning_turnover_value"
_ROW_TIMESTAMP_FIELDS = ("event_time", "available_at", "ingested_at")
_D_FILL_KEEP_FIELDS = ("source", "code", "date")


@dataclass(frozen=True)
class PersonalRetrospectiveSessionResult:
    """Allowlisted session-view rows plus reconstruction metadata.

    This is not a canonical :class:`~pit.models.PitResult`. Feature readers
    only need ``.rows`` and ``.metadata``.
    """

    rows: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __iter__(self):
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __bool__(self) -> bool:
        return bool(self.rows)


def _as_day(value: Any) -> str:
    return parse_date_str(str(value))


def _official_pm_close(day: str) -> str:
    hhmmss = "15:30:00" if day >= CLOSE_CHANGE_DATE else "15:00:00"
    return f"{day}T{hhmmss}+09:00"


def _positive_price(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price == price and price not in (float("inf"), float("-inf")) and price > 0.0:
        return price
    return None


def _row_payload_mapping(row: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("raw_payload", "payload"):
        raw = row.get(key)
        if isinstance(raw, dict):
            return dict(raw)
        if isinstance(raw, str) and raw:
            try:
                decoded = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(decoded, dict):
                return dict(decoded)
    return {}


def _morning_raw_close(row: Mapping[str, Any]) -> float | None:
    """Raw morning close from MC only. Never daily C/AC or afternoon fields."""

    typed = _positive_price(row.get("morning_close"))
    if typed is not None:
        return typed
    payload = _row_payload_mapping(row)
    for key in ("MC", "MorningClose", "morning_close"):
        price = _positive_price(payload.get(key))
        if price is not None:
            return price
    return None


def _require_latest_n(
    latest_n: int | None, *, code: str | None, codes: Any
) -> None:
    if latest_n is None:
        return
    if isinstance(latest_n, bool) or not isinstance(latest_n, int) or latest_n < 1:
        raise ValueError("latest_n must be a positive integer")
    if not isinstance(code, str) or not code.strip() or codes is not None:
        raise ValueError("latest_n requires one non-empty code")


def _canonical_digest(body: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(body),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def am_session_view_contract(
    *, include_morning_turnover_history: bool = False
) -> dict[str, Any]:
    """Stable AM session-view contract used in feature provenance."""

    d_row_fields = list(_D_AM_IDENTITY_FIELDS) + list(_D_AM_VALUE_FIELDS)
    if include_morning_turnover_history:
        d_row_fields.append(_D_AM_TURNOVER_FIELD)
    return {
        "session_view": AM_SIGNAL_SESSION_VIEW,
        "information_cutoff": INFORMATION_CUTOFF,
        "operational_usable_by": OPERATIONAL_USABLE_BY,
        "non_price_pit_cutoff": INFORMATION_CUTOFF,
        "historical_source": "equities_bars_daily",
        "d_row_fields": d_row_fields,
        "publication_claim": False,
        "field_time_reconstruction": True,
        "include_morning_turnover_history": bool(include_morning_turnover_history),
        "last_return_interval": "prior PM/full -> D morning",
    }


def am_session_view_digest(*, include_morning_turnover_history: bool = False) -> str:
    return _canonical_digest(
        am_session_view_contract(
            include_morning_turnover_history=include_morning_turnover_history
        )
    )


def _synthetic_d_am_signal_row(
    row: Mapping[str, Any], *, include_morning_turnover_history: bool
) -> dict[str, Any]:
    """Expose only allowlisted D morning fields to a signal caller."""

    out = {field: row.get(field) for field in _D_AM_IDENTITY_FIELDS}
    out["close"] = _morning_raw_close(row)
    out["adjustment_close"] = row.get("morning_adjustment_close")
    out["adjustment_volume"] = row.get("morning_adjustment_volume")
    if include_morning_turnover_history:
        out["morning_turnover_value"] = row.get("morning_turnover_value")
    return out


def _d_row_reconstruction_timestamps(row: Mapping[str, Any]) -> dict[str, Any]:
    evidence = {
        "code": row.get("code"),
        "date": row.get("date"),
        "source": row.get("source"),
    }
    for field in _ROW_TIMESTAMP_FIELDS:
        evidence[f"source_{field}"] = row.get(field)
    return evidence


def _consistent_morning_turnover_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Offer morning turnover without mixing in full-day ``Va``."""

    out = dict(row)
    out.pop("turnover_value", None)
    return out


def _mask_d_pm_fill_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the D PM adjusted price on the fill-price path."""

    aadjc = row.get("afternoon_adjustment_close")
    out = {field: row.get(field) for field in _D_FILL_KEEP_FIELDS}
    out["adjustment_close"] = aadjc
    out["afternoon_adjustment_close"] = aadjc
    return out


def _source_row_visible_at(row: Mapping[str, Any], as_of: str) -> bool:
    available = _aware_instant(str(row.get("available_at") or ""), label="available_at")
    event = _aware_instant(str(row.get("event_time") or ""), label="event_time")
    decision = _aware_instant(as_of, label="as_of")
    return available <= decision and event <= decision


def personal_retrospective_am_signal_from_source_rows(
    source_rows: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
    observed_through: str,
    code: str | None = None,
    from_event: Any = None,
    to_event: Any = None,
    codes: tuple[str, ...] | list[str] | set[str] | None = None,
    latest_n: int | None = None,
    include_morning_turnover_history: bool = False,
) -> PersonalRetrospectiveSessionResult:
    """Apply the shared AM allowlist/mask to already-selected source bars."""

    as_of_iso = normalize_as_of(as_of)
    if not as_of_iso.endswith(_MORNING_CLOSE_SUFFIX):
        raise ValueError(
            "personal retrospective AM signal view requires as_of at 11:30 JST"
        )
    _require_latest_n(latest_n, code=code, codes=codes)
    observed = str(observed_through)
    if _aware_instant(as_of_iso, label="as_of") > _aware_instant(
        observed, label="observed_through"
    ):
        raise ValueError(
            "personal retrospective AM signal as_of must not be later than "
            "snapshot observed_through"
        )
    decision_date = as_of_iso[:10]
    include_d = True
    if from_event is not None and _as_day(from_event) > decision_date:
        include_d = False
    if to_event is not None and _as_day(to_event) < decision_date:
        include_d = False
    wanted: set[str] | None
    if code is not None:
        wanted = {code}
    elif codes is not None:
        wanted = {str(value) for value in codes}
    else:
        wanted = None
    from_day = _as_day(from_event) if from_event is not None else None
    to_day = _as_day(to_event) if to_event is not None else None
    prior_rows: list[dict[str, Any]] = []
    d_rows: list[dict[str, Any]] = []
    reconstruction_timestamps: list[dict[str, Any]] = []
    for raw in source_rows:
        row = dict(raw)
        row_code = str(row.get("code") or "")
        day = str(row.get("date") or "")
        if wanted is not None and row_code not in wanted:
            continue
        if from_day is not None and day < from_day:
            continue
        if to_day is not None and day > to_day:
            continue
        if day < decision_date:
            if not _source_row_visible_at(row, as_of_iso):
                continue
            if include_morning_turnover_history:
                prior_rows.append(_consistent_morning_turnover_row(row))
            else:
                prior_rows.append(row)
            continue
        if include_d and day == decision_date:
            reconstruction_timestamps.append(_d_row_reconstruction_timestamps(row))
            d_rows.append(
                _synthetic_d_am_signal_row(
                    row,
                    include_morning_turnover_history=include_morning_turnover_history,
                )
            )
    rows = [*prior_rows, *d_rows]
    rows.sort(key=lambda item: (item.get("code") or "", item.get("date") or ""))
    if latest_n is not None:
        rows = rows[-latest_n:]
    contract = am_session_view_contract(
        include_morning_turnover_history=include_morning_turnover_history
    )
    extra: dict[str, Any] = {
        **contract,
        "session_view_digest": _canonical_digest(contract),
        "d_row_source": "equities_bars_daily_synthetic_allowlist_at_snapshot_observation",
        "retrospective_reconstruction": {
            "d_row_source_dataset": "equities_bars_daily",
            "d_row_source_read_as_of": observed if include_d else None,
            "d_row_source_cutoff": "snapshot_observed_through",
            "d_row_source_publication_timestamps": reconstruction_timestamps,
            "contemporaneous_observation_unproven": True,
        },
    }
    if latest_n is not None:
        extra["latest_n"] = latest_n
    return _session_result(rows, as_of=as_of_iso, extra_metadata=extra)


def _session_result(
    rows: list[dict[str, Any]],
    *,
    as_of: str,
    extra_metadata: Mapping[str, Any],
) -> PersonalRetrospectiveSessionResult:
    md: dict[str, Any] = {
        "as_of": as_of,
        "table": "jquants_daily_bars",
        "count": len(rows),
        "source": "jquants",
        "pit_api_version": PIT_API_VERSION,
        "information_cutoff": INFORMATION_CUTOFF,
        "operational_usable_by": OPERATIONAL_USABLE_BY,
        "publication_claim": False,
        "field_time_reconstruction": True,
        "historical_source": "equities_bars_daily",
    }
    md.update(dict(extra_metadata))
    return PersonalRetrospectiveSessionResult(rows=rows, metadata=md)


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
) -> PersonalRetrospectiveSessionResult:
    """Prior PIT-visible full daily rows at 11:30 plus a D morning-only row.

    Prior rows are read at the decision ``as_of`` (D 11:30 JST). When
    ``latest_n`` is set, that bound is applied to the prior query so the
    adapter never decodes a full 2008-present history. The exact D row is
    read from ``equities_bars_daily`` at the snapshot observation cutoff,
    then rebuilt as an allowlisted synthetic session row. Source publication
    timestamps stay in retrospective reconstruction metadata and are not
    backdated to 11:30.
    """
    as_of_iso = normalize_as_of(as_of)
    if not as_of_iso.endswith(_MORNING_CLOSE_SUFFIX):
        raise ValueError(
            "personal retrospective AM signal view requires as_of at 11:30 JST"
        )
    _require_latest_n(latest_n, code=code, codes=codes)
    decision_date = as_of_iso[:10]
    d_source_read_as_of = snapshot_observed_through(db_path)
    if as_of_iso > d_source_read_as_of:
        raise ValueError(
            "personal retrospective AM signal as_of must not be later than "
            "snapshot observed_through"
        )
    include_d = True
    if from_event is not None and _as_day(from_event) > decision_date:
        include_d = False
    if to_event is not None and _as_day(to_event) < decision_date:
        include_d = False

    prior_kwargs: dict[str, Any] = {
        "as_of": as_of_iso,
        "code": code,
        "from_event": from_event,
        "to_event": to_event,
        "codes": codes,
        "db_path": db_path,
    }
    if latest_n is not None:
        prior_kwargs["latest_n"] = latest_n
    prior = get_equity_bars_daily(**prior_kwargs)
    prior_rows = [
        row for row in prior.rows if str(row.get("date") or "") < decision_date
    ]
    if include_morning_turnover_history:
        prior_rows = [_consistent_morning_turnover_row(row) for row in prior_rows]

    d_rows: list[dict[str, Any]] = []
    reconstruction_timestamps: list[dict[str, Any]] = []
    if include_d:
        d_result = get_equity_bars_daily(
            as_of=d_source_read_as_of,
            code=code,
            from_event=decision_date,
            to_event=decision_date,
            codes=codes,
            db_path=db_path,
        )
        for row in d_result.rows:
            if str(row.get("date") or "") != decision_date:
                continue
            reconstruction_timestamps.append(_d_row_reconstruction_timestamps(row))
            d_rows.append(
                _synthetic_d_am_signal_row(
                    row,
                    include_morning_turnover_history=include_morning_turnover_history,
                )
            )

    rows = [*prior_rows, *d_rows]
    rows.sort(key=lambda row: (row.get("code") or "", row.get("date") or ""))
    if latest_n is not None:
        rows = rows[-latest_n:]

    contract = am_session_view_contract(
        include_morning_turnover_history=include_morning_turnover_history
    )
    extra: dict[str, Any] = {
        **contract,
        "session_view_digest": _canonical_digest(contract),
        "d_row_source": "equities_bars_daily_synthetic_allowlist_at_snapshot_observation",
        "retrospective_reconstruction": {
            "d_row_source_dataset": "equities_bars_daily",
            "d_row_source_read_as_of": d_source_read_as_of if include_d else None,
            "d_row_source_cutoff": "snapshot_observed_through",
            "d_row_source_publication_timestamps": reconstruction_timestamps,
            "contemporaneous_observation_unproven": True,
        },
    }
    if latest_n is not None:
        extra["latest_n"] = latest_n
    return _session_result(rows, as_of=as_of_iso, extra_metadata=extra)


def get_personal_retrospective_pm_fill_equity_bars_daily(
    as_of: Any = _NOT_GIVEN,
    *,
    session_date: str,
    code: str | None = None,
    codes: tuple[str, ...] | list[str] | set[str] | None = None,
    db_path: Any = None,
) -> PersonalRetrospectiveSessionResult:
    """D PM adjusted close (AAdjC) only; no fallback to full close/AdjC."""
    day = _as_day(session_date)
    observed = snapshot_observed_through(db_path)
    as_of_iso = normalize_as_of(as_of)
    official = _official_pm_close(day)
    if as_of_iso < official or as_of_iso > observed:
        raise ValueError(
            "personal retrospective PM fill as_of must satisfy "
            "official_pm_close(session_date) <= as_of <= snapshot_observed_through"
        )
    result = get_equity_bars_daily(
        as_of=observed,
        code=code,
        from_event=day,
        to_event=day,
        codes=codes,
        db_path=db_path,
    )
    source_event_times: list[str] = []
    rows = []
    for row in result.rows:
        if str(row.get("date") or "") != day:
            continue
        source_event_times.append(str(row.get("event_time") or ""))
        rows.append(_mask_d_pm_fill_row(row))
    rows.sort(key=lambda row: (row.get("code") or "", row.get("date") or ""))
    return _session_result(
        rows,
        as_of=as_of_iso,
        extra_metadata={
            "session_view": PM_FILL_SESSION_VIEW,
            "fill_price_field": "afternoon_adjustment_close",
            "retrospective_reconstruction": {
                "d_row_source_dataset": "equities_bars_daily",
                "d_row_source_read_as_of": observed,
                "d_row_source_cutoff": "snapshot_observed_through",
                "official_pm_close": official,
                "d_row_source_event_times": source_event_times,
                "contemporaneous_observation_unproven": True,
            },
        },
    )
