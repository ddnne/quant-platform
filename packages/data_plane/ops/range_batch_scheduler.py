"""Range-batch scheduler for CF premium historical acceleration (Track A).

Queues **dataset × inclusive date-range** jobs from :class:`BackfillPlanner`,
applies dual RPM pools (general vs fins), and optionally dispatches
``POST /v1/run`` with bounded parallelism.

Hard rules
----------
* Default is **dry-run** (no network). ``execute=True`` required to POST.
* Tokens are never logged or written to plan/state payloads.
* Worker ``summary.status=pass`` is **not** Coverage COMPLETE.
* Local DB is a research mirror, not CF SoT.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from ingestion.common.rate_limit import RateLimiter
from ops.backfill_planner import (
    BackfillJob,
    BackfillPlan,
    BackfillPlanner,
    PLAN_VERSION,
)

# ---------------------------------------------------------------------------
# Rate / pool config (explicit; also documented in ADR)
# J-Quants Premium general ~500/min; fins endpoints are a separate budget.
# P0: drive near the Premium ceiling (495–500 RPM). Low-rate parking is banned.
# ---------------------------------------------------------------------------

RATE_POOL_GENERAL = "general"
RATE_POOL_FINS = "fins"

# Near ~500/min general Premium cap (client host dispatch; upstream paced by Worker).
DEFAULT_GENERAL_RPM: float = 495.0
# Separate fins budget — do not share the general token bucket.
DEFAULT_FINS_RPM: float = 495.0

# Parallel host POSTs overlap Worker RTT; RPM still bounds token acquisition.
DEFAULT_GENERAL_WORKERS: int = 12
DEFAULT_FINS_WORKERS: int = 6

# After HTTP 429 / retryable failure: short pause then resume near-limit RPM.
DEFAULT_SLEEP_ON_RETRY_S: float = 2.0

# Track A acceleration focus (priority order). History starts come from
# Coverage Contract via BackfillPlanner — not from this tuple.
TRACK_A_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "indices_bars_daily_topix",
    "markets_breakdown",
    "fins_summary",
    "equities_master",
    "markets_margin_interest",
)

# Preferred deep-history windows for Track A (inclusive). Planner still owns
# segment inventory; these only filter the queue for acceleration runs.
TRACK_A_FOCUS_RANGES: dict[str, tuple[str, str]] = {
    # Proven observed floors (w0815ae/W38) through pre-FRESH history.
    "equities_bars_daily": ("2008-05-01", "2023-12-31"),
    # Full TOPIX history is contract-driven; focus filter is wide open.
    "indices_bars_daily_topix": ("2008-05-01", "2099-12-31"),
    "markets_breakdown": ("2015-03-26", "2099-12-31"),
    "fins_summary": ("2008-07-01", "2099-12-31"),
    "equities_master": ("2000-07-13", "2099-12-31"),  # not raised (misdate band)
    # Latest-only preference is applied via max_jobs / latest_only, not range.
    "markets_margin_interest": ("2013-01-04", "2099-12-31"),
}

SCHEDULER_CONFIG: dict[str, Any] = {
    "version": "range-batch-scheduler/v1",
    "plan_version": PLAN_VERSION,
    "rate_pools": {
        RATE_POOL_GENERAL: {
            "rpm": DEFAULT_GENERAL_RPM,
            "workers": DEFAULT_GENERAL_WORKERS,
            "note": "J-Quants Premium general ~500/min; driver default 495 near ceiling",
        },
        RATE_POOL_FINS: {
            "rpm": DEFAULT_FINS_RPM,
            "workers": DEFAULT_FINS_WORKERS,
            "note": "fins_* endpoints: separate rate budget; isolated token bucket",
        },
    },
    "sleep_on_retry_s": DEFAULT_SLEEP_ON_RETRY_S,
    "track_a_datasets": list(TRACK_A_DATASETS),
    "date_range_batch_standard": True,
    "evidence_closure": "raw_plus_structured_only",
    "default_mode": "dry-run",
}


def rate_pool_for_dataset(dataset_id: str) -> str:
    """Map dataset id → rate pool. Only ``fins_*`` uses the fins budget."""
    if dataset_id.startswith("fins_"):
        return RATE_POOL_FINS
    return RATE_POOL_GENERAL


def rpm_to_min_interval(rpm: float) -> float:
    """Convert requests-per-minute to min interval seconds (0 if unlimited)."""
    if rpm is None or rpm <= 0:
        return 0.0
    return 60.0 / float(rpm)


@dataclass
class SchedulerConfig:
    """Runtime knobs for :class:`RangeBatchScheduler`."""

    general_rpm: float = DEFAULT_GENERAL_RPM
    fins_rpm: float = DEFAULT_FINS_RPM
    general_workers: int = DEFAULT_GENERAL_WORKERS
    fins_workers: int = DEFAULT_FINS_WORKERS
    max_jobs: int = 0  # 0 = no limit
    execute: bool = False  # dry-run unless True
    # Short 429 cooldown; do not park far below the Premium ceiling.
    sleep_on_retry_s: float = DEFAULT_SLEEP_ON_RETRY_S
    request_timeout_s: int = 600

    def to_dict(self) -> dict[str, Any]:
        return {
            "general_rpm": self.general_rpm,
            "fins_rpm": self.fins_rpm,
            "general_workers": self.general_workers,
            "fins_workers": self.fins_workers,
            "max_jobs": self.max_jobs,
            "execute": self.execute,
            "sleep_on_retry_s": self.sleep_on_retry_s,
            "request_timeout_s": self.request_timeout_s,
            "mode": "execute" if self.execute else "dry-run",
        }


@dataclass
class ScheduledJob:
    """One queued range job with pool assignment."""

    job: BackfillJob
    pool: str
    queue_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = self.job.to_dict()
        d["rate_pool"] = self.pool
        d["queue_index"] = self.queue_index
        return d


@dataclass
class SchedulerResult:
    """Outcome of a dry-run or execute pass."""

    mode: str
    config: dict[str, Any]
    plan_contract_digest: str
    plan_cutoff: str
    queued: list[dict[str, Any]] = field(default_factory=list)
    executed: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0
    counts_by_pool: dict[str, int] = field(default_factory=dict)
    counts_by_dataset: dict[str, int] = field(default_factory=dict)
    counts_by_state: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "config": self.config,
            "plan_contract_digest": self.plan_contract_digest,
            "plan_cutoff": self.plan_cutoff,
            "queued_count": len(self.queued),
            "executed_count": len(self.executed),
            "skipped": self.skipped,
            "counts_by_pool": self.counts_by_pool,
            "counts_by_dataset": self.counts_by_dataset,
            "counts_by_state": self.counts_by_state,
            "notes": self.notes,
            "queued": self.queued,
            "executed": self.executed,
        }


def filter_plan_jobs(
    plan: BackfillPlan,
    *,
    datasets: Sequence[str] | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    track_a: bool = False,
    latest_only: bool = False,
    apply_track_a_focus_ranges: bool = True,
) -> list[BackfillJob]:
    """Filter pending jobs by dataset / range / Track A focus.

    Does not invent COMPLETE skips — planner already omitted COMPLETE segs
    when a local DB was provided.
    """
    allow: set[str] | None = None
    if track_a:
        allow = set(TRACK_A_DATASETS)
    if datasets:
        extra = {d.strip() for d in datasets if d and d.strip()}
        allow = extra if allow is None else (allow & extra)

    from_d = date.fromisoformat(from_date[:10]) if from_date else None
    to_d = date.fromisoformat(to_date[:10]) if to_date else None

    selected: list[BackfillJob] = []
    for job in plan.pending_jobs():
        if allow is not None and job.dataset not in allow:
            continue
        j_from = date.fromisoformat(job.requested_from[:10])
        j_to = date.fromisoformat(job.requested_to[:10])
        if from_d is not None and j_to < from_d:
            continue
        if to_d is not None and j_from > to_d:
            continue
        if track_a and apply_track_a_focus_ranges and job.dataset in TRACK_A_FOCUS_RANGES:
            fa, ta = TRACK_A_FOCUS_RANGES[job.dataset]
            fa_d, ta_d = date.fromisoformat(fa), date.fromisoformat(ta)
            if j_to < fa_d or j_from > ta_d:
                continue
        selected.append(job)

    if latest_only and selected:
        # Keep only the chronologically latest job per dataset.
        by_ds: dict[str, BackfillJob] = {}
        for job in selected:
            prev = by_ds.get(job.dataset)
            if prev is None or job.requested_from > prev.requested_from:
                by_ds[job.dataset] = job
        selected = sorted(
            by_ds.values(),
            key=lambda j: (j.priority, j.dataset, j.requested_from),
        )
    return selected


def build_queue(
    jobs: Sequence[BackfillJob],
    *,
    max_jobs: int = 0,
) -> list[ScheduledJob]:
    """Assign rate pools and optional cap; preserve planner priority order."""
    out: list[ScheduledJob] = []
    for i, job in enumerate(jobs):
        if max_jobs and len(out) >= max_jobs:
            break
        out.append(
            ScheduledJob(
                job=job,
                pool=rate_pool_for_dataset(job.dataset),
                queue_index=i,
            )
        )
    return out


RunJobFn = Callable[..., tuple[int, dict]]


class RangeBatchScheduler:
    """Queue dataset×range jobs; dry-run by default; dual-pool parallel execute."""

    def __init__(
        self,
        plan: BackfillPlan,
        *,
        config: SchedulerConfig | None = None,
        run_job: RunJobFn | None = None,
        premium_url: str = "",
        token: str = "",
    ) -> None:
        self.plan = plan
        self.config = config or SchedulerConfig()
        self._run_job = run_job
        self.premium_url = premium_url
        # token kept only for execute path; never included in to_dict / logs
        self._token = token

    def queue(
        self,
        *,
        datasets: Sequence[str] | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        track_a: bool = False,
        latest_only: bool = False,
    ) -> list[ScheduledJob]:
        jobs = filter_plan_jobs(
            self.plan,
            datasets=datasets,
            from_date=from_date,
            to_date=to_date,
            track_a=track_a,
            latest_only=latest_only,
        )
        return build_queue(jobs, max_jobs=self.config.max_jobs)

    def run(
        self,
        *,
        datasets: Sequence[str] | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        track_a: bool = False,
        latest_only: bool = False,
        state_path: Path | None = None,
    ) -> SchedulerResult:
        queued = self.queue(
            datasets=datasets,
            from_date=from_date,
            to_date=to_date,
            track_a=track_a,
            latest_only=latest_only,
        )
        mode = "execute" if self.config.execute else "dry-run"
        result = SchedulerResult(
            mode=mode,
            config=self.config.to_dict(),
            plan_contract_digest=self.plan.contract_digest,
            plan_cutoff=self.plan.cutoff,
            notes=[
                "Worker pass != Coverage COMPLETE; seal only with raw+structured.",
                "Token is never written into this result.",
                f"scheduler_config={SCHEDULER_CONFIG['version']}",
            ],
        )
        if track_a:
            result.notes.append(f"track_a_datasets={list(TRACK_A_DATASETS)}")
        if latest_only:
            result.notes.append("latest_only=1 job per dataset (e.g. margin refresh)")

        by_pool: dict[str, int] = {RATE_POOL_GENERAL: 0, RATE_POOL_FINS: 0}
        by_ds: dict[str, int] = {}
        for sq in queued:
            by_pool[sq.pool] = by_pool.get(sq.pool, 0) + 1
            by_ds[sq.job.dataset] = by_ds.get(sq.job.dataset, 0) + 1
            result.queued.append(sq.to_dict())
        result.counts_by_pool = by_pool
        result.counts_by_dataset = by_ds

        if not self.config.execute:
            result.counts_by_state = {"dry_run_pending": len(queued)}
            result.notes.append("dry-run: no HTTP calls issued")
            return result

        if self._run_job is None:
            raise RuntimeError("execute=True requires run_job callback")
        if not self._token:
            raise RuntimeError("execute=True requires non-empty token (not logged)")

        # Dual rate limiters — fins isolated from general.
        limiters = {
            RATE_POOL_GENERAL: RateLimiter(
                rpm_to_min_interval(self.config.general_rpm)
            ),
            RATE_POOL_FINS: RateLimiter(rpm_to_min_interval(self.config.fins_rpm)),
        }
        # Split queues so worker caps are pool-local.
        general_q = [s for s in queued if s.pool == RATE_POOL_GENERAL]
        fins_q = [s for s in queued if s.pool == RATE_POOL_FINS]
        state_lock = threading.Lock()
        executed_rows: list[dict[str, Any]] = []

        def _dispatch(sq: ScheduledJob) -> dict[str, Any]:
            job = sq.job
            job.attempt += 1
            job.state = "running"
            started_at = datetime.now(timezone.utc).isoformat()
            limiters[sq.pool].acquire()
            # Never pass token into log lines; callback owns the header.
            code, summary = self._run_job(
                premium_url=self.premium_url,
                token=self._token,
                dataset=job.dataset,
                from_d=job.requested_from,
                to_d=job.requested_to,
                timeout=self.config.request_timeout_s,
            )
            job.apply_worker_summary(summary, http_status=code)
            if job.state == "retry":
                # Short cooldown only; rate limiters stay at configured near-ceiling RPM.
                time.sleep(self.config.sleep_on_retry_s)
            finished_at = datetime.now(timezone.utc).isoformat()
            row = sq.to_dict()
            row["started_at"] = started_at
            row["finished_at"] = finished_at
            row["http_status"] = code
            # Safety: strip any accidental token-like keys
            for k in list(row.keys()):
                if "token" in k.lower() or "secret" in k.lower() or "authorization" in k.lower():
                    row.pop(k, None)
            with state_lock:
                executed_rows.append(row)
                if state_path is not None:
                    state_path.parent.mkdir(parents=True, exist_ok=True)
                    with state_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            return row

        # Run pools concurrently; each pool has its own worker cap.
        futures = []
        with ThreadPoolExecutor(
            max_workers=max(1, self.config.general_workers)
            + max(1, self.config.fins_workers)
        ) as pool:
            # Submit general and fins with separate conceptual caps by
            # chunking submit order; ThreadPoolExecutor max is sum of caps.
            # Enforce per-pool concurrency with semaphores.
            gen_sem = threading.Semaphore(max(1, self.config.general_workers))
            fins_sem = threading.Semaphore(max(1, self.config.fins_workers))

            def _guarded(sq: ScheduledJob) -> dict[str, Any]:
                sem = gen_sem if sq.pool == RATE_POOL_GENERAL else fins_sem
                with sem:
                    return _dispatch(sq)

            for sq in general_q + fins_q:
                futures.append(pool.submit(_guarded, sq))
            for fut in as_completed(futures):
                fut.result()  # propagate exceptions

        result.executed = executed_rows
        states: dict[str, int] = {}
        for row in executed_rows:
            st = str(row.get("state") or "unknown")
            states[st] = states.get(st, 0) + 1
        result.counts_by_state = states
        return result


def plan_and_queue(
    *,
    db_path: Path | str | None = None,
    cutoff: date | None = None,
    datasets: Sequence[str] | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    track_a: bool = False,
    latest_only: bool = False,
    max_jobs: int = 0,
    chunk_days_for_today_mode: int = 7,
) -> tuple[BackfillPlan, list[ScheduledJob]]:
    """Convenience: build contract plan + filtered range queue (dry planning)."""
    planner = BackfillPlanner(
        cutoff=cutoff,
        db_path=db_path,
        chunk_days_for_today_mode=chunk_days_for_today_mode,
    )
    plan = planner.plan()
    jobs = filter_plan_jobs(
        plan,
        datasets=datasets,
        from_date=from_date,
        to_date=to_date,
        track_a=track_a,
        latest_only=latest_only,
    )
    return plan, build_queue(jobs, max_jobs=max_jobs)


def estimate_dispatch_envelope(
    queued: Sequence[ScheduledJob],
    *,
    general_rpm: float = DEFAULT_GENERAL_RPM,
    fins_rpm: float = DEFAULT_FINS_RPM,
) -> dict[str, Any]:
    """Rough host-side dispatch floor (not upstream page throughput)."""
    n_gen = sum(1 for s in queued if s.pool == RATE_POOL_GENERAL)
    n_fins = sum(1 for s in queued if s.pool == RATE_POOL_FINS)
    # Sequential floor if single-threaded at RPM:
    gen_min = (n_gen / general_rpm) if general_rpm > 0 else 0.0
    fins_min = (n_fins / fins_rpm) if fins_rpm > 0 else 0.0
    # Parallel pools run concurrently → wall floor ≈ max of pool floors.
    return {
        "queued_general": n_gen,
        "queued_fins": n_fins,
        "general_rpm": general_rpm,
        "fins_rpm": fins_rpm,
        "host_dispatch_floor_minutes_if_parallel_pools": round(
            max(gen_min, fins_min), 3
        ),
        "host_dispatch_floor_minutes_if_serial_all": round(gen_min + fins_min, 3),
        "note": (
            "Host dispatch only. Worker pagination dominates wall-clock; "
            "this is not a COMPLETE/SLA estimate."
        ),
    }


def measure_dispatch_rpm(
    executed: Sequence[Mapping[str, Any]],
    *,
    timestamp_key: str = "finished_at",
) -> dict[str, Any]:
    """Measure host POST throughput from executed job rows (or state jsonl).

    Returns observed requests/min over the wall window spanned by timestamps.
    Does **not** equal JQ upstream page rate (Worker pagination is separate).
    """
    times: list[float] = []
    for row in executed:
        raw = row.get(timestamp_key) or row.get("started_at")
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        times.append(ts.timestamp())
    if len(times) < 2:
        return {
            "n_events": len(times),
            "requests_per_min": None,
            "window_seconds": None,
            "note": "need >=2 timestamped events to measure host RPM",
        }
    times.sort()
    window_s = max(times[-1] - times[0], 1e-9)
    rpm = (len(times) - 1) * 60.0 / window_s
    by_pool: dict[str, int] = {}
    by_state: dict[str, int] = {}
    n_429 = 0
    for row in executed:
        pool = str(row.get("rate_pool") or "unknown")
        by_pool[pool] = by_pool.get(pool, 0) + 1
        st = str(row.get("state") or "unknown")
        by_state[st] = by_state.get(st, 0) + 1
        if int(row.get("http_status") or 0) == 429 or row.get("reason_code") == "http_429":
            n_429 += 1
    return {
        "n_events": len(times),
        "requests_per_min": round(rpm, 2),
        "window_seconds": round(window_s, 3),
        "first_at": datetime.fromtimestamp(times[0], tz=timezone.utc).isoformat(),
        "last_at": datetime.fromtimestamp(times[-1], tz=timezone.utc).isoformat(),
        "by_pool": by_pool,
        "by_state": by_state,
        "http_429_count": n_429,
        "note": (
            "Host POST /v1/run rate only. Upstream JQ pages are paced by Worker "
            "RATE_LIMIT_INTERVAL_MS (~120 ms → 500/min)."
        ),
    }


def theoretical_upstream_rpm(rate_limit_interval_ms: float) -> float | None:
    """Convert Worker min-interval (ms) to theoretical max upstream requests/min."""
    if rate_limit_interval_ms is None or rate_limit_interval_ms <= 0:
        return None
    return round(60_000.0 / float(rate_limit_interval_ms), 2)


__all__ = [
    "DEFAULT_FINS_RPM",
    "DEFAULT_FINS_WORKERS",
    "DEFAULT_GENERAL_RPM",
    "DEFAULT_GENERAL_WORKERS",
    "DEFAULT_SLEEP_ON_RETRY_S",
    "RATE_POOL_FINS",
    "RATE_POOL_GENERAL",
    "SCHEDULER_CONFIG",
    "TRACK_A_DATASETS",
    "TRACK_A_FOCUS_RANGES",
    "RangeBatchScheduler",
    "ScheduledJob",
    "SchedulerConfig",
    "SchedulerResult",
    "build_queue",
    "estimate_dispatch_envelope",
    "filter_plan_jobs",
    "measure_dispatch_rpm",
    "plan_and_queue",
    "rate_pool_for_dataset",
    "rpm_to_min_interval",
    "theoretical_upstream_rpm",
]
