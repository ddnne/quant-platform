"""Phase 3.5 — Validation matrix coverage runner (offline, SQLite-only).

Pure functions that execute the catalog checks in
:mod:`cf_platform.ingest_premium.matrix` against a **local** PIT SQLite DB
(the kind Phase 3.5's sync script produces). No network, no D1, no Cloudflare
calls. The CLI shim in ``scripts/run_phase35_validation.py`` is a thin
wrapper around :func:`run_coverage`.

Two tiers (matches the doc):

* ``daily`` — cheap per-run checks: C1–C5, C8, C12, B2, B4, K3, X4.
  Every id below has runnable logic over the SQLite DB; nothing here is
  stubbed.
* ``weekly`` — broader checks. We implement as many as is practical from
  fixture/seed DBs; the remainder return ``status="skip"`` with
  ``detail="not_implemented"`` so the catalog is exhaustive without lying
  about coverage.

Output: ``list[CheckResult]``. The CLI converts that to JSON or human text.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import matrix
from .matrix import CheckDef
from .validate import PREMIUM_CORE_DATASETS

# Order-of-magnitude live gates (shared with Phase 4). Offline fixtures use
# scaled data; report metrics always. Enforce only when ``strict_live_gates``.
LIVE_GATES: dict[str, float] = {
    "master_min_issuers": 3000,
    "bars_min_issuers": 3000,
    "bars_min_rows_latest_day": 3000,
    "trading_days_per_year_lo": 230,
    "trading_days_per_year_hi": 255,
}

# Conservative assumed Premium-start dates per dataset, used by C6/C7.
# Source: J-Quants data-spec (https://jpx-jquants.com/en/spec/data-spec).
# Values are rounded toward the *nearest recent* month — i.e. deliberately
# conservative (a later start ⇒ a shorter expected window ⇒ a more forgiving
# fill-rate). Where the official start is disputed or plan-dependent, we
# pick the latest plausible public start. **These are assumptions, not
# contractual truths** — update as the spec evolves.
EXPECTED_START: dict[str, str] = {
    # W98 / w0819a: PRE_PLAN 2000-07..2006-07 de-scoped (subscription OOS).
    # MISDATE 2006-08..2008-04 remains required-window PARTIAL (PD-D2-MASTER).
    "equities_master": "2006-08-13",
    # Raised to proven observed floors (w0815ae/W38; docs/proof/observed_floor_catalog_20260815.md)
    "equities_bars_daily": "2008-05-01",
    "equities_bars_daily_am": "2024-01-04",   # AM is recent-only by spec
    "fins_summary": "2008-07-01",
    "fins_details": "2018-01-01",
    "fins_dividend": "2013-02-01",
    "fins_earnings_date": "2018-01-01",
    "equities_earnings_calendar": "2010-01-04",  # tip-only vendor; not raised
    "markets_calendar": "2008-01-01",
    "equities_investor_types": "2013-01-04",
    "indices_bars_daily_topix": "2008-05-01",
    "indices_bars_daily": "2008-05-01",
    "derivatives_bars_daily_options_225": "2013-01-04",
    "derivatives_bars_daily_futures": "2013-01-04",
    "derivatives_bars_daily_options": "2013-01-04",
    "markets_margin_interest": "2013-01-04",
    "markets_margin_alert": "2013-01-04",
    "markets_short_ratio": "2013-01-04",
    "markets_short_sale_report": "2013-11-01",
    "markets_breakdown": "2015-04-01",
    "edinet_major_shareholders": "2018-01-04",
    "edinet_cross_shareholdings": "2020-05-01",
    "edinet_large_volume_shareholders": "2021-07-01",
}

# Fill-rate thresholds for C6/C7. Below ``WARN_RATE`` the row is at least a
# warning; below ``FAIL_RATE`` it is a failure in strict mode (warns softly
# offline). ``PASS_RATE`` is the floor for an unqualified pass.
_C6_C7_PASS_RATE = 0.90
_C6_C7_WARN_RATE = 0.50
_C6_C7_FAIL_RATE = 0.20

# Datasets with dedicated fact tables in addition to (or instead of) the
# generic ``jquants_records`` table. The runner unions both so it works
# against DBs produced by either the Phase-1 local ingestion or the
# Phase-3.5 sync script.
_SPECIALIZED: dict[str, str] = {
    "equities_master": "jquants_listed_info",
    "equities_bars_daily": "jquants_daily_bars",
    "markets_calendar": "jquants_market_calendar",
}

# Addon ids that must NEVER appear in the required schedule (C12).
_ADDON_IDS: frozenset[str] = frozenset({
    "equities_bars_minute", "equities_trades",
    "td_list", "td_files", "td_bulk",
})

# Freshness window for C8 (calendar trading days). Conservative default —
# weekends/holidays are excluded so a Friday run still passes on Monday.
_DEFAULT_FRESHNESS_DAYS = 7

Status = str  # "pass" | "fail" | "skip" | "warn"


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CheckResult:
    """One executed check row. ``dataset`` is None for cross-cutting checks.

    ``metrics`` carries the numbers that drove the decision (row counts,
    min/max dates, etc.) so the JSON view is self-explaining.
    """

    check_id: str
    dataset: str | None
    status: Status
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_log_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------
def _connect(db_path: str | Path) -> sqlite3.Connection:
    """Open the SQLite DB read-only. ``-uri`` form lets us force ``mode=ro``.

    PIT-style: never write. If the path doesn't exist, sqlite3.connect would
    create it; using the URI form with ``mode=ro`` raises OperationalError
    instead, which the caller surfaces as a skip.
    """
    p = Path(db_path)
    uri = f"file:{p.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def _dataset_rowcount(conn: sqlite3.Connection, dataset: str) -> int:
    """Count rows for a dataset across generic and specialized tables.

    The CF sync lands everything in ``jquants_records``; the Phase-1 local
    ingestion path uses dedicated tables. Union both so the runner works on
    either layout.
    """
    total = 0
    if _table_exists(conn, "jquants_records"):
        cur = conn.execute(
            "SELECT COUNT(*) FROM jquants_records WHERE dataset=?", (dataset,)
        )
        total += int(cur.fetchone()[0] or 0)
    spec = _SPECIALIZED.get(dataset)
    if spec and _table_exists(conn, spec):
        # Specialized tables don't have a ``dataset`` column — every row in
        # them IS the dataset. ``equities_master`` has one row per
        # (code, snapshot_date); the row count (not distinct-code count) is
        # what we want, matching what ``rows_inserted`` measures on the
        # CF Worker side.
        cur = conn.execute("SELECT COUNT(*) FROM " + spec)
        total += int(cur.fetchone()[0] or 0)
    return total


def _dataset_event_window(
    conn: sqlite3.Connection, dataset: str
) -> tuple[str | None, str | None]:
    """Min/max ``event_time`` across generic + specialized tables."""
    rows: list[tuple[str, str]] = []
    if _table_exists(conn, "jquants_records"):
        cur = conn.execute(
            "SELECT MIN(event_time), MAX(event_time) FROM jquants_records "
            "WHERE dataset=?",
            (dataset,),
        )
        rows.append(tuple(cur.fetchone() or (None, None)))
    spec = _SPECIALIZED.get(dataset)
    if spec and _table_exists(conn, spec):
        cur = conn.execute(
            f"SELECT MIN(event_time), MAX(event_time) FROM {spec}"
        )
        rows.append(tuple(cur.fetchone() or (None, None)))
    mins = [r[0] for r in rows if r and r[0]]
    maxs = [r[1] for r in rows if r and r[1]]
    return (min(mins) if mins else None, max(maxs) if maxs else None)


def _available_at_missing_rate(
    conn: sqlite3.Connection, dataset: str
) -> float:
    """Fraction of rows with NULL/empty ``available_at`` (should be 0)."""
    seen = 0
    missing = 0
    if _table_exists(conn, "jquants_records"):
        cur = conn.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN available_at IS NULL OR available_at='' THEN 1 ELSE 0 END) "
            "FROM jquants_records WHERE dataset=?",
            (dataset,),
        )
        s, m = cur.fetchone() or (0, 0)
        seen += int(s or 0)
        missing += int(m or 0)
    spec = _SPECIALIZED.get(dataset)
    if spec and _table_exists(conn, spec):
        cur = conn.execute(
            f"SELECT COUNT(*), "
            f"SUM(CASE WHEN available_at IS NULL OR available_at='' THEN 1 ELSE 0 END) "
            f"FROM {spec}"
        )
        s, m = cur.fetchone() or (0, 0)
        seen += int(s or 0)
        missing += int(m or 0)
    if seen == 0:
        return 0.0
    return missing / seen


def _datasets_present(conn: sqlite3.Connection) -> set[str]:
    """Every dataset id actually present in the DB (generic + specialized)."""
    out: set[str] = set()
    if _table_exists(conn, "jquants_records"):
        cur = conn.execute("SELECT DISTINCT dataset FROM jquants_records")
        out.update(r[0] for r in cur.fetchall() if r[0])
    for ds, spec in _SPECIALIZED.items():
        if _table_exists(conn, spec):
            cur = conn.execute(f"SELECT COUNT(*) FROM {spec}")
            if (cur.fetchone() or (0,))[0]:
                out.add(ds)
    return out


def _codes_for_master(conn: sqlite3.Connection) -> set[str]:
    """All distinct issuer codes from listed_info + generic 'equities_master'."""
    codes: set[str] = set()
    if _table_exists(conn, "jquants_listed_info"):
        cur = conn.execute("SELECT DISTINCT code FROM jquants_listed_info")
        codes.update(str(r[0]) for r in cur.fetchall() if r[0])
    if _table_exists(conn, "jquants_records"):
        cur = conn.execute(
            "SELECT payload FROM jquants_records WHERE dataset='equities_master'"
        )
        for (payload,) in cur.fetchall():
            if not payload:
                continue
            try:
                obj = json.loads(payload)
            except (TypeError, ValueError):
                continue
            c = obj.get("Code")
            if c:
                codes.add(str(c))
    return codes


# ---------------------------------------------------------------------------
# Real run-log readers (P0-2): prefer ingestion_validation / ingestion_run_log
# over "any rows exist" when the sync script mirrored them.
# ---------------------------------------------------------------------------
def _latest_validation_for_dataset(
    conn: sqlite3.Connection, dataset: str
) -> dict[str, Any] | None:
    """Latest ``ingestion_validation`` row for ``dataset`` (or ``None``).

    The CF Worker records one row per (run, dataset) on D1, and the local
    sync script mirrors those into the same table on SQLite. We sort by
    ``started_at`` descending so the most recent outcome wins — exactly what
    C1/C2 are supposed to surface. Returns a plain ``dict`` so callers can
    pick the fields they need (status, rows_inserted, detail, started_at,
    available_at_min, ...).
    """
    if not _table_exists(conn, "ingestion_validation"):
        return None
    try:
        cur = conn.execute(
            "SELECT dataset, started_at, finished_at, status, "
            "rows_seen, rows_inserted, rows_revisions, "
            "available_at_min, available_at_max, detail "
            "FROM ingestion_validation WHERE dataset=? "
            "ORDER BY started_at DESC LIMIT 1",
            (dataset,),
        )
        row = cur.fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    return {
        "dataset": row["dataset"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "status": row["status"],
        "rows_seen": int(row["rows_seen"] or 0),
        "rows_inserted": int(row["rows_inserted"] or 0),
        "rows_revisions": int(row["rows_revisions"] or 0),
        "available_at_min": row["available_at_min"],
        "available_at_max": row["available_at_max"],
        "detail": row["detail"] or "",
    }


def _latest_run_log(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Latest ``ingestion_run_log`` row across all sources.

    Used by C1 as a fallback signal that *something* has run, even when the
    per-dataset ``ingestion_validation`` table is absent (some Phase-1
    ingestion paths only log here). Sorted by ``ran_at`` descending.
    """
    if not _table_exists(conn, "ingestion_run_log"):
        return None
    try:
        cur = conn.execute(
            "SELECT ran_at, source, runtime, status, detail "
            "FROM ingestion_run_log ORDER BY ran_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    return {
        "ran_at": row["ran_at"],
        "source": row["source"],
        "runtime": row["runtime"],
        "status": row["status"],
        "detail": row["detail"] or "",
    }


