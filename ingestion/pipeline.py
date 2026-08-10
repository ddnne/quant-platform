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
    api_key: str,
    data_base: Path,
    today,
    runtime: str = "local",
    code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[RunReport]:
    if not api_key:
        return [RunReport("jquants", "*", skipped="JQUANTS_API_KEY not set")]
    if runtime != "local":
        return _cannot_fetch("jquants", runtime)

    from .jquants import normalize as JN
    from .jquants.client import JQuantsClient

    client = JQuantsClient(http, api_key)
    reg = Registrar(store)
    ingested = now_iso()
    reports: List[RunReport] = []

    # 1) listed info
    try:
        info = client.listed_info()
        save_raw(
            data_base, "jquants", _stamped("listed_info.json", ingested),
            json.dumps(info, ensure_ascii=False).encode("utf-8"), today,
        )
        rows = JN.normalize_listed_info(info, ingested_at=ingested, snapshot_date=str(today)[:10])
        n = reg.register("jquants_listed_info", rows)
        reports.append(RunReport("jquants", "listed_info", fetched=len(info), registered=n))
    except Exception as exc:  # noqa: BLE001
        reports.append(RunReport("jquants", "listed_info", error=f"{exc}"))

    # 2) daily bars
    try:
        bars = client.daily_bars(code=code, from_date=date_from, to_date=date_to)
        save_raw(
            data_base, "jquants", _stamped("daily_bars.json", ingested),
            json.dumps(bars, ensure_ascii=False).encode("utf-8"), today,
        )
        rows = JN.normalize_daily_bars(bars, ingested_at=ingested)
        n = reg.register("jquants_daily_bars", rows)
        reports.append(RunReport("jquants", "daily_bars", fetched=len(bars), registered=n))
    except Exception as exc:  # noqa: BLE001
        reports.append(RunReport("jquants", "daily_bars", error=f"{exc}"))

    # 3) market calendar
    try:
        cal = client.market_calendar(from_date=date_from, to_date=date_to)
        save_raw(
            data_base, "jquants", _stamped("calendar.json", ingested),
            json.dumps(cal, ensure_ascii=False).encode("utf-8"), today,
        )
        rows = JN.normalize_market_calendar(cal, ingested_at=ingested)
        n = reg.register("jquants_market_calendar", rows)
        reports.append(RunReport("jquants", "calendar", fetched=len(cal), registered=n))
    except Exception as exc:  # noqa: BLE001
        reports.append(RunReport("jquants", "calendar", error=f"{exc}"))

    # 4) OPTIONAL fins/summary — save raw only; skip cleanly on failure.
    #    registered==0 is intentional here (raw-only endpoint).
    try:
        summ = client.fins_summary(code=code)
        save_raw(
            data_base, "jquants", _stamped("fins_summary.json", ingested),
            json.dumps(summ, ensure_ascii=False).encode("utf-8"), today,
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


# ---------------------------------------------------------------------------
# EDINET DB
# ---------------------------------------------------------------------------

def run_edinetdb(
    *,
    http,
    store,
    api_key: str,
    data_base: Path,
    today,
    runtime: str = "local",
    financial_codes: Optional[List[str]] = None,
) -> List[RunReport]:
    if not api_key:
        return [RunReport("edinetdb", "*", skipped="EDINETDB_API_KEY not set")]
    if runtime != "local":
        return _cannot_fetch("edinetdb", runtime)

    from .edinetdb import normalize as EN
    from .edinetdb.client import EdinetDbClient

    client = EdinetDbClient(http, api_key)
    reg = Registrar(store)
    ingested = now_iso()
    reports: List[RunReport] = []
    companies: list[dict] = []

    try:
        companies = client.list_companies()
        save_raw(
            data_base, "edinetdb", _stamped("companies.json", ingested),
            json.dumps(companies, ensure_ascii=False).encode("utf-8"), today,
        )
        rows = EN.normalize_companies(companies, ingested_at=ingested)
        n = reg.register("edinetdb_companies", rows)
        reports.append(RunReport("edinetdb", "companies", fetched=len(companies), registered=n))
    except Exception as exc:  # noqa: BLE001
        reports.append(RunReport("edinetdb", "companies", error=f"{exc}"))

    # Financials for an explicit sample of codes (best-effort, optional).
    # Codes the caller passed explicitly (e.g. via the CLI --code) are
    # *expected* — a failure there is an error. Codes we auto-picked from the
    # company list are a best-effort sample, so a per-code failure is a clean
    # skip rather than a failing run.
    sample = list(financial_codes or [])
    codes_explicit = bool(sample)
    if not sample and companies:
        sample = [c.get("code") or c.get("edinet_code") for c in companies[:3]]
        sample = [c for c in sample if c]
    for code in sample:
        try:
            fins = client.financials(code)
            save_raw(
                data_base, "edinetdb", _stamped(f"financials_{code}.json", ingested),
                json.dumps(fins, ensure_ascii=False).encode("utf-8"), today,
            )
            rows = EN.normalize_financials(fins, code=code, ingested_at=ingested)
            n = reg.register("edinetdb_financials", rows)
            reports.append(
                RunReport("edinetdb", f"financials/{code}", fetched=len(fins), registered=n)
            )
        except Exception as exc:  # noqa: BLE001
            if codes_explicit:
                reports.append(
                    RunReport("edinetdb", f"financials/{code}", error=f"{exc}")
                )
            else:
                reports.append(
                    RunReport(
                        "edinetdb", f"financials/{code}",
                        skipped=f"auto-sampled financials failed: {exc}",
                    )
                )

    _log(store, "edinetdb", runtime, reports)
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
