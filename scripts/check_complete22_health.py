#!/usr/bin/env python3
"""W73 / w0816g — COMPLETE 22 health floor check (not growth targets).

Verifies "not broken" thresholds for the Dataset COMPLETE **22** maintain
baseline. Does **not** invent COMPLETE 23, densify history, declare READY,
or enable Mass / Phase7.

Thresholds (floors / exacts)
---------------------------
* Dataset COMPLETE == 22 (exact baseline; optional --complete-floor uses >=22)
* Dataset PARTIAL includes the 4 tip-only/DEFER ids (bars_am, earn_cal, master, OTC)
* fins_earnings_date COMPLETE segments == 104 (exact when present)
* empty COMPLETE segments == 0 (receipt_run_id null/0)
* OTC tip COMPLETE >= 93 floor
* bars_am tip COMPLETE >= 1 floor

Examples
--------
  # Local SQLite:
  .venv/bin/python scripts/check_complete22_health.py \\
      --db data/structured/ingestion.sqlite

  # Remote D1 (wrangler):
  .venv/bin/python scripts/check_complete22_health.py --remote

  # Both (local + remote):
  .venv/bin/python scripts/check_complete22_health.py \\
      --db data/structured/ingestion.sqlite --remote --json
"""

from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
else:
    raise RuntimeError("scripts/_bootstrap.py not found")
from _bootstrap import ensure_repo_root  # noqa: E402

import argparse
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

ROOT = ensure_repo_root()

WAVE = "W73 / w0816g"
EXPECTED_DATASET_COMPLETE = 22
EXPECTED_PARTIAL_DATASETS: frozenset[str] = frozenset(
    {
        "equities_bars_daily_am",  # PD-D4-BARS-AM tip continuous
        "equities_earnings_calendar",  # PD-D4-EARN-CAL
        "equities_master",  # PD-D2-MASTER
        "jsda_otc_bond_reference_prices",  # PD-D5-JSDA-OTC tip island
    }
)
FINS_DATASET = "fins_earnings_date"
FINS_COMPLETE_SEGMENTS = 104
EMPTY_COMPLETE_MAX = 0
OTC_COMPLETE_FLOOR = 93
BARS_AM_COMPLETE_FLOOR = 1
BARS_AM_DATASET = "equities_bars_daily_am"
OTC_DATASET = "jsda_otc_bond_reference_prices"

