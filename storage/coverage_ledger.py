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
    """Create the required inventory independently of observed rows/receipts.

    Supported granularities:
    - calendar_month: one segment per calendar month
    - official_archive_year: one segment per year (JSDA annual archives)
    - official_archive_day: one segment per day within [start, end]
    - source_time_series_file: single segment covering full target window
    """
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
        scope = {
            "coverage_mode": policy.coverage_mode,
            "expected_frequency": policy.expected_frequency,
            "expected_item_unit": (
                "source_event"
                if policy.expected_frequency == "event_driven"
                else "source_query"
            ),
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
        cursor = start
        while cursor <= end:
            _append(cursor.isoformat(), cursor, cursor)
            cursor = date.fromordinal(cursor.toordinal() + 1)
    elif granularity == "source_time_series_file":
        _append(
            f"{start.isoformat()}_{end.isoformat()}",
            start,
            end,
        )
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
    # Trusted-path gate: only TrustedReceiptIssuer-minted receipts may COMPLETE.
    if not is_complete_eligible_receipt(receipt):
        return "PARTIAL", {
            "reason": "receipt not COMPLETE-eligible (TrustedReceiptIssuer required)",
            "eligibility": receipt_eligibility(receipt),
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


def _dataset_status(
    results: list[CheckResult],
) -> tuple[str, int, str | None, str | None]:
    """Apply validation/freshness gates without claiming collection coverage."""
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

    # A complete row requires a real per-dataset validation verdict. Facts-only
    # fallbacks remain UNKNOWN even when facts happen to exist.
    validation = checks.get("C2")
    if validation is None or validation.metrics.get("source") != "ingestion_validation":
        return "UNKNOWN", row_count, observed_start, observed_end
    if validation.metrics.get("validation_status") != "pass":
        return "FAILED", row_count, observed_start, observed_end

    # A successful validation (including a legitimate empty event window) is
    # only a prerequisite. Required segments and their receipts own COMPLETE.
    return "COMPLETE", row_count, observed_start, observed_end


def _coverage_source(dataset: str) -> str:
    return "jsda" if dataset.startswith("jsda_") else "jquants"


def _jsda_validation_status(
    conn: sqlite3.Connection, dataset: str
) -> tuple[str, int, str | None, str | None]:
    """PIT-shape prerequisite for locally governed JSDA facts.

    Collection completeness remains receipt-owned. An empty table is not a
    validation failure when every expected source segment is still missing;
    those independently planned segments correctly aggregate to PARTIAL.
    """
    # Every jsda_* governed dataset MUST map here or validation stays UNKNOWN.
    # Corporate bond transactions is NOT legacy jsda_bond_trades (different NK).
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
    """Upsert one run-scoped receipt; callers own the surrounding transaction."""
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


def _latest_receipt_for(
    receipts: Sequence[CollectionReceipt],
    required: RequiredCoverageSegment,
) -> CollectionReceipt | None:
    """Pick best receipt for a segment.

    Prefer COMPLETE-eligible TRUSTED_COLLECTION over RECOVERED_RAW_ONLY even if
    a recovery rebuild is newer (recovery must not clobber live trust).
    """
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

    def _rank(item: CollectionReceipt) -> tuple:
        trusted = 1 if is_complete_eligible_receipt(item) else 0
        return (trusted, item.checked_at, item.run_id)

    return max(exact, key=_rank)


def evaluate_required_segments(
    policy: CollectionCoverageContract,
    required_segments: Sequence[RequiredCoverageSegment],
    receipts: Sequence[CollectionReceipt],
) -> tuple[str, list[tuple[RequiredCoverageSegment, CollectionReceipt | None, str, dict[str, Any]]]]:
    """Evaluate the complete planned inventory, including missing receipts."""
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
    inventory_cursor = conn.execute(
        "SELECT source,dataset,segment_id,segment_start,segment_end,"
        "expected_scope,expected_items FROM coverage_segments "
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
        dataset_evidence = by_dataset[dataset]
        if source == "jsda":
            validation_status, count, observed_start, observed_end = (
                _jsda_validation_status(conn, dataset)
            )
        else:
            validation_status, count, observed_start, observed_end = _dataset_status(
                dataset_evidence
            )
        if policy.segment_granularity in {
            "official_archive_day", "source_time_series_file"
        }:
            required_segments = tuple(sorted(
                (
                    _required_from_inventory(row)
                    for row in inventory_by_dataset[dataset].values()
                    if str(row["source"]) == source
                    and str(row["segment_start"]) <= target_end
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


# ---------------------------------------------------------------------------
# Receipt construction helpers (Lane H)
# ---------------------------------------------------------------------------
#
# The JSDA governed archive runners (ingestion/jsda/archive.py,
# repo_archive.py, corrections.py) already write real collection receipts
# inline as each archive segment is fetched. The J-Quants catalog path
# (ingestion.pipeline.run_jquants) historically persisted raw bytes and
# structured rows but emitted **no** receipts — leaving every J-Quants
# governed dataset at PARTIAL/UNKNOWN with zero receipts.
#
# The helpers below give the J-Quants emit path (ingestion/jquants/receipts.py)
# and the operational CLI (scripts/write_collection_receipts.py) a single,
# honest way to build a receipt whose ``raw`` digest is computed over the
# *actual* persisted source bytes — never a placeholder — so any COMPLETE
# verdict is always backed by verifiable raw retention.
#
# ``build_synthetic_complete_receipt`` exists ONLY for offline fixture
# databases (tests). It carries an explicit ``synthetic`` sentinel in its
# digests so it can never be mistaken for a live collection receipt and must
# never be written to a production database.


def compute_raw_digest(raw: bytes) -> str:
    """SHA-256 over the verbatim source bytes, in the ledger's digest form.

    Returns ``"sha256:" + hex``. ``raw`` must be the exact bytes persisted
    under ``data/raw/...`` for the segment — the digest is what makes raw
    retention auditable, so it must be computed over real bytes, not a
    placeholder string.
    """
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
    """Build a REAL receipt whose raw digest is computed over ``raw`` bytes.

    The receipt inherits ``expected_scope``/``expected_items`` from the planned
    ``required`` segment, so it is identity-compatible with
    :func:`evaluate_segment` (which demands an exact scope match). The ``raw``
    digest is always a real SHA-256 over the supplied source bytes; callers
    MUST pass the bytes actually persisted for the segment.

    This helper records the truth. Whether the segment later evaluates to
    COMPLETE is decided by :func:`evaluate_segment` against the policy — it
    never fakes a verdict (a non-event segment without explicit expected items
    stays PARTIAL, correctly).
    """
    if status not in {"SUCCESS", "FAILED"}:
        raise ValueError("receipt status must be SUCCESS or FAILED")
    structured = int(structured_row_count)
    raw_rows = int(raw_row_count) if raw_row_count is not None else structured
    digests: dict[str, Any] = {
        "raw": compute_raw_digest(raw),
        # Default is NOT trusted. Only TrustedReceiptIssuer may set
        # eligibility=TRUSTED_COLLECTION with issuer_class/issuer_id.
        "eligibility": "RECOVERED_RAW_ONLY",
    }
    if extra_digests:
        digests.update(dict(extra_digests))
        # Strip bare TRUSTED claims without a trusted issuer capability.
        if digests.get("eligibility") == "TRUSTED_COLLECTION":
            if digests.get("issuer_class") != "TrustedReceiptIssuer" or not digests.get(
                "issuer_id"
            ):
                digests["eligibility"] = "RECOVERED_RAW_ONLY"
                digests.setdefault(
                    "trust_note",
                    "TRUSTED_COLLECTION requires TrustedReceiptIssuer",
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


# Sentinel embedded in every offline-fixture (synthetic) receipt's digests so
# it is distinguishable from any live collection receipt and auditable.
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
    """Build a COMPLETE-shaped receipt for an OFFLINE FIXTURE DATABASE ONLY.

    This is the documented offline synthetic receipt writer used by tests and
    by the CLI's hard-gated ``--synthetic`` fixture mode. It embeds the
    :data:`SYNTHETIC_RECEIPT_MARKER` (``synthetic: True`` /
    ``origin: offline-test-fixture``) in its digests so it can be distinguished
    from any live collection receipt and **must never be written to a
    production database**.

    ``observed_items`` defaults to a non-zero count (or ``0`` for event-driven
    segments whose ``expected_items`` is ``0``) so the receipt can satisfy
    :func:`evaluate_segment` in a fixture. It records no real raw bytes — the
    digest is a deterministic placeholder, intentionally marked synthetic.
    """
    expected = required.expected_items
    if observed_items is None:
        observed_items = 0 if expected == 0 else 1
    digests: dict[str, Any] = {
        # Deterministic placeholder digest; the synthetic sentinel is what
        # matters, not the hex value. eligibility is explicitly TRUSTED so
        # offline fixtures can exercise COMPLETE; production rebuild path
        # must never set this combination.
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
    """True if a receipt carries the offline-fixture synthetic sentinel."""
    return bool(receipt.digests.get("synthetic"))


def receipt_eligibility(receipt: CollectionReceipt) -> str:
    """Return COMPLETE-eligibility class for a receipt.

    A raw SHA-256 alone is never enough for TRUSTED_COLLECTION. Only an
    issuer-minted receipt (TrustedReceiptIssuer) is trusted.
    """
    if is_synthetic_receipt(receipt) or receipt.digests.get("origin") in {
        "offline-test-fixture",
        "recovered-raw-only",
    }:
        return "RECOVERED_RAW_ONLY"
    if (
        receipt.digests.get("issuer_class") == "TrustedReceiptIssuer"
        and isinstance(receipt.digests.get("issuer_id"), str)
        and str(receipt.digests.get("issuer_id")).strip()
        and receipt.digests.get("eligibility") == "TRUSTED_COLLECTION"
    ):
        return "TRUSTED_COLLECTION"
    elig = receipt.digests.get("eligibility")
    if isinstance(elig, str) and elig == "RECOVERED_RAW_ONLY":
        return "RECOVERED_RAW_ONLY"
    if isinstance(elig, str) and elig == "TRUSTED_COLLECTION":
        # Labeled TRUSTED without issuer → not COMPLETE-eligible.
        return "RECOVERED_RAW_ONLY"
    return "RECOVERED_RAW_ONLY"


def is_complete_eligible_receipt(receipt: CollectionReceipt) -> bool:
    return (
        receipt_eligibility(receipt) == "TRUSTED_COLLECTION"
        and not is_synthetic_receipt(receipt)
        and receipt.digests.get("issuer_class") == "TrustedReceiptIssuer"
        and bool(str(receipt.digests.get("issuer_id") or "").strip())
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