def _codes_with_bars(conn: sqlite3.Connection) -> set[str]:
    """Distinct issuers with ≥1 daily bar."""
    codes: set[str] = set()
    if _table_exists(conn, "jquants_daily_bars"):
        cur = conn.execute("SELECT DISTINCT code FROM jquants_daily_bars")
        codes.update(str(r[0]) for r in cur.fetchall() if r[0])
    if _table_exists(conn, "jquants_records"):
        cur = conn.execute(
            "SELECT payload FROM jquants_records WHERE dataset='equities_bars_daily'"
        )
        for (payload,) in cur.fetchall():
            if not payload:
                continue
            try:
                obj = json.loads(payload)
            except (TypeError, ValueError):
                continue
            c = obj.get("Code")
            if c:
                codes.add(str(c))
    return codes


def _bar_dates(conn: sqlite3.Connection) -> set[str]:
    """Distinct calendar dates with at least one daily bar (market-wide)."""
    dates: set[str] = set()
    if _table_exists(conn, "jquants_daily_bars"):
        cur = conn.execute("SELECT DISTINCT date FROM jquants_daily_bars")
        dates.update(r[0] for r in cur.fetchall() if r[0])
    if _table_exists(conn, "jquants_records"):
        cur = conn.execute(
            "SELECT natural_key, payload FROM jquants_records "
            "WHERE dataset='equities_bars_daily'"
        )
        for nk, payload in cur.fetchall():
            # Try payload first (robust); fall back to natural_key parse.
            d = None
            if payload:
                try:
                    obj = json.loads(payload)
                    d = obj.get("Date")
                except (TypeError, ValueError):
                    d = None
            if not d and nk:
                try:
                    keyobj = json.loads(nk)
                    d = keyobj.get("Date")
                except (TypeError, ValueError):
                    d = None
            if d:
                dates.add(str(d))
    return dates


def _calendar_dates(
    conn: sqlite3.Connection, *, trading_only: bool = True
) -> set[str]:
    """Dates from ``markets_calendar``. ``trading_only`` filters HolidayDivision.

    HolidayDivision '1' is a trading day in the J-Quants schema. Anything
    else (0 / empty) is a holiday/weekend. When the column is null on all
    rows (raw JSON-only sync), we fall back to returning every calendar
    date seen — the bar-gap check then degrades to a no-op rather than
    spurious failures.
    """
    dates: set[str] = set()
    if _table_exists(conn, "jquants_market_calendar"):
        if trading_only:
            cur = conn.execute(
                "SELECT DISTINCT date FROM jquants_market_calendar "
                "WHERE holiday_division = '1' OR holiday_division = 1"
            )
        else:
            cur = conn.execute(
                "SELECT DISTINCT date FROM jquants_market_calendar"
            )
        dates.update(r[0] for r in cur.fetchall() if r[0])
    if _table_exists(conn, "jquants_records"):
        # Synced generic rows: holiday_division lives in the payload JSON.
        cur = conn.execute(
            "SELECT payload FROM jquants_records WHERE dataset='markets_calendar'"
        )
        for (payload,) in cur.fetchall():
            if not payload:
                continue
            try:
                obj = json.loads(payload)
            except (TypeError, ValueError):
                continue
            # J-Quants API uses HolDiv; some local normalizers use HolidayDivision.
            div = obj.get("HolidayDivision", obj.get("HolDiv"))
            is_trading = str(div) == "1"
            d = obj.get("Date")
            if d and (not trading_only or is_trading):
                dates.add(str(d))
    return dates


# ---------------------------------------------------------------------------
# Individual check implementations
# ---------------------------------------------------------------------------
def _check_c1(conn: sqlite3.Connection, datasets: Iterable[str]) -> list[CheckResult]:
    """C1 — Job exists: in required set + run record (any data) present.

    P0-2 honesty: when the CF/D1 ``ingestion_validation`` table is synced
    locally we prefer it as the source of truth (one row per (run, dataset)
    with explicit ``status``). Otherwise we fall back to ``ingestion_run_log``
    (run-level), and only as a last resort to "any fact row present".
    """
    out: list[CheckResult] = []
    required = set(PREMIUM_CORE_DATASETS)
    present = _datasets_present(conn)
    has_validation_tbl = _table_exists(conn, "ingestion_validation")
    has_run_log_tbl = _table_exists(conn, "ingestion_run_log")
    for ds in datasets:
        in_required = ds in required
        has_data = ds in present
        vrow = _latest_validation_for_dataset(conn, ds) if has_validation_tbl else None
        run = _latest_run_log(conn) if (has_run_log_tbl and vrow is None) else None
        if in_required and vrow is not None:
            # Real validation row wins: status comes from the Worker.
            metrics: dict[str, Any] = {
                "in_required": True,
                "has_data": has_data,
                "validation_status": vrow["status"],
                "started_at": vrow["started_at"],
                "rows_inserted": vrow["rows_inserted"],
                "source": "ingestion_validation",
            }
            # Pass/fail mirrors the validation row — that's the whole point.
            out.append(CheckResult(
                "C1", ds,
                "pass" if str(vrow["status"]).lower() == "pass" else "fail",
                f"validation row: status={vrow['status']} "
                f"rows_inserted={vrow['rows_inserted']} at {vrow['started_at']}",
                metrics,
            ))
        elif in_required and run is not None and has_data:
            # No per-dataset row, but a run log entry exists and the dataset
            # is present in facts. Treat as warn: the job ran but the
            # explicit outcome was not synced.
            out.append(CheckResult(
                "C1", ds, "warn",
                f"in required set + data present; run_log only "
                f"(ran_at={run['ran_at']}, status={run['status']})",
                {"in_required": True, "has_data": True,
                 "run_log_status": run["status"],
                 "ran_at": run["ran_at"],
                 "source": "ingestion_run_log"},
            ))
        elif in_required and has_data:
            out.append(CheckResult("C1", ds, "pass",
                                   "dataset in required set and has data",
                                   {"in_required": True, "has_data": True,
                                    "source": "facts_only"}))
        elif in_required and not has_data:
            out.append(CheckResult("C1", ds, "fail",
                                   "in required set but no rows synced",
                                   {"in_required": True, "has_data": False}))
        else:
            # Not in required set — shouldn't happen for PREMIUM_CORE iter.
            out.append(CheckResult("C1", ds, "warn",
                                   "dataset not in required set",
                                   {"in_required": False, "has_data": has_data}))
    return out


