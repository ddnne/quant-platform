"""Fetcher vs Registrar orchestration (Pattern B).

Fetcher is local-only (HTTP + raw bytes + normalize). Registrar validates
``available_at`` and upserts structured rows. Each ``run_*`` returns
:class:`RunReport` rows; :func:`decide_exit` maps them to a CLI code.

``skipped`` is a clean skip. ``error`` is a raised failure or schema miss
(fetched>0, registered=0, not expected_empty). ``ok`` requires registered>0
or an explicit expected-empty endpoint.
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
        return (
            not self.skipped
            and not self.error
            and not self.expected_empty
            and self.fetched > 0
            and self.registered == 0
        )

    @property
    def effective_error(self) -> str:
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
    """1 on error/schema miss, 0 if any ok, else 2 (all clean skips)."""
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
        # Persist canonical +09:00 available_at so lexicographic MIN is chronological.
        canonical = []
        for r in rows:
            r = dict(r)
            r["available_at"] = validate_available_at(r.get("available_at"))
            canonical.append(r)
        return self._store.upsert(table, canonical)


def _compact_stamp(iso_ts: str) -> str:
    s = (iso_ts or "").replace(":", "").replace("-", "")
    # e.g. "20250402T090000+0900"
    return s[:15] if len(s) >= 15 else s


def _stamped(name: str, stamp: str) -> str:
    stamp = _compact_stamp(stamp)
    if not stamp:
        return name
    stem, ext = os.path.splitext(name)
    return f"{stem}_{stamp}{ext}"


def save_raw(
    data_base: Path, source: str, filename: str, data: bytes, when
) -> Path:
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
    """Return ``(parser, kind)``. Legacy ``.xls`` raises (not a silent zero-row parse)."""
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


def _choose_jsda_repo_parser(filename: str, data: bytes):
    """Return ``(parser, kind)``. Official ``.xls`` is required, never a clean skip."""
    from .jsda.parse import parse_repo_csv, parse_repo_xls, parse_repo_xlsx

    low = (filename or "").lower()
    is_xlsx_blob = bool(data) and bytes(data[:2]) == b"PK"

    if low.endswith(".xls") and not is_xlsx_blob:
        return parse_repo_xls, "xls"
    if low.endswith(".xlsx") or is_xlsx_blob:
        return parse_repo_xlsx, "xlsx"
    return parse_repo_csv, "csv"


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
    """J-Quants pass: catalog-driven ``datasets`` or the Phase-1 curated path."""
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

    # 4) fins/summary — raw-only; skip cleanly on failure.
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
    """incremental: last 5 calendar days. backfill: no default window."""
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
    """Catalog-driven parallel fetch → raw → normalize_generic → jquants_records."""
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
        # Per-job PIT stamp; parallel jobs must not share a pre-pool timestamp.
        res.completed_at = now_iso()

    def _persist(job, rows: list, when: str) -> RunReport:
        # kind = dataset id. Window lives in the filename so jobs don't clobber.
        kind = job.dataset_id
        stamp_name = job.label.replace(" ", "_")[:120]
        raw_bytes = json.dumps(rows, ensure_ascii=False).encode("utf-8")
        try:
            with write_lock:
                rp = save_raw(
                    data_base,
                    "jquants",
                    _stamped(f"{stamp_name}.json", when),
                    raw_bytes,
                    when,
                )
                norm = JN.normalize_generic(
                    rows, dataset=job.dataset_id, ingested_at=when
                )
                n = reg.register("jquants_records", norm)
                # Coverage V2: emit a real collection receipt for this job's
                # window when we can map it to a planned segment. Never fakes
                # COMPLETE — evaluate_segment decides after ledger refresh.
                try:
                    from data_contracts import coverage_contract_for
                    from storage.coverage_ledger import (
                        plan_required_segments,
                        record_required_segments,
                    )
                    from .jquants.receipts import emit_segment_receipt

                    params = dict(getattr(job, "params", None) or {})
                    policy = coverage_contract_for(job.dataset_id)
                    target_end = (
                        params.get("to")
                        or params.get("date")
                        or str(when)[:10]
                    )
                    target_end = str(target_end)[:10]
                    job_start = str(
                        params.get("from") or params.get("date") or target_end
                    )[:10]
                    job_end = target_end
                    # First plan without expected counts to discover segment ids.
                    segs = list(
                        plan_required_segments(
                            policy, target_end, source="jquants"
                        )
                    )
                    req0 = None
                    for s in segs:
                        if s.segment_start <= job_end and s.segment_end >= job_start:
                            req0 = s
                            break
                    if req0 is None and segs:
                        req0 = segs[-1]
                    if req0 is not None:
                        unit = (req0.expected_scope or {}).get(
                            "expected_item_unit", "source_query"
                        )
                        exp_map = None
                        if (
                            policy.expected_frequency != "event_driven"
                            and unit == "source_query"
                        ):
                            exp_map = {req0.segment_id: 1}
                            segs = list(
                                plan_required_segments(
                                    policy,
                                    target_end,
                                    source="jquants",
                                    expected_items_by_segment=exp_map,
                                )
                            )
                            req = next(
                                s for s in segs if s.segment_id == req0.segment_id
                            )
                        else:
                            req = req0
                        record_required_segments(store._conn, [req])
                        run_id_row = store._conn.execute(
                            "SELECT COALESCE(MAX(id), 0) FROM ingestion_run_log"
                        ).fetchone()
                        run_id = int(run_id_row[0]) if run_id_row else 0
                        if unit == "source_query":
                            obs = 1 if len(rows) > 0 else 0
                        else:
                            obs = len(rows)
                        from ingestion.runtime_authority import (
                            open_ingestion_signing_authority,
                        )

                        authority = open_ingestion_signing_authority()
                        emit_segment_receipt(
                            store._conn,
                            required=req,
                            run_id=run_id,
                            raw=raw_bytes,
                            observed_items=obs,
                            structured_row_count=n,
                            raw_row_count=len(rows),
                            pagination_exhausted=True,
                            status="SUCCESS",
                            authority=authority,
                            commit=False,
                        )
                        store._conn.commit()
                except Exception as rec_exc:  # noqa: BLE001
                    # Governed: receipt failure must not leave structured rows as PASS.
                    try:
                        store._conn.rollback()
                    except Exception:  # noqa: BLE001
                        pass
                    return RunReport(
                        "jquants",
                        kind,
                        fetched=len(rows),
                        registered=0,
                        error=f"receipt emit failed (governed): {rec_exc}",
                        raw_path=str(rp),
                    )
            return RunReport(
                "jquants", kind, fetched=len(rows), registered=n, raw_path=str(rp)
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
    repo_target_url: Optional[str] = None,
    bond: bool = True,
    repo: bool = True,
) -> List[RunReport]:
    """JSDA pass: bond trades and/or repo rates. Local-only; independent reports."""
    if runtime != "local":
        return [
            RunReport(
                "jsda", "*",
                skipped="JSDA is local-only in Phase 1 (bot/DC risk on the edge)",
            )
        ]

    from .jsda.fetch import JsdaFetcher

    fetcher = JsdaFetcher(http)
    reg = Registrar(store)
    ingested = now_iso()
    reports: List[RunReport] = []

    if bond:
        reports.append(
            _run_jsda_bond(fetcher, reg, data_base, today, ingested, target_url)
        )
    if repo:
        reports.append(
            _run_jsda_repo(fetcher, reg, data_base, today, ingested, repo_target_url)
        )

    _log(store, "jsda", runtime, reports)
    return reports


def _run_jsda_bond(fetcher, reg, data_base, today, ingested, target_url) -> RunReport:
    from .jsda import normalize as SN

    try:
        url = target_url or fetcher.pick()
        if not url:
            return RunReport(
                "jsda", "bond_trades", skipped="no download links found on index"
            )
        data = fetcher.fetch_file(url)
        fname = url.rsplit("/", 1)[-1] or "jsda.csv"
        rp = save_raw(data_base, "jsda", _stamped(fname, ingested), data, today)
        parser, _kind = _choose_jsda_parser(fname, data)  # raises ValueError on .xls
        records = parser(data)
        rows = SN.normalize_bond_trades(records, ingested_at=ingested)
        n = reg.register("jsda_bond_trades", rows)
        return RunReport(
            "jsda", "bond_trades",
            fetched=len(records), registered=n, raw_path=str(rp),
        )
    except Exception as exc:  # noqa: BLE001
        return RunReport("jsda", "bond_trades", error=f"{exc}")


def _run_jsda_repo(fetcher, reg, data_base, today, ingested, target_url) -> RunReport:
    from .jsda import normalize as SN

    try:
        url = target_url or fetcher.pick_repo()
        if not url:
            return RunReport(
                "jsda", "repo_rates", skipped="no repo download links found on TRR index"
            )
        data = fetcher.fetch_file(url)
        fname = url.rsplit("/", 1)[-1] or "jsda_repo.csv"
        rp = save_raw(data_base, "jsda", _stamped(fname, ingested), data, today)
        parser, _kind = _choose_jsda_repo_parser(fname, data)
        records = parser(data)
        rows = SN.normalize_repo_rates(records, ingested_at=ingested)
        n = reg.register("jsda_repo_rates", rows)
        return RunReport(
            "jsda", "repo_rates",
            fetched=len(records), registered=n, raw_path=str(rp),
        )
    except Exception as exc:  # noqa: BLE001
        return RunReport("jsda", "repo_rates", error=f"{exc}")


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
