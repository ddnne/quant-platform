"""Persistent collection-coverage ledger built from Phase 3.5 checks."""

from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

from cf_platform.ingest_premium.coverage import CheckResult, run_coverage
from data_contracts.coverage import (
    COVERAGE_STATUSES,
    POLICY_VERSION,
    CollectionCoverageContract,
    all_coverage_contracts,
    coverage_contract_for,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True)
class RequiredCoverageSegment:
    """One independently planned segment required by a coverage contract."""

    source: str
    dataset: str
    segment_id: str
    segment_start: str
    segment_end: str
    expected_scope: Mapping[str, Any]
    expected_items: int | None = None


@dataclass(frozen=True)
class CollectionReceipt:
    """Auditable result of collecting and structuring one source window."""

    source: str
    dataset: str
    segment_id: str
    segment_start: str
    segment_end: str
    expected_scope: Mapping[str, Any]
    expected_items: int | None
    observed_items: int
    raw_page_count: int
    raw_row_count: int
    structured_row_count: int
    pagination_exhausted: bool
    digests: Mapping[str, Any]
    run_id: int
    status: str
    error: str | None
    checked_at: str


def _month_end(value: date) -> date:
    return value.replace(day=calendar.monthrange(value.year, value.month)[1])


def plan_required_segments(
    policy: CollectionCoverageContract,
    target_end: str,
    *,
    source: str = "jquants",
    expected_items_by_segment: Mapping[str, int] | None = None,
) -> tuple[RequiredCoverageSegment, ...]:
    """Create the required inventory independently of observed rows/receipts."""
    start = date.fromisoformat(policy.history_target_start)
    end = date.fromisoformat(target_end)
    if end < start:
        raise ValueError("target_end precedes coverage history target")
    granularity = policy.segment_granularity
    segments: list[RequiredCoverageSegment] = []

    def _append(segment_id: str, segment_start: date, segment_end: date) -> None:
        expected_items = None
        if expected_items_by_segment is not None:
            expected_items = expected_items_by_segment.get(segment_id)
            if expected_items is not None and expected_items < 0:
                raise ValueError("expected segment items must be non-negative")
        unit = (
            "source_event"
            if policy.expected_frequency == "event_driven"
            else "source_query"
        )
        # Non-event source_query needs expected_items for COMPLETE; default one exhausted query.
        if expected_items is None and unit == "source_query":
            expected_items = 1
        scope = {
            "coverage_mode": policy.coverage_mode,
            "expected_frequency": policy.expected_frequency,
            "expected_item_unit": unit,
            "segment_end": segment_end.isoformat(),
            "segment_start": segment_start.isoformat(),
            "universe_rule": policy.universe_rule,
            "segment_granularity": granularity,
        }
        segments.append(RequiredCoverageSegment(
            source=source,
            dataset=policy.dataset_id,
            segment_id=segment_id,
            segment_start=segment_start.isoformat(),
            segment_end=segment_end.isoformat(),
            expected_scope=scope,
            expected_items=expected_items,
        ))

    if granularity == "calendar_month":
        cursor = start
        while cursor <= end:
            segment_end = min(_month_end(cursor), end)
            _append(cursor.strftime("%Y-%m"), cursor, segment_end)
            cursor = date.fromordinal(segment_end.toordinal() + 1)
    elif granularity == "official_archive_year":
        for year in range(start.year, end.year + 1):
            segment_start = max(start, date(year, 1, 1))
            segment_end = min(end, date(year, 12, 31))
            _append(str(year), segment_start, segment_end)
    elif granularity == "official_archive_day":
        # Walks every calendar day. JSDA OTC coverage_mode is
        # official_archive_index_reconciled — required publication days come
        # from the official year index, not weekends/holidays. Calendar-day
        # inventory is why jsda_otc PARTIAL (~2898) >> PARSE_ZERO (2).
        # Do not COMPLETE empty non-index days from this expansion.
        cursor = start
        while cursor <= end:
            _append(cursor.isoformat(), cursor, cursor)
            cursor = date.fromordinal(cursor.toordinal() + 1)
    elif granularity == "source_time_series_file":
        # Stable id must match discovery/ingest. Date-range ids create phantom PARTIAL inventory.
        stable_ids = {
            "jsda_tokyo_repo_rates": "jsda-era-timeseries",
        }
        segment_id = stable_ids.get(
            policy.dataset_id, f"{policy.dataset_id}_timeseries"
        )
        _append(segment_id, start, end)
    else:  # pragma: no cover
        raise ValueError(
            f"unsupported segment granularity: {policy.segment_granularity!r}"
        )
    return tuple(segments)


def evaluate_segment(
    policy: CollectionCoverageContract,
    required: RequiredCoverageSegment,
    receipt: CollectionReceipt | None,
) -> tuple[str, dict[str, Any]]:
    """Evaluate one required segment without treating absent events as gaps."""
    if receipt is None:
        return "PARTIAL", {"reason": "missing collection receipt"}
    identity_matches = (
        receipt.source == required.source
        and receipt.dataset == required.dataset
        and receipt.segment_id == required.segment_id
        and receipt.segment_start == required.segment_start
        and receipt.segment_end == required.segment_end
        and dict(receipt.expected_scope) == dict(required.expected_scope)
        and receipt.expected_items == required.expected_items
    )
    if not identity_matches:
        return "PARTIAL", {"reason": "receipt does not match required scope"}
    # Trusted-path gate: only Ed25519-verified signed receipts may COMPLETE.
    if not is_complete_eligible_receipt(receipt):
        return "PARTIAL", {
            "reason": "receipt not COMPLETE-eligible (valid Ed25519 signature required)",
            "eligibility": receipt_eligibility(receipt),
            "issuer_key_id": receipt.digests.get("issuer_key_id"),
            "issuer_class": receipt.digests.get("issuer_class"),
        }
    if receipt.status == "FAILED" and receipt.digests.get("failure_kind") in {
        "MISSING_EXPECTED_SEGMENT", "DEFERRED_SOURCE_GAP"
    }:
        reason = (
            "expected source segment is missing"
            if receipt.digests.get("failure_kind") == "MISSING_EXPECTED_SEGMENT"
            else "authoritative source gap explicitly deferred"
        )
        return "PARTIAL", {"reason": reason}
    if receipt.status != "SUCCESS" or receipt.error:
        return "FAILED", {"reason": receipt.error or "collection failed"}
    if not receipt.pagination_exhausted:
        return "PARTIAL", {"reason": "pagination not exhausted"}
    if (
        policy.expected_frequency != "event_driven"
        and required.expected_items is None
    ):
        return "PARTIAL", {
            "reason": "non-event segment lacks explicit expected items"
        }
    if receipt.expected_items is not None and (
        receipt.observed_items != receipt.expected_items
    ):
        return "PARTIAL", {"reason": "expected scope not fully observed"}
    if (
        policy.expected_frequency != "event_driven"
        and receipt.observed_items == 0
    ):
        return "PARTIAL", {
            "reason": "empty receipt is complete only for event-driven windows"
        }
    raw_digest = receipt.digests.get("raw")
    if policy.raw_retention_required and (
        receipt.raw_page_count < 1
        or not isinstance(raw_digest, str)
        or not raw_digest
    ):
        return "PARTIAL", {"reason": "raw pages/digest not retained"}
    if (
        policy.structured_reconciliation_required
        and receipt.raw_row_count != receipt.structured_row_count
    ):
        return "FAILED", {"reason": "raw/structured row mismatch"}
    return "COMPLETE", {
        "reason": "receipt reconciled",
        "event_zero": receipt.observed_items == 0,
    }