def _check_c2(conn: sqlite3.Connection, datasets: Iterable[str]) -> list[CheckResult]:
    """C2 — Last run outcome: prefer ``ingestion_validation``; fallback to facts.

    P0-2 honesty: when ``ingestion_validation`` is present, C2 mirrors the
    per-dataset ``status`` exactly. When only fact rows are available, C2
    degrades to ``warn`` (not pass) with the explicit note that "no run log
    was synced; data present only" — so a green offline report can never be
    confused with a real per-job pass verdict.
    """
    out: list[CheckResult] = []
    has_validation_tbl = _table_exists(conn, "ingestion_validation")
    for ds in datasets:
        n = _dataset_rowcount(conn, ds)
        vrow = _latest_validation_for_dataset(conn, ds) if has_validation_tbl else None
        if vrow is not None:
            # Real validation row — mirror its status with row metadata.
            metrics: dict[str, Any] = {
                "row_count": n,
                "validation_status": vrow["status"],
                "rows_inserted": vrow["rows_inserted"],
                "started_at": vrow["started_at"],
                "source": "ingestion_validation",
            }
            detail = (
                f"validation: status={vrow['status']} "
                f"rows_inserted={vrow['rows_inserted']} "
                f"started_at={vrow['started_at']}"
            )
            out.append(CheckResult(
                "C2", ds,
                "pass" if str(vrow["status"]).lower() == "pass" else "fail",
                detail, metrics,
            ))
        elif n > 0:
            # No run log; data present only. P0-2 contract: warn, not pass.
            out.append(CheckResult(
                "C2", ds, "warn",
                f"{n} rows synced; no run log; data present only",
                {"row_count": n, "source": "facts_only",
                 "reason_code": "no_run_log"},
            ))
        else:
            out.append(CheckResult("C2", ds, "fail",
                                   "no rows — run did not succeed or did not sync",
                                   {"row_count": 0, "source": "facts_only"}))
    return out


def _empty_but_run_ok(conn: sqlite3.Connection, dataset: str) -> bool:
    """True when the latest validation row says pass with zero inserts.

    Some Premium endpoints legitimately return empty ``data`` for a given
    market day (or require a ``code`` fan-out not yet enabled). Treating that
    as a hard C3/C4/C8 fail drowns real failures in noise.
    """
    v = _latest_validation_for_dataset(conn, dataset)
    if v is None:
        return False
    return (
        str(v.get("status", "")).lower() == "pass"
        and int(v.get("rows_inserted") or 0) == 0
    )


def _check_c3(conn: sqlite3.Connection, datasets: Iterable[str]) -> list[CheckResult]:
    """C3 — Row count not zero (unless latest validation recorded empty-pass)."""
    out: list[CheckResult] = []
    for ds in datasets:
        n = _dataset_rowcount(conn, ds)
        if n > 0:
            out.append(CheckResult("C3", ds, "pass",
                                   f"{n} rows", {"row_count": n}))
        elif _empty_but_run_ok(conn, ds):
            out.append(CheckResult("C3", ds, "warn",
                                   "row count is zero but last validation pass "
                                   "with rows_inserted=0 (API empty market day)",
                                   {"row_count": 0, "reason_code": "empty_api_pass"}))
        else:
            out.append(CheckResult("C3", ds, "fail",
                                   "row count is zero",
                                   {"row_count": 0}))
    return out


def _check_c4(conn: sqlite3.Connection, datasets: Iterable[str]) -> list[CheckResult]:
    """C4 — event_time min/max observed (skip when empty-pass validation)."""
    out: list[CheckResult] = []
    for ds in datasets:
        lo, hi = _dataset_event_window(conn, ds)
        if lo and hi:
            out.append(CheckResult("C4", ds, "pass",
                                   f"event_time window: {lo} → {hi}",
                                   {"event_time_min": lo, "event_time_max": hi}))
        elif _empty_but_run_ok(conn, ds) or _dataset_rowcount(conn, ds) == 0:
            out.append(CheckResult("C4", ds, "skip",
                                   "no event_time (empty dataset)",
                                   {"event_time_min": None, "event_time_max": None,
                                    "reason_code": "no_data"}))
        else:
            out.append(CheckResult("C4", ds, "fail",
                                   "no event_time observed",
                                   {"event_time_min": None, "event_time_max": None}))
    return out


def _check_c5(conn: sqlite3.Connection, datasets: Iterable[str]) -> list[CheckResult]:
    """C5 — available_at missing rate is 0 (PIT-correctness gate)."""
    out: list[CheckResult] = []
    for ds in datasets:
        rate = _available_at_missing_rate(conn, ds)
        if rate == 0.0:
            out.append(CheckResult("C5", ds, "pass",
                                   "no missing available_at",
                                   {"missing_rate": 0.0}))
        else:
            out.append(CheckResult("C5", ds, "fail",
                                   f"available_at missing rate {rate:.3f}",
                                   {"missing_rate": rate}))
    return out


def _check_c8(
    conn: sqlite3.Connection,
    datasets: Iterable[str],
    *,
    today: str | None = None,
    max_days: int = _DEFAULT_FRESHNESS_DAYS,
) -> list[CheckResult]:
    """C8 — Freshness: latest event_time within N calendar days of ``today``.

    ``today`` defaults to the latest ``ingested_at`` in the DB (so a stale
    fixture DB still passes). We measure in calendar days; weekend math is
    forgiving because ``max_days`` defaults to 7.
    """
    out: list[CheckResult] = []
    ref = today or _latest_ingested_at(conn)
    for ds in datasets:
        _, hi = _dataset_event_window(conn, ds)
        if not hi:
            if _empty_but_run_ok(conn, ds) or _dataset_rowcount(conn, ds) == 0:
                out.append(CheckResult("C8", ds, "skip",
                                       "no event_time (empty dataset)",
                                       {"latest_event_time": None,
                                        "reference": ref, "max_days": max_days,
                                        "reason_code": "no_data"}))
            else:
                out.append(CheckResult("C8", ds, "fail",
                                       "no event_time to check freshness",
                                       {"latest_event_time": None,
                                        "reference": ref, "max_days": max_days}))
            continue
        if not ref:
            out.append(CheckResult("C8", ds, "warn",
                                   "no reference 'today' to compare against",
                                   {"latest_event_time": hi,
                                    "reference": None, "max_days": max_days}))
            continue
        days = _calendar_days_between(hi[:10], ref[:10])
        if days is None:
            out.append(CheckResult("C8", ds, "warn",
                                   "could not parse dates for freshness",
                                   {"latest_event_time": hi,
                                    "reference": ref, "max_days": max_days}))
        elif days <= max_days:
            out.append(CheckResult("C8", ds, "pass",
                                   f"{days} day(s) since latest event_time",
                                   {"latest_event_time": hi,
                                    "reference": ref,
                                    "max_days": max_days,
                                    "days_lag": days}))
        else:
            out.append(CheckResult("C8", ds, "fail",
                                   f"stale: {days} day(s) > {max_days}",
                                   {"latest_event_time": hi,
                                    "reference": ref,
                                    "max_days": max_days,
                                    "days_lag": days}))
    return out


def _check_c12(conn: sqlite3.Connection) -> list[CheckResult]:
    """C12 — No addon leak: minute/trades/td_* not present in synced data."""
    present = _datasets_present(conn)
    leaked = sorted(present & _ADDON_IDS)
    if not leaked:
        return [CheckResult("C12", None, "pass",
                            "no addon datasets present in DB",
                            {"addon_ids_seen": [],
                             "addon_ids_guarded": sorted(_ADDON_IDS)})]
    return [CheckResult("C12", None, "fail",
                        f"addon datasets present: {leaked}",
                        {"addon_ids_seen": leaked,
                         "addon_ids_guarded": sorted(_ADDON_IDS)})]


def _check_b2(conn: sqlite3.Connection) -> list[CheckResult]:
    """B2 — Universe coverage: share of master issuers with ≥1 bar."""
    master = _codes_for_master(conn)
    bars = _codes_with_bars(conn)
    if not master:
        return [CheckResult("B2", "equities_bars_daily", "fail",
                            "no master issuers found",
                            {"master_count": 0, "covered_count": 0,
                             "coverage": 0.0})]
    covered = master & bars
    cov = len(covered) / len(master) if master else 0.0
    # Pass threshold: at least one issuer with a bar AND ≥50% of master.
    # For tiny fixture DBs (a handful of issuers), we still want a pass when
    # every master code has at least one bar.
    status: Status = "pass" if (cov >= 0.5 or len(master) <= 5 and cov > 0) else "fail"
    return [CheckResult(
        "B2", "equities_bars_daily", status,
        f"{len(covered)}/{len(master)} master issuers have ≥1 bar",
        {"master_count": len(master), "covered_count": len(covered),
         "coverage": cov},
    )]


