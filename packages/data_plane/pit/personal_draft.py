"""Typed PIT reads and DRAFT evidence for personal research.

These helpers reuse the canonical PIT wall, compact-v7 classification,
revision ranking, and read-only connection scope. They expose result and
evidence documents, not a raw SQLite capability. R2-derived Container
SQLite remains an implementation detail of the data plane.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

from data_contracts.personal_history_compact import (
    PERSONAL_HISTORY_COMPACT_BARS_TABLE,
    allowed_missing_observed_bars,
)
from ingestion.jquants.normalize import CLOSE_CHANGE_DATE
from storage.schema import CATALOG_CODE_SQL

from .api import (
    _compact_v8_or_legacy,
    _date_bound,
    get_equity_bars_daily,
)
from .errors import PitError
from .query import (
    _readonly_connection_scope,
    _scoped_read_connection,
    connect_readonly,
    normalize_as_of,
    run_query,
)
from .read_clock import bound_read_clock, resolve_read_clock

PERSONAL_BAR_COVERAGE_EVIDENCE = "observed-pit-market-breadth/v1"
UNMANAGED_DRAFT_BASIS = "unmanaged_draft"
_PERSONAL_RETROSPECTIVE_ADJUSTED = "PERSONAL_RETROSPECTIVE_ADJUSTED"
_BAR_CODE_CHUNK = 8
_AM_SIGNAL_PRICE_SQL = """COALESCE(
    CASE WHEN json_valid(payload)
         THEN json_extract(payload, '$.MAdjC') END,
    CASE WHEN json_valid(payload)
         THEN json_extract(payload, '$.MorningAdjustmentClose') END,
    CASE WHEN json_valid(raw_payload)
         THEN json_extract(raw_payload, '$.MAdjC') END,
    CASE WHEN json_valid(raw_payload)
         THEN json_extract(raw_payload, '$.MorningAdjustmentClose') END
)"""


def _session_close_as_of(day: str) -> str:
    hhmmss = "15:30:00" if day >= CLOSE_CHANGE_DATE else "15:00:00"
    return f"{day}T{hhmmss}+09:00"


def _morning_acquisition_as_of(day: str) -> str:
    return f"{str(day)[:10]}T12:30:00+09:00"


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if table not in _table_names(connection):
        return set()
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _code_chunks(codes: Sequence[str], *, size: int | None = None):
    ordered = tuple(sorted({str(code).strip() for code in codes if str(code).strip()}))
    step = max(int(_BAR_CODE_CHUNK if size is None else size), 1)
    for index in range(0, len(ordered), step):
        yield ordered[index : index + step]


def _bar_code_clause(
    codes: Sequence[str], *, catalog: bool = False
) -> tuple[str, list[Any]]:
    wanted = [str(code).strip() for code in codes if str(code).strip()]
    if not wanted:
        return "0", []
    placeholders = ",".join("?" for _ in wanted)
    column = CATALOG_CODE_SQL if catalog else "code"
    return f"{column} IN ({placeholders})", wanted


def _iter_bar_presence(
    db_path: Any,
    *,
    as_of: str,
    from_event: str,
    to_event: str,
    codes: Sequence[str],
):
    """Yield ``(code, date, available_at)`` only for one code page."""

    wanted = tuple(str(code).strip() for code in codes if str(code).strip())
    if not wanted:
        return
    code_sql, code_params = _bar_code_clause(wanted)
    conn = _scoped_read_connection(db_path)
    close_connection = conn is None
    if conn is None:
        conn = connect_readonly(db_path)
    try:
        clock = resolve_read_clock(as_of, conn=conn)
        params = [
            clock.decision_at,
            clock.decision_at,
            clock.observed_through,
            _date_bound(from_event),
            _date_bound(to_event),
            *code_params,
        ]
        table = (
            PERSONAL_HISTORY_COMPACT_BARS_TABLE
            if _compact_v8_or_legacy(db_path)
            else "jquants_daily_bars"
        )
        rows = conn.execute(
            f"SELECT code, date, available_at, event_time, ingested_at FROM {table} "
            "WHERE available_at IS NOT NULL AND event_time IS NOT NULL "
            "AND ingested_at IS NOT NULL "
            "AND available_at <= ? AND event_time <= ? AND ingested_at <= ? "
            f"AND date >= ? AND date <= ? AND {code_sql}",
            params,
        )
        for code, day, available, event_time, ingested in rows:
            if not available or available > clock.decision_at:
                continue
            if not event_time or str(event_time) > clock.decision_at:
                continue
            if not ingested or str(ingested) > clock.observed_through:
                continue
            yield str(code), str(day)[:10], str(available or "")
        return
    except sqlite3.OperationalError:
        pass
    finally:
        if close_connection:
            conn.close()
    for row in get_equity_bars_daily(
        as_of=as_of,
        from_event=from_event,
        to_event=to_event,
        codes=wanted,
        db_path=db_path,
    ):
        yield (
            str(row.get("code") or ""),
            str(row.get("date") or "")[:10],
            str(row.get("available_at") or ""),
        )


def _iter_catalog_bar_presence(
    db_path: Any,
    *,
    as_of: str,
    dataset: str,
    from_event: str,
    to_event: str,
    codes: Sequence[str],
    event_cutoff: str | None = None,
    ingested_cutoff: str | None = None,
):
    """Yield catalog bar presence for one governed product. No session-close substitute."""

    wanted = tuple(str(code).strip() for code in codes if str(code).strip())
    if not wanted:
        return
    code_sql, code_params = _bar_code_clause(wanted, catalog=True)
    conn = _scoped_read_connection(db_path)
    close_connection = conn is None
    if conn is None:
        conn = connect_readonly(db_path)
    try:
        clock = resolve_read_clock(as_of, conn=conn)
        event_wall = normalize_as_of(event_cutoff or clock.decision_at)
        ingested_wall = normalize_as_of(ingested_cutoff or clock.observed_through)
        if event_wall > clock.decision_at:
            raise PitError("catalog event cutoff exceeds decision clock")
        if ingested_wall > clock.observed_through:
            raise PitError("catalog ingestion cutoff exceeds observation clock")
        vis_sql = [
            "event_time IS NOT NULL",
            "event_time <= ?",
            "available_at IS NOT NULL",
            "available_at <= ?",
            "ingested_at IS NOT NULL",
            "ingested_at <= ?",
        ]
        vis_bound = [event_wall, clock.decision_at, ingested_wall]
        signal_gate = (
            f" AND CAST({_AM_SIGNAL_PRICE_SQL} AS REAL) > 0"
            if dataset == "equities_bars_daily_am"
            else ""
        )
        params = [
            dataset,
            *vis_bound,
            _date_bound(from_event),
            _date_bound(to_event),
            *code_params,
        ]
        select_columns = (
            "source,dataset,natural_key,event_time,available_at,ingested_at,"
            "payload,raw_payload"
        )
        versions = [
            f"SELECT {select_columns},1 AS _pit_current FROM jquants_records"
        ]
        revision_columns = _table_columns(conn, "jquants_records_revisions")
        if set(select_columns.split(",")) <= revision_columns:
            versions.append(
                f"SELECT {select_columns},0 AS _pit_current "
                "FROM jquants_records_revisions"
            )
        rows = conn.execute(
            "WITH pit_versions AS ("
            + " UNION ALL ".join(versions)
            + "), pit_visible AS (SELECT * FROM pit_versions "
            "WHERE source='jquants' AND dataset=? AND "
            + " AND ".join(vis_sql)
            + " AND substr(event_time, 1, 10) >= ? "
            "AND substr(event_time, 1, 10) <= ? AND "
            + code_sql
            + "), pit_ranked AS (SELECT *,ROW_NUMBER() OVER ("
            "PARTITION BY source,dataset,natural_key "
            "ORDER BY available_at DESC,ingested_at DESC,_pit_current DESC"
            ") AS _pit_rank FROM pit_visible) "
            f"SELECT {CATALOG_CODE_SQL},substr(event_time,1,10),available_at,"
            "event_time,ingested_at FROM pit_ranked WHERE _pit_rank=1"
            + signal_gate,
            params,
        )
        for code, day, available, event_time, ingested in rows:
            if not available or available > clock.decision_at:
                continue
            if not event_time or str(event_time) > str(
                event_cutoff or clock.decision_at
            ):
                continue
            if (
                not ingested
                or str(ingested) > clock.observed_through
                or str(ingested) > str(ingested_cutoff or clock.decision_at)
            ):
                continue
            yield str(code or ""), str(day)[:10], str(available or "")
    finally:
        if close_connection:
            conn.close()


def _iter_equity_bars_visible(
    db_path: Any,
    *,
    as_of: str,
    from_event: str,
    to_event: str,
    codes: Sequence[str],
):
    """Yield PIT-visible bars for one code. Peak memory is O(dates)."""

    wanted = tuple(str(code).strip() for code in codes if str(code).strip())
    if not wanted:
        return
    try:
        yield from get_equity_bars_daily(
            as_of=as_of,
            from_event=from_event,
            to_event=to_event,
            codes=wanted,
            db_path=db_path,
        )
        return
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
    code_sql, code_params = _bar_code_clause(wanted)
    extra_where = f"date >= ? AND date <= ? AND {code_sql}"
    params = [_date_bound(from_event), _date_bound(to_event), *code_params]
    yield from run_query(
        db_path,
        as_of=as_of,
        table="jquants_daily_bars",
        extra_where=extra_where,
        params=list(params),
        order_by="code, date",
    )


def _compact_fail_reason(exc: BaseException) -> str | None:
    message = str(exc)
    if (
        "rebuild as personal-draft-history/v8" in message
        or "compact v7 marker or schema is invalid" in message
    ):
        return "compact_v7_marker_or_schema_invalid"
    if "cannot mix compact" in message:
        return "mixed_compact_and_typed_or_generic_bars"
    return None


def _observed_bar_day_evidence(
    day: str,
    *,
    expected: int,
    observed: int,
    minimum_ratio: float,
) -> dict[str, Any]:
    missing = expected - observed
    allowed_missing = allowed_missing_observed_bars(expected, minimum_ratio)
    ratio = (observed / expected) if expected else 0.0
    return {
        "date": day,
        "expected": expected,
        "observed": observed,
        "missing": missing,
        "allowed_missing": allowed_missing,
        "ratio": ratio,
        "within_allowed_missing": missing <= allowed_missing,
        "meets_minimum_ratio": ratio >= minimum_ratio,
    }


def _coverage_fail(reason: str, *, minimum_ratio: float) -> dict[str, Any]:
    return {
        "version": PERSONAL_BAR_COVERAGE_EVIDENCE,
        "evidence_kind": "OBSERVED",
        "status": "FAIL",
        "reason": reason,
        "minimum_ratio": minimum_ratio,
    }


def observed_market_bar_coverage(
    db_path: Any,
    universe: Any,
    *,
    minimum_ratio: float,
    bar_dataset: str = "equities_bars_daily",
    as_of_for_day: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Measure PIT-visible bar breadth for one resolved daily universe."""

    expected_by_day = dict(universe.decision_memberships)
    expected_total = sum(len(codes) for codes in expected_by_day.values())
    if expected_total == 0:
        return {
            "version": PERSONAL_BAR_COVERAGE_EVIDENCE,
            "evidence_kind": "OBSERVED",
            "status": "UNKNOWN",
            "reason": "bar_tables_or_expected_membership_missing",
            "minimum_ratio": minimum_ratio,
            "bar_dataset": bar_dataset,
        }
    if as_of_for_day is None:
        if bar_dataset == "equities_bars_daily_am":
            raise PitError("AM coverage requires an explicit per-day decision clock")
        as_of_for_day = {
            str(day): _session_close_as_of(str(day))
            for day, _codes in universe.decision_memberships
        }
    observed_counts: dict[str, int] = {day: 0 for day in expected_by_day}
    missing_sample: list[dict[str, str]] = []
    am_product = bar_dataset == "equities_bars_daily_am"
    try:
        with _readonly_connection_scope(db_path):
            conn = _scoped_read_connection(db_path)
            if conn is None:
                raise PitError("PIT observation cutoff is missing; bind a snapshot or draft view")
            sample_as_of = next(iter(as_of_for_day.values()))
            resolve_read_clock(sample_as_of, conn=conn)
            if am_product:
                tables = _table_names(conn)
                if "jquants_records" not in tables:
                    return {
                        "version": PERSONAL_BAR_COVERAGE_EVIDENCE,
                        "evidence_kind": "OBSERVED",
                        "status": "UNKNOWN",
                        "reason": "equities_bars_daily_am_product_unavailable",
                        "minimum_ratio": minimum_ratio,
                        "bar_dataset": bar_dataset,
                    }
                present = conn.execute(
                    "SELECT 1 FROM jquants_records WHERE source='jquants' "
                    "AND dataset='equities_bars_daily_am' LIMIT 1"
                ).fetchone()
                if present is None:
                    return {
                        "version": PERSONAL_BAR_COVERAGE_EVIDENCE,
                        "evidence_kind": "OBSERVED",
                        "status": "UNKNOWN",
                        "reason": "equities_bars_daily_am_product_unavailable",
                        "minimum_ratio": minimum_ratio,
                        "bar_dataset": bar_dataset,
                    }
            for day, day_codes in universe.decision_memberships:
                information_as_of = (as_of_for_day or {}).get(day)
                if not information_as_of:
                    raise PitError(
                        "coverage requires an explicit per-day decision clock"
                    )
                acquisition_as_of = (
                    _morning_acquisition_as_of(day)
                    if am_product
                    else information_as_of
                )
                seen: set[str] = set()
                expected_today = set(day_codes)
                from .cooperative_deadline import check_deadline

                check_deadline()
                for chunk in _code_chunks(tuple(expected_today)):
                    check_deadline()
                    iterator = (
                        _iter_catalog_bar_presence(
                            db_path,
                            as_of=acquisition_as_of,
                            dataset=bar_dataset,
                            from_event=day,
                            to_event=day,
                            codes=chunk,
                            event_cutoff=information_as_of,
                            ingested_cutoff=acquisition_as_of,
                        )
                        if am_product
                        else _iter_bar_presence(
                            db_path,
                            as_of=information_as_of,
                            from_event=day,
                            to_event=day,
                            codes=chunk,
                        )
                    )
                    for code, bar_day, available in iterator:
                        if bar_day != day or not code or code in seen:
                            continue
                        if not available or available > acquisition_as_of:
                            continue
                        seen.add(code)
                observed_counts[day] = len(seen & expected_today)
                if len(missing_sample) < 20:
                    missing_sample.extend(
                        {"date": day, "code": code}
                        for code in sorted(expected_today - seen)[
                            : 20 - len(missing_sample)
                        ]
                    )
    except PitError as exc:
        reason = _compact_fail_reason(exc)
        if reason is not None:
            return _coverage_fail(reason, minimum_ratio=minimum_ratio)
        raise
    except sqlite3.Error:
        return {
            "version": PERSONAL_BAR_COVERAGE_EVIDENCE,
            "evidence_kind": "OBSERVED",
            "status": "UNKNOWN",
            "reason": "bar_tables_or_expected_membership_missing",
            "minimum_ratio": minimum_ratio,
        }

    observed_total = 0
    daily: list[dict[str, Any]] = []
    for day, codes in universe.decision_memberships:
        expected = len(codes)
        observed = int(observed_counts.get(day, 0))
        observed_total += observed
        daily.append(
            _observed_bar_day_evidence(
                day,
                expected=expected,
                observed=observed,
                minimum_ratio=minimum_ratio,
            )
        )
    overall_ratio = observed_total / expected_total
    minimum_daily_ratio = min(float(row["ratio"]) for row in daily)
    daily_missing_ok = all(bool(row["within_allowed_missing"]) for row in daily)
    passed = overall_ratio >= minimum_ratio and daily_missing_ok
    evidence: dict[str, Any] = {
        "version": PERSONAL_BAR_COVERAGE_EVIDENCE,
        "evidence_kind": "OBSERVED",
        "status": "PASS" if passed else "FAIL",
        "bar_dataset": bar_dataset,
        "minimum_ratio": minimum_ratio,
        "overall_ratio": overall_ratio,
        "minimum_daily_ratio": minimum_daily_ratio,
        "daily_missing_ok": daily_missing_ok,
        "expected_rows": expected_total,
        "observed_rows": observed_total,
        "missing_rows": expected_total - observed_total,
        "worst_days": sorted(
            daily, key=lambda row: (float(row["ratio"]), str(row["date"]))
        )[:10],
        "missing_sample": missing_sample,
    }
    if not passed:
        evidence["reason"] = (
            "daily_missing_above_allowance"
            if not daily_missing_ok
            else "overall_ratio_below_minimum"
        )
    return evidence