def _latest_run_id(conn: sqlite3.Connection, dataset: str) -> int | None:
    try:
        row = conn.execute(
            "SELECT run_id FROM ingestion_validation WHERE dataset=? "
            "ORDER BY started_at DESC, id DESC LIMIT 1",
            (dataset,),
        ).fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row is not None and row[0] is not None else None


def _date_prefix(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) < 10:
        return None
    return text[:10]


def _receipt_observed_window(
    receipts: Sequence[CollectionReceipt],
) -> tuple[str | None, str | None, int]:
    """Observed calendar span from SUCCESS receipts with ``raw_row_count > 0``."""
    starts: list[str] = []
    ends: list[str] = []
    raw_total = 0
    for receipt in receipts:
        if receipt.status != "SUCCESS":
            continue
        raw_n = int(receipt.raw_row_count or 0)
        if raw_n <= 0:
            continue
        start = _date_prefix(receipt.segment_start)
        end = _date_prefix(receipt.segment_end)
        if start is None or end is None:
            continue
        starts.append(start)
        ends.append(end)
        raw_total += raw_n
    if not starts:
        return None, None, 0
    return min(starts), max(ends), raw_total


def _merge_observed_window(
    hot_start: str | None,
    hot_end: str | None,
    receipt_start: str | None,
    receipt_end: str | None,
) -> tuple[str | None, str | None]:
    """Union D1-hot C4 window with receipt-plane evidence (calendar dates)."""
    candidates_start = [
        v for v in (_date_prefix(hot_start), _date_prefix(receipt_start)) if v
    ]
    candidates_end = [
        v for v in (_date_prefix(hot_end), _date_prefix(receipt_end)) if v
    ]
    if not candidates_start and not candidates_end:
        return hot_start, hot_end
    merged_start = min(candidates_start) if candidates_start else None
    merged_end = max(candidates_end) if candidates_end else None
    if (
        merged_start is not None
        and hot_start is not None
        and _date_prefix(hot_start) == merged_start
    ):
        out_start: str | None = str(hot_start)
    else:
        out_start = merged_start
    if (
        merged_end is not None
        and hot_end is not None
        and _date_prefix(hot_end) == merged_end
    ):
        out_end: str | None = str(hot_end)
    else:
        out_end = merged_end
    return out_start, out_end


def _calendar_days_between(start: str, end: str) -> int | None:
    try:
        a = date.fromisoformat(str(start)[:10])
        b = date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    return (b - a).days


def _apply_receipt_freshness_c8(
    evidence: list[CheckResult],
    *,
    dataset: str,
    receipt_end: str | None,
    reference: str,
    freshness_days: int,
) -> list[CheckResult]:
    """Re-score C8 from SUCCESS receipt ``segment_end`` when newer than D1-hot."""
    if not receipt_end:
        return evidence
    receipt_hi = _date_prefix(receipt_end)
    ref = _date_prefix(reference) or str(reference)[:10]
    if receipt_hi is None or ref is None:
        return evidence
    days = _calendar_days_between(receipt_hi, ref)
    if days is None:
        return evidence
    out: list[CheckResult] = []
    replaced = False
    for result in evidence:
        if result.check_id != "C8" or str(result.dataset or "") != dataset:
            out.append(result)
            continue
        hot_hi = result.metrics.get("latest_event_time")
        hot_prefix = _date_prefix(str(hot_hi)) if hot_hi is not None else None
        if hot_prefix is not None and hot_prefix >= receipt_hi:
            out.append(result)
            continue
        if days <= freshness_days:
            status = "pass"
            detail = f"{days} day(s) since latest event_time"
        else:
            status = "fail"
            detail = f"stale: {days} day(s) > {freshness_days}"
        out.append(
            CheckResult(
                "C8",
                dataset,
                status,
                detail,
                {
                    "latest_event_time": receipt_hi,
                    "reference": ref,
                    "max_days": freshness_days,
                    "days_lag": days,
                    "source": "receipt_observed_end",
                    "hot_latest_event_time": hot_hi,
                },
            )
        )
        replaced = True
    if not replaced:
        # No hot C8 (empty dataset) — still emit receipt C8.
        if days <= freshness_days:
            status = "pass"
            detail = f"{days} day(s) since latest event_time"
        else:
            status = "fail"
            detail = f"stale: {days} day(s) > {freshness_days}"
        out.append(
            CheckResult(
                "C8",
                dataset,
                status,
                detail,
                {
                    "latest_event_time": receipt_hi,
                    "reference": ref,
                    "max_days": freshness_days,
                    "days_lag": days,
                    "source": "receipt_observed_end",
                    "hot_latest_event_time": None,
                },
            )
        )
    return out