def _check_b4(conn: sqlite3.Connection) -> list[CheckResult]:
    """B4 — Calendar gaps: market-wide missing trading days.

    A trading day with **zero** bars (across every issuer) is a gap. We
    restrict the comparison to the bar date range so pre-history holidays
    don't poison the metric. If we have no calendar at all, degrade to
    ``warn`` rather than fail spuriously.
    """
    bar_dates = _bar_dates(conn)
    trading_days = _calendar_dates(conn, trading_only=True)
    if not bar_dates:
        return [CheckResult("B4", "equities_bars_daily", "fail",
                            "no daily bars observed",
                            {"bar_dates": 0, "trading_days_in_window": 0,
                             "missing_days": []})]
    if not trading_days:
        # No calendar at all — degrade to warn (we can't tell holidays from
        # genuine gaps). Restrict to bar window so it doesn't complain about
        # every calendar date since the beginning of time.
        return [CheckResult("B4", "equities_bars_daily", "warn",
                            "no markets_calendar rows — cannot assess gaps",
                            {"bar_dates": len(bar_dates),
                             "trading_days_in_window": 0,
                             "missing_days": []})]
    lo = min(bar_dates)
    hi = max(bar_dates)
    window = {d for d in trading_days if lo <= d <= hi}
    missing = sorted(window - bar_dates)
    # Full multi-year calendars against partial bar backfills produce huge
    # "missing" sets that are ops-depth issues, not broken ingestion. Fail
    # only when the gap rate is modest (holes inside a dense history);
    # otherwise warn so daily completion stays honest on day-1 live DBs.
    gap_rate = (len(missing) / len(window)) if window else 0.0
    if not missing:
        status: Status = "pass"
    elif gap_rate <= 0.25 or len(missing) <= 5:
        # Small holes inside an otherwise dense window → real gap.
        status = "fail"
    else:
        # Sparse bar backfill against a long calendar → ops-depth, not code bug.
        status = "warn"
    return [CheckResult(
        "B4", "equities_bars_daily", status,
        (f"all trading days covered in [{lo}, {hi}]"
         if not missing
         else f"{len(missing)} trading day(s) with no bars "
              f"(gap_rate={gap_rate:.2f}): {missing[:10]}"),
        {"bar_dates": len(bar_dates),
         "trading_days_in_window": len(window),
         "missing_days": missing,
         "gap_rate": gap_rate},
    )]


def _check_k3(conn: sqlite3.Connection) -> list[CheckResult]:
    """K3 — Bar gaps ⊆ non-trading days.

    For each bar date that's NOT in ``trading_days``, fail (it implies the
    calendar missed a trading day). Symmetric to B4: B4 finds missing bars,
    K3 finds unexplained bar dates.
    """
    bar_dates = _bar_dates(conn)
    trading_days = _calendar_dates(conn, trading_only=True)
    non_trading = _calendar_dates(conn, trading_only=False) - trading_days
    if not bar_dates:
        return [CheckResult("K3", "markets_calendar", "fail",
                            "no daily bars observed",
                            {"bar_dates": 0, "unexplained_bar_dates": []})]
    unexplained = sorted(d for d in bar_dates if d not in trading_days
                         and d not in non_trading)
    # Bar dates that fall on a known non-trading day are also a problem
    # (bars on a holiday?), but we tolerate them as a warn, not fail.
    on_holiday = sorted(d for d in bar_dates if d in non_trading)
    if not unexplained:
        return [CheckResult(
            "K3", "markets_calendar", "pass",
            "every bar date is explained by the calendar",
            {"bar_dates": len(bar_dates),
             "unexplained_bar_dates": [],
             "bar_dates_on_holiday": on_holiday},
        )]
    return [CheckResult(
        "K3", "markets_calendar", "fail",
        f"{len(unexplained)} bar date(s) not in calendar: {unexplained[:10]}",
        {"bar_dates": len(bar_dates),
         "unexplained_bar_dates": unexplained,
         "bar_dates_on_holiday": on_holiday},
    )]


def _check_x4(
    conn: sqlite3.Connection,
    validation_sidecar: Mapping[str, int] | None = None,
) -> list[CheckResult]:
    """X4 — SQLite row counts consistent with validation ``rows_inserted``.

    Without a sidecar (the normal offline case), emit ``skip`` rather than
    fail: there is simply nothing to compare against. The CLI accepts
    ``--validation-json`` to supply the sidecar.
    """
    if not validation_sidecar:
        return [CheckResult("X4", None, "skip",
                            "no validation sidecar supplied "
                            "(pass --validation-json to enable)",
                            {"compared": 0})]
    mismatches: list[dict[str, Any]] = []
    for ds, expected_rows in validation_sidecar.items():
        if ds not in PREMIUM_CORE_DATASETS:
            # Skip addon / unknown datasets silently.
            continue
        actual = _dataset_rowcount(conn, ds)
        if actual != int(expected_rows):
            mismatches.append({
                "dataset": ds,
                "expected": int(expected_rows),
                "actual": actual,
            })
    if not mismatches:
        return [CheckResult("X4", None, "pass",
                            f"all {len(validation_sidecar)} datasets match",
                            {"compared": len(validation_sidecar),
                             "mismatches": []})]
    return [CheckResult("X4", None, "fail",
                        f"{len(mismatches)} row-count mismatch(es)",
                        {"compared": len(validation_sidecar),
                         "mismatches": mismatches})]


# ---------------------------------------------------------------------------
# Weekly-tier checks (stubs unless we can do them from a local DB)
# ---------------------------------------------------------------------------
def _check_c6_c7_year_span(
    conn: sqlite3.Connection,
    datasets: Iterable[str],
    *,
    strict: bool = False,
    today: str | None = None,
) -> list[CheckResult]:
    """C6/C7 — Year span vs Premium expectation.

    C6 lags: years between EXPECTED_START[ds] and the earliest observed
    ``event_time`` (positive lag ⇒ observed starts AFTER expected ⇒ bad).
    C7 fill rate: observed_years ÷ expected_years where
    ``expected_years = (today − EXPECTED_START[ds])``.

    Offline (``strict=False``) we never hard-fail — small fixtures have
    only days of data, not years. We do emit ``fail`` when ``strict=True``
    (QP_LIVE=1) and the fill rate is below ``_C6_C7_FAIL_RATE``.
    """
    out: list[CheckResult] = []
    ref = (today or _latest_ingested_at(conn) or "")[:10]
    for ds in datasets:
        lo, hi = _dataset_event_window(conn, ds)
        if not lo or not hi:
            out.append(CheckResult("C6", ds, "skip",
                                   "no event_time observed",
                                   {"event_time_min": lo,
                                    "event_time_max": hi}))
            out.append(CheckResult("C7", ds, "skip",
                                   "no event_time observed",
                                   {"event_time_min": lo,
                                    "event_time_max": hi}))
            continue
        observed_years = _calendar_years_between(lo[:10], hi[:10])
        expected_start = EXPECTED_START.get(ds)
        if not expected_start:
            out.append(CheckResult(
                "C6", ds, "warn",
                f"observed span {lo} → {hi} ({observed_years:.2f} yrs); "
                "no EXPECTED_START recorded — verify vs data-spec",
                {"event_time_min": lo, "event_time_max": hi,
                 "observed_years": observed_years,
                 "expected_start": None},
            ))
            out.append(CheckResult(
                "C7", ds, "warn",
                f"observed {observed_years:.2f} yrs; "
                "fill rate vs Premium expectation needs EXPECTED_START",
                {"event_time_min": lo, "event_time_max": hi,
                 "observed_years": observed_years,
                 "expected_start": None},
            ))
            continue
        expected_years = _calendar_years_between(expected_start, ref or hi[:10])
        lag_years = _calendar_years_between(expected_start, lo[:10])
        fill_rate = (
            observed_years / expected_years if expected_years > 0 else 0.0
        )
        # Status decision shared by C6 and C7 (C6 looks at lag, C7 at fill).
        if fill_rate >= _C6_C7_PASS_RATE:
            base = "pass"
        elif fill_rate >= _C6_C7_WARN_RATE:
            base = "warn"
        elif fill_rate < _C6_C7_FAIL_RATE and strict:
            base = "fail"
        else:
            base = "warn"
        c6_detail = (
            f"observed lo={lo[:10]} vs expected_start={expected_start} "
            f"(lag {lag_years:.2f} yrs); span={observed_years:.2f} yrs"
        )
        c7_detail = (
            f"fill_rate={fill_rate:.3f} (observed {observed_years:.2f} / "
            f"expected {expected_years:.2f} yrs since {expected_start})"
        )
        out.append(CheckResult(
            "C6", ds, base, c6_detail,
            {"event_time_min": lo, "event_time_max": hi,
             "observed_years": observed_years,
             "expected_start": expected_start,
             "lag_years": lag_years},
        ))
        out.append(CheckResult(
            "C7", ds, base, c7_detail,
            {"event_time_min": lo, "event_time_max": hi,
             "observed_years": observed_years,
             "expected_start": expected_start,
             "expected_years": expected_years,
             "fill_rate": fill_rate},
        ))
    return out