WRANGLER = (
    ROOT
    / "platform"
    / "workers"
    / "ingestion-premium"
    / "node_modules"
    / ".bin"
    / "wrangler"
)
WRANGLER_CONFIG = (
    ROOT / "platform" / "workers" / "ingestion-premium" / "wrangler.toml"
)
REMOTE_DB = "quant-ingest"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def evaluate_complete22_health(
    snapshot: Mapping[str, Any],
    *,
    exact_complete: bool = True,
    require_fins: bool = True,
) -> dict[str, Any]:
    """Evaluate a coverage snapshot against COMPLETE 22 maintain floors.

    Parameters
    ----------
    snapshot:
        Keys used (all optional except counts when require_*):
        - dataset_complete: int
        - dataset_partial: int | None
        - partial_datasets: sequence[str]
        - fins_complete_segments: int | None
        - empty_complete: int
        - otc_complete: int
        - bars_am_complete: int
        - platform_complete_segments: int | None (informational)
    exact_complete:
        When True, require dataset_complete == 22. When False, require >= 22.
    require_fins:
        When True, require fins COMPLETE segs == 104. Unit fixtures may set
        False if fins is intentionally omitted.
    """
    complete = int(snapshot.get("dataset_complete") or 0)
    partial_n = snapshot.get("dataset_partial")
    partial_list = [str(x) for x in (snapshot.get("partial_datasets") or [])]
    partial_set = set(partial_list)
    fins_n = snapshot.get("fins_complete_segments")
    empty_n = int(snapshot.get("empty_complete") or 0)
    otc_n = int(snapshot.get("otc_complete") or 0)
    bars_n = int(snapshot.get("bars_am_complete") or 0)

    if exact_complete:
        complete_ok = complete == EXPECTED_DATASET_COMPLETE
        complete_rule = f"COMPLETE_eq_{EXPECTED_DATASET_COMPLETE}"
    else:
        complete_ok = complete >= EXPECTED_DATASET_COMPLETE
        complete_rule = f"COMPLETE_ge_{EXPECTED_DATASET_COMPLETE}"

    missing_partial = sorted(EXPECTED_PARTIAL_DATASETS - partial_set)
    extra_note = sorted(partial_set - EXPECTED_PARTIAL_DATASETS)
    partial_includes_ok = not missing_partial
    if partial_n is not None:
        partial_n_ok = int(partial_n) == len(EXPECTED_PARTIAL_DATASETS)
    else:
        partial_n_ok = True

    if require_fins:
        fins_ok = fins_n is not None and int(fins_n) == FINS_COMPLETE_SEGMENTS
    else:
        fins_ok = True

    empty_ok = empty_n <= EMPTY_COMPLETE_MAX
    otc_ok = otc_n >= OTC_COMPLETE_FLOOR
    bars_ok = bars_n >= BARS_AM_COMPLETE_FLOOR
    # Never allow invent-COMPLETE growth claim via this health check.
    no_invent = complete <= EXPECTED_DATASET_COMPLETE or not exact_complete
    # With exact mode, complete==22 implies no invent 23.
    if exact_complete:
        no_invent = complete == EXPECTED_DATASET_COMPLETE

    checks = {
        complete_rule: complete_ok,
        "PARTIAL_includes_tip_only_defer4": partial_includes_ok,
        "PARTIAL_n_eq_4": partial_n_ok,
        "fins_segs_104": fins_ok,
        "empty_complete_0": empty_ok,
        f"otc_complete_ge_{OTC_COMPLETE_FLOOR}": otc_ok,
        f"bars_am_complete_ge_{BARS_AM_COMPLETE_FLOOR}": bars_ok,
        "no_invent_complete_23": no_invent and complete <= EXPECTED_DATASET_COMPLETE
        if exact_complete
        else complete >= EXPECTED_DATASET_COMPLETE,
    }
    # Clarify no_invent under floor mode: still refuse claiming growth past
    # what snapshot has; floor mode allows >22 only if live reality moved.
    if not exact_complete:
        checks["no_invent_complete_23"] = True  # floor mode; not a growth assert

    all_pass = all(checks.values())
    return {
        "wave": WAVE,
        "evaluated_at_utc": _now(),
        "exact_complete": exact_complete,
        "require_fins": require_fins,
        "observed": {
            "dataset_complete": complete,
            "dataset_partial": partial_n,
            "partial_datasets": sorted(partial_set),
            "fins_complete_segments": fins_n,
            "empty_complete": empty_n,
            "otc_complete": otc_n,
            "bars_am_complete": bars_n,
            "platform_complete_segments": snapshot.get(
                "platform_complete_segments"
            ),
        },
        "thresholds": {
            "dataset_complete": EXPECTED_DATASET_COMPLETE,
            "partial_datasets_required": sorted(EXPECTED_PARTIAL_DATASETS),
            "fins_complete_segments": FINS_COMPLETE_SEGMENTS,
            "empty_complete_max": EMPTY_COMPLETE_MAX,
            "otc_complete_floor": OTC_COMPLETE_FLOOR,
            "bars_am_complete_floor": BARS_AM_COMPLETE_FLOOR,
        },
        "missing_partial_datasets": missing_partial,
        "extra_partial_datasets": extra_note,
        "checks": checks,
        "all_checks_pass": all_pass,
        "residual_note": (
            "coverage expand = tip-wait; do not invent COMPLETE 23; "
            "bars_am history_reprobe FORBIDDEN; OTC bulk densify FORBIDDEN"
        ),
        "mass": "NO-GO",
        "ready": "not_declared",
        "phase7": "OFF",
    }


def collect_local_sqlite(db_path: Path | str) -> dict[str, Any]:
    """Read COMPLETE 22 health metrics from a local structured SQLite DB."""
    path = Path(db_path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        status_rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM dataset_coverage GROUP BY status"
        ).fetchall()
        by_status = {str(s): int(n) for s, n in status_rows}
        partials = [
            str(r[0])
            for r in conn.execute(
                "SELECT dataset FROM dataset_coverage "
                "WHERE status='PARTIAL' ORDER BY dataset"
            ).fetchall()
        ]
        fins_n = conn.execute(
            "SELECT COUNT(*) FROM coverage_segments "
            "WHERE dataset=? AND status='COMPLETE'",
            (FINS_DATASET,),
        ).fetchone()[0]
        empty_n = conn.execute(
            "SELECT COUNT(*) FROM coverage_segments "
            "WHERE status='COMPLETE' "
            "AND (receipt_run_id IS NULL OR receipt_run_id=0)"
        ).fetchone()[0]
        otc_n = conn.execute(
            "SELECT COUNT(*) FROM coverage_segments "
            "WHERE dataset=? AND status='COMPLETE'",
            (OTC_DATASET,),
        ).fetchone()[0]
        bars_n = conn.execute(
            "SELECT COUNT(*) FROM coverage_segments "
            "WHERE dataset=? AND status='COMPLETE'",
            (BARS_AM_DATASET,),
        ).fetchone()[0]
        platform_n = conn.execute(
            "SELECT COUNT(*) FROM coverage_segments WHERE status='COMPLETE'"
        ).fetchone()[0]
        bars_partial = conn.execute(
            "SELECT COUNT(*) FROM coverage_segments "
            "WHERE dataset=? AND status='PARTIAL'",
            (BARS_AM_DATASET,),
        ).fetchone()[0]
        otc_partial = conn.execute(
            "SELECT COUNT(*) FROM coverage_segments "
            "WHERE dataset=? AND status='PARTIAL'",
            (OTC_DATASET,),
        ).fetchone()[0]
    finally:
        conn.close()

    return {
        "source": "local_sqlite",
        "db": str(path),
        "dataset_complete": int(by_status.get("COMPLETE", 0)),
        "dataset_partial": int(by_status.get("PARTIAL", 0)),
        "partial_datasets": partials,
        "fins_complete_segments": int(fins_n),
        "empty_complete": int(empty_n),
        "otc_complete": int(otc_n),
        "otc_partial": int(otc_partial),
        "bars_am_complete": int(bars_n),
        "bars_am_partial": int(bars_partial),
        "platform_complete_segments": int(platform_n),
    }