def _dataset_status(
    results: list[CheckResult],
) -> tuple[str, int, str | None, str | None]:
    """Validation/freshness gates only; segments/receipts own COMPLETE."""
    checks = {result.check_id: result for result in results}
    c3 = checks.get("C3")
    row_count = int(c3.metrics.get("row_count", 0)) if c3 is not None else 0
    c4 = checks.get("C4")
    observed_start = None if c4 is None else c4.metrics.get("event_time_min")
    observed_end = None if c4 is None else c4.metrics.get("event_time_max")

    if any(
        result.check_id in {"C1", "C2", "C3", "C4", "C5"}
        and result.status == "fail"
        for result in results
    ):
        return "FAILED", row_count, observed_start, observed_end
    freshness = checks.get("C8")
    if freshness is not None and freshness.status == "fail":
        return "STALE", row_count, observed_start, observed_end

    validation = checks.get("C2")
    if validation is None or validation.metrics.get("source") != "ingestion_validation":
        return "UNKNOWN", row_count, observed_start, observed_end
    if validation.metrics.get("validation_status") != "pass":
        return "FAILED", row_count, observed_start, observed_end
    return "COMPLETE", row_count, observed_start, observed_end


def _coverage_source(dataset: str) -> str:
    return "jsda" if dataset.startswith("jsda_") else "jquants"


def _jsda_validation_status(
    conn: sqlite3.Connection, dataset: str
) -> tuple[str, int, str | None, str | None]:
    """PIT-shape prerequisite; collection completeness stays receipt-owned."""
    # jsda_* must map here (UNKNOWN otherwise). Not legacy jsda_bond_trades.
    fact_tables = {
        "jsda_otc_bond_reference_prices": "jsda_otc_bond_reference_prices",
        "jsda_tokyo_repo_rates": "jsda_repo_rates",
        "jsda_corporate_bond_transactions": "jsda_corporate_bond_transactions",
    }
    table = fact_tables.get(dataset)
    if table is None:
        return "UNKNOWN", 0, None, None
    try:
        row = conn.execute(
            "SELECT COUNT(*),MIN(event_time),MAX(event_time),"
            "SUM(CASE WHEN available_at IS NULL OR available_at='' THEN 1 ELSE 0 END) "
            f"FROM {table}"
        ).fetchone()
    except sqlite3.Error:
        return "UNKNOWN", 0, None, None
    count = int(row[0] or 0)
    observed_start = None if row[1] is None else str(row[1])
    observed_end = None if row[2] is None else str(row[2])
    missing_available = int(row[3] or 0)
    if missing_available:
        return "FAILED", count, observed_start, observed_end
    return "COMPLETE", count, observed_start, observed_end


