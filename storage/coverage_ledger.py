"""Persistent collection-coverage ledger built from Phase 3.5 checks."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable
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
    policy: CollectionCoverageContract,
    results: list[CheckResult],
) -> tuple[str, int, str | None, str | None]:
    """Collapse C1-C5/C8 without assuming event rows that do not exist."""
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

    # No daily/event count is invented for irregular series. An empty event
    # window may be legitimate, but cannot prove historical reconciliation.
    if not observed_start:
        return "PARTIAL", row_count, observed_start, observed_end
    if str(observed_start)[:10] > policy.history_target_start:
        return "PARTIAL", row_count, observed_start, observed_end
    return "COMPLETE", row_count, observed_start, observed_end


def refresh_coverage_ledger(
    conn: sqlite3.Connection,
    db_path: str | Path,
    *,
    datasets: Iterable[str] | None = None,
    today: str | None = None,
    freshness_days: int = 7,
) -> list[dict[str, Any]]:
    """Run C1-C5/C8 and atomically replace selected ledger rows."""
    selected = tuple(datasets) if datasets is not None else tuple(
        policy.dataset_id for policy in all_coverage_contracts()
    )
    if not selected:
        raise ValueError("datasets must not be empty")
    policies = {dataset: coverage_contract_for(dataset) for dataset in selected}
    evidence = run_coverage(
        db_path,
        tier="daily",
        datasets=selected,
        today=today,
        freshness_days=freshness_days,
        workers=1,
        strict_live_gates=False,
    )
    by_dataset: dict[str, list[CheckResult]] = {dataset: [] for dataset in selected}
    global_failures = [
        result for result in evidence
        if result.dataset is None and result.status == "fail"
    ]
    for result in evidence:
        if result.dataset in by_dataset:
            by_dataset[str(result.dataset)].append(result)

    evaluated_at = _now()
    rows: list[dict[str, Any]] = []
    for dataset in selected:
        policy = policies[dataset]
        dataset_evidence = by_dataset[dataset]
        status, count, observed_start, observed_end = _dataset_status(
            policy, dataset_evidence
        )
        if global_failures:
            status = "FAILED"
        if status not in COVERAGE_STATUSES:  # pragma: no cover
            raise AssertionError(f"unexpected coverage status: {status}")
        detail = {
            "checks": [result.as_log_dict() for result in dataset_evidence],
            "global_failures": [result.as_log_dict() for result in global_failures],
        }
        rows.append({
            "dataset": dataset,
            **asdict(policy),
            "status": status,
            "policy_version": POLICY_VERSION,
            "observed_start": observed_start,
            "observed_end": observed_end,
            "row_count": count,
            "source_run_id": _latest_run_id(conn, dataset),
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
    try:
        conn.execute("BEGIN IMMEDIATE")
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


__all__ = [
    "coverage_gaps",
    "coverage_summary",
    "read_dataset_coverage",
    "refresh_coverage_ledger",
]
