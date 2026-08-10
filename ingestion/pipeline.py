"""Fetcher vs Registrar orchestration (Pattern B).

* **Fetcher** runs on **local**: it issues HTTP, saves verbatim raw bytes to
  ``data/raw/{source}/...`` and normalizes them.
* **Registrar** validates ``available_at`` and persists structured rows. It
  has no network dependency, so it is the only part that could later run on
  Cloudflare reading from storage (Phase 2+).

Each ``run_*`` function returns a list of :class:`RunReport` so the CLI can
print a per-source, per-kind summary and choose an exit code. Missing API
keys and unsupported runtimes produce *clean skips*, not exceptions.
"""

from __future__ import annotations

import json
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
    skipped: str = ""
    raw_path: str = ""

    @property
    def ok(self) -> bool:
        return not self.skipped

    def summary(self) -> str:
        if self.skipped:
            tag = "SKIPPED"
            return f"[{self.source}/{self.kind}] {tag} ({self.skipped})"
        tag = "OK"
        rp = f" raw={self.raw_path}" if self.raw_path else ""
        return (
            f"[{self.source}/{self.kind}] {tag} "
            f"fetched={self.fetched} registered={self.registered}{rp}"
        )


class Registrar:
    """Persist structured rows. ``available_at`` is mandatory."""

    def __init__(self, store) -> None:
        self._store = store

    def register(self, table: str, rows) -> int:
        rows = list(rows)
        for r in rows:
            # Double-check PIT gate before the store rejects the whole batch.
            validate_available_at(r.get("available_at"))
        return self._store.upsert(table, rows)


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
            data_base, "jquants", "listed_info.json",
            json.dumps(info, ensure_ascii=False).encode("utf-8"), today,
        )
        rows = JN.normalize_listed_info(info, ingested_at=ingested, snapshot_date=str(today)[:10])
        n = reg.register("jquants_listed_info", rows)
        reports.append(RunReport("jquants", "listed_info", fetched=len(info), registered=n))
    except Exception as exc:  # noqa: BLE001
        reports.append(RunReport("jquants", "listed_info", skipped=f"error: {exc}"))

    # 2) daily bars
    try:
        bars = client.daily_bars(code=code, from_date=date_from, to_date=date_to)
        save_raw(
            data_base, "jquants", "daily_bars.json",
            json.dumps(bars, ensure_ascii=False).encode("utf-8"), today,
        )
        rows = JN.normalize_daily_bars(bars, ingested_at=ingested)
        n = reg.register("jquants_daily_bars", rows)
        reports.append(RunReport("jquants", "daily_bars", fetched=len(bars), registered=n))
    except Exception as exc:  # noqa: BLE001
        reports.append(RunReport("jquants", "daily_bars", skipped=f"error: {exc}"))

    # 3) market calendar
    try:
        cal = client.market_calendar(from_date=date_from, to_date=date_to)
        save_raw(
            data_base, "jquants", "calendar.json",
            json.dumps(cal, ensure_ascii=False).encode("utf-8"), today,
        )
        rows = JN.normalize_market_calendar(cal, ingested_at=ingested)
        n = reg.register("jquants_market_calendar", rows)
        reports.append(RunReport("jquants", "calendar", fetched=len(cal), registered=n))
    except Exception as exc:  # noqa: BLE001
        reports.append(RunReport("jquants", "calendar", skipped=f"error: {exc}"))

    # 4) OPTIONAL fins/summary — save raw only; skip cleanly on failure
    try:
        summ = client.fins_summary(code=code)
        save_raw(
            data_base, "jquants", "fins_summary.json",
            json.dumps(summ, ensure_ascii=False).encode("utf-8"), today,
        )
        reports.append(RunReport("jquants", "fins_summary", fetched=len(summ), registered=0))
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
            data_base, "edinetdb", "companies.json",
            json.dumps(companies, ensure_ascii=False).encode("utf-8"), today,
        )
        rows = EN.normalize_companies(companies, ingested_at=ingested)
        n = reg.register("edinetdb_companies", rows)
        reports.append(RunReport("edinetdb", "companies", fetched=len(companies), registered=n))
    except Exception as exc:  # noqa: BLE001
        reports.append(RunReport("edinetdb", "companies", skipped=f"error: {exc}"))

    # Financials for an explicit sample of codes (best-effort, optional).
    sample = list(financial_codes or [])
    if not sample and companies:
        sample = [c.get("code") or c.get("edinet_code") for c in companies[:3]]
        sample = [c for c in sample if c]
    for code in sample:
        try:
            fins = client.financials(code)
            save_raw(
                data_base, "edinetdb", f"financials_{code}.json",
                json.dumps(fins, ensure_ascii=False).encode("utf-8"), today,
            )
            rows = EN.normalize_financials(fins, code=code, ingested_at=ingested)
            n = reg.register("edinetdb_financials", rows)
            reports.append(
                RunReport("edinetdb", f"financials/{code}", fetched=len(fins), registered=n)
            )
        except Exception as exc:  # noqa: BLE001
            reports.append(
                RunReport("edinetdb", f"financials/{code}", skipped=f"error: {exc}")
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
    from .jsda.parse import parse_csv

    fetcher = JsdaFetcher(http)
    reg = Registrar(store)
    ingested = now_iso()
    reports: List[RunReport] = []

    try:
        url = target_url or fetcher.pick()
        if not url:
            reports.append(RunReport("jsda", "bond_trades", skipped="no download links found on index"))
        else:
            data = fetcher.fetch_file(url)
            fname = url.rsplit("/", 1)[-1] or "jsda.csv"
            rp = save_raw(data_base, "jsda", fname, data, today)
            records = parse_csv(data)
            rows = SN.normalize_bond_trades(records, ingested_at=ingested)
            n = reg.register("jsda_bond_trades", rows)
            reports.append(
                RunReport(
                    "jsda", "bond_trades",
                    fetched=len(records), registered=n, raw_path=str(rp),
                )
            )
    except Exception as exc:  # noqa: BLE001
        reports.append(RunReport("jsda", "bond_trades", skipped=f"error: {exc}"))

    _log(store, "jsda", runtime, reports)
    return reports


# ---------------------------------------------------------------------------

def _log(store, source: str, runtime: str, reports: List[RunReport]) -> None:
    try:
        status = "ok" if any(r.ok for r in reports) else "skipped"
        store.log_run(
            source=source,
            runtime=runtime,
            status=status,
            detail="; ".join(r.summary() for r in reports),
        )
    except Exception:  # noqa: BLE001
        pass
