#!/usr/bin/env python3
"""Surgical re-aggregate dataset_coverage from coverage_segments (SoT).

After segment seals (restore / issue), the segment plane can be fully COMPLETE
while ``dataset_coverage.status`` stays PARTIAL with stale
``coverage_v2.status_counts``. Full ``refresh_coverage_ledger`` re-evaluates
every segment and is riskier than necessary when segments are already correct.

This CLI updates **only** ``dataset_coverage`` rows after canonical inventory
and selected signed-receipt verification:

- never invents segments
- never rewrites ``coverage_segments``
- never promotes PARTIAL to COMPLETE while C10 transition authority is open
- retains an existing current-policy COMPLETE only for an exact inventory with
  one verified selected receipt per segment and no failing checks
- honest status_counts always written on change

Post-seal checklist (preferred after a tip seal):

```bash
.venv/bin/python scripts/sync_dataset_coverage_from_segments.py \\
  --db data/structured/ingestion.sqlite --datasets fins_earnings_date
.venv/bin/python scripts/publish_ops_projection.py \\
  --db data/structured/ingestion.sqlite --apply-remote
```

Prefer one-dataset mode when only one dataset's segs flipped COMPLETE.
Use ``--dry-run`` first. Mass / READY remain OFF; this does not declare READY.
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
from urllib.parse import quote

ROOT = ensure_repo_root()

from storage.coverage_ledger import (  # noqa: E402
    coverage_summary,
    sync_dataset_coverage_from_segments,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "structured" / "ingestion.sqlite",
        help="path to structured SQLite (default: data/structured/ingestion.sqlite)",
    )
    parser.add_argument(
        "--datasets",
        nargs="*",
        default=None,
        help="datasets to re-aggregate (default: all rows in dataset_coverage)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compute actions without writing dataset_coverage",
    )
    parser.add_argument(
        "--wave",
        default=None,
        help="optional audit stamp written into detail_json.coverage_v2.surgical_reagg",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable results JSON to stdout",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="after apply, print coverage_summary status_counts",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    if not db_path.is_file():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 2

    mode = "rw" if not args.dry_run else "ro"
    uri = "file:" + quote(str(db_path)) + f"?mode={mode}"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=120)
    except sqlite3.Error as exc:
        print(f"ERROR: cannot open db ({mode}): {exc}", file=sys.stderr)
        return 2
    conn.row_factory = sqlite3.Row

    try:
        pre_platform = conn.execute(
            "SELECT COUNT(*) FROM coverage_segments WHERE status='COMPLETE'"
        ).fetchone()[0]
        pre_dc = {
            str(r["status"]): int(r["n"])
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM dataset_coverage GROUP BY status"
            )
        }

        results = sync_dataset_coverage_from_segments(
            conn,
            datasets=args.datasets,
            dry_run=args.dry_run,
            wave=args.wave,
        )

        post_platform = conn.execute(
            "SELECT COUNT(*) FROM coverage_segments WHERE status='COMPLETE'"
        ).fetchone()[0]
        post_dc = {
            str(r["status"]): int(r["n"])
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM dataset_coverage GROUP BY status"
            )
        }

        payload = {
            "dry_run": args.dry_run,
            "pre_dataset_coverage": pre_dc,
            "post_dataset_coverage": post_dc,
            "pre_platform_complete_segs": pre_platform,
            "post_platform_complete_segs": post_platform,
            "segments_untouched": pre_platform == post_platform,
            "results": results,
        }

        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(
                f"sync_dataset_coverage_from_segments "
                f"dry_run={args.dry_run} datasets="
                f"{args.datasets if args.datasets else 'ALL'}",
                flush=True,
            )
            for row in results:
                ds = row.get("dataset")
                action = row.get("action")
                old = row.get("old_status")
                new = row.get("to") or row.get("status") or row.get("derived_status")
                counts = row.get("status_counts")
                print(
                    f"  {ds}: action={action} status {old} -> {new} "
                    f"segs={counts} complete={row.get('complete')}/"
                    f"{row.get('total')}",
                    flush=True,
                )
            print(
                f"dataset_coverage PRE {pre_dc} -> POST {post_dc}",
                flush=True,
            )
            print(
                f"platform COMPLETE segs {pre_platform} -> {post_platform} "
                f"(untouched={pre_platform == post_platform})",
                flush=True,
            )

        if args.summary and not args.dry_run:
            summary = coverage_summary(db_path)
            print("Coverage Summary:", flush=True)
            print(f"  Policy version: {summary['policy_version']}", flush=True)
            print(f"  Dataset count: {summary['dataset_count']}", flush=True)
            for status, count in sorted(summary["status_counts"].items()):
                if count:
                    print(f"    {status}: {count}", flush=True)
            print(f"  Governed READY: {summary['governed_ready']}", flush=True)

        # Exit 0 for verification-only, demotion, or authority-pending results.
        # Exit 1 only if integrity would have been violated (segments changed).
        if pre_platform != post_platform:
            print(
                "ERROR: coverage_segments COMPLETE count changed — refuse",
                file=sys.stderr,
            )
            return 4
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