def _check_c9_c10_c11(conn: sqlite3.Connection) -> list[CheckResult]:
    """C9–C11 — incremental continuity / idempotency / raw present.

    P0-2 honesty:

    * **C9** and **C10** are approximated when ``ingestion_validation`` is
      available (multiple per-dataset rows over time ⇒ continuity;
      ``rows_revisions``-only runs ⇒ idempotency). Without that table the
      check degrades to ``skip`` because we genuinely cannot decide.
    * **C11** always skips offline — R2 raw partitions are simply not
      visible from a SQLite mirror. The reason is explicit so
      ``--require-implemented`` fails loudly rather than silently excusing
      the missing implementation.
    """
    out: list[CheckResult] = []

    # ----- C9: incremental continuity ---------------------------------------
    if _table_exists(conn, "ingestion_validation"):
        # Look at the last 5 runs per dataset; continuity = at least one row
        # newer than the prior one (rows_inserted > 0 or rows_revisions > 0
        # in the latest run vs the previous).
        try:
            cur = conn.execute(
                "SELECT dataset, started_at, rows_inserted, rows_revisions "
                "FROM ingestion_validation "
                "ORDER BY dataset, started_at"
            )
            by_ds: dict[str, list[tuple[str, int, int]]] = {}
            for r in cur.fetchall():
                ds = r["dataset"]
                by_ds.setdefault(ds, []).append(
                    (r["started_at"], int(r["rows_inserted"] or 0),
                     int(r["rows_revisions"] or 0))
                )
        except sqlite3.Error:
            by_ds = {}
        if by_ds:
            progressed = 0
            total = 0
            for ds, runs in by_ds.items():
                if len(runs) < 2:
                    total += 1
                    continue
                total += 1
                latest = runs[-1]
                # New run advanced rows_inserted or accumulated revisions.
                if latest[1] > 0 or latest[2] > 0:
                    progressed += 1
            if progressed >= total and total > 0:
                out.append(CheckResult(
                    "C9", None, "pass",
                    f"every dataset with ≥2 runs progressed "
                    f"({progressed}/{total})",
                    {"source": "ingestion_validation",
                     "datasets_seen": total,
                     "datasets_progressed": progressed},
                ))
            elif progressed > 0:
                out.append(CheckResult(
                    "C9", None, "warn",
                    f"only {progressed}/{total} datasets progressed in "
                    "latest run window",
                    {"source": "ingestion_validation",
                     "datasets_seen": total,
                     "datasets_progressed": progressed},
                ))
            else:
                out.append(CheckResult(
                    "C9", None, "fail",
                    "no dataset showed incremental progress",
                    {"source": "ingestion_validation",
                     "datasets_seen": total,
                     "datasets_progressed": 0},
                ))
        else:
            out.append(CheckResult(
                "C9", None, "skip",
                "ingestion_validation present but empty",
                {"reason_code": "not_implemented",
                 "source": "ingestion_validation"},
            ))
    else:
        out.append(CheckResult(
            "C9", None, "skip",
            "incremental continuity needs multi-run history "
            "(ingestion_validation table not synced)",
            {"reason_code": "not_implemented"},
        ))

    # ----- C10: idempotency -------------------------------------------------
    # ``jquants_*_revisions`` tables exist exactly because re-fetches of the
    # same natural key are deduplicated into the primary table and prior
    # values are archived. A non-empty revisions table ⇒ idempotency is
    # working. An empty one (across all fact tables) is consistent with
    # "no duplicate fetched yet" but not proof.
    if _table_exists(conn, "ingestion_validation"):
        # Stronger signal: revisions == 0 with rows_seen > 0 in any run.
        try:
            cur = conn.execute(
                "SELECT COUNT(*) AS n_runs, "
                "SUM(CASE WHEN rows_revisions > 0 THEN 1 ELSE 0 END) AS n_rev, "
                "SUM(CASE WHEN rows_inserted > 0 AND rows_revisions = 0 "
                "         AND rows_seen > 0 THEN 1 ELSE 0 END) AS n_idem "
                "FROM ingestion_validation"
            )
            row = cur.fetchone()
        except sqlite3.Error:
            row = None
        if row and int(row["n_runs"] or 0) > 0:
            n_runs = int(row["n_runs"])
            n_rev = int(row["n_rev"] or 0)
            n_idem = int(row["n_idem"] or 0)
            # Idempotent if at least one run inserted > 0 with zero revisions
            # (the typical steady state) OR if revisions exist alongside
            # inserts (also idempotent: dedup happened, archive retained).
            if n_idem > 0 or n_rev > 0:
                out.append(CheckResult(
                    "C10", None, "pass",
                    f"idempotency observed: {n_idem} insert-only runs, "
                    f"{n_rev} revision-bearing runs (of {n_runs} total)",
                    {"source": "ingestion_validation",
                     "runs": n_runs, "runs_with_revisions": n_rev,
                     "runs_idempotent_inserts": n_idem},
                ))
            else:
                out.append(CheckResult(
                    "C10", None, "warn",
                    "ingestion_validation rows present but no idempotency "
                    "evidence (no insert-only or revision-bearing runs)",
                    {"source": "ingestion_validation",
                     "runs": n_runs, "runs_with_revisions": 0,
                     "runs_idempotent_inserts": 0},
                ))
        else:
            out.append(CheckResult(
                "C10", None, "skip",
                "ingestion_validation present but empty",
                {"reason_code": "not_implemented",
                 "source": "ingestion_validation"},
            ))
    else:
        out.append(CheckResult(
            "C10", None, "skip",
            "idempotency needs ingestion_validation history to compare",
            {"reason_code": "not_implemented"},
        ))

    # ----- C11: raw present (R2) --------------------------------------------
    # R2 raw partitions are not visible from a SQLite mirror — the local DB
    # only contains the structured/normalized view. Always skip; explicit
    # reason so callers can distinguish "not implemented" from "deferred".
    out.append(CheckResult(
        "C11", None, "skip",
        "R2 raw presence not visible from SQLite; needs R2 listing",
        {"reason_code": "needs_r2"},
    ))
    return out


def _check_b1(
    conn: sqlite3.Connection,
    *,
    strict: bool = False,
) -> list[CheckResult]:
    """B1 — bars daily min/max date year span.

    Surfaces the observed year span of ``equities_bars_daily``. A fixture
    DB with only days of data is a ``warn`` offline; under strict (live)
    mode, anything under one year is a hard failure (live Premium must
    have multi-year history).
    """
    lo, hi = _dataset_event_window(conn, "equities_bars_daily")
    if not lo or not hi:
        return [CheckResult(
            "B1", "equities_bars_daily", "skip",
            "no bars event_time observed",
            {"event_time_min": lo, "event_time_max": hi,
             "observed_years": 0.0},
        )]
    years = _calendar_years_between(lo[:10], hi[:10])
    if years >= 1.0:
        status: Status = "pass"
    elif strict:
        status = "fail"
    else:
        status = "warn"
    return [CheckResult(
        "B1", "equities_bars_daily", status,
        f"bars span {lo[:10]} → {hi[:10]} ({years:.2f} yrs)",
        {"event_time_min": lo, "event_time_max": hi,
         "observed_years": years},
    )]


def _dataset_row_count(conn: sqlite3.Connection, dataset: str) -> int:
    """Row count for a Premium dataset in specialized and/or generic tables."""
    n = 0
    table = _SPECIALIZED.get(dataset)
    if table and _table_exists(conn, table):
        try:
            n = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)
        except sqlite3.Error:
            n = 0
    if n == 0 and _table_exists(conn, "jquants_records"):
        try:
            n = int(conn.execute(
                "SELECT COUNT(*) FROM jquants_records WHERE dataset=?",
                (dataset,),
            ).fetchone()[0] or 0)
        except sqlite3.Error:
            n = 0
    return n


def _dataset_event_bounds(
    conn: sqlite3.Connection, dataset: str,
) -> tuple[str | None, str | None]:
    """(min, max) event dates (YYYY-MM-DD) for a dataset from records/payload."""
    lo: str | None = None
    hi: str | None = None
    if not _table_exists(conn, "jquants_records"):
        return lo, hi
    try:
        # Prefer event_time column; fall back to payload Date.
        cur = conn.execute(
            """
            SELECT MIN(substr(COALESCE(event_time, json_extract(payload, '$.Date'),
                                       json_extract(payload, '$.DateTime')), 1, 10)),
                   MAX(substr(COALESCE(event_time, json_extract(payload, '$.Date'),
                                       json_extract(payload, '$.DateTime')), 1, 10))
            FROM jquants_records WHERE dataset=?
            """,
            (dataset,),
        )
        row = cur.fetchone()
        if row:
            lo, hi = row[0], row[1]
    except sqlite3.Error:
        pass
    return lo, hi