def _corporate_fail(reason: str) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "price_basis": _PERSONAL_RETROSPECTIVE_ADJUSTED,
        "reason": reason,
        "checked_codes": 0,
        "affected_codes": [],
        "suspicious_jump_codes": [],
        "supported_factor_events": [],
        "extreme_price_move_events": [],
    }


def _corporate_unknown(reason: str) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "price_basis": _PERSONAL_RETROSPECTIVE_ADJUSTED,
        "reason": reason,
        "checked_codes": 0,
        "affected_codes": [],
        "suspicious_jump_codes": [],
        "supported_factor_events": [],
        "extreme_price_move_events": [],
    }


def classify_corporate_action_observations(
    observations: Sequence[Mapping[str, Any]],
    *,
    expected_codes: Sequence[str],
    lookback_start: str,
    period_end: str,
) -> dict[str, Any]:
    """Classify factor-ratio changes and advisory adjusted moves from bars."""

    wanted = {str(code).strip() for code in expected_codes if str(code).strip()}
    if not wanted:
        return _corporate_unknown("resolved_universe_empty")
    supported_events: list[dict[str, Any]] = []
    extreme_price_move_events: list[dict[str, Any]] = []
    observed_codes: set[str] = set()
    missing_adjusted_codes: set[str] = set()
    adjusted_observations = 0
    observations_n = 0
    previous: dict[str, tuple[str, float, float, float | None]] = {}
    ordered = sorted(
        observations,
        key=lambda row: (str(row.get("code") or ""), str(row.get("date") or "")[:10]),
    )
    for row in ordered:
        code = str(row.get("code") or "")
        day = str(row.get("date") or "")[:10]
        if code not in wanted or not day:
            continue
        raw_value = row.get("close")
        if raw_value is None:
            continue
        observed_codes.add(code)
        observations_n += 1
        try:
            raw_close = float(raw_value)
        except (TypeError, ValueError):
            missing_adjusted_codes.add(code)
            continue
        adjusted_value = row.get("adjustment_close")
        if adjusted_value is None or raw_close <= 0.0:
            missing_adjusted_codes.add(code)
            continue
        try:
            adjusted = float(adjusted_value)
        except (TypeError, ValueError):
            missing_adjusted_codes.add(code)
            continue
        if adjusted <= 0.0:
            missing_adjusted_codes.add(code)
            continue
        adjusted_observations += 1
        price_ratio = adjusted / raw_close
        raw_volume = row.get("volume")
        adjusted_volume = row.get("adjustment_volume")
        volume_ratio: float | None = None
        if (
            raw_volume is not None
            and float(raw_volume) != 0.0
            and adjusted_volume is not None
        ):
            volume_ratio = float(adjusted_volume) / float(raw_volume)
        prior = previous.get(code)
        if prior is not None:
            (
                prior_day,
                prior_adjusted,
                prior_price_ratio,
                prior_volume_ratio,
            ) = prior
            price_factor_changed = (
                prior_price_ratio != 0.0
                and abs(price_ratio / prior_price_ratio - 1.0) > 0.01
            )
            volume_factor_changed = (
                volume_ratio is not None
                and prior_volume_ratio is not None
                and prior_volume_ratio != 0.0
                and abs(volume_ratio / prior_volume_ratio - 1.0) > 0.01
            )
            if price_factor_changed or volume_factor_changed:
                supported_events.append(
                    {
                        "code": code,
                        "date": day,
                        "previous_date": prior_day,
                        "price_ratio_changed": price_factor_changed,
                        "volume_ratio_changed": volume_factor_changed,
                    }
                )
            adjusted_return = adjusted / prior_adjusted - 1.0
            if abs(adjusted_return) > 0.35:
                extreme_price_move_events.append(
                    {
                        "code": code,
                        "date": day,
                        "previous_date": prior_day,
                        "adjusted_close_return": adjusted_return,
                        "classification": "advisory_market_or_data_move",
                    }
                )
        previous[code] = (day, adjusted, price_ratio, volume_ratio)

    missing_codes = sorted(wanted - observed_codes)
    supported_codes = sorted({event["code"] for event in supported_events})
    extreme_move_codes = sorted(
        {event["code"] for event in extreme_price_move_events}
    )
    warned = bool(
        extreme_price_move_events or missing_codes or missing_adjusted_codes
    )
    adjustment_ratio = (
        adjusted_observations / observations_n if observations_n else 0.0
    )
    return {
        "status": "WARN" if warned else "OBSERVED",
        "price_basis": _PERSONAL_RETROSPECTIVE_ADJUSTED,
        "reason": (
            "extreme_adjusted_price_move_or_missing_evidence"
            if warned
            else "supported_factor_events_handled_by_retrospective_basis"
        ),
        "checked_codes": len(wanted),
        "lookback_start": lookback_start,
        "period_end": period_end,
        "adjustment_observation_ratio": adjustment_ratio,
        "affected_codes": supported_codes,
        "suspicious_jump_codes": extreme_move_codes,
        "risk_codes": [],
        "supported_factor_events": supported_events,
        "extreme_price_move_events": extreme_price_move_events,
        "missing_codes": missing_codes,
        "missing_adjusted_codes": sorted(missing_adjusted_codes),
        "adjusted_jump_threshold": 0.35,
        "adjustment_factor_change_threshold": 0.01,
        "handling": (
            "supported_factor_events_are_handled; extreme_adjusted_price_"
            "moves_are_review_advisories_not_corporate_action_proof"
        ),
        "future_event_policy": "never_reject_an_earlier_fold",
        "unfilled_rank_bias_possible": True,
    }


