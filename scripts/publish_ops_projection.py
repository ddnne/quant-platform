#!/usr/bin/env python3
"""Automate Coverage refresh + Ops projection publish.

Pipeline:
  1. Optional: refresh_coverage_ledger on local research DB
  2. export_ops_projection SQL
  3. If --apply-remote: wrangler d1 execute quant-ingest --remote --file=...

Removes the "human must remember export commands" sole path. Remote MCP still
never gains write tools; this script is an out-of-band publisher.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.export_ops_projection import render_projection_sql  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "structured" / "ingestion.sqlite",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=ROOT / "data" / "research_snapshots",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "ops" / "projection.sql",
    )
    parser.add_argument(
        "--meta-output",
        type=Path,
        default=ROOT / "data" / "ops" / "projection_meta.json",
    )
    parser.add_argument(
        "--refresh-coverage",
        action="store_true",
        help="Run coverage ledger refresh before export (requires evidence/receipts).",
    )
    parser.add_argument(
        "--apply-remote",
        action="store_true",
        help="Apply exported SQL to remote D1 via wrangler (requires CF auth).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render SQL only; do not write meta apply.",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"ERROR: local DB not found: {args.db}", file=sys.stderr)
        return 2

    refresh_status = "skipped"
    refresh_error = None
    last_refresh_attempt_at = _now()
    last_success_at = None
    if args.refresh_coverage:
        from storage.sqlite_store import SqliteStore
        from storage.coverage_ledger import refresh_coverage_ledger

        last_refresh_attempt_at = _now()
        store = SqliteStore(args.db)
        try:
            refresh_coverage_ledger(store._conn, args.db)  # noqa: SLF001
            store._conn.commit()  # noqa: SLF001
            refresh_status = "success"
            last_success_at = _now()
            print("coverage ledger refresh ok")
        except Exception as exc:  # noqa: BLE001
            refresh_status = "failed"
            refresh_error = str(exc)[:2000]
            print(f"coverage ledger refresh FAILED: {exc}", file=sys.stderr)
        finally:
            store.close()

    sql = render_projection_sql(args.db, snapshot_dir=args.snapshot_dir)
    from ops.projection_meta import build_projection_metadata

    meta = build_projection_metadata(
        args.db,
        refresh_status=refresh_status,
        refresh_error=refresh_error,
        last_refresh_attempt_at=last_refresh_attempt_at,
        last_success_at=last_success_at,
        publisher="scripts/publish_ops_projection.py",
    )
    meta["local_db"] = str(args.db)
    meta["snapshot_dir"] = str(args.snapshot_dir)
    meta["sql_bytes"] = len(sql.encode("utf-8"))
    # Back-compat aliases for older readers
    meta["projection_status"] = meta["status"]
    meta["projection_generated_at"] = meta["generated_at"]
    meta["projection_source_generation"] = meta.get("source_generation")

    if args.dry_run:
        print(sql[:2000])
        print(json.dumps(meta, indent=2))
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(sql, encoding="utf-8")
    args.meta_output.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} ({meta['sql_bytes']} bytes)")
    print(f"wrote {args.meta_output}")

    if args.apply_remote:
        # D1 remote execute rejects explicit SQL BEGIN/COMMIT.
        remote_sql = "\n".join(
            line
            for line in sql.splitlines()
            if line.strip().upper()
            not in {"BEGIN TRANSACTION;", "BEGIN;", "COMMIT;", "COMMIT"}
        ) + "\n"
        remote_path = args.output.with_suffix(".d1.sql")
        remote_path.write_text(remote_sql, encoding="utf-8")
        cmd = [
            "npx",
            "wrangler",
            "d1",
            "execute",
            "quant-ingest",
            "--remote",
            f"--file={remote_path}",
        ]
        print("running:", " ".join(cmd))
        proc = subprocess.run(cmd, cwd=ROOT / "platform" / "workers" / "quant-ops-mcp")
        if proc.returncode != 0:
            print("ERROR: remote apply failed", file=sys.stderr)
            return proc.returncode
        meta["applied_at"] = _now()
        meta["status"] = meta.get("status", "FRESH")
        meta["projection_status"] = meta["status"]
        args.meta_output.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print("remote projection applied")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
