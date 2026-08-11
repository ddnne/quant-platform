#!/usr/bin/env python3
"""Phase 4 — feature registry + backtest accept report.

Generates a JSON report that proves the Phase 4 closed loop is sound:

* **F1 — Registry integrity**: every built-in feature carries the required
  P0-5 metadata (``intended_role``, ``status``) and the runtime can resolve
  each id.
* **F2 — Feature hit rates**: across a multi-code, multi-day fixture (or a
  real DB when ``QP_LIVE=1``), what fraction of ``(code, as_of)`` decisions
  produce a non-``None`` feature value for each of
  ``return_1d`` / ``momentum_n`` / ``volatility_n``?
* **F3 — Feature-using backtest**: ``run_backtest`` on a strategy that
  consumes ``return_1d`` at each decision instant. Offline: ~20+ day
  window on a fixture DB; live: 50+ trading days on the real DB.
* **F4 — B0 strict (live only)**: live runs enforce ``LIVE_GATES`` so a
  fixture-scale DB cannot be confused with a real one.

Output: ``data/reports/phase4_accept_YYYYMMDD_HHMMSS.json``. The directory
is gitignored; only ``.gitkeep`` is committed.

Examples
--------
  # Offline (default): fixture DB, ~25-day feature backtest.
  python3 scripts/run_phase4_accept.py

  # Live: real DB, sample 50 codes, 50-day minimum window.
  QP_LIVE=1 QP_DB=data/structured/ingestion.sqlite \\
      python3 scripts/run_phase4_accept.py

  # Custom output path (overrides default under data/reports/).
  python3 scripts/run_phase4_accept.py --out /tmp/phase4.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import features  # noqa: E402
import pit  # noqa: E402
from core import run_backtest, standard_cost  # noqa: E402
from core.strategy_protocol import BarContext, OrderIntent  # noqa: E402

FEATURE_IDS = ("return_1d", "momentum_n", "volatility_n")


# ---------------------------------------------------------------------------
# Offline fixture builder — mirrors tests/_coreseed.py but is self-contained
# so the script works without the test harness on sys.path.
# ---------------------------------------------------------------------------
def _weekdays(start: date, n: int) -> list[str]:
    """First ``n`` weekday dates from ``start`` (YYYY-MM-DD strings)."""
    out: list[str] = []
    cur = start
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _build_offline_db(path: Path) -> tuple[Path, list[str], list[str]]:
    """Seed a fixture DB with multi-code multi-day bars; return (db, days, codes)."""
    from storage.sqlite_store import SqliteStore

    days = _weekdays(date(2025, 4, 1), 30)
    codes = ["1332", "8697", "7203", "6758", "9984", "8306"]

    def close_iso(d: str) -> str:
        return f"{d}T15:30:00+09:00"

    cal = [
        {
            "source": "jquants",
            "date": d,
            "event_time": f"{d}T09:00:00+09:00",
            "available_at": "2025-01-01T00:00:00+09:00",
            "ingested_at": "2025-01-01T00:00:00+09:00",
            "holiday_division": "1",
        }
        for d in days
    ]
    master = [
        {
            "source": "jquants",
            "code": c,
            "snapshot_date": days[0],
            "event_time": f"{days[0]}T09:00:00+09:00",
            "available_at": "2025-01-01T00:00:00+09:00",
            "ingested_at": "2025-01-01T00:00:00+09:00",
            "company_name": f"Co-{c}",
            "sector_17_code": "1",
            "market_code": "1",
        }
        for c in codes
    ]
    bars: list[dict] = []
    for ci, c in enumerate(codes):
        for di, d in enumerate(days):
            close = 100.0 + ci * 10.0 + di * 0.5
            bars.append({
                "source": "jquants",
                "code": c,
                "date": d,
                "event_time": close_iso(d),
                "available_at": close_iso(d),
                "ingested_at": close_iso(d),
                "open": close, "high": close, "low": close, "close": close,
                "volume": 1000.0,
            })

    store = SqliteStore(path)
    store.upsert("jquants_market_calendar", cal)
    store.upsert("jquants_listed_info", master)
    store.upsert("jquants_daily_bars", bars)
    store.close()
    return path, days, codes


# ---------------------------------------------------------------------------
# Feature-driven strategy for the accept backtest
# ---------------------------------------------------------------------------
class MomentumTopPickStrategy:
    """At each decision bar, pick the universe code with the highest ``return_1d``.

    The strategy demonstrates the F1–F3 contract end-to-end:

    * it uses :func:`features.compute` (PIT-scoped, ``as_of``-required);
    * it captures the DB path at construction so it never reaches around PIT;
    * it produces a deterministic, reproducible decision stream.

    On the first bar where any code has a non-``None`` return, it goes 100%
    into the top pick. Thereafter it rebalances to the latest top pick each
    day so the backtest exercises the engine's delta-trading path.
    """

    strategy_id = "momentum_top_pick_v1"
    params: dict = {"feature": "return_1d", "rebalance": True}

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
        best_code: str | None = None
        best_ret = float("-inf")
        for code in ctx.universe:
            out = features.compute(
                "return_1d",
                as_of=ctx.as_of,
                code=code,
                db_path=self._db_path,
            )
            if out.value is None:
                continue
            if out.value > best_ret:
                best_ret = out.value
                best_code = code
        if best_code is None:
            return []
        return [OrderIntent(code=best_code, target_weight=1.0)]


# ---------------------------------------------------------------------------
# Accept checks
# ---------------------------------------------------------------------------
def _registry_integrity_section() -> dict[str, Any]:
    """F1 — every built-in feature carries required P0-5 metadata."""
    feats = features.list_features()
    by_id = {f.id: f for f in feats}
    required_ids = set(FEATURE_IDS)
    missing = sorted(required_ids - set(by_id))
    rows: list[dict[str, Any]] = []
    role_violations: list[dict[str, Any]] = []
    status_violations: list[dict[str, Any]] = []
    for fid in FEATURE_IDS:
        if fid not in by_id:
            continue
        f = by_id[fid]
        rows.append({
            "id": f.id,
            "version": str(f.version),
            "intended_role": f.intended_role,
            "status": f.status,
            "tags": list(f.tags),
            "description": f.description,
        })
        if f.intended_role not in ("signal", "state", "structural", "utility"):
            role_violations.append({"id": f.id, "intended_role": f.intended_role})
        if f.status not in ("candidate", "shadow", "approved", "retired"):
            status_violations.append({"id": f.id, "status": f.status})
    ok = (
        not missing
        and not role_violations
        and not status_violations
    )
    return {
        "ok": ok,
        "features": rows,
        "missing_required_ids": missing,
        "role_violations": role_violations,
        "status_violations": status_violations,
    }


def _feature_hit_rates_section(
    db_path: Path, codes: list[str], as_ofs: list[str]
) -> dict[str, Any]:
    """F2 — per-feature hit rate over (code, as_of) grid.

    ``hit_rate = (#calls with value not None) / (#calls total)``. Per-feature
    diagnostics include the average ``rows_seen`` so an operator can tell a
    genuine miss (short history) from a compute bug.
    """
    out: dict[str, Any] = {}
    for fid in FEATURE_IDS:
        values: list[Any] = []
        non_none = 0
        rows_seen_total = 0
        for code in codes:
            for as_of in as_ofs:
                try:
                    r = features.compute(
                        fid, as_of=as_of, code=code, db_path=db_path
                    )
                except Exception as exc:  # noqa: BLE001
                    values.append({"code": code, "as_of": as_of,
                                   "error": f"{type(exc).__name__}: {exc}"})
                    continue
                rows_seen_total += int(r.metadata.get("rows_seen", 0) or 0)
                if r.value is not None:
                    non_none += 1
                values.append({"code": code, "as_of": as_of,
                               "value": r.value})
        total = len(codes) * len(as_ofs)
        hit_rate = (non_none / total) if total else 0.0
        out[fid] = {
            "hit_rate": hit_rate,
            "non_none": non_none,
            "total": total,
            "avg_rows_seen": (rows_seen_total / total) if total else 0.0,
        }
    return out


def _backtest_section(
    db_path: Path,
    codes: list[str],
    days: list[str],
    *,
    min_trading_days: int,
    live: bool,
) -> dict[str, Any]:
    """F3 — feature-using backtest exercising the engine end-to-end."""
    strat = MomentumTopPickStrategy(db_path)
    start = days[0]
    end = days[-1]
    res = run_backtest(
        strat,
        start, end,
        db_path=db_path,
        universe=tuple(codes),
        cost_model=standard_cost(),
    )
    metrics = dict(res.metrics) if res.metrics else {}
    md = dict(res.metadata) if res.metadata else {}
    return {
        "ok": int(metrics.get("num_trading_days", 0)) >= min_trading_days,
        "strategy_id": md.get("strategy_id"),
        "start": start,
        "end": end,
        "trading_days": int(md.get("trading_days", 0)),
        "num_trading_days": int(metrics.get("num_trading_days", 0)),
        "min_required": min_trading_days,
        "n_trades": len(res.trades),
        "n_equity_curve_points": len(res.equity_curve),
        "universe_size": len(codes),
        "core_engine_version": md.get("core_engine_version"),
        "execution_mode": md.get("execution_mode"),
        "cost_model": md.get("cost_model"),
        "live": live,
        "total_return": metrics.get("total_return"),
        "max_drawdown": metrics.get("max_drawdown"),
    }


def _b0_section(db_path: Path) -> dict[str, Any]:
    """F4 — B0 strict gates. Only emitted when QP_LIVE=1."""
    from cf_platform.live_gates import b0_pass

    ok, results = b0_pass(db_path, strict=True)
    return {
        "ok": ok,
        "gates": [r.as_dict() for r in results],
    }


# ---------------------------------------------------------------------------
# Live helpers
# ---------------------------------------------------------------------------
def _table_exists(conn: "sqlite3.Connection", name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _bar_dates_from_records(conn: "sqlite3.Connection", *, limit: int = 100) -> list[str]:
    """Distinct equities_bars_daily dates from generic ``jquants_records``."""
    try:
        cur = conn.execute(
            """
            SELECT DISTINCT json_extract(payload, '$.Date') AS d
            FROM jquants_records
            WHERE dataset = 'equities_bars_daily'
              AND json_extract(payload, '$.Date') IS NOT NULL
            ORDER BY d DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [str(r[0])[:10] for r in cur.fetchall() if r[0]]
    except sqlite3.Error:
        return []


def _bar_codes_from_records(conn: "sqlite3.Connection", *, target: int = 50) -> list[str]:
    """Sample codes from equities_bars_daily in ``jquants_records``."""
    try:
        cur = conn.execute(
            """
            SELECT DISTINCT json_extract(payload, '$.Code') AS c
            FROM jquants_records
            WHERE dataset = 'equities_bars_daily'
              AND json_extract(payload, '$.Code') IS NOT NULL
            ORDER BY c
            LIMIT ?
            """,
            (target,),
        )
        return [str(r[0]) for r in cur.fetchall() if r[0]]
    except sqlite3.Error:
        return []


def _sample_live_codes(db_path: Path, *, target: int = 50) -> list[str]:
    """Sample up to ``target`` codes that have a daily bar in the DB.

    Prefer specialized ``jquants_daily_bars``; fall back to ``jquants_records``
    (Premium closed-loop stores structured rows generically).
    """
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        codes: list[str] = []
        if _table_exists(conn, "jquants_daily_bars"):
            try:
                cur = conn.execute(
                    "SELECT DISTINCT code FROM jquants_daily_bars "
                    "ORDER BY code LIMIT ?", (target,),
                )
                codes = [str(r[0]) for r in cur.fetchall() if r[0]]
            except sqlite3.Error:
                codes = []
        if not codes and _table_exists(conn, "jquants_records"):
            codes = _bar_codes_from_records(conn, target=target)
        conn.close()
    except sqlite3.Error:
        codes = []
    return codes


def _live_recent_as_ofs(db_path: Path, *, count: int = 5) -> list[str]:
    """Up to ``count`` recent session closes as ``as_of`` strings."""
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        dates: list[str] = []
        if _table_exists(conn, "jquants_daily_bars"):
            try:
                cur = conn.execute("SELECT MAX(date) FROM jquants_daily_bars")
                last = cur.fetchone()[0]
                if last:
                    cur = conn.execute(
                        "SELECT DISTINCT date FROM jquants_daily_bars "
                        "WHERE date <= ? ORDER BY date DESC LIMIT ?",
                        (last, count),
                    )
                    dates = [str(r[0])[:10] for r in cur.fetchall() if r[0]]
            except sqlite3.Error:
                dates = []
        if len(dates) < 2 and _table_exists(conn, "jquants_records"):
            dates = _bar_dates_from_records(conn, limit=count)
        conn.close()
    except sqlite3.Error:
        dates = []
    return [f"{d}T15:30:00+09:00" for d in dates]


def _live_trading_days(db_path: Path) -> list[str]:
    """Recent trading days spanning the live backtest window."""
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        dates: list[str] = []
        if _table_exists(conn, "jquants_daily_bars"):
            try:
                cur = conn.execute(
                    "SELECT DISTINCT date FROM jquants_daily_bars "
                    "ORDER BY date DESC LIMIT 100"
                )
                dates = sorted(str(r[0])[:10] for r in cur.fetchall() if r[0])
            except sqlite3.Error:
                dates = []
        if len(dates) < 2 and _table_exists(conn, "jquants_records"):
            # DESC list → sort ascending for the backtest window
            dates = sorted(_bar_dates_from_records(conn, limit=100))
        conn.close()
    except sqlite3.Error:
        dates = []
    return dates


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Phase 4 feature accept report runner")
    p.add_argument(
        "--db",
        default=None,
        help="Structured DB path. Offline: builds a fixture DB in --out-dir. "
             "Live: defaults to QP_DB or data/structured/ingestion.sqlite.",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output JSON path (default: data/reports/phase4_accept_<ts>.json).",
    )
    p.add_argument(
        "--reports-dir",
        default=str(Path(_REPO_ROOT) / "data" / "reports"),
        help="Directory for the JSON report when --out is omitted.",
    )
    p.add_argument(
        "--fixture-dir",
        default=None,
        help="Where to write the offline fixture DB (default: tmp dir).",
    )
    p.add_argument(
        "--live-sample-codes",
        type=int,
        default=50,
        help="Live: how many codes to sample for feature hit rates (default 50).",
    )
    p.add_argument(
        "--min-trading-days",
        type=int,
        default=None,
        help="Override the minimum trading-day floor for the backtest window. "
             "Offline default 20; live default 50.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    live = os.environ.get("QP_LIVE", "") == "1"

    import datetime as _dt
    timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report: dict[str, Any] = {
        "generated_at": timestamp,
        "live": live,
        "sections": {},
    }

    # F1 — registry integrity (no DB needed).
    f1 = _registry_integrity_section()
    report["sections"]["registry_integrity"] = f1

    if live:
        db_path = Path(args.db or os.environ.get(
            "QP_DB", "data/structured/ingestion.sqlite"))
        if not db_path.exists():
            report["sections"]["error"] = {"ok": False,
                                           "detail": f"DB not found: {db_path}"}
            _write_report(report, args.out, args.reports_dir, timestamp)
            return 1
        codes = _sample_live_codes(db_path, target=args.live_sample_codes)
        if not codes:
            codes = ["7203", "6758", "9984"]  # safe fallback
        as_ofs = _live_recent_as_ofs(db_path, count=5)
        days = _live_trading_days(db_path)
        if len(days) < 2:
            report["sections"]["error"] = {"ok": False,
                                           "detail": "not enough trading days"}
            _write_report(report, args.out, args.reports_dir, timestamp)
            return 1
        min_days = args.min_trading_days if args.min_trading_days is not None else 50
        report["db_path"] = str(db_path)
        report["sections"]["b0_strict"] = _b0_section(db_path)
        report["sections"]["feature_hit_rates"] = _feature_hit_rates_section(
            db_path, codes, as_ofs,
        )
        report["sections"]["backtest"] = _backtest_section(
            db_path, codes, days, min_trading_days=min_days, live=True,
        )
        report["sections"]["sample_codes"] = {"count": len(codes),
                                              "codes": codes,
                                              "as_ofs": as_ofs}
    else:
        # Offline fixture.
        import tempfile
        fdir = Path(args.fixture_dir) if args.fixture_dir else Path(tempfile.mkdtemp(
            prefix="qp-phase4-"))
        fdir.mkdir(parents=True, exist_ok=True)
        db_path, days, codes = _build_offline_db(fdir / "phase4_accept.sqlite")
        min_days = args.min_trading_days if args.min_trading_days is not None else 20
        report["db_path"] = str(db_path)
        report["sections"]["feature_hit_rates"] = _feature_hit_rates_section(
            db_path,
            codes,
            [f"{d}T15:30:00+09:00" for d in days[-5:]],
        )
        report["sections"]["backtest"] = _backtest_section(
            db_path, codes, days, min_trading_days=min_days, live=False,
        )

    # Overall ok = F1 + F2 (every feature has at least one non-None) + F3.
    f1_ok = bool(f1.get("ok"))
    fhr = report["sections"].get("feature_hit_rates", {})
    f2_ok = all(
        (entry.get("non_none", 0) > 0)
        for entry in fhr.values()
        if isinstance(entry, dict)
    )
    f3 = report["sections"].get("backtest", {})
    f3_ok = bool(f3.get("ok"))
    report["ok"] = f1_ok and f2_ok and f3_ok
    report["section_ok"] = {
        "registry_integrity": f1_ok,
        "feature_hit_rates": f2_ok,
        "backtest": f3_ok,
    }
    if live:
        b0 = report["sections"].get("b0_strict", {})
        report["section_ok"]["b0_strict"] = bool(b0.get("ok"))
        report["ok"] = bool(report["ok"]) and bool(b0.get("ok"))

    out_path = _write_report(report, args.out, args.reports_dir, timestamp)
    print(f"[phase4-accept] live={live} ok={report['ok']} -> {out_path}")
    return 0 if report["ok"] else 1


def _write_report(
    report: dict[str, Any],
    out_arg: str | None,
    reports_dir: str,
    timestamp: str,
) -> Path:
    if out_arg:
        out_path = Path(out_arg)
    else:
        d = Path(reports_dir)
        d.mkdir(parents=True, exist_ok=True)
        out_path = d / f"phase4_accept_{timestamp}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return out_path


if __name__ == "__main__":
    sys.exit(main())