def universe_corporate_action_check(
    db_path: Any,
    *,
    universe: Any,
    lookback_days: int,
    decision_cutoff: str = "session_close",
) -> dict[str, Any]:
    """Classify handled split boundaries and advisory adjusted-price moves.

    Morning cutoff never reads daily session close. Callers with a typed
    research view must supply AM vintages; this helper is session-close only.
    """

    if str(decision_cutoff) == "morning_close":
        return _corporate_unknown("morning_corporate_action_evidence_unavailable")

    expected_codes = {
        code
        for _day, codes in universe.decision_memberships
        for code in codes
    }
    if not expected_codes:
        return _corporate_unknown("resolved_universe_empty")
    start = (
        date.fromisoformat(universe.period_start) - timedelta(days=lookback_days)
    ).isoformat()
    end = str(universe.period_end)
    end_as_of = _session_close_as_of(end)
    collected: list[dict[str, Any]] = []
    try:
        with _readonly_connection_scope(db_path):
            for chunk in _code_chunks(tuple(expected_codes), size=1):
                for row in _iter_equity_bars_visible(
                    db_path,
                    as_of=end_as_of,
                    from_event=start,
                    to_event=end,
                    codes=chunk,
                ):
                    collected.append(dict(row))
    except PitError as exc:
        reason = _compact_fail_reason(exc)
        if reason is not None:
            return _corporate_fail(reason)
        raise
    except sqlite3.Error:
        return _corporate_unknown("bar_tables_missing")
    return classify_corporate_action_observations(
        collected,
        expected_codes=tuple(expected_codes),
        lookback_start=start,
        period_end=end,
    )


