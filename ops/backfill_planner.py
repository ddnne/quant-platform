"""Contract-driven BackfillPlanner (Phase 6.2.2 P0).

Coverage Contract is the sole source of history targets. Dataset lists and
history starts are never hand-written in driver scripts.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from data_contracts.canonical import governed_datasets
from data_contracts.coverage import (
    POLICY_VERSION as COVERAGE_POLICY_VERSION,
    all_coverage_contracts,
    coverage_contract_for,
)
PLAN_VERSION = "backfill-plan/v1"
JobState = Literal[
    "pending",
    "running",
    "pass",
    "partial",
    "fail",
    "retry",
]

ReasonCode = Literal[
    "ok",
    "http_429",
    "timeout",
    "entitlement",
    "source_empty",
    "worker_error",
    "auth",
    "unknown",
]


def _digest(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _parse_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def _month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    if start > end:
        return []
    out: list[tuple[date, date]] = []
    y, m = start.year, start.month
    while True:
        first = date(y, m, 1)
        if m == 12:
            nxt = date(y + 1, 1, 1)
        else:
            nxt = date(y, m + 1, 1)
        last = nxt - timedelta(days=1)
        a = max(first, start)
        b = min(last, end)
        if a <= b:
            out.append((a, b))
        if (y, m) == (end.year, end.month):
            break
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _week_chunks(start: date, end: date, days: int = 7) -> list[tuple[date, date]]:
    if start > end:
        return []
    out: list[tuple[date, date]] = []
    cur = start
    step = max(1, days)
    while cur <= end:
        chunk_end = min(cur + timedelta(days=step - 1), end)
        out.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return out


@dataclass(frozen=True)
class EndpointCapability:
    dataset_id: str
    path: str
    date_mode: str  # today | range | none
    params: tuple[str, ...]
    source: str = "jquants"


def load_premium_endpoint_capabilities() -> dict[str, EndpointCapability]:
    path = (
        Path(__file__).resolve().parents[1]
        / "data_contracts"
        / "jquants_premium_core.json"
    )
    doc = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, EndpointCapability] = {}
    for row in doc.get("datasets") or []:
        ds = str(row["dataset_id"])
        out[ds] = EndpointCapability(
            dataset_id=ds,
            path=str(row["path"]),
            date_mode=str(row.get("date_mode") or "today"),
            params=tuple(str(p) for p in (row.get("params") or [])),
            source="jquants",
        )
    return out


@dataclass
class BackfillJob:
    dataset: str
    source: str
    segment_id: str
    requested_from: str
    requested_to: str
    endpoint_query_mode: str
    priority: int
    attempt: int = 0
    state: JobState = "pending"
    expected_evidence: str = "worker_summary_pass"
    contract_digest: str = ""
    reason_code: ReasonCode = "ok"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "source": self.source,
            "segment_id": self.segment_id,
            "requested_from": self.requested_from,
            "requested_to": self.requested_to,
            "endpoint_query_mode": self.endpoint_query_mode,
            "priority": self.priority,
            "attempt": self.attempt,
            "state": self.state,
            "expected_evidence": self.expected_evidence,
            "contract_digest": self.contract_digest,
            "reason_code": self.reason_code,
            "detail": self.detail,
        }

    def apply_worker_summary(self, summary: Mapping[str, Any], *, http_status: int) -> None:
        """Map worker HTTP + summary.status to job state. Never treat partial as pass."""
        if http_status == 429:
            self.state = "retry"
            self.reason_code = "http_429"
            self.detail = "rate limited"
            return
        if http_status == 401:
            self.state = "fail"
            self.reason_code = "auth"
            self.detail = f"HTTP {http_status}"
            return
        if http_status == 403:
            # Worker JSON 403 may be entitlement; edge HTML 403 is retryable.
            detail = str(summary.get("error") or summary.get("detail") or "")
            if "edge_forbidden" in detail or "html" in detail.lower():
                self.state = "retry"
                self.reason_code = "http_429"  # treat as transient edge/rate
                self.detail = detail[:300]
            else:
                self.state = "fail"
                self.reason_code = "entitlement"
                self.detail = f"HTTP 403 {detail[:200]}"
            return
        if http_status != 200:
            self.state = "fail"
            self.reason_code = "worker_error"
            self.detail = f"HTTP {http_status}"
            return
        status = str(summary.get("status") or "").lower()
        if status == "pass":
            self.state = "pass"
            self.reason_code = "ok"
            self.detail = json.dumps(
                {
                    "passed": summary.get("passed"),
                    "failed": summary.get("failed"),
                    "rowsInserted": summary.get("rowsInserted"),
                },
                sort_keys=True,
            )
        elif status == "partial":
            self.state = "partial"
            self.reason_code = "source_empty"
            self.detail = "worker reported partial"
        elif status == "fail":
            self.state = "fail"
            failures = summary.get("failures") or []
            self.reason_code = "worker_error"
            self.detail = json.dumps(failures[:3], default=str)[:500]
        else:
            self.state = "fail"
            self.reason_code = "unknown"
            self.detail = f"unrecognized status {status!r}"


@dataclass
class BackfillPlan:
    plan_version: str
    coverage_policy_version: str
    contract_digest: str
    cutoff: str
    created_at: str
    jobs: list[BackfillJob] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_version": self.plan_version,
            "coverage_policy_version": self.coverage_policy_version,
            "contract_digest": self.contract_digest,
            "cutoff": self.cutoff,
            "created_at": self.created_at,
            "job_count": len(self.jobs),
            "jobs": [j.to_dict() for j in self.jobs],
        }

    def pending_jobs(self) -> list[BackfillJob]:
        return [j for j in self.jobs if j.state in {"pending", "retry"}]


# Priority order from Phase 6.2.2 §11 (lower runs first).
_PRIORITY: dict[str, int] = {
    "markets_calendar": 10,
    "indices_bars_daily_topix": 20,
    "equities_bars_daily": 30,
    "equities_master": 40,
    "indices_bars_daily": 50,
    "equities_investor_types": 60,
    "equities_earnings_calendar": 61,
    "fins_summary": 70,
    "fins_details": 71,
    "fins_dividend": 72,
    "fins_earnings_date": 73,
    "markets_margin_interest": 80,
    "markets_margin_alert": 81,
    "markets_short_ratio": 82,
    "markets_short_sale_report": 83,
    "markets_breakdown": 84,
    "edinet_major_shareholders": 90,
    "edinet_cross_shareholdings": 91,
    "edinet_large_volume_shareholders": 92,
    "derivatives_bars_daily_futures": 100,
    "derivatives_bars_daily_options_225": 101,
    "derivatives_bars_daily_options": 102,
    "equities_bars_daily_am": 110,
}


def _contract_bundle_digest() -> str:
    rows = []
    for c in all_coverage_contracts():
        if c.governance_tier != "governed":
            continue
        rows.append(
            {
                "dataset_id": c.dataset_id,
                "history_target_start": c.history_target_start,
                "segment_granularity": c.segment_granularity,
                "coverage_mode": c.coverage_mode,
            }
        )
    return _digest({"policy": COVERAGE_POLICY_VERSION, "datasets": rows})


def _read_complete_segments(
    conn: sqlite3.Connection | None, dataset: str
) -> set[str]:
    if conn is None:
        return set()
    try:
        rows = conn.execute(
            """
            SELECT segment_id FROM coverage_segments
            WHERE dataset=? AND status='COMPLETE'
            """,
            (dataset,),
        ).fetchall()
        return {str(r[0]) for r in rows}
    except sqlite3.Error:
        return set()


class BackfillPlanner:
    """Plan backfill jobs from Coverage Contract + endpoint capabilities."""

    def __init__(
        self,
        *,
        cutoff: date | None = None,
        db_path: Path | str | None = None,
        sources: Sequence[str] = ("jquants",),
        chunk_days_for_today_mode: int = 7,
    ) -> None:
        self.cutoff = cutoff or (_today_utc() - timedelta(days=1))
        self.db_path = Path(db_path) if db_path else None
        self.sources = frozenset(sources)
        self.chunk_days = chunk_days_for_today_mode
        self.endpoints = load_premium_endpoint_capabilities()

    def plan(self) -> BackfillPlan:
        conn: sqlite3.Connection | None = None
        if self.db_path and self.db_path.is_file():
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            jobs: list[BackfillJob] = []
            contract_digest = _contract_bundle_digest()
            # Inventory ALL governed datasets from coverage (includes fins_details).
            for cov in all_coverage_contracts():
                if cov.governance_tier != "governed":
                    continue
                # JSDA planned separately (different runtime).
                if cov.dataset_id.startswith("jsda_"):
                    continue
                if "jquants" not in self.sources:
                    continue
                ep = self.endpoints.get(cov.dataset_id)
                if ep is None:
                    # Governed JQ without endpoint capability is a hard inventory gap.
                    jobs.append(
                        BackfillJob(
                            dataset=cov.dataset_id,
                            source="jquants",
                            segment_id="UNPLANNABLE",
                            requested_from=cov.history_target_start,
                            requested_to=self.cutoff.isoformat(),
                            endpoint_query_mode="missing",
                            priority=_PRIORITY.get(cov.dataset_id, 500),
                            state="fail",
                            expected_evidence="endpoint_capability",
                            contract_digest=contract_digest,
                            reason_code="entitlement",
                            detail="missing premium endpoint capability",
                        )
                    )
                    continue
                start = _parse_date(cov.history_target_start)
                end = self.cutoff
                complete = _read_complete_segments(conn, cov.dataset_id)
                mode = ep.date_mode
                if mode == "range":
                    # One range job per month segment (aligns with calendar_month granularity).
                    chunks = _month_chunks(start, end)
                elif mode == "none":
                    chunks = [(start, end)]
                else:
                    # today-mode: week chunks by default
                    if cov.segment_granularity == "calendar_month":
                        chunks = _month_chunks(start, end)
                    else:
                        chunks = _week_chunks(start, end, self.chunk_days)
                for a, b in chunks:
                    segment_id = f"{a.isoformat()}_{b.isoformat()}"
                    if segment_id in complete:
                        continue
                    # Also skip if monthly segment id form already complete
                    month_id = a.strftime("%Y-%m")
                    if month_id in complete:
                        continue
                    jobs.append(
                        BackfillJob(
                            dataset=cov.dataset_id,
                            source="jquants",
                            segment_id=segment_id,
                            requested_from=a.isoformat(),
                            requested_to=b.isoformat(),
                            endpoint_query_mode=mode,
                            priority=_PRIORITY.get(cov.dataset_id, 200),
                            contract_digest=contract_digest,
                        )
                    )
            jobs.sort(key=lambda j: (j.priority, j.dataset, j.requested_from))
            return BackfillPlan(
                plan_version=PLAN_VERSION,
                coverage_policy_version=COVERAGE_POLICY_VERSION,
                contract_digest=contract_digest,
                cutoff=self.cutoff.isoformat(),
                created_at=datetime.now(timezone.utc).isoformat(),
                jobs=jobs,
            )
        finally:
            if conn is not None:
                conn.close()


def inventory_governed_jq_datasets() -> list[str]:
    """Return sorted governed JQ dataset ids from coverage (no hand list)."""
    return sorted(
        c.dataset_id
        for c in all_coverage_contracts()
        if c.governance_tier == "governed" and not c.dataset_id.startswith("jsda_")
    )


__all__ = [
    "BackfillJob",
    "BackfillPlan",
    "BackfillPlanner",
    "EndpointCapability",
    "PLAN_VERSION",
    "inventory_governed_jq_datasets",
    "load_premium_endpoint_capabilities",
]