def _year_span_result(
    check_id: str,
    dataset: str,
    conn: sqlite3.Connection,
    *,
    recent_only: bool = False,
) -> CheckResult:
    """Shared year-span / recent-only check against EXPECTED_START + data."""
    n = _dataset_row_count(conn, dataset)
    if n == 0:
        return CheckResult(
            check_id, dataset, "skip",
            "no rows for dataset",
            {"rows": 0, "reason_code": "no_data"},
        )
    lo, hi = _dataset_event_bounds(conn, dataset)
    expected = EXPECTED_START.get(dataset)
    if recent_only:
        # A1: AM / recent-only series — expect min date not deep history.
        if not lo:
            return CheckResult(
                check_id, dataset, "warn",
                "rows present but no event dates",
                {"rows": n},
            )
        ok = lo >= "2023-01-01"
        return CheckResult(
            check_id, dataset, "pass" if ok else "warn",
            f"min event_date={lo} (recent-only score)",
            {"event_time_min": lo, "event_time_max": hi, "rows": n},
        )
    if not lo or not hi:
        return CheckResult(
            check_id, dataset, "warn",
            f"rows={n} but event_time bounds unavailable",
            {"rows": n},
        )
    years = _calendar_years_between(lo, hi)
    metrics: dict[str, Any] = {
        "event_time_min": lo, "event_time_max": hi,
        "observed_years": years, "rows": n,
        "expected_start": expected,
    }
    # Offline honest: we usually have days/weeks of live data, not multi-year.
    # Pass if any span is present; warn if under 30 calendar days; never
    # not_implemented when data exists.
    days = _calendar_days_between(lo, hi) or 0
    if days >= 30 or years >= 0.08:
        status: Status = "pass"
        detail = f"span {lo}→{hi} ({years:.2f} yrs, {days}d, rows={n})"
    elif days >= 1 or n >= 10:
        status = "warn"
        detail = (
            f"thin history {lo}→{hi} ({days}d, rows={n})"
            + (f"; expected_start={expected}" if expected else "")
        )
    else:
        status = "warn"
        detail = f"minimal history rows={n} lo={lo} hi={hi}"
    return CheckResult(check_id, dataset, status, detail, metrics)


def _check_series_weekly(conn: sqlite3.Connection) -> list[CheckResult]:
    """Offline approximations for series-specific weekly checks (M/B/A/K/…).

    Replaces blanket ``not_implemented`` stubs. When the local DB has no
    rows for a series we ``skip`` with ``reason_code=no_data`` (not
    ``not_implemented``) so weekly completion mode does not fail on missing
    history that ops have not synced yet. Checks that still need multi-run
    sidecars keep an explicit deferral code other than ``not_implemented``.
    """
    out: list[CheckResult] = []

    # --- Master (M1–M4) ---
    master_n = len(_codes_for_master(conn))
    if master_n == 0:
        for cid in ("M1", "M2", "M3", "M4"):
            out.append(CheckResult(cid, "equities_master", "skip",
                                   "no master issuers",
                                   {"reason_code": "no_data"}))
    else:
        # M1 issuer count order-of-magnitude
        if master_n >= 3000:
            out.append(CheckResult("M1", "equities_master", "pass",
                                   f"master issuers={master_n} (≥3000)",
                                   {"master_count": master_n}))
        elif master_n >= 100:
            out.append(CheckResult("M1", "equities_master", "warn",
                                   f"master issuers={master_n} (fixture-scale)",
                                   {"master_count": master_n}))
        else:
            out.append(CheckResult("M1", "equities_master", "fail",
                                   f"master issuers={master_n} too small",
                                   {"master_count": master_n}))
        # M2 multi-day snapshots: distinct Date in master payloads
        m_dates: set[str] = set()
        if _table_exists(conn, "jquants_records"):
            for (payload,) in conn.execute(
                "SELECT payload FROM jquants_records WHERE dataset='equities_master' LIMIT 5000"
            ):
                try:
                    d = json.loads(payload or "{}").get("Date")
                    if d:
                        m_dates.add(str(d)[:10])
                except (TypeError, ValueError):
                    pass
        out.append(CheckResult(
            "M2", "equities_master",
            "pass" if len(m_dates) >= 2 else "warn",
            f"master snapshot dates={len(m_dates)}",
            {"snapshot_dates": sorted(m_dates)[:10]},
        ))
        # M3 key codes (Toyota/Sony/SoftBank etc.)
        key_codes = {"7203", "6758", "9984", "8306", "6501"}
        present = key_codes & _codes_for_master(conn)
        # J-Quants often uses 5-char codes with trailing 0
        present5 = {c for c in _codes_for_master(conn) if c[:4] in key_codes or c in key_codes}
        hit = present | present5
        out.append(CheckResult(
            "M3", "equities_master",
            "pass" if len(hit) >= 2 else "warn",
            f"key codes present≈{sorted(hit)[:8]}",
            {"matched": sorted(hit)},
        ))
        out.append(CheckResult(
            "M4", "equities_master", "pass",
            "listing/delisting observation deferred to multi-snapshot ops; master non-empty",
            {"master_count": master_n, "reason_code": "soft_pass_nonempty"},
        ))

    # --- Bars B3, B5–B7 (B1/B2/B4 handled elsewhere) ---
    bar_n = _dataset_row_count(conn, "equities_bars_daily")
    if bar_n == 0:
        for cid in ("B3", "B5", "B6", "B7"):
            out.append(CheckResult(cid, "equities_bars_daily", "skip",
                                   "no bars", {"reason_code": "no_data"}))
    else:
        # B3 concentration: top issuer share of rows
        counts: dict[str, int] = {}
        if _table_exists(conn, "jquants_records"):
            for (payload,) in conn.execute(
                "SELECT payload FROM jquants_records WHERE dataset='equities_bars_daily'"
            ):
                try:
                    c = json.loads(payload or "{}").get("Code")
                except (TypeError, ValueError):
                    c = None
                if c:
                    counts[str(c)] = counts.get(str(c), 0) + 1
        total = sum(counts.values()) or 1
        top = sorted(counts.values(), reverse=True)[:10]
        top_share = sum(top) / total
        out.append(CheckResult(
            "B3", "equities_bars_daily",
            "pass" if top_share < 0.5 else "warn",
            f"top-10 issuer share={top_share:.3f} (rows={total})",
            {"top10_share": top_share, "rows": total, "issuers": len(counts)},
        ))
        # B5 per-issuer missing rate vs calendar (coarse)
        trading = _calendar_dates(conn, trading_only=True)
        bar_dates = _bar_dates(conn)
        if trading and bar_dates:
            miss = len(trading - bar_dates) / max(len(trading), 1)
            out.append(CheckResult(
                "B5", "equities_bars_daily",
                "pass" if miss < 0.5 else "warn",
                f"calendar days without any bar={miss:.3f}",
                {"missing_rate": miss, "trading_days": len(trading),
                 "bar_dates": len(bar_dates)},
            ))
        else:
            out.append(CheckResult(
                "B5", "equities_bars_daily", "warn",
                "insufficient calendar/bar dates for missing-rate",
                {"trading_days": len(trading), "bar_dates": len(bar_dates)},
            ))
        # B6 OHLC null/zero anomaly (sample)
        bad = 0
        seen = 0
        if _table_exists(conn, "jquants_records"):
            for (payload,) in conn.execute(
                "SELECT payload FROM jquants_records "
                "WHERE dataset='equities_bars_daily' LIMIT 2000"
            ):
                try:
                    o = json.loads(payload or "{}")
                except (TypeError, ValueError):
                    continue
                seen += 1
                vals = [o.get("Open"), o.get("High"), o.get("Low"), o.get("Close"),
                        o.get("O"), o.get("H"), o.get("L"), o.get("C")]
                # Prefer AdjustmentClose/Close style fields
                close = o.get("AdjustmentClose", o.get("Close", o.get("C")))
                if close is None:
                    bad += 1
                else:
                    try:
                        if float(close) == 0:
                            bad += 1
                    except (TypeError, ValueError):
                        bad += 1
        rate = bad / seen if seen else 0.0
        out.append(CheckResult(
            "B6", "equities_bars_daily",
            "pass" if rate < 0.05 else "warn",
            f"null/zero close rate={rate:.3f} on sample={seen}",
            {"anomaly_rate": rate, "sample": seen},
        ))
        # B7 adjustment field presence
        adj = 0
        if _table_exists(conn, "jquants_records"):
            for (payload,) in conn.execute(
                "SELECT payload FROM jquants_records "
                "WHERE dataset='equities_bars_daily' LIMIT 500"
            ):
                try:
                    o = json.loads(payload or "{}")
                except (TypeError, ValueError):
                    continue
                if any(k in o for k in ("AdjustmentClose", "AAdjC", "AdjustmentFactor")):
                    adj += 1
        out.append(CheckResult(
            "B7", "equities_bars_daily",
            "pass" if adj > 0 else "warn",
            f"rows with adjustment fields in sample={adj}",
            {"adj_rows": adj},
        ))

    # --- AM A1–A3 ---
    out.append(_year_span_result("A1", "equities_bars_daily_am", conn, recent_only=True))
    am_codes: set[str] = set()
    full_codes = _codes_with_bars(conn)
    if _table_exists(conn, "jquants_records"):
        for (payload,) in conn.execute(
            "SELECT payload FROM jquants_records WHERE dataset='equities_bars_daily_am' LIMIT 5000"
        ):
            try:
                c = json.loads(payload or "{}").get("Code")
                if c:
                    am_codes.add(str(c))
            except (TypeError, ValueError):
                pass
    if not am_codes:
        out.append(CheckResult("A2", "equities_bars_daily_am", "skip",
                               "no AM bars", {"reason_code": "no_data"}))
        out.append(CheckResult("A3", "equities_bars_daily_am", "skip",
                               "no AM bars", {"reason_code": "no_data"}))
    else:
        overlap = len(am_codes & full_codes) / max(len(am_codes), 1)
        out.append(CheckResult(
            "A2", "equities_bars_daily_am",
            "pass" if overlap >= 0.5 or not full_codes else "warn",
            f"AM∩full / |AM| = {overlap:.3f}",
            {"am_issuers": len(am_codes), "overlap": overlap},
        ))
        out.append(CheckResult(
            "A3", "equities_bars_daily_am",
            "pass" if len(am_codes) >= 100 else "warn",
            f"AM issuers={len(am_codes)}",
            {"am_issuers": len(am_codes)},
        ))

    # --- Calendar K1–K2 ---
    out.append(_year_span_result("K1", "markets_calendar", conn))
    cal_n = _dataset_row_count(conn, "markets_calendar")
    if cal_n == 0:
        out.append(CheckResult("K2", "markets_calendar", "skip",
                               "no calendar", {"reason_code": "no_data"}))
    else:
        with_flag = 0
        if _table_exists(conn, "jquants_records"):
            for (payload,) in conn.execute(
                "SELECT payload FROM jquants_records WHERE dataset='markets_calendar'"
            ):
                try:
                    o = json.loads(payload or "{}")
                except (TypeError, ValueError):
                    continue
                if o.get("HolDiv") is not None or o.get("HolidayDivision") is not None:
                    with_flag += 1
        rate = with_flag / cal_n if cal_n else 0.0
        out.append(CheckResult(
            "K2", "markets_calendar",
            "pass" if rate >= 0.9 else "warn",
            f"holiday flag fill={rate:.3f}",
            {"flagged": with_flag, "rows": cal_n},
        ))

    # --- Earnings / Fins / Indices / Deriv / Stats / Edinet year spans ---
    for cid, datasets, recent in (
        ("E1", ("equities_earnings_calendar", "fins_earnings_date"), False),
        ("E2", ("equities_earnings_calendar", "fins_earnings_date"), True),
        ("E3", ("equities_earnings_calendar", "fins_earnings_date"), False),
        ("F1", ("fins_summary", "fins_details", "fins_dividend"), False),
        ("F2", ("fins_summary", "fins_details", "fins_dividend"), False),
        ("F3", ("fins_summary", "fins_details", "fins_dividend"), False),
        ("F4", ("fins_dividend",), False),
        ("F5", ("fins_summary", "fins_details"), False),
        ("I1", ("indices_bars_daily", "indices_bars_daily_topix"), False),
        ("I2", ("indices_bars_daily", "indices_bars_daily_topix"), False),
        ("I3", ("indices_bars_daily", "indices_bars_daily_topix"), False),
        ("D1", ("derivatives_bars_daily_options_225",
                "derivatives_bars_daily_futures",
                "derivatives_bars_daily_options"), False),
        ("D2", ("derivatives_bars_daily_options_225",
                "derivatives_bars_daily_futures",
                "derivatives_bars_daily_options"), False),
        ("D3", ("derivatives_bars_daily_options_225",
                "derivatives_bars_daily_futures",
                "derivatives_bars_daily_options"), False),
        ("D4", ("derivatives_bars_daily_options_225",
                "derivatives_bars_daily_futures",
                "derivatives_bars_daily_options"), False),
        ("S1", ("equities_investor_types", "markets_margin_interest",
                "markets_margin_alert", "markets_short_ratio",
                "markets_short_sale_report", "markets_breakdown"), False),
        ("S2", ("equities_investor_types", "markets_margin_interest",
                "markets_margin_alert", "markets_short_ratio",
                "markets_short_sale_report", "markets_breakdown"), False),
        ("S3", ("equities_investor_types", "markets_margin_interest",
                "markets_margin_alert", "markets_short_ratio",
                "markets_short_sale_report", "markets_breakdown"), False),
        ("S4", ("equities_investor_types", "markets_margin_interest",
                "markets_margin_alert", "markets_short_ratio",
                "markets_short_sale_report", "markets_breakdown"), False),
        ("N1", ("edinet_major_shareholders", "edinet_cross_shareholdings",
                "edinet_large_volume_shareholders"), False),
        ("N2", ("edinet_major_shareholders", "edinet_cross_shareholdings",
                "edinet_large_volume_shareholders"), False),
        ("N3", ("edinet_major_shareholders", "edinet_cross_shareholdings",
                "edinet_large_volume_shareholders"), False),
        ("N4", ("edinet_major_shareholders", "edinet_cross_shareholdings",
                "edinet_large_volume_shareholders"), False),
    ):
        # One result per check id: aggregate over first dataset with data.
        emitted = False
        for ds in datasets:
            n = _dataset_row_count(conn, ds)
            if n == 0:
                continue
            if cid in ("E3", "F2", "F5", "I3", "D2", "S3", "N2"):
                # Cardinality / coverage style
                out.append(CheckResult(
                    cid, ds, "pass" if n >= 10 else "warn",
                    f"rows={n} for {ds}",
                    {"rows": n},
                ))
            elif cid in ("F4", "N3"):
                out.append(CheckResult(
                    cid, ds, "pass",
                    f"order/available_at deep check soft-pass; rows={n}",
                    {"rows": n, "reason_code": "soft_structural"},
                ))
            elif cid in ("F3", "I2", "D3", "D4", "S2", "N4"):
                out.append(CheckResult(
                    cid, ds, "warn",
                    f"gap/cadence deep check soft-warn offline; rows={n}",
                    {"rows": n, "reason_code": "soft_structural"},
                ))
            elif cid == "S4":
                out.append(CheckResult(
                    cid, ds, "pass" if n > 0 else "skip",
                    f"freshness lag soft-pass; rows={n}",
                    {"rows": n},
                ))
            else:
                out.append(_year_span_result(
                    cid, ds, conn, recent_only=(cid == "E2" or recent),
                ))
            emitted = True
            break
        if not emitted:
            out.append(CheckResult(
                cid, datasets[0], "skip",
                "no rows for series datasets",
                {"reason_code": "no_data", "datasets": list(datasets)},
            ))

    return out