def _source_sync_document(
    *,
    status: str,
    basis: str,
    execution_allowed: bool,
    quality_verified: bool,
    required_datasets: Sequence[str],
    source_publication_state: Any,
    failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "status": status,
        "basis": basis,
        "execution_allowed": execution_allowed,
        "quality_verified": quality_verified,
        "source_publication_state": source_publication_state,
        "required_datasets": list(required_datasets),
        "source_complete_claim": False,
        "completeness_scope": None,
    }
    if failures is not None:
        document["failures"] = failures
    return document


def source_sync_evidence(
    db_path: Any,
    snapshot_manifest: Mapping[str, Any],
    *,
    required_datasets: Sequence[str],
) -> dict[str, Any]:
    """Read managed sync controls when present; unmanaged DRAFT stays UNKNOWN."""

    provenance = snapshot_manifest.get("source_policy_provenance")
    source_policy = dict(provenance) if isinstance(provenance, dict) else {}
    managed = bool(
        source_policy.get("table_present") and source_policy.get("row_present")
    )
    publication_state = source_policy.get("publication_state")
    connection = connect_readonly(db_path)
    try:
        tables = _table_names(connection)
        has_validation = "ingestion_validation" in tables
        has_watermarks = "ingestion_watermarks" in tables
        if not managed and not has_validation and not has_watermarks:
            return _source_sync_document(
                status="UNKNOWN",
                basis=UNMANAGED_DRAFT_BASIS,
                execution_allowed=True,
                quality_verified=False,
                required_datasets=required_datasets,
                source_publication_state=publication_state,
            )
        if not has_validation or not has_watermarks:
            return _source_sync_document(
                status="UNKNOWN",
                basis="managed_sync_controls_missing",
                execution_allowed=False,
                quality_verified=False,
                required_datasets=required_datasets,
                source_publication_state=publication_state,
            )
        validation_columns = _table_columns(connection, "ingestion_validation")
        watermark_columns = _table_columns(connection, "ingestion_watermarks")
        if not {"dataset", "status"} <= validation_columns or not {
            "dataset",
            "last_ingested_at",
        } <= watermark_columns:
            return _source_sync_document(
                status="UNKNOWN",
                basis="managed_sync_controls_incompatible",
                execution_allowed=False,
                quality_verified=False,
                required_datasets=required_datasets,
                source_publication_state=publication_state,
            )
        order_column = "id" if "id" in validation_columns else "rowid"
        latest_rows = connection.execute(
            "SELECT v.dataset,v.status"
            + " FROM ingestion_validation v JOIN ("
            + f"SELECT dataset,MAX({order_column}) AS latest_id "
            + "FROM ingestion_validation GROUP BY dataset) latest "
            + f"ON latest.dataset=v.dataset AND latest.latest_id=v.{order_column}",
        ).fetchall()
        validation: dict[str, dict[str, Any]] = {}
        for row in latest_rows:
            dataset = str(row["dataset"] or "")
            validation[dataset] = {
                "status": str(row["status"] or "").lower(),
            }
        watermark_rows = connection.execute(
            "SELECT dataset,last_ingested_at FROM ingestion_watermarks"
        ).fetchall()
        watermarks = {
            str(row["dataset"]): str(row["last_ingested_at"] or "")
            for row in watermark_rows
        }
        failures: list[dict[str, Any]] = []
        for dataset in required_datasets:
            latest = validation.get(dataset)
            watermark = watermarks.get(dataset, "")
            if latest is None or latest["status"] != "pass":
                failures.append(
                    {
                        "dataset": dataset,
                        "reason": "latest_validation_not_pass",
                        "observed_status": None if latest is None else latest["status"],
                    }
                )
            if not watermark:
                failures.append(
                    {"dataset": dataset, "reason": "watermark_missing"}
                )
        if not tuple(required_datasets):
            return _source_sync_document(
                status="UNKNOWN",
                basis="required_datasets_empty",
                execution_allowed=False,
                quality_verified=False,
                required_datasets=required_datasets,
                source_publication_state=publication_state,
            )
        failed = bool(failures)
        return _source_sync_document(
            status="FAIL" if failed else "UNKNOWN",
            basis="local_validation_and_watermark",
            execution_allowed=not failed,
            quality_verified=False,
            required_datasets=required_datasets,
            source_publication_state=publication_state,
            failures=failures,
        )
    finally:
        connection.close()


__all__ = [
    "PERSONAL_BAR_COVERAGE_EVIDENCE",
    "UNMANAGED_DRAFT_BASIS",
    "classify_corporate_action_observations",
    "observed_market_bar_coverage",
    "source_sync_evidence",
    "universe_corporate_action_check",
]
