#!/usr/bin/env python3
"""Read-only D1→local sync lag report (export cursor + applied change_seq).

Does **not** claim READY / COMPLETE / materialization health. It only reports
watermarks and applied sequence state that are already present in local SQLite
and (optionally) remote numbers you pass on the CLI.

Examples
--------
  # Local only:
  python3 scripts/report_d1_local_sync_lag.py \\
      --db data/structured/ingestion.sqlite

  # With remote max_seq measured separately via wrangler:
  python3 scripts/report_d1_local_sync_lag.py \\
      --db data/structured/ingestion.sqlite \\
      --remote-max-seq 2859279 \\
      --remote-change-log-n 362 \\
      --focus markets_calendar,equities_bars_daily
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Report D1→local export/applied lag (read-only)."
    )
    p.add_argument("--db", required=True, help="Local ingestion SQLite path")
    p.add_argument(
        "--remote-max-seq",
        type=int,
        default=None,
        help="Remote MAX(ingestion_change_log.change_seq) if already measured",
    )
    p.add_argument(
        "--remote-change-log-n",
        type=int,
        default=None,
        help="Remote COUNT(ingestion_change_log) if already measured",
    )
    p.add_argument(
        "--focus",
        default="markets_calendar,equities_bars_daily,indices_bars_daily_topix",
        help="Comma-separated dataset ids to highlight (default: thin core set)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON only",
    )
    return p


def _open_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def collect(
    db: Path,
    *,
    remote_max_seq: int | None,
    remote_change_log_n: int | None,
    focus: list[str],
) -> dict:
    con = _open_ro(db)
    try:
        watermarks = [
            dict(r)
            for r in con.execute(
                "SELECT dataset, last_event_date, last_ingested_at, "
                "last_export_cursor FROM ingestion_watermarks ORDER BY dataset"
            )
        ]
        null_export = sum(1 for w in watermarks if w["last_export_cursor"] is None)
        applied_rows = [
            dict(r)
            for r in con.execute(
                "SELECT feed, last_applied_change_seq, updated_at "
                "FROM sync_change_state ORDER BY feed"
            )
        ]
        applied = None
        for row in applied_rows:
            if row["feed"] == "jquants_records":
                applied = int(row["last_applied_change_seq"])
                break

        focus_out = []
        for ds in focus:
            wm = next((w for w in watermarks if w["dataset"] == ds), None)
            export_cur = wm["last_export_cursor"] if wm else None
            entry: dict = {
                "dataset": ds,
                "local_last_export_cursor": export_cur,
                "local_last_event_date": wm["last_event_date"] if wm else None,
            }
            if remote_max_seq is not None and export_cur is not None:
                entry["export_lag"] = remote_max_seq - int(export_cur)
            elif export_cur is None:
                entry["export_lag"] = None
            # Optional local fact counts when jquants_records exists.
            try:
                row = con.execute(
                    "SELECT COUNT(*) AS n, MAX(event_time) AS max_event "
                    "FROM jquants_records WHERE dataset = ?",
                    (ds,),
                ).fetchone()
                entry["local_jquants_records_n"] = row["n"]
                entry["local_max_event_time"] = row["max_event"]
            except sqlite3.Error:
                pass
            try:
                cov = con.execute(
                    "SELECT status, row_count, observed_end FROM dataset_coverage "
                    "WHERE dataset = ?",
                    (ds,),
                ).fetchone()
                if cov:
                    entry["local_dataset_coverage_status"] = cov["status"]
                    entry["local_dataset_coverage_row_count"] = cov["row_count"]
                    entry["local_dataset_coverage_observed_end"] = cov["observed_end"]
            except sqlite3.Error:
                pass
            focus_out.append(entry)

        report = {
            "db": str(db),
            "local": {
                "watermarks_n": len(watermarks),
                "null_export": null_export,
                "sync_change_state": applied_rows,
                "last_applied_change_seq": applied,
            },
            "remote_inputs": {
                "max_seq": remote_max_seq,
                "change_log_n": remote_change_log_n,
            },
            "focus": focus_out,
            "notes": [
                "export_lag = remote_max_seq - local last_export_cursor "
                "(requires --remote-max-seq).",
                "applied_lag = remote_max_seq - local last_applied_change_seq "
                "(0 means local applied watermark caught the remote tip of the "
                "retained change_log window; not a READY claim).",
                "Does not assert COMPLETE/materialization of fact tables.",
                "Legacy table jquants_market_calendar may be empty when remote "
                "stores calendar rows in jquants_records / R2 only.",
            ],
        }
        if remote_max_seq is not None and applied is not None:
            report["local"]["applied_lag"] = remote_max_seq - applied
        elif applied is None:
            report["local"]["applied_lag"] = None
        return report
    finally:
        con.close()


def _print_text(report: dict) -> None:
    local = report["local"]
    remote = report["remote_inputs"]
    print(f"db={report['db']}")
    print(
        f"local watermarks: n={local['watermarks_n']} "
        f"null_export={local['null_export']}"
    )
    print(
        f"local applied: last_applied_change_seq="
        f"{local['last_applied_change_seq']} "
        f"applied_lag={local.get('applied_lag')}"
    )
    print(
        f"remote inputs: max_seq={remote['max_seq']} "
        f"change_log_n={remote['change_log_n']}"
    )
    print("focus datasets:")
    for entry in report["focus"]:
        bits = [
            f"dataset={entry['dataset']}",
            f"export_cursor={entry['local_last_export_cursor']}",
            f"export_lag={entry.get('export_lag')}",
            f"last_event_date={entry['local_last_event_date']}",
        ]
        if "local_jquants_records_n" in entry:
            bits.append(f"records_n={entry['local_jquants_records_n']}")
            bits.append(f"max_event={entry['local_max_event_time']}")
        if "local_dataset_coverage_status" in entry:
            bits.append(
                f"coverage_status={entry['local_dataset_coverage_status']}"
            )
        print("  " + " ".join(bits))
    print("notes:")
    for note in report["notes"]:
        print(f"  - {note}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = Path(args.db)
    if not db.is_file():
        print(f"db not found: {db}", file=sys.stderr)
        return 2
    focus = [s.strip() for s in args.focus.split(",") if s.strip()]
    report = collect(
        db,
        remote_max_seq=args.remote_max_seq,
        remote_change_log_n=args.remote_change_log_n,
        focus=focus,
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
