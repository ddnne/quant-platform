#!/usr/bin/env python3
"""Hydrate compact local J-Quants history for personal DRAFT research.

Dry-run is the default and does not require opt-in.  Pass ``--execute`` to
make network requests and write the dedicated SQLite file; that executable
path requires ``QP_ALLOW_LOCAL_MARKET_DATA=1``.  This command cannot issue
receipts, Coverage, READY, controlled-pilot evidence, or trading authorization.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

_here = Path(__file__).resolve().parent
for _directory in (_here, _here.parent):
    if (_directory / "_bootstrap.py").is_file():
        if str(_directory) not in sys.path:
            sys.path.insert(0, str(_directory))
        break
else:  # pragma: no cover - checkout corruption
    raise RuntimeError("scripts/_bootstrap.py not found")

from _bootstrap import ensure_repo_root  # noqa: E402

ROOT = ensure_repo_root()

from ingestion.common.http import make_jquants_http  # noqa: E402
from ingestion.common.rate_limit import RateLimiter  # noqa: E402
from ingestion.jquants.client import JQuantsClient  # noqa: E402
from ingestion.personal_history import (  # noqa: E402
    DEFAULT_CALENDAR_WINDOW_DAYS,
    DEFAULT_LOOKBACK_SESSIONS,
    DEFAULT_MAX_DATABASE_BYTES,
    DEFAULT_MINIMUM_FREE_BYTES,
    PersonalHistoryError,
    PersonalHistoryHydrator,
    assert_personal_history_database,
    build_personal_history_plan,
)
from storage.sqlite_store import SqliteStore  # noqa: E402


_UA = "quant-platform-personal-history/0.1 (+personal-draft; JST)"
DEFAULT_RPM = 30.0
PROXY_MAX_RPM = 60.0


def _effective_rpm(requested: float, *, via_proxy: bool) -> float:
    return min(float(requested), PROXY_MAX_RPM) if via_proxy else float(requested)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date", required=True, dest="period_start")
    parser.add_argument("--to-date", required=True, dest="period_end")
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "structured" / "personal-history.sqlite",
        help="dedicated personal SQLite file",
    )
    parser.add_argument(
        "--lookback-sessions",
        type=int,
        default=DEFAULT_LOOKBACK_SESSIONS,
        help="bar lookback before the requested period (default: 10)",
    )
    parser.add_argument(
        "--calendar-window-days",
        type=int,
        default=DEFAULT_CALENDAR_WINDOW_DAYS,
        help="bounded calendar request window (default: 180)",
    )
    parser.add_argument(
        "--requests-per-minute",
        type=float,
        default=DEFAULT_RPM,
        help=(
            "shared sequential request pace "
            f"(default: conservative {DEFAULT_RPM:g} rpm)"
        ),
    )
    parser.add_argument(
        "--max-db-gib",
        type=float,
        default=DEFAULT_MAX_DATABASE_BYTES / 1024**3,
        help="hard SQLite+WAL+SHM size ceiling (default: 5 GiB)",
    )
    parser.add_argument(
        "--min-free-gib",
        type=float,
        default=DEFAULT_MINIMUM_FREE_BYTES / 1024**3,
        help="free-space reserve kept for snapshots/recovery (default: 8 GiB)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="perform requests and writes (default: dry-run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="force plan-only mode even when --execute is present",
    )
    parser.add_argument(
        "--no-jquants-proxy",
        action="store_true",
        help="use an explicitly enabled local API key instead of the saved proxy",
    )
    return parser


def _print_plan(
    plan,
    db_path: Path,
    rpm: float,
    *,
    max_database_bytes: int,
    minimum_free_bytes: int,
) -> None:
    parent = db_path.expanduser().resolve().parent
    usage_path = parent if parent.exists() else parent.parent
    available = shutil.disk_usage(usage_path).free if usage_path.exists() else None
    document = {
        "mode": "PERSONAL_DRAFT_HISTORY",
        "execution": "dry-run",
        "database": str(db_path.expanduser().resolve()),
        "datasets": [
            "markets_calendar",
            "equities_master",
            "fins_summary",
            "equities_bars_daily",
        ],
        "sequential": True,
        "requests_per_minute": rpm,
        "max_database_bytes": max_database_bytes,
        "minimum_free_bytes": minimum_free_bytes,
        "plan": plan.to_dict(),
        "disk_free_bytes": available,
        "capacity_warning": (
            "estimated database plus free-space reserve exceeds available space"
            if available is not None
            and plan.estimated_bytes + minimum_free_bytes > available
            else "estimated database exceeds configured hard limit"
            if plan.estimated_bytes > max_database_bytes
            else None
        ),
        "warning": (
            "DRAFT only; master Date 08:00 is a scheduled snapshot "
            "approximation, not revision-PIT. No completeness, receipt, "
            "Coverage, READY, controlled/live, or promotion claim."
        ),
    }
    print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not 1.0 <= args.requests_per_minute <= 480.0:
        parser.error("--requests-per-minute must be between 1 and 480")
    if not 0.25 <= args.max_db_gib <= 20.0:
        parser.error("--max-db-gib must be between 0.25 and 20")
    if not 0.0 <= args.min_free_gib <= 100.0:
        parser.error("--min-free-gib must be between 0 and 100")
    max_database_bytes = int(args.max_db_gib * 1024**3)
    minimum_free_bytes = int(args.min_free_gib * 1024**3)
    try:
        plan = build_personal_history_plan(
            period_start=args.period_start,
            period_end=args.period_end,
            lookback_sessions=args.lookback_sessions,
            calendar_window_days=args.calendar_window_days,
        )
    except PersonalHistoryError as exc:
        parser.error(str(exc))
    _print_plan(
        plan,
        args.db,
        args.requests_per_minute,
        max_database_bytes=max_database_bytes,
        minimum_free_bytes=minimum_free_bytes,
    )
    if not args.execute or args.dry_run:
        print("dry-run complete; re-run with --execute to hydrate")
        return 0

    governed = ROOT / "data" / "structured" / "ingestion.sqlite"
    try:
        assert_personal_history_database(args.db, governed_default=governed)
    except PersonalHistoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    http = None
    store = None
    try:
        http = make_jquants_http(
            "local",
            via_cf_proxy=False if args.no_jquants_proxy else None,
            user_agent=_UA,
        )
        via_proxy = getattr(http, "name", "") == "cf-jquants-proxy"
        unsafe_direct = os.environ.get(
            "UNSAFE_DEV_DIRECT_JQUANTS", ""
        ).strip().lower() in {"1", "true", "yes"}
        api_key = os.environ.get("JQUANTS_API_KEY", "") if unsafe_direct else ""
        if not via_proxy and not api_key:
            print(
                "ERROR: no saved J-Quants proxy and no explicitly enabled "
                "local API key",
                file=sys.stderr,
            )
            return 2
        effective_rpm = _effective_rpm(
            args.requests_per_minute, via_proxy=via_proxy
        )
        print(
            json.dumps(
                {
                    "transport": "saved_proxy" if via_proxy else "direct",
                    "requested_requests_per_minute": args.requests_per_minute,
                    "effective_requests_per_minute": effective_rpm,
                },
                sort_keys=True,
            )
        )
        client = JQuantsClient(
            http,
            api_key,
            rate_limiter=RateLimiter(60.0 / effective_rpm),
        )
        store = SqliteStore(args.db)
        summary = PersonalHistoryHydrator(
            client=client,
            store=store,
            plan=plan,
            max_database_bytes=max_database_bytes,
            minimum_free_bytes=minimum_free_bytes,
        ).hydrate()
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI reports checkpointed failure
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()
        if http is not None and hasattr(http, "close"):
            try:
                http.close()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    from _local_market_data_guard import require_local_market_data_opt_in

    _argv = sys.argv[1:]
    if "--execute" in _argv and "--dry-run" not in _argv:
        require_local_market_data_opt_in()
    raise SystemExit(main())
