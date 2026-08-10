"""Fetcher vs Registrar orchestration (Pattern B).

* **Fetcher** runs on **local**: it issues HTTP, saves verbatim raw bytes to
  ``data/raw/{source}/...`` and normalizes them.
* **Registrar** validates ``available_at`` and persists structured rows. It
  has no network dependency, so it is the only part that could later run on
  Cloudflare reading from storage (Phase 2+).

Each ``run_*`` function returns a list of :class:`RunReport` so the CLI can
print a per-source, per-kind summary and choose an exit code via
:func:`decide_exit`.

Report semantics (Phase 1 fix):

* ``skipped`` — *clean* skip (missing API key, unsupported runtime, optional
  endpoint absent, or an auto-sampled optional sub-fetch that failed). Not a
  failure.
* ``error`` — a fetch/parse/register step raised, **or** a silent schema miss:
  ``fetched > 0`` but ``registered == 0`` with no skip reason and not
  ``expected_empty`` (normalize produced nothing — schema drift / empty parse).
  Both are failures.
* ``ok`` — registered at least one row, OR an explicitly expected-empty case
  (e.g. the raw-only ``fins/summary`` endpoint). A zero-row result without a
  skip reason is **not** ``ok`` (guards against a silent schema miss looking
  like success).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .common.available_at import validate_available_at
from .common.paths import raw_path
from .common.timeutil import now_iso


@dataclass
class RunReport:
    source: str
    kind: str
    fetched: int = 0
    registered: int = 0
    skipped: str = ""        # clean skip reason (missing key / unsupported runtime)
    error: str = ""          # failure reason (an exception was raised)
    expected_empty: bool = False  # registered==0 is intentional (e.g. raw-only)
    raw_path: str = ""

    @property
    def schema_miss(self) -> bool:
        """``fetched > 0`` but ``registered == 0`` with no skip/error and not
        ``expected_empty``: normalize produced nothing (schema drift or empty
        parse). Treated as an error so a silent miss can never read as success.
        """
        return (
            not self.skipped
            and not self.error
            and not self.expected_empty
            and self.fetched > 0
            and self.registered == 0
        )

    @property
    def effective_error(self) -> str:
        """Error text for display/exit: an explicit error, or a schema miss."""
        if self.error:
            return self.error
        if self.schema_miss:
            return (
                f"fetched={self.fetched} but registered=0 "
                "(schema miss / empty normalize)"
            )
        return ""

    @property
    def ok(self) -> bool:
        if self.skipped or self.error or self.schema_miss:
            return False
        return self.registered > 0 or self.expected_empty

    def summary(self) -> str:
        err = self.effective_error
        if err:
            return f"[{self.source}/{self.kind}] ERROR ({err})"
        if self.skipped:
            return f"[{self.source}/{self.kind}] SKIPPED ({self.skipped})"
        tag = "OK"
        rp = f" raw={self.raw_path}" if self.raw_path else ""
        return (
            f"[{self.source}/{self.kind}] {tag} "
            f"fetched={self.fetched} registered={self.registered}{rp}"
        )


def decide_exit(reports: List[RunReport]) -> int:
    """CLI exit code from a flat list of reports.

    ``1`` if any report errored (explicit error or schema miss); else ``0`` if
    any succeeded; else ``2`` (every source cleanly skipped, e.g. all API keys
    absent / cloudflare).
    """
    if any(r.effective_error for r in reports):
        return 1
    if any(r.ok for r in reports):
        return 0
    return 2


class Registrar:
    """Persist structured rows. ``available_at`` is mandatory."""

    def __init__(self, store) -> None:
        self._store = store

    def register(self, table: str, rows) -> int:
        # Canonicalize available_at on every row before it reaches the store.
        # validate_available_at is the PIT hard gate (raises on missing/empty)
        # AND returns the canonical +09:00 ISO form; persisting that form is
        # what makes the store's lexicographic MIN(available_at) chronologically
        # correct across rows that may have arrived in different offsets.
        canonical = []
        for r in rows:
            r = dict(r)
            r["available_at"] = validate_available_at(r.get("available_at"))
            canonical.append(r)
        return self._store.upsert(table, canonical)


def _compact_stamp(iso_ts: str) -> str:
    """``2025-04-02T09:00:00+09:00`` -> ``20250402T090000`` (filename-safe)."""
    s = (iso_ts or "").replace(":", "").replace("-", "")
    # e.g. "20250402T090000+0900"
    return s[:15] if len(s) >= 15 else s


def _stamped(name: str, stamp: str) -> str:
    """Append a compact timestamp before the extension so same-day re-fetches
    of the same source do not clobber each other under the day partition."""
    stamp = _compact_stamp(stamp)
    if not stamp:
        return name
    stem, ext = os.path.splitext(name)
    return f"{stem}_{stamp}{ext}"


def save_raw(
    data_base: Path, source: str, filename: str, data: bytes, when
) -> Path:
    """Persist verbatim source bytes under the raw partition for ``when``."""
    p = raw_path(data_base, source, when, filename)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _cannot_fetch(source: str, runtime: str) -> List[RunReport]:
    return [
        RunReport(
            source,
            "*",
            skipped=(
                f"runtime={runtime} cannot fetch in Phase 1 "
                "(Pattern B: fetch on local only)"
            ),
        )
    ]


def _choose_jsda_parser(filename: str, data: bytes):
    """Pick the JSDA parser for a downloaded file.

    Returns ``(parser_callable, kind)``. Raises ``ValueError`` for legacy
    ``.xls`` (unsupported) instead of silently parsing zero rows.
    """
    from .jsda.parse import parse_csv, parse_xlsx

    low = (filename or "").lower()
    is_xlsx_blob = bool(data) and bytes(data[:2]) == b"PK"  # ZIP / XLSX magic

    if low.endswith(".xls") and not is_xlsx_blob:
        raise ValueError(
            "legacy .xls is not supported; provide .xlsx or .csv "
            "(convert the source file)"
        )
    if low.endswith(".xlsx") or is_xlsx_blob:
        return parse_xlsx, "xlsx"
    return parse_csv, "csv"


# ---------------------------------------------------------------------------
# J-Quants
# ---------------------------------------------------------------------------

def run_jquants(
    *,
    http,
    store,
    api_key: str = "",
    data_base: Path,
    today,
    runtime: str = "local",
    code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    datasets: Optional[List[str]] = None,
    mode: str = "incremental",
    max_workers: int = 8,
    chunk_days: int = 30,
) -> List[RunReport]:
    """Run a J-Quants pass.

    Two modes of operation:

    * **catalog-driven** (``datasets`` is a non-empty list): for each dataset
      id fetch via :meth:`JQuantsClient.fetch_dataset`, save raw, normalize
      with :func:`normalize_generic`, and upsert into the generic
      ``jquants_records`` table. This is the full Premium + add-on coverage
      path. ``mode`` (``incremental``/``backfill``) controls the default date
      window when ``date_from``/``date_to`` are not supplied.
      Long ranges are split into ``chunk_days`` grids and run with up to
      ``max_workers`` threads under a shared Premium rate limit.
    * **legacy default** (``datasets`` is ``None``): the Phase-1 curated path
      (listed_info / daily_bars / market_calendar / fins_summary raw-only)
      into the specialized tables — unchanged behaviour.

    The API key is required for direct fetch, but **not** when ``http`` is the
    Cloudflare proxy client (the Worker injects the key upstream).
    """
    via_proxy = getattr(http, "name", "") == "cf-jquants-proxy"
    if not api_key and not via_proxy:
        return [
            RunReport(
                "jquants", "*",
                skipped="JQUANTS_API_KEY not set (and no CF proxy configured)",
            )
        ]
    if runtime != "local":
        return _cannot_fetch("jquants", runtime)

    from .jquants import normalize as JN
    from .jquants.client import JQuantsClient

    client = JQuantsClient(http, api_key)
    reg = Registrar(store)
    reports: List[RunReport] = []

    if datasets:
        return _run_jquants_catalog(
            client=client,
            reg=reg,
            store=store,
            datasets=datasets,
            mode=mode,
            code=code,
            date_from=date_from,
            date_to=date_to,
            data_base=data_base,
            today=today,
            runtime=runtime,
            max_workers=max_workers,
            chunk_days=chunk_days,
        )

    # Each sub-fetch stamps its own ``when`` right after the HTTP call returns —
    # the per-job fetch-completion time. The raw partition (yyyy/mm/dd) follows
    # ``when`` (not the process-start ``today``) so a sub-fetch that finishes
    # after midnight lands in the correct day; the same ``when`` drives the
    # filename stamp and the rows' ``ingested_at`` for consistency.

    # 1) listed info
    try:
        info = client.listed_info()
        when = now_iso()
        save_raw(
            data_base, "jquants", _stamped("listed_info.json", when),
            json.dumps(info, ensure_ascii=False).encode("utf-8"), when,
        )
        rows = JN.normalize_listed_info(info, ingested_at=when, snapshot_date=str(today)[:10])
        n = reg.register("jquants_listed_info", rows)
        reports.append(RunReport("jquants", "listed_info", fetched=len(info), registered=n))
    except Exception as exc:  # noqa: BLE001
        reports.append(RunReport("jquants", "listed_info", error=f"{exc}"))

    # 2) daily bars
    try:
        bars = client.daily_bars(code=code, from_date=date_from, to_date=date_to)
        when = now_iso()
        save_raw(
            data_base, "jquants", _stamped("daily_bars.json", when),
            json.dumps(bars, ensure_ascii=False).encode("utf-8"), when,
        )
        rows = JN.normalize_daily_bars(bars, ingested_at=when)
        n = reg.register("jquants_daily_bars", rows)
        reports.append(RunReport("jquants", "daily_bars", fetched=len(bars), registered=n))
    except Exception as exc:  # noqa: BLE001
        reports.append(RunReport("jquants", "daily_bars", error=f"{exc}"))

    # 3) market calendar
    try:
        cal = client.market_calendar(from_date=date_from, to_date=date_to)
        when = now_iso()
        save_raw(
            data_base, "jquants", _stamped("calendar.json", when),
            json.dumps(cal, ensure_ascii=False).encode("utf-8"), when,
        )
        rows = JN.normalize_market_calendar(cal, ingested_at=when)
        n = reg.register("jquants_market_calendar", rows)
        reports.append(RunReport("jquants", "calendar", fetched=len(cal), registered=n))
    except Exception as exc:  # noqa: BLE001
        reports.append(RunReport("jquants", "calendar", error=f"{exc}"))

    # 4) OPTIONAL fins/summary — save raw only; skip cleanly on failure.
    #    registered==0 is intentional here (raw-only endpoint).
    try:
        summ = client.fins_summary(code=code)
        when = now_iso()
        save_raw(
            data_base, "jquants", _stamped("fins_summary.json", when),
            json.dumps(summ, ensure_ascii=False).encode("utf-8"), when,
        )
        reports.append(
            RunReport(
                "jquants", "fins_summary",
                fetched=len(summ), registered=0, expected_empty=True,
            )
        )
    except Exception as exc:  # noqa: BLE001
        reports.append(
            RunReport("jquants", "fins_summary", skipped=f"optional endpoint skipped: {exc}")
        )

    _log(store, "jquants", runtime, reports)
    return reports


def _jquants_default_window(today, mode: str) -> tuple[Optional[str], Optional[str]]:
    """Default date window when the caller passes none.

    ``incremental`` -> the last ~5 calendar days (catch the latest bars /
    filings without a heavy backfill). ``backfill`` -> no window (let the
    server return its full default range, or rely on explicit CLI dates).
    """
    if mode == "incremental":
        try:
            start = today - _days(5)
            end = today.strftime("%Y-%m-%d") if hasattr(today, "strftime") else str(today)[:10]
            return start.strftime("%Y-%m-%d"), end
        except Exception:  # pragma: no cover - today isn't date-ish
            return None, None
    return None, None


def _days(n: int):
    from datetime import timedelta

    return timedelta(days=n)


def _dataset_params(accept: list[str], code, date_from, date_to) -> dict:
    """Build request params for a dataset, limited to what it accepts.

    ``accept`` is the catalog entry's ``params`` list. Avoids sending
    ``code``/``from``/``to`` to endpoints that don't take them (e.g. a
    market-wide calendar or index series).
    """
    ok = set(accept or [])
    p: dict = {}
    if code and "code" in ok:
        p["code"] = code
    if date_from and "from" in ok:
        p["from_date"] = date_from
    if date_to and "to" in ok:
        p["to_date"] = date_to
    return p


def _run_jquants_catalog(
    *,
    client,
    reg,
    store,
    datasets: List[str],
    mode: str,
    code,
    date_from,
    date_to,
    data_base,
    today,
    runtime: str,
    max_workers: int = 8,
    chunk_days: int = 30,
) -> List[RunReport]:
    """Catalog-driven parallel fetch -> raw -> normalize_generic -> jquants_records.

    Jobs = datasets × optional codes × date windows (``chunk_days``). Execution
    uses a thread pool with a **shared** rate limiter on the client (Premium
    500/min budget). Pagination within each job stays sequential.

    PIT: each job's ``available_at``/``ingested_at`` default to **that job's
    own fetch-completion time** (stamped in the worker right after the fetch
    returns), not a single pre-pool timestamp shared across every job. Parallel
    jobs finish at different wall-clock instants, so they must carry different
    PIT stamps.
    """
    from .jquants import normalize as JN
    from .jquants.catalog import DATASETS
    from .jquants.parallel import expand_jobs, run_parallel, summarize_results

    if mode not in ("incremental", "backfill"):
        mode = "incremental"
    if not date_from and not date_to:
        date_from, date_to = _jquants_default_window(today, mode)

    known = [d for d in datasets if d in DATASETS]
    unknown = [d for d in datasets if d not in DATASETS]
    reports: List[RunReport] = []
    for did in unknown:
        reports.append(RunReport("jquants", did, skipped=f"unknown dataset id: {did}"))

    codes = [code] if code else None
    jobs = expand_jobs(
        known,
        from_date=date_from,
        to_date=date_to,
        chunk_days=max(1, int(chunk_days)),
        codes=codes,
    )
    workers = max(1, int(max_workers))
    print(
        f"[jquants] parallel jobs={len(jobs)} workers={workers} "
        f"chunk_days={chunk_days} window={date_from}..{date_to}"
    )

    # Serialize register/save_raw: SQLite and path writes are not all thread-safe.
    write_lock = __import__("threading").Lock()

    def _stamp_completion(res) -> None:
        # Capture this job's fetch-completion time inside the worker, the
        # instant its data landed. Used as the per-job available_at/ingested_at
        # default so parallel jobs that finish at different times do not share
        # one stale pre-pool timestamp. ``now_iso`` is resolved from the module
        # namespace at call time (thread-safe; reads the system clock).
        res.completed_at = now_iso()

    def _persist(job, rows: list, when: str) -> RunReport:
        # kind stays the dataset id (tests / aggregators key on it). Window
        # detail is only in the raw filename so multi-window jobs don't clobber.
        # The raw partition (yyyy/mm/dd) follows ``when`` — this job's own
        # fetch-completion time — not the process-start ``today``, so a job that
        # finishes after midnight lands in the correct day.
        kind = job.dataset_id
        stamp_name = job.label.replace(" ", "_")[:120]
        try:
            with write_lock:
                save_raw(
                    data_base,
                    "jquants",
                    _stamped(f"{stamp_name}.json", when),
                    json.dumps(rows, ensure_ascii=False).encode("utf-8"),
                    when,
                )
                norm = JN.normalize_generic(
                    rows, dataset=job.dataset_id, ingested_at=when
                )
                n = reg.register("jquants_records", norm)
            return RunReport(
                "jquants", kind, fetched=len(rows), registered=n
            )
        except Exception as exc:  # noqa: BLE001
            return RunReport("jquants", kind, error=f"{exc}")

    results = run_parallel(
        client, jobs, max_workers=workers, on_job_done=_stamp_completion
    )
    for res in results:
        if not res.ok:
            reports.append(
                RunReport("jquants", res.job.dataset_id, error=res.error)
            )
            continue
        when = getattr(res, "completed_at", "") or now_iso()
        reports.append(_persist(res.job, res.rows, when))

    summary = summarize_results(results)
    print(
        f"[jquants] parallel done ok={summary['ok']}/{summary['jobs']} "
        f"rows={summary['rows']} errors={summary['errors']}"
    )

    _log(store, "jquants", runtime, reports)
    return reports


# ---------------------------------------------------------------------------
# JSDA
# ---------------------------------------------------------------------------

def run_jsda(
    *,
    http,
    store,
    data_base: Path,
    today,
    runtime: str = "local",
    target_url: Optional[str] = None,
) -> List[RunReport]:
    if runtime != "local":
        return [
            RunReport(
                "jsda", "*",
                skipped="JSDA is local-only in Phase 1 (bot/DC risk on the edge)",
            )
        ]

    from .jsda import normalize as SN
    from .jsda.fetch import JsdaFetcher

    fetcher = JsdaFetcher(http)
    reg = Registrar(store)
    ingested = now_iso()
    reports: List[RunReport] = []

    try:
        url = target_url or fetcher.pick()
        if not url:
            reports.append(
                RunReport("jsda", "bond_trades", skipped="no download links found on index")
            )
        else:
            data = fetcher.fetch_file(url)
            fname = url.rsplit("/", 1)[-1] or "jsda.csv"
            rp = save_raw(data_base, "jsda", _stamped(fname, ingested), data, today)
            parser, _kind = _choose_jsda_parser(fname, data)  # raises ValueError on .xls
            records = parser(data)
            rows = SN.normalize_bond_trades(records, ingested_at=ingested)
            n = reg.register("jsda_bond_trades", rows)
            reports.append(
                RunReport(
                    "jsda", "bond_trades",
                    fetched=len(records), registered=n, raw_path=str(rp),
                )
            )
    except Exception as exc:  # noqa: BLE001
        reports.append(RunReport("jsda", "bond_trades", error=f"{exc}"))

    _log(store, "jsda", runtime, reports)
    return reports


# ---------------------------------------------------------------------------

def _log(store, source: str, runtime: str, reports: List[RunReport]) -> None:
    try:
        if any(r.effective_error for r in reports):
            status = "error"
        elif any(r.ok for r in reports):
            status = "ok"
        else:
            status = "skipped"
        store.log_run(
            source=source,
            runtime=runtime,
            status=status,
            detail="; ".join(r.summary() for r in reports),
        )
    except Exception:  # noqa: BLE001
        pass