def _remote_d1(sql: str, *, retries: int = 8, base_sleep: float = 2.0) -> list[dict]:
    """Execute SQL against remote D1 via wrangler (retry on 7403)."""
    import time

    if not WRANGLER.is_file():
        raise FileNotFoundError(f"wrangler not found: {WRANGLER}")
    last_err: Exception | None = None
    for attempt in range(retries):
        proc = subprocess.run(
            [
                str(WRANGLER),
                "d1",
                "execute",
                REMOTE_DB,
                "--remote",
                f"--config={WRANGLER_CONFIG}",
                f"--command={sql}",
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        combined = (proc.stderr or "") + (proc.stdout or "")
        if proc.returncode == 0:
            text = proc.stdout or ""
            start = text.rfind("\n[")
            if start < 0:
                start = text.find("[")
            else:
                start += 1
            data = json.loads(text[start:].strip())
            if isinstance(data, list) and data:
                return list(data[0].get("results") or [])
            return []
        if (
            "7403" in combined
            or "network connection was lost" in combined.lower()
            or "D1_ERROR" in combined
        ):
            sleep_s = base_sleep * (1.5**attempt)
            print(
                f"[check_complete22_health] d1 retry {attempt + 1}/{retries} "
                f"(sleep {sleep_s:.1f}s)",
                file=sys.stderr,
            )
            time.sleep(sleep_s)
            last_err = RuntimeError(
                f"d1 failed rc={proc.returncode}\n{proc.stderr}\n{proc.stdout}"
            )
            continue
        raise RuntimeError(
            f"d1 failed rc={proc.returncode}\n{proc.stderr}\n{proc.stdout}"
        )
    raise last_err or RuntimeError("d1 failed after retries")


def collect_remote_d1() -> dict[str, Any]:
    """Read COMPLETE 22 health metrics from remote D1 quant-ingest."""
    status_rows = _remote_d1(
        "SELECT status, COUNT(*) AS n FROM dataset_coverage GROUP BY status"
    )
    by_status = {str(r["status"]): int(r["n"]) for r in status_rows}
    partials = [
        str(r["dataset"])
        for r in _remote_d1(
            "SELECT dataset FROM dataset_coverage "
            "WHERE status='PARTIAL' ORDER BY dataset"
        )
    ]
    fins_n = int(
        (
            _remote_d1(
                "SELECT COUNT(*) AS n FROM coverage_segments "
                f"WHERE dataset='{FINS_DATASET}' AND status='COMPLETE'"
            )
            or [{"n": 0}]
        )[0]["n"]
    )
    empty_n = int(
        (
            _remote_d1(
                "SELECT COUNT(*) AS n FROM coverage_segments "
                "WHERE status='COMPLETE' "
                "AND (receipt_run_id IS NULL OR receipt_run_id=0)"
            )
            or [{"n": 0}]
        )[0]["n"]
    )
    otc_n = int(
        (
            _remote_d1(
                "SELECT COUNT(*) AS n FROM coverage_segments "
                f"WHERE dataset='{OTC_DATASET}' AND status='COMPLETE'"
            )
            or [{"n": 0}]
        )[0]["n"]
    )
    bars_n = int(
        (
            _remote_d1(
                "SELECT COUNT(*) AS n FROM coverage_segments "
                f"WHERE dataset='{BARS_AM_DATASET}' AND status='COMPLETE'"
            )
            or [{"n": 0}]
        )[0]["n"]
    )
    platform_n = int(
        (
            _remote_d1(
                "SELECT COUNT(*) AS n FROM coverage_segments "
                "WHERE status='COMPLETE'"
            )
            or [{"n": 0}]
        )[0]["n"]
    )
    bars_partial = int(
        (
            _remote_d1(
                "SELECT COUNT(*) AS n FROM coverage_segments "
                f"WHERE dataset='{BARS_AM_DATASET}' AND status='PARTIAL'"
            )
            or [{"n": 0}]
        )[0]["n"]
    )
    otc_partial = int(
        (
            _remote_d1(
                "SELECT COUNT(*) AS n FROM coverage_segments "
                f"WHERE dataset='{OTC_DATASET}' AND status='PARTIAL'"
            )
            or [{"n": 0}]
        )[0]["n"]
    )
    return {
        "source": "remote_d1",
        "db": REMOTE_DB,
        "dataset_complete": int(by_status.get("COMPLETE", 0)),
        "dataset_partial": int(by_status.get("PARTIAL", 0)),
        "partial_datasets": partials,
        "fins_complete_segments": fins_n,
        "empty_complete": empty_n,
        "otc_complete": otc_n,
        "otc_partial": otc_partial,
        "bars_am_complete": bars_n,
        "bars_am_partial": bars_partial,
        "platform_complete_segments": platform_n,
    }


def good_fixture_snapshot() -> dict[str, Any]:
    """Canonical healthy fixture for unit tests (no live D1)."""
    return {
        "source": "fixture",
        "dataset_complete": EXPECTED_DATASET_COMPLETE,
        "dataset_partial": len(EXPECTED_PARTIAL_DATASETS),
        "partial_datasets": sorted(EXPECTED_PARTIAL_DATASETS),
        "fins_complete_segments": FINS_COMPLETE_SEGMENTS,
        "empty_complete": 0,
        "otc_complete": OTC_COMPLETE_FLOOR,
        "bars_am_complete": BARS_AM_COMPLETE_FLOOR,
        "platform_complete_segments": 3482,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="local structured SQLite path (e.g. data/structured/ingestion.sqlite)",
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="also/only query remote D1 quant-ingest via wrangler",
    )
    parser.add_argument(
        "--complete-floor",
        action="store_true",
        help="use COMPLETE >= 22 floor instead of exact == 22",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON only",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="optional path to write full JSON report",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.db is None and not args.remote:
        default_db = ROOT / "data" / "structured" / "ingestion.sqlite"
        if default_db.is_file():
            args.db = default_db
        else:
            parser.error("provide --db and/or --remote")

    exact = not args.complete_floor
    reports: list[dict[str, Any]] = []
    any_fail = False

    if args.db is not None:
        snap = collect_local_sqlite(args.db)
        rep = evaluate_complete22_health(snap, exact_complete=exact)
        rep["snapshot"] = snap
        reports.append(rep)
        if not rep["all_checks_pass"]:
            any_fail = True

    if args.remote:
        snap = collect_remote_d1()
        rep = evaluate_complete22_health(snap, exact_complete=exact)
        rep["snapshot"] = snap
        reports.append(rep)
        if not rep["all_checks_pass"]:
            any_fail = True

    payload: dict[str, Any] = {
        "wave": WAVE,
        "generated_at_utc": _now(),
        "exact_complete": exact,
        "reports": reports,
        "all_checks_pass": not any_fail and bool(reports),
        "residual_note": (
            "coverage expand = tip-wait; health check is maintain floor only"
        ),
    }

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for rep in reports:
            src = (rep.get("snapshot") or {}).get("source", "?")
            obs = rep["observed"]
            print(f"=== COMPLETE 22 health ({src}) ===")
            print(
                f"  COMPLETE={obs['dataset_complete']}  "
                f"PARTIAL={obs['dataset_partial']}  "
                f"fins={obs['fins_complete_segments']}  "
                f"empty={obs['empty_complete']}  "
                f"otc={obs['otc_complete']}  "
                f"bars_am={obs['bars_am_complete']}  "
                f"platform_segs={obs['platform_complete_segments']}"
            )
            print(f"  partial_datasets={obs['partial_datasets']}")
            for k, v in rep["checks"].items():
                mark = "PASS" if v else "FAIL"
                print(f"  [{mark}] {k}")
            print(
                f"  all_checks_pass={rep['all_checks_pass']}  "
                f"mass={rep['mass']} ready={rep['ready']} phase7={rep['phase7']}"
            )
            print(f"  residual_note: {rep['residual_note']}")
        print(f"=== overall all_checks_pass={payload['all_checks_pass']} ===")
        if args.out:
            print(f"wrote {args.out}")

    return 0 if payload["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