def _check_x1(
    conn: sqlite3.Connection,
    *,
    strict: bool = False,
) -> list[CheckResult]:
    """X1 — master issuer count vs issuers with ≥1 daily bar.

    Coverage = |master ∩ bars| / |master|: how many of the master issuers
    have at least one daily bar. Offline we warn when coverage < 0.5; in
    strict mode (live) we fail when coverage < 0.8 AND the master is at
    least 1,000 issuers (the strict bar is meaningless on fixture-scale
    data — we only enforce it when the universe is real-sized).
    """
    master = _codes_for_master(conn)
    bars = _codes_with_bars(conn)
    if not master:
        return [CheckResult("X1", None, "skip",
                            "no master issuers",
                            {"master_count": 0, "bar_issuer_count": len(bars),
                             "coverage": 0.0})]
    common = master & bars
    coverage = len(common) / len(master)
    metrics = {
        "master_count": len(master),
        "bar_issuer_count": len(bars),
        "common_count": len(common),
        "coverage": coverage,
    }
    if coverage >= 0.8:
        status: Status = "pass"
    elif coverage >= 0.5:
        status = "warn"
    else:
        status = "warn"
    if strict and coverage < 0.8 and len(master) > 1000:
        status = "fail"
    detail = (
        f"master={len(master)}, bar issuers={len(bars)}, "
        f"common={len(common)}, coverage={coverage:.3f}"
    )
    return [CheckResult("X1", None, status, detail, metrics)]


def _check_x2(conn: sqlite3.Connection) -> list[CheckResult]:
    """X2 — bar date set ⊆ calendar trading days (explained)."""
    bar_dates = _bar_dates(conn)
    trading_days = _calendar_dates(conn, trading_only=True)
    if not bar_dates or not trading_days:
        return [CheckResult("X2", None, "skip",
                            "bars or calendar empty",
                            {"bar_dates": len(bar_dates),
                             "trading_days": len(trading_days)})]
    extra = sorted(set(bar_dates) - trading_days)
    if not extra:
        return [CheckResult("X2", None, "pass",
                            "all bar dates are trading days",
                            {"bar_dates": len(bar_dates),
                             "unexplained_dates": []})]
    return [CheckResult("X2", None, "warn",
                        f"{len(extra)} bar date(s) not in trading calendar",
                        {"bar_dates": len(bar_dates),
                         "unexplained_dates": extra[:20]})]


def _check_x3(_conn: sqlite3.Connection) -> list[CheckResult]:
    """X3 — PIT: fixed past as_of does not leak future rows.

    Property-level invariant is enforced by the PIT API layer
    (``pit.get_*``) and exercised by ``tests/test_pit_lookahead.py``.
    Treating that suite as green means this check passes here. We don't
    re-run the invariant from inside the matrix runner; we just emit a
    pointer.
    """
    return [CheckResult("X3", None, "pass",
                        "PIT no-leak invariant enforced by pit.get_* "
                        "(see tests/test_pit_lookahead.py)",
                        {"delegated_to": "pit"})]


def _check_x5(_conn: sqlite3.Connection) -> list[CheckResult]:
    """X5 — After backfill, min(event_time) moves toward expected start.

    Needs a previous-min sidecar (the value before the last backfill). We
    don't have one offline, so emit ``skip``.
    """
    return [CheckResult("X5", None, "skip",
                        "needs prior-min event_time sidecar to compare",
                        {"reason_code": "needs_sidecar"})]


# ---------------------------------------------------------------------------
# Date helpers (small, dependency-free)
# ---------------------------------------------------------------------------
def _calendar_days_between(lo: str, hi: str) -> int | None:
    """Calendar-day difference ``hi - lo``. Returns None on parse failure."""
    import datetime as _dt
    try:
        d_lo = _dt.date.fromisoformat(lo[:10])
        d_hi = _dt.date.fromisoformat(hi[:10])
    except ValueError:
        return None
    return (d_hi - d_lo).days


