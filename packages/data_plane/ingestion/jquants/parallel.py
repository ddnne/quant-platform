"""Parallel J-Quants fetch: by dataset and by date-grid windows.

Why parallel helps under a hard rate limit
-----------------------------------------
Premium allows ~500 req/min. A shared :class:`RateLimiter` keeps the account
under that budget. Parallelism does **not** increase the request rate; it
**overlaps network RTT** so wall-clock time approaches the rate-limit floor
instead of (rate wait + RTT) sequential.

What is parallelized
--------------------
1. **Across datasets** (API endpoints) — independent jobs.
2. **Across date windows** — long ``from``/``to`` ranges are split into
   ``chunk_days`` grids (default 30) so history backfill runs as many jobs.
3. **Across codes** (optional) — when ``codes`` is given and the dataset
   accepts ``code``, one job per (dataset, code, window).

What stays sequential
---------------------
* **Pagination** inside a single job (``pagination_key`` chain).
* Jobs that do not accept date ranges run as a single unit.

Usage::

    from ingestion.jquants.parallel import expand_jobs, run_parallel
    jobs = expand_jobs(
        ["equities_bars_daily", "markets_calendar"],
        from_date="2010-01-01",
        to_date="2025-12-31",
        chunk_days=90,
    )
    results = run_parallel(client, jobs, max_workers=8)
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable, List, Optional, Sequence

from . import catalog
from .client import JQuantsClient


@dataclass(frozen=True)
class FetchJob:
    """One independent fetch unit (dataset + params)."""

    dataset_id: str
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        parts = [self.dataset_id]
        for k in ("code", "from", "to", "date"):
            if k in self.params and self.params[k] not in (None, ""):
                parts.append(f"{k}={self.params[k]}")
        return " ".join(parts)


@dataclass
class JobResult:
    job: FetchJob
    rows: list[dict] = field(default_factory=list)
    fetch_result: Any = None
    error: str = ""
    elapsed_s: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.error


def _parse_ymd(s: str) -> date:
    s = str(s).strip()[:10]
    return datetime.strptime(s, "%Y-%m-%d").date()


def _fmt(d: date) -> str:
    return d.isoformat()


def iter_date_windows(
    from_date: str,
    to_date: str,
    chunk_days: int = 30,
) -> List[tuple[str, str]]:
    """Split ``[from_date, to_date]`` into inclusive windows of ``chunk_days``.

    Example: 2020-01-01 .. 2020-02-15 with chunk_days=30 →
    (2020-01-01, 2020-01-30), (2020-01-31, 2020-02-15).
    """
    if chunk_days < 1:
        raise ValueError("chunk_days must be >= 1")
    start = _parse_ymd(from_date)
    end = _parse_ymd(to_date)
    if end < start:
        raise ValueError(f"to_date {to_date!r} is before from_date {from_date!r}")

    windows: list[tuple[str, str]] = []
    cur = start
    step = timedelta(days=chunk_days)
    while cur <= end:
        w_end = min(cur + step - timedelta(days=1), end)
        windows.append((_fmt(cur), _fmt(w_end)))
        cur = w_end + timedelta(days=1)
    return windows


def iter_dates(from_date: str, to_date: str) -> List[str]:
    """Inclusive list of per-day ``YYYY-MM-DD`` strings over ``[from_date, to_date]``.

    Used for datasets that accept a single ``date`` param (not ``from``/``to``):
    a date range is expanded into one job per day so the requested span is
    actually fetched rather than silently dropped.
    """
    start = _parse_ymd(from_date)
    end = _parse_ymd(to_date)
    if end < start:
        raise ValueError(f"to_date {to_date!r} is before from_date {from_date!r}")
    days: list[str] = []
    cur = start
    while cur <= end:
        days.append(_fmt(cur))
        cur += timedelta(days=1)
    return days


def _supports_range(dataset_id: str) -> bool:
    params = catalog.get(dataset_id).get("params") or []
    return "from" in params and "to" in params


def _supports_date(dataset_id: str) -> bool:
    params = catalog.get(dataset_id).get("params") or []
    return "date" in params


def _supports_code(dataset_id: str) -> bool:
    params = catalog.get(dataset_id).get("params") or []
    return "code" in params


def expand_jobs(
    datasets: Sequence[str],
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    chunk_days: int = 30,
    codes: Optional[Sequence[str]] = None,
    extra_params: Optional[dict[str, Any]] = None,
) -> List[FetchJob]:
    """Build a flat job list from datasets × optional codes × date windows.

    * If both ``from_date`` and ``to_date`` are set **and** the dataset
      supports ``from``/``to``, the range is gridded into ``chunk_days`` windows.
    * If both ``from_date`` and ``to_date`` are set **and** the dataset accepts
      ``date`` (but not ``from``/``to``), the range is expanded into one job per
      day so the requested span is fetched rather than dropped.
    * If ``codes`` is set and the dataset supports ``code``, jobs fan out per code.
    * Otherwise a single job per dataset (plus any ``extra_params``).
    """
    base_extra = dict(extra_params or {})
    jobs: list[FetchJob] = []

    for did in datasets:
        catalog.get(did)  # raise KeyError early
        supports_range = _supports_range(did)
        supports_date = _supports_date(did)
        code_list: Sequence[Optional[str]]
        if codes and _supports_code(did):
            code_list = list(codes)
        else:
            code_list = [None]

        # Date fan-out shape for this dataset:
        #   * range datasets (from/to) → chunk_days windows of (from, to).
        #   * date-only datasets (date, no from/to) → one job per day.
        #   * single-sided date param → one job (no filter dropped).
        #   * no applicable date param → one job with no date filter.
        date_windows: list[tuple[Optional[str], Optional[str]]] = []
        date_days: list[str] = []
        if from_date and to_date and supports_date and supports_range:
            # J-Quants equities bars/daily rejects bare from/to without code
            # ("requires date or code"). Prefer per-day ``date=`` when both
            # styles are declared so backfill works without a code filter.
            date_days = iter_dates(from_date, to_date)
        elif from_date and to_date and supports_range:
            date_windows = iter_date_windows(from_date, to_date, chunk_days)
        elif from_date and to_date and supports_date:
            date_days = iter_dates(from_date, to_date)
        elif (from_date or to_date) and supports_range:
            # Open-ended / single-sided range: one job, no grid.
            date_windows = [(from_date, to_date)]
        elif (from_date or to_date) and supports_date:
            date_days = [from_date or to_date]
        else:
            date_windows = [(None, None)]

        for code in code_list:
            for w_from, w_to in date_windows:
                params = dict(base_extra)
                if code is not None:
                    params["code"] = code
                if w_from is not None:
                    params["from"] = w_from
                if w_to is not None:
                    params["to"] = w_to
                jobs.append(FetchJob(dataset_id=did, params=params))
            for d in date_days:
                params = dict(base_extra)
                if code is not None:
                    params["code"] = code
                params["date"] = d
                jobs.append(FetchJob(dataset_id=did, params=params))

    return jobs


def run_parallel(
    client: JQuantsClient,
    jobs: Sequence[FetchJob],
    *,
    max_workers: int = 8,
    on_job_done: Optional[Callable[[JobResult], None]] = None,
) -> List[JobResult]:
    """Execute ``jobs`` with a thread pool.

    The client must share one thread-safe :class:`RateLimiter` so total
    throughput stays under Premium limits. Each worker calls
    ``client.fetch_dataset`` for its job.
    """
    if max_workers < 1:
        raise ValueError("max_workers must be >= 1")
    if not jobs:
        return []

    def _one(job: FetchJob) -> JobResult:
        import time

        t0 = time.monotonic()
        try:
            fetch_result = client.fetch_dataset_evidenced(
                job.dataset_id, **job.params
            )
            res = JobResult(
                job=job,
                rows=list(fetch_result.rows),
                fetch_result=fetch_result,
                elapsed_s=time.monotonic() - t0,
            )
        except Exception as exc:  # noqa: BLE001 — surface per-job
            res = JobResult(
                job=job, error=f"{type(exc).__name__}: {exc}", elapsed_s=time.monotonic() - t0
            )
        if on_job_done is not None:
            on_job_done(res)
        return res

    # Preserve input order in the returned list.
    results: list[Optional[JobResult]] = [None] * len(jobs)
    workers = min(max_workers, len(jobs))

    if workers == 1:
        for i, job in enumerate(jobs):
            results[i] = _one(job)
        return [r for r in results if r is not None]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(_one, job): i for i, job in enumerate(jobs)}
        for fut in as_completed(future_map):
            i = future_map[fut]
            results[i] = fut.result()

    return [r for r in results if r is not None]


def run_datasets_parallel(
    client: JQuantsClient,
    datasets: Sequence[str],
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    chunk_days: int = 30,
    codes: Optional[Sequence[str]] = None,
    max_workers: int = 8,
    extra_params: Optional[dict[str, Any]] = None,
    on_job_done: Optional[Callable[[JobResult], None]] = None,
) -> List[JobResult]:
    """expand_jobs + run_parallel convenience."""
    jobs = expand_jobs(
        datasets,
        from_date=from_date,
        to_date=to_date,
        chunk_days=chunk_days,
        codes=codes,
        extra_params=extra_params,
    )
    return run_parallel(
        client, jobs, max_workers=max_workers, on_job_done=on_job_done
    )


def summarize_results(results: Iterable[JobResult]) -> dict[str, Any]:
    """Aggregate counts for logging / CLI."""
    results = list(results)
    ok = [r for r in results if r.ok]
    bad = [r for r in results if not r.ok]
    return {
        "jobs": len(results),
        "ok": len(ok),
        "errors": len(bad),
        "rows": sum(len(r.rows) for r in ok),
        "error_labels": [r.job.label for r in bad],
    }