def _required_from_inventory(row: Mapping[str, Any]) -> RequiredCoverageSegment:
    try:
        expected_scope = json.loads(str(row["expected_scope"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("coverage segment contains invalid expected scope") from exc
    if not isinstance(expected_scope, dict):
        raise ValueError("coverage segment expected scope must be an object")
    return RequiredCoverageSegment(
        source=str(row["source"]),
        dataset=str(row["dataset"]),
        segment_id=str(row["segment_id"]),
        segment_start=str(row["segment_start"]),
        segment_end=str(row["segment_end"]),
        expected_scope=expected_scope,
        expected_items=(
            None if row["expected_items"] is None else int(row["expected_items"])
        ),
    )


def _receipt_from_row(row: Mapping[str, Any]) -> CollectionReceipt:
    try:
        expected_scope = json.loads(str(row["expected_scope"]))
        digests = json.loads(str(row["digests_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("collection receipt contains invalid JSON evidence") from exc
    if not isinstance(expected_scope, dict) or not isinstance(digests, dict):
        raise ValueError("collection receipt JSON evidence must be objects")
    return CollectionReceipt(
        source=str(row["source"]),
        dataset=str(row["dataset"]),
        segment_id=str(row["segment_id"]),
        segment_start=str(row["segment_start"]),
        segment_end=str(row["segment_end"]),
        expected_scope=expected_scope,
        expected_items=(
            None if row["expected_items"] is None else int(row["expected_items"])
        ),
        observed_items=int(row["observed_items"]),
        raw_page_count=int(row["raw_page_count"]),
        raw_row_count=int(row["raw_row_count"]),
        structured_row_count=int(row["structured_row_count"]),
        pagination_exhausted=bool(row["pagination_exhausted"]),
        digests=digests,
        run_id=int(row["run_id"]),
        status=str(row["status"]),
        error=None if row["error"] is None else str(row["error"]),
        checked_at=str(row["checked_at"]),
    )


def record_collection_receipt(
    conn: sqlite3.Connection, receipt: CollectionReceipt
) -> None:
    """Upsert one run-scoped receipt; caller owns the transaction."""
    if receipt.status not in {"SUCCESS", "FAILED"}:
        raise ValueError("receipt status must be SUCCESS or FAILED")
    counts = (
        receipt.observed_items,
        receipt.raw_page_count,
        receipt.raw_row_count,
        receipt.structured_row_count,
    )
    if any(value < 0 for value in counts):
        raise ValueError("receipt counts must be non-negative")
    columns = (
        "source", "dataset", "segment_id", "segment_start", "segment_end",
        "expected_scope", "expected_items", "observed_items", "raw_page_count",
        "raw_row_count", "structured_row_count", "pagination_exhausted",
        "digests_json", "run_id", "status", "error", "checked_at",
    )
    values = (
        receipt.source, receipt.dataset, receipt.segment_id,
        receipt.segment_start, receipt.segment_end,
        _canonical_json(dict(receipt.expected_scope)), receipt.expected_items,
        receipt.observed_items, receipt.raw_page_count, receipt.raw_row_count,
        receipt.structured_row_count, int(receipt.pagination_exhausted),
        _canonical_json(dict(receipt.digests)), receipt.run_id, receipt.status,
        receipt.error, receipt.checked_at,
    )
    conn.execute(
        "INSERT INTO collection_receipts (" + ",".join(columns) + ") VALUES ("
        + ",".join("?" for _ in columns) + ") "
        "ON CONFLICT(source,dataset,segment_id,run_id) DO UPDATE SET "
        + ",".join(
            f"{column}=excluded.{column}"
            for column in columns
            if column not in {"source", "dataset", "segment_id", "run_id"}
        ),
        values,
    )


def record_required_segments(
    conn: sqlite3.Connection,
    required_segments: Sequence[RequiredCoverageSegment],
    *,
    policy_version: str = POLICY_VERSION,
) -> None:
    """Persist source-planned requirements independently of any receipt."""
    evaluated_at = _now()
    columns = (
        "source", "dataset", "segment_id", "policy_version",
        "segment_start", "segment_end", "expected_scope", "expected_items",
        "status", "receipt_run_id", "evaluated_at", "detail_json",
    )
    sql = (
        "INSERT INTO coverage_segments (" + ",".join(columns) + ") VALUES ("
        + ",".join("?" for _ in columns) + ") "
        "ON CONFLICT(source,dataset,segment_id,policy_version) DO UPDATE SET "
        + ",".join(
            f"{column}=excluded.{column}"
            for column in columns
            if column not in {"source", "dataset", "segment_id", "policy_version"}
        )
    )
    rows = []
    for segment in required_segments:
        if segment.expected_items is not None and segment.expected_items < 0:
            raise ValueError("expected segment items must be non-negative")
        rows.append((
            segment.source, segment.dataset, segment.segment_id, policy_version,
            segment.segment_start, segment.segment_end,
            _canonical_json(dict(segment.expected_scope)), segment.expected_items,
            "UNKNOWN", None, evaluated_at,
            _canonical_json({"reason": "required segment planned"}),
        ))
    conn.executemany(sql, rows)


def _rank_receipt_for_match(item: CollectionReceipt) -> tuple:
    """Trusted first, recovered last, then structured/time."""
    trusted = 1 if is_complete_eligible_receipt(item) else 0
    origin = str(item.digests.get("origin") or "")
    recovered = 1 if (
        item.digests.get("eligibility") == "RECOVERED_RAW_ONLY"
        or origin in {
            "recovered-raw-only",
            "parsed-staging-only",
            "offline-test-fixture",
        }
        or bool(item.digests.get("synthetic"))
    ) else 0
    structured = int(item.structured_row_count or 0)
    return (trusted, -recovered, structured, item.checked_at, item.run_id)


def _latest_receipt_for(
    receipts: Sequence[CollectionReceipt],
    required: RequiredCoverageSegment,
) -> CollectionReceipt | None:
    """Best receipt for a segment; trusted wins over a newer recovered rebuild."""
    exact = [
        receipt for receipt in receipts
        if receipt.source == required.source
        and receipt.dataset == required.dataset
        and receipt.segment_id == required.segment_id
        and receipt.segment_start == required.segment_start
        and receipt.segment_end == required.segment_end
    ]
    if not exact:
        return None
    return max(exact, key=_rank_receipt_for_match)


def _latest_eligible_success_for_segment_id(
    receipts: Sequence[CollectionReceipt],
    *,
    source: str,
    dataset: str,
    segment_id: str,
) -> CollectionReceipt | None:
    """Best COMPLETE-eligible SUCCESS receipt for a segment_id (sticky fallback)."""
    candidates = [
        receipt
        for receipt in receipts
        if receipt.source == source
        and receipt.dataset == dataset
        and receipt.segment_id == segment_id
        and receipt.status == "SUCCESS"
        and is_complete_eligible_receipt(receipt)
    ]
    if not candidates:
        return None
    return max(candidates, key=_rank_receipt_for_match)


def evaluate_required_segments(
    policy: CollectionCoverageContract,
    required_segments: Sequence[RequiredCoverageSegment],
    receipts: Sequence[CollectionReceipt],
) -> tuple[str, list[tuple[RequiredCoverageSegment, CollectionReceipt | None, str, dict[str, Any]]]]:
    """Evaluate the planned inventory, including missing receipts."""
    evaluated = []
    for required in required_segments:
        receipt = _latest_receipt_for(receipts, required)
        status, detail = evaluate_segment(policy, required, receipt)
        evaluated.append((required, receipt, status, detail))
    statuses = [item[2] for item in evaluated]
    if any(status == "FAILED" for status in statuses):
        aggregate = "FAILED"
    elif statuses and all(status == "COMPLETE" for status in statuses):
        aggregate = "COMPLETE"
    else:
        aggregate = "PARTIAL"
    return aggregate, evaluated


def refresh_coverage_ledger(
    conn: sqlite3.Connection,
    db_path: str | Path,
    *,
    datasets: Iterable[str] | None = None,
    today: str | None = None,
    freshness_days: int = 7,
) -> list[dict[str, Any]]:
    """Evaluate Coverage V2 segments and atomically refresh aggregate rows."""
    selected = tuple(datasets) if datasets is not None else tuple(
        policy.dataset_id for policy in all_coverage_contracts()
    )
    if not selected:
        raise ValueError("datasets must not be empty")
    policies = {dataset: coverage_contract_for(dataset) for dataset in selected}
    target_end = today or datetime.now(timezone.utc).date().isoformat()
    jquants_selected = tuple(
        dataset for dataset in selected if _coverage_source(dataset) == "jquants"
    )
    evidence = (
        run_coverage(
            db_path,
            tier="daily",
            datasets=jquants_selected,
            today=target_end,
            freshness_days=freshness_days,
            workers=1,
            strict_live_gates=False,
        )
        if jquants_selected else []
    )
    by_dataset: dict[str, list[CheckResult]] = {dataset: [] for dataset in selected}
    global_failures = [
        result for result in evidence
        if result.dataset is None and result.status == "fail"
    ]
    for result in evidence:
        if result.dataset in by_dataset:
            by_dataset[str(result.dataset)].append(result)

    placeholders = ",".join("?" for _ in selected)
    # status + receipt_run_id: sticky COMPLETE needs prior COMPLETE inventory.
    inventory_cursor = conn.execute(
        "SELECT source,dataset,segment_id,segment_start,segment_end,"
        "expected_scope,expected_items,status,receipt_run_id FROM coverage_segments "
        f"WHERE policy_version=? AND dataset IN ({placeholders})",
        (POLICY_VERSION, *selected),
    )
    inventory_by_dataset: dict[str, dict[str, Mapping[str, Any]]] = {
        dataset: {} for dataset in selected
    }
    for raw in inventory_cursor.fetchall():
        row: Mapping[str, Any] = dict(raw) if isinstance(raw, sqlite3.Row) else {
            "source": raw[0], "dataset": raw[1], "segment_id": raw[2],
            "segment_start": raw[3], "segment_end": raw[4],
            "expected_scope": raw[5], "expected_items": raw[6],
            "status": raw[7], "receipt_run_id": raw[8],
        }
        inventory_by_dataset[str(row["dataset"])][str(row["segment_id"])] = row
    receipt_cursor = conn.execute(
        "SELECT * FROM collection_receipts "
        f"WHERE dataset IN ({placeholders}) "
        "ORDER BY checked_at, run_id",
        selected,
    )
    receipt_columns = tuple(item[0] for item in receipt_cursor.description or ())
    receipts_by_dataset: dict[str, list[CollectionReceipt]] = {
        dataset: [] for dataset in selected
    }
    for raw in receipt_cursor.fetchall():
        row = dict(zip(receipt_columns, raw))
        receipt = _receipt_from_row(row)
        receipts_by_dataset[receipt.dataset].append(receipt)

    evaluated_at = _now()
    rows: list[dict[str, Any]] = []
    segment_rows: list[dict[str, Any]] = []
    for dataset in selected:
        policy = policies[dataset]
        source = _coverage_source(dataset)
        # D1 jquants_records is hot-window only; observed_*/C8 expand from SUCCESS raw receipts.
        receipt_start, receipt_end, receipt_raw_rows = _receipt_observed_window(
            receipts_by_dataset[dataset]
        )
        dataset_evidence = by_dataset[dataset]
        if source == "jquants":
            dataset_evidence = _apply_receipt_freshness_c8(
                dataset_evidence,
                dataset=dataset,
                receipt_end=receipt_end,
                reference=target_end,
                freshness_days=freshness_days,
            )
            by_dataset[dataset] = dataset_evidence
        if source == "jsda":
            validation_status, count, observed_start, observed_end = (
                _jsda_validation_status(conn, dataset)
            )
        else:
            validation_status, count, observed_start, observed_end = _dataset_status(
                dataset_evidence
            )
        if receipt_start is not None or receipt_end is not None:
            observed_start, observed_end = _merge_observed_window(
                observed_start, observed_end, receipt_start, receipt_end,
            )
        if policy.segment_granularity in {
            "official_archive_day", "source_time_series_file"
        }:
            # Keep inventory through target_end, plus already-COMPLETE days past UTC (JST can lead).
            required_segments = tuple(sorted(
                (
                    _required_from_inventory(row)
                    for row in inventory_by_dataset[dataset].values()
                    if str(row["source"]) == source
                    and (
                        str(row["segment_start"]) <= target_end
                        or str(row.get("status") or "") == "COMPLETE"
                    )
                ),
                key=lambda item: (item.segment_start, item.segment_id),
            ))
        else:
            base_segments = plan_required_segments(policy, target_end, source=source)
            expected_items_by_segment: dict[str, int] = {}
            for segment in base_segments:
                inventory = inventory_by_dataset[dataset].get(segment.segment_id)
                if (
                    inventory is not None
                    and inventory["segment_start"] == segment.segment_start
                    and inventory["segment_end"] == segment.segment_end
                    and inventory["expected_scope"] == _canonical_json(
                        dict(segment.expected_scope)
                    )
                    and inventory["expected_items"] is not None
                ):
                    expected_items_by_segment[segment.segment_id] = int(
                        inventory["expected_items"]
                    )
            required_segments = plan_required_segments(
                policy,
                target_end,
                source=source,
                expected_items_by_segment=expected_items_by_segment,
            )
        segment_aggregate, segment_evaluations = evaluate_required_segments(
            policy, required_segments, receipts_by_dataset[dataset]
        )
        segment_statuses: list[str] = []
        for (
            required_segment, receipt, segment_status, segment_detail
        ) in segment_evaluations:
            # Sticky COMPLETE: never demote while a COMPLETE-eligible SUCCESS receipt remains.
            prior_inv = inventory_by_dataset[dataset].get(
                required_segment.segment_id
            )
            prior_status = (
                None if prior_inv is None else str(prior_inv.get("status") or "")
            )
            sticky_receipt = receipt
            if (
                segment_status != "COMPLETE"
                and prior_status == "COMPLETE"
                and (
                    sticky_receipt is None
                    or sticky_receipt.status != "SUCCESS"
                    or not is_complete_eligible_receipt(sticky_receipt)
                )
            ):
                sticky_receipt = _latest_eligible_success_for_segment_id(
                    receipts_by_dataset[dataset],
                    source=required_segment.source,
                    dataset=required_segment.dataset,
                    segment_id=required_segment.segment_id,
                )
            if (
                segment_status != "COMPLETE"
                and prior_status == "COMPLETE"
                and sticky_receipt is not None
                and sticky_receipt.status == "SUCCESS"
                and is_complete_eligible_receipt(sticky_receipt)
            ):
                segment_detail = {
                    **dict(segment_detail),
                    "sticky_complete": True,
                    "demotion_blocked": segment_detail.get("reason"),
                    "reason": "sticky COMPLETE: eligible SUCCESS receipt retained",
                    "sticky_receipt_run_id": sticky_receipt.run_id,
                }
                segment_status = "COMPLETE"
                receipt = sticky_receipt
            segment_statuses.append(segment_status)
            segment_rows.append({
                "source": required_segment.source,
                "dataset": required_segment.dataset,
                "segment_id": required_segment.segment_id,
                "policy_version": POLICY_VERSION,
                "segment_start": required_segment.segment_start,
                "segment_end": required_segment.segment_end,
                "expected_scope": _canonical_json(
                    dict(required_segment.expected_scope)
                ),
                "expected_items": required_segment.expected_items,
                "status": segment_status,
                "receipt_run_id": None if receipt is None else receipt.run_id,
                "evaluated_at": evaluated_at,
                "detail_json": _canonical_json(segment_detail),
            })
        # Recompute aggregate after sticky upgrades so day-roll does not pin dataset PARTIAL.
        if any(status == "FAILED" for status in segment_statuses):
            segment_aggregate = "FAILED"
        elif segment_statuses and all(
            status == "COMPLETE" for status in segment_statuses
        ):
            segment_aggregate = "COMPLETE"
        else:
            segment_aggregate = "PARTIAL"
        if validation_status != "COMPLETE":
            status = validation_status
        else:
            status = segment_aggregate
        if source == "jquants" and global_failures:
            status = "FAILED"
        if status not in COVERAGE_STATUSES:  # pragma: no cover
            raise AssertionError(f"unexpected coverage status: {status}")
        detail = {
            "checks": [result.as_log_dict() for result in dataset_evidence],
            "global_failures": [result.as_log_dict() for result in global_failures],
            "coverage_v2": {
                "required_segments": len(segment_statuses),
                "status_counts": {
                    value: segment_statuses.count(value)
                    for value in sorted(COVERAGE_STATUSES)
                    if segment_statuses.count(value)
                },
                "target_end": target_end,
            },
            "observed_window": {
                "receipt_start": receipt_start,
                "receipt_end": receipt_end,
                "receipt_raw_rows": receipt_raw_rows,
                "source": (
                    "receipt_union_hot"
                    if receipt_start is not None or receipt_end is not None
                    else "hot_c4_only"
                ),
            },
        }
        rows.append({
            "dataset": dataset,
            **asdict(policy),
            "status": status,
            "policy_version": POLICY_VERSION,
            "observed_start": observed_start,
            "observed_end": observed_end,
            "row_count": count,
            "source_run_id": (
                _latest_run_id(conn, dataset)
                if source == "jquants"
                else max(
                    (receipt.run_id for receipt in receipts_by_dataset[dataset]),
                    default=None,
                )
            ),
            "evaluated_at": evaluated_at,
            "detail_json": _canonical_json(detail),
        })

    columns = (
        "dataset", "status", "policy_version", "collection_scope",
        "history_target_start", "history_target_end_rule", "coverage_mode",
        "expected_frequency", "universe_rule", "raw_retention_required",
        "structured_reconciliation_required", "governance_tier",
        "observed_start", "observed_end", "row_count", "source_run_id",
        "evaluated_at", "detail_json",
    )
    sql = (
        "INSERT INTO dataset_coverage (" + ",".join(columns) + ") VALUES ("
        + ",".join("?" for _ in columns) + ") ON CONFLICT(dataset) DO UPDATE SET "
        + ",".join(f"{column}=excluded.{column}" for column in columns if column != "dataset")
    )
    segment_columns = (
        "source", "dataset", "segment_id", "policy_version",
        "segment_start", "segment_end", "expected_scope", "expected_items",
        "status", "receipt_run_id", "evaluated_at", "detail_json",
    )
    segment_sql = (
        "INSERT INTO coverage_segments (" + ",".join(segment_columns)
        + ") VALUES (" + ",".join("?" for _ in segment_columns) + ")"
    )
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            "DELETE FROM coverage_segments "
            "WHERE source=? AND dataset=? AND policy_version=?",
            [(_coverage_source(dataset), dataset, POLICY_VERSION) for dataset in selected],
        )
        conn.executemany(
            segment_sql,
            [tuple(row[column] for column in segment_columns) for row in segment_rows],
        )
        conn.executemany(
            sql,
            [
                tuple(
                    int(row[column])
                    if column in {
                        "raw_retention_required",
                        "structured_reconciliation_required",
                    }
                    else row[column]
                    for column in columns
                )
                for row in rows
            ],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return rows


def read_dataset_coverage(
    db_path: str | Path, *, dataset: str | None = None
) -> list[dict[str, Any]]:
    """Read ledger rows through a forced read-only connection."""
    path = Path(db_path).resolve()
    uri = "file:" + quote(str(path)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if dataset is None:
            cursor = conn.execute("SELECT * FROM dataset_coverage ORDER BY dataset")
        else:
            cursor = conn.execute(
                "SELECT * FROM dataset_coverage WHERE dataset=?", (dataset,)
            )
        return [dict(row) for row in cursor]
    finally:
        conn.close()


def read_collection_receipts(
    db_path: str | Path,
    *,
    dataset: str | None = None,
    segment_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read run-scoped receipt evidence through a forced read-only connection."""
    path = Path(db_path).resolve()
    uri = "file:" + quote(str(path)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        clauses: list[str] = []
        values: list[str] = []
        if dataset is not None:
            clauses.append("dataset=?")
            values.append(dataset)
        if segment_id is not None:
            clauses.append("segment_id=?")
            values.append(segment_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        cursor = conn.execute(
            "SELECT * FROM collection_receipts" + where
            + " ORDER BY dataset, segment_start, checked_at, run_id",
            values,
        )
        return [dict(row) for row in cursor]
    finally:
        conn.close()


def read_coverage_segments(
    db_path: str | Path,
    *,
    dataset: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Read the independently planned V2 inventory and evaluated status."""
    if status is not None and status not in COVERAGE_STATUSES:
        raise ValueError(f"unknown coverage status: {status!r}")
    path = Path(db_path).resolve()
    uri = "file:" + quote(str(path)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        clauses = ["policy_version=?"]
        values: list[Any] = [POLICY_VERSION]
        if dataset is not None:
            clauses.append("dataset=?")
            values.append(dataset)
        if status is not None:
            clauses.append("status=?")
            values.append(status)
        cursor = conn.execute(
            "SELECT * FROM coverage_segments WHERE " + " AND ".join(clauses)
            + " ORDER BY dataset, segment_start, segment_id",
            values,
        )
        return [dict(row) for row in cursor]
    finally:
        conn.close()


def coverage_summary(db_path: str | Path) -> dict[str, Any]:
    rows = read_dataset_coverage(db_path)
    counts = {status: 0 for status in sorted(COVERAGE_STATUSES)}
    for row in rows:
        counts[str(row["status"])] += 1
    governed = [row for row in rows if row["governance_tier"] == "governed"]
    return {
        "policy_version": POLICY_VERSION,
        "dataset_count": len(rows),
        "status_counts": counts,
        "governed_ready": bool(governed) and all(
            row["status"] == "COMPLETE" for row in governed
        ),
    }


def coverage_gaps(db_path: str | Path) -> list[dict[str, Any]]:
    return [
        row for row in read_dataset_coverage(db_path)
        if row["status"] != "COMPLETE"
    ]


def aggregate_status_from_segment_counts(
    status_counts: Mapping[str, int],
) -> str:
    """Fail-closed aggregate: empty→UNKNOWN; any FAILED→FAILED; else all COMPLETE."""
    counts = {
        str(status): int(n)
        for status, n in dict(status_counts or {}).items()
        if int(n) > 0
    }
    total = sum(counts.values())
    if total <= 0:
        return "UNKNOWN"
    if int(counts.get("FAILED", 0)) > 0:
        return "FAILED"
    if int(counts.get("COMPLETE", 0)) == total:
        return "COMPLETE"
    return "PARTIAL"


def honest_status_counts(
    status_counts: Mapping[str, int],
) -> dict[str, int]:
    """Drop zero counts; coerce values to int."""
    return {
        str(status): int(n)
        for status, n in sorted(dict(status_counts or {}).items())
        if int(n) > 0
    }


def _failing_checks_from_detail(detail: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    checks = [] if detail is None else list(detail.get("checks") or [])
    failing: list[dict[str, Any]] = []
    for check in checks:
        if not isinstance(check, Mapping):
            continue
        status = str(check.get("status", "")).lower()
        if status in {"fail", "failed", "error"}:
            failing.append(dict(check))
    return failing


def build_surgical_reagg_detail(
    existing_detail: Mapping[str, Any] | None,
    *,
    status_counts: Mapping[str, int],
    required_segments: int,
    audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge honest coverage_v2 status_counts into ``detail_json``."""
    detail = dict(existing_detail or {})
    cov = dict(detail.get("coverage_v2") or {})
    prev_counts = cov.get("status_counts")
    new_counts = honest_status_counts(status_counts)
    cov["status_counts"] = new_counts
    cov["required_segments"] = int(required_segments)
    if audit is not None:
        cov["surgical_reagg"] = dict(audit)
        if prev_counts is not None and "prev_status_counts" not in cov["surgical_reagg"]:
            cov["surgical_reagg"]["prev_status_counts"] = prev_counts
    detail["coverage_v2"] = cov
    detail["aggregate_source"] = "surgical_reagg_from_coverage_segments"
    return detail


def sync_dataset_coverage_from_segments(
    conn: sqlite3.Connection,
    *,
    datasets: Iterable[str] | None = None,
    policy_version: str = POLICY_VERSION,
    dry_run: bool = False,
    require_no_failing_checks: bool = True,
    refuse_empty_complete: bool = True,
    wave: str | None = None,
) -> list[dict[str, Any]]:
    """Re-aggregate ``dataset_coverage`` from ``coverage_segments``; never rewrite segs."""
    if datasets is None:
        selected = [
            str(row[0])
            for row in conn.execute(
                "SELECT dataset FROM dataset_coverage ORDER BY dataset"
            ).fetchall()
        ]
    else:
        selected = list(datasets)
    if not selected:
        return []

    evaluated_at = _now()
    results: list[dict[str, Any]] = []
    pre_platform = conn.execute(
        "SELECT COUNT(*) FROM coverage_segments WHERE status='COMPLETE'"
    ).fetchone()[0]

    for dataset in selected:
        seg_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS n
            FROM coverage_segments
            WHERE dataset=? AND policy_version=?
            GROUP BY status
            """,
            (dataset, policy_version),
        ).fetchall()
        raw_counts = {
            str(row[0]): int(row[1]) for row in seg_rows if int(row[1]) > 0
        }
        status_counts = honest_status_counts(raw_counts)
        total = sum(status_counts.values())
        complete = int(status_counts.get("COMPLETE", 0))
        derived = aggregate_status_from_segment_counts(status_counts)

        dc = conn.execute(
            "SELECT status, detail_json, observed_start, observed_end, row_count "
            "FROM dataset_coverage WHERE dataset=?",
            (dataset,),
        ).fetchone()
        if dc is None:
            results.append(
                {
                    "dataset": dataset,
                    "action": "skip_missing_dataset_coverage",
                    "status_counts": status_counts,
                    "derived_status": derived,
                    "total": total,
                    "complete": complete,
                }
            )
            continue

        old_status = str(dc[0] if not isinstance(dc, sqlite3.Row) else dc["status"])
        detail_raw = dc[1] if not isinstance(dc, sqlite3.Row) else dc["detail_json"]
        try:
            detail = json.loads(detail_raw or "{}")
            if not isinstance(detail, dict):
                detail = {}
        except (TypeError, ValueError, json.JSONDecodeError):
            detail = {}
        prev_counts = (detail.get("coverage_v2") or {}).get("status_counts")
        failing = _failing_checks_from_detail(detail)

        empty_complete = 0
        if refuse_empty_complete and complete > 0:
            empty_complete = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM coverage_segments
                    WHERE dataset=? AND policy_version=? AND status='COMPLETE'
                      AND (receipt_run_id IS NULL OR receipt_run_id=0)
                    """,
                    (dataset, policy_version),
                ).fetchone()[0]
            )

        base = {
            "dataset": dataset,
            "old_status": old_status,
            "status_counts": status_counts,
            "prev_status_counts": prev_counts,
            "derived_status": derived,
            "total": total,
            "complete": complete,
            "failing_checks": len(failing),
            "empty_complete": empty_complete,
            "dry_run": dry_run,
        }

        if total <= 0:
            results.append({**base, "action": "skip_empty_inventory"})
            continue

        # Only PARTIAL→COMPLETE is gated; never demote COMPLETE for historical C* noise.
        if derived == "COMPLETE":
            promoting = old_status != "COMPLETE"
            if promoting and require_no_failing_checks and failing:
                results.append(
                    {
                        **base,
                        "action": "skip_failing_checks",
                        "failing_check_ids": [
                            c.get("id") or c.get("check_id") or c.get("name")
                            for c in failing
                        ],
                    }
                )
                continue
            if promoting and refuse_empty_complete and empty_complete > 0:
                results.append(
                    {
                        **base,
                        "action": "skip_empty_complete_segments",
                        "reason": "COMPLETE segs with null/0 receipt_run_id",
                    }
                )
                continue
            new_status = "COMPLETE"
        elif derived == "FAILED":
            new_status = "FAILED"
        else:
            new_status = "PARTIAL"

        new_counts = honest_status_counts(status_counts)
        prev_norm = honest_status_counts(prev_counts or {})
        status_same = old_status == new_status
        counts_same = prev_norm == new_counts

        if status_same and counts_same:
            results.append(
                {
                    **base,
                    "action": "verify_only",
                    "status": new_status,
                    "eligible": new_status == "COMPLETE",
                }
            )
            continue

        if old_status == "COMPLETE" and new_status != "COMPLETE":
            action = "demoted"
        elif old_status != new_status and new_status == "COMPLETE":
            action = "promoted"
        else:
            action = "counts_refreshed"

        audit = {
            "at": evaluated_at,
            "reason": (
                "all required segments COMPLETE; stale aggregate re-synced"
                if new_status == "COMPLETE"
                else "honest re-aggregate from coverage_segments SoT"
            ),
            "prev_status": old_status,
            "new_status": new_status,
            "prev_status_counts": prev_counts,
            "wave": wave,
        }
        new_detail = build_surgical_reagg_detail(
            detail,
            status_counts=new_counts,
            required_segments=total,
            audit=audit,
        )
        detail_json = _canonical_json(new_detail)

        if not dry_run:
            conn.execute(
                """
                UPDATE dataset_coverage
                SET status=?, detail_json=?, evaluated_at=?
                WHERE dataset=?
                """,
                (new_status, detail_json, evaluated_at, dataset),
            )

        results.append(
            {
                **base,
                "action": action,
                "from": old_status,
                "to": new_status,
                "status": new_status,
                "new_status_counts": new_counts,
            }
        )

    if not dry_run and any(
        r.get("action") in {"promoted", "demoted", "counts_refreshed"}
        for r in results
    ):
        conn.commit()

    post_platform = conn.execute(
        "SELECT COUNT(*) FROM coverage_segments WHERE status='COMPLETE'"
    ).fetchone()[0]
    if post_platform != pre_platform:
        raise RuntimeError(
            "coverage_segments mutated during surgical re-aggregate: "
            f"COMPLETE {pre_platform} -> {post_platform}"
        )

    for row in results:
        row["platform_complete_segs"] = post_platform
    return results


def compute_raw_digest(raw: bytes) -> str:
    """SHA-256 over the verbatim persisted source bytes (``sha256:`` + hex)."""
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError(
            "raw must be bytes (the verbatim persisted source bytes), "
            f"got {type(raw).__name__}"
        )
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def build_collection_receipt(
    *,
    required: RequiredCoverageSegment,
    run_id: int,
    raw: bytes,
    observed_items: int,
    structured_row_count: int,
    raw_row_count: int | None = None,
    pagination_exhausted: bool = True,
    status: str = "SUCCESS",
    error: str | None = None,
    checked_at: str | None = None,
    extra_digests: Mapping[str, Any] | None = None,
) -> CollectionReceipt:
    """Build a receipt with a real SHA-256 over ``raw``; never fakes COMPLETE."""
    if status not in {"SUCCESS", "FAILED"}:
        raise ValueError("receipt status must be SUCCESS or FAILED")
    structured = int(structured_row_count)
    raw_rows = int(raw_row_count) if raw_row_count is not None else structured
    digests: dict[str, Any] = {
        "raw": compute_raw_digest(raw),
        # Default is NOT trusted. COMPLETE needs verified Ed25519, not issuer strings.
        "eligibility": "RECOVERED_RAW_ONLY",
    }
    if extra_digests:
        digests.update(dict(extra_digests))
        # Strip bare TRUSTED claims that lack signature material.
        if digests.get("eligibility") == "TRUSTED_COLLECTION":
            has_sig = (
                isinstance(digests.get("signature"), str)
                and str(digests.get("signature")).startswith("ed25519:")
                and isinstance(digests.get("signed_body_b64"), str)
                and isinstance(digests.get("issuer_key_id"), str)
            )
            if not has_sig:
                digests["eligibility"] = "RECOVERED_RAW_ONLY"
                digests.setdefault(
                    "trust_note",
                    "TRUSTED_COLLECTION requires Ed25519 signature fields",
                )

    return CollectionReceipt(
        source=required.source,
        dataset=required.dataset,
        segment_id=required.segment_id,
        segment_start=required.segment_start,
        segment_end=required.segment_end,
        expected_scope=required.expected_scope,
        expected_items=required.expected_items,
        observed_items=int(observed_items),
        raw_page_count=1 if raw else 0,
        raw_row_count=raw_rows,
        structured_row_count=structured,
        pagination_exhausted=bool(pagination_exhausted),
        digests=digests,
        run_id=int(run_id),
        status=status,
        error=error,
        checked_at=checked_at or _now(),
    )


# Offline-fixture sentinel; never write to a production database.
SYNTHETIC_RECEIPT_MARKER = {
    "synthetic": True,
    "origin": "offline-test-fixture",
}


def build_synthetic_complete_receipt(
    *,
    required: RequiredCoverageSegment,
    run_id: int,
    observed_items: int | None = None,
    checked_at: str | None = None,
) -> CollectionReceipt:
    """Offline-fixture COMPLETE-shaped receipt. Never write to production."""
    expected = required.expected_items
    if observed_items is None:
        observed_items = 0 if expected == 0 else 1
    digests: dict[str, Any] = {
        # Placeholder digest + TRUSTED so fixtures can exercise COMPLETE; production must not.
        "raw": "sha256:" + "0" * 64,
        "eligibility": "TRUSTED_COLLECTION",
        **SYNTHETIC_RECEIPT_MARKER,
    }
    items = int(observed_items)
    return CollectionReceipt(
        source=required.source,
        dataset=required.dataset,
        segment_id=required.segment_id,
        segment_start=required.segment_start,
        segment_end=required.segment_end,
        expected_scope=required.expected_scope,
        expected_items=expected,
        observed_items=items,
        raw_page_count=1,
        raw_row_count=items,
        structured_row_count=items,
        pagination_exhausted=True,
        digests=digests,
        run_id=int(run_id),
        status="SUCCESS",
        error=None,
        checked_at=checked_at or _now(),
    )


def is_synthetic_receipt(receipt: CollectionReceipt) -> bool:
    return bool(receipt.digests.get("synthetic"))


def receipt_eligibility(receipt: CollectionReceipt) -> str:
    """TRUSTED_COLLECTION only with a verified Ed25519 signature, never issuer strings."""
    if is_synthetic_receipt(receipt) or receipt.digests.get("origin") in {
        "offline-test-fixture",
        "recovered-raw-only",
        "parsed-staging-only",
        "failed-collection",
    }:
        return "RECOVERED_RAW_ONLY"
    # Lazy import avoids circular import at module load.
    from storage.receipt_crypto import verify_receipt_signature

    if (
        receipt.digests.get("eligibility") == "TRUSTED_COLLECTION"
        and verify_receipt_signature(receipt.digests)
    ):
        return "TRUSTED_COLLECTION"
    return "RECOVERED_RAW_ONLY"


def is_complete_eligible_receipt(receipt: CollectionReceipt) -> bool:
    """COMPLETE only with cryptographically verified signature."""
    if is_synthetic_receipt(receipt):
        return False
    from storage.receipt_crypto import verify_receipt_signature

    return (
        receipt.digests.get("eligibility") == "TRUSTED_COLLECTION"
        and verify_receipt_signature(receipt.digests)
    )

__all__ = [
    "CollectionReceipt",
    "RequiredCoverageSegment",
    "SYNTHETIC_RECEIPT_MARKER",
    "build_collection_receipt",
    "build_synthetic_complete_receipt",
    "compute_raw_digest",
    "coverage_gaps",
    "coverage_summary",
    "evaluate_segment",
    "evaluate_required_segments",
    "is_synthetic_receipt",
    "plan_required_segments",
    "read_collection_receipts",
    "read_coverage_segments",
    "read_dataset_coverage",
    "record_collection_receipt",
    "record_required_segments",
    "refresh_coverage_ledger",
]