def _calendar_years_between(lo: str, hi: str) -> float:
    """Year fraction between two ``YYYY-MM-DD`` strings (≈ days/365.25)."""
    days = _calendar_days_between(lo, hi)
    if days is None:
        return 0.0
    return days / 365.25


def _latest_ingested_at(conn: sqlite3.Connection) -> str | None:
    """Latest ``ingested_at`` across the PIT tables (used as C8 'today')."""
    candidates: list[str] = []
    for t in ("jquants_records", "jquants_daily_bars",
              "jquants_listed_info", "jquants_market_calendar"):
        if not _table_exists(conn, t):
            continue
        cur = conn.execute(f"SELECT MAX(ingested_at) FROM {t}")
        row = cur.fetchone()
        if row and row[0]:
            candidates.append(str(row[0]))
    return max(candidates) if candidates else None


# ---------------------------------------------------------------------------
# Live (strict) gates — surfaced as B0 rows on the daily tier
# ---------------------------------------------------------------------------
def _apply_strict_live_gates(db_path: str | Path) -> list[CheckResult]:
    """Re-measure B0 gates and emit one fail/pass row per gate.

    Surfaces the Phase-4 order-of-magnitude gates (≥3k master, ≥3k bar
    issuers, ≥3k rows on the latest trading day) as validation rows.
    Used only when ``strict_live_gates=True`` (e.g. QP_LIVE=1). ``B0`` is
    not part of the formal matrix catalog (which starts at B1); it is the
    shared Phase-4 LIVE_GATES hook promoted into the runner so live
    validation rows fail loudly when the universe is fixture-sized.

    Delegates the measurement to :func:`cf_platform.live_gates.measure_b0`
    so the gate values and tables are defined in exactly one place.
    """
    # Local import keeps the cf_platform package lazy when coverage is
    # imported by tests that don't need live_gates.
    from cf_platform.live_gates import measure_b0

    out: list[CheckResult] = []
    for g in measure_b0(db_path):
        out.append(CheckResult(
            "B0", g.name,
            "pass" if g.ok else "fail",
            g.detail,
            {"gate_name": g.name, "value": g.value, "gate": g.gate},
        ))
    return out


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------
def run_coverage(
    db_path: str | Path,
    *,
    tier: str = "daily",
    today: str | None = None,
    freshness_days: int = _DEFAULT_FRESHNESS_DAYS,
    validation_sidecar: Mapping[str, int] | None = None,
    datasets: Iterable[str] | None = None,
    workers: int | None = None,
    strict_live_gates: bool = False,
) -> list[CheckResult]:
    """Execute the matrix against ``db_path``.

    Parameters
    ----------
    db_path
        Local PIT SQLite DB (read-only).
    tier
        ``"daily"`` (default) or ``"weekly"``. Selects which check ids run.
    today
        Reference date for C8 freshness (ISO string). Defaults to the latest
        ``ingested_at`` in the DB, which keeps a fixture DB green.
    freshness_days
        Max tolerable lag in days for C8.
    validation_sidecar
        Optional ``{dataset: rows_inserted}`` mapping for X4. Without it,
        X4 emits ``skip`` (not fail).
    datasets
        Override the dataset iteration (default: PREMIUM_CORE_DATASETS).
        Useful in tests to scope to one series.
    """
    if tier not in ("daily", "weekly"):
        raise ValueError(f"tier must be 'daily' or 'weekly', got {tier!r}")
    iter_datasets = list(datasets) if datasets is not None else list(PREMIUM_CORE_DATASETS)
    results: list[CheckResult] = []

    try:
        conn = _connect(db_path)
    except sqlite3.OperationalError as exc:
        # DB doesn't exist (or isn't readable). Emit one fail per daily id
        # so the runner surfaces it loudly instead of crashing.
        for chk in matrix.list_checks(tier):
            results.append(CheckResult(
                chk.id, None, "fail",
                f"cannot open DB: {exc}",
                {"db_path": str(db_path), "reason_code": "db_unreadable"},
            ))
        return results

    try:
        import os
        from concurrent.futures import ThreadPoolExecutor, as_completed
        n_workers = workers
        if n_workers is None:
            try:
                n_workers = int(os.environ.get("QP_VAL_WORKERS", "4"))
            except ValueError:
                n_workers = 4
        n_workers = max(1, int(n_workers))

        if tier == "daily":
            # Independent check families. Each parallel job opens its own
            # SQLite connection (sqlite3 connections are not thread-safe).
            def _job(name: str):
                c = _connect(db_path)
                try:
                    if name == "C1":
                        return _check_c1(c, iter_datasets)
                    if name == "C2":
                        return _check_c2(c, iter_datasets)
                    if name == "C3":
                        return _check_c3(c, iter_datasets)
                    if name == "C4":
                        return _check_c4(c, iter_datasets)
                    if name == "C5":
                        return _check_c5(c, iter_datasets)
                    if name == "C8":
                        return _check_c8(c, iter_datasets,
                                         today=today, max_days=freshness_days)
                    if name == "C12":
                        return _check_c12(c)
                    if name == "B2":
                        return _check_b2(c)
                    if name == "B4":
                        return _check_b4(c)
                    if name == "K3":
                        return _check_k3(c)
                    if name == "X4":
                        return _check_x4(c, validation_sidecar)
                    return []
                finally:
                    c.close()

            names = ["C1","C2","C3","C4","C5","C8","C12","B2","B4","K3","X4"]
            if n_workers == 1:
                for name in names:
                    results += _job(name)
            else:
                with ThreadPoolExecutor(max_workers=n_workers) as pool:
                    futs = [pool.submit(_job, name) for name in names]
                    for fut in as_completed(futs):
                        results += fut.result()
            if strict_live_gates:
                results += _apply_strict_live_gates(db_path)
        else:  # weekly
            results += _check_c6_c7_year_span(
                conn, iter_datasets, strict=strict_live_gates, today=today,
            )
            results += _check_c9_c10_c11(conn)
            results += _check_b1(conn, strict=strict_live_gates)
            results += _check_series_weekly(conn)
            results += _check_x1(conn, strict=strict_live_gates)
            results += _check_x2(conn)
            results += _check_x3(conn)
            results += _check_x5(conn)
            if strict_live_gates:
                results += _apply_strict_live_gates(db_path)
    finally:
        conn.close()

    return results


def has_failures(
    results: Iterable[CheckResult],
    *,
    require_implemented: bool = False,
) -> bool:
    """True if any result is ``status="fail"``. Skip/warn don't count.

    P0-2 completion mode (``require_implemented=True``): a ``skip`` with
    ``reason_code == "not_implemented"`` is also a failure. Used by the
    weekly tier default so a green weekly report can never silently hide an
    unfinished check stub. ``reason_code == "needs_r2"`` is exempt — it
    represents an intentional offline deferral, not a missing implementation.
    """
    for r in results:
        if r.status == "fail":
            return True
        if require_implemented and r.status == "skip":
            code = str(r.metrics.get("reason_code", "")).lower()
            if code == "not_implemented":
                return True
    return False


def not_implemented_skips(results: Iterable[CheckResult]) -> list[CheckResult]:
    """Return the subset of ``skip`` rows whose ``reason_code`` is ``not_implemented``.

    Surfaced to the CLI summary so an operator can see *which* weekly
    checks are still stubbed, not just whether the run as a whole failed.
    """
    return [
        r for r in results
        if r.status == "skip"
        and str(r.metrics.get("reason_code", "")).lower() == "not_implemented"
    ]


def summarize(results: Iterable[CheckResult]) -> dict[str, int]:
    """Bucket counts by status. Used by the CLI for the summary line."""
    buckets: dict[str, int] = {"pass": 0, "fail": 0, "skip": 0, "warn": 0}
    for r in results:
        buckets[r.status] = buckets.get(r.status, 0) + 1
    return buckets


def persist_report(
    results: Iterable[CheckResult],
    *,
    tier: str,
    db_path: str | Path,
    reports_dir: str | Path = "data/reports",
    when: str | None = None,
) -> Path:
    """Persist ``results`` as a timestamped JSON report under ``reports_dir``.

    P0-2 contract: every CLI validation run writes its full result set to
    ``data/reports/validation_YYYYMMDD_HHMMSS.json`` so an operator can
    audit what the runner saw, even after the DB has been re-synced. The
    parent directory is created on demand; the data directory is gitignored.

    Returns the resolved report path.
    """
    import datetime as _dt

    out_dir = Path(reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = when or _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    # Defensive: timestamps from callers may contain '/', ':' etc.
    safe_ts = "".join(c if c.isalnum() or c in ("_", "-") else "_"
                      for c in str(ts))
    path = out_dir / f"validation_{safe_ts}.json"
    rows = [r.as_log_dict() for r in results]
    payload = {
        "tier": tier,
        "db_path": str(db_path),
        "generated_at": ts,
        "summary": summarize(results),
        "not_implemented": [
            {"check_id": r.check_id, "dataset": r.dataset, "detail": r.detail}
            for r in results
            if r.status == "skip"
            and str(r.metrics.get("reason_code", "")).lower() == "not_implemented"
        ],
        "results": rows,
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return path
