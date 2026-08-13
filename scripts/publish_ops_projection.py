#!/usr/bin/env python3
"""Automate Coverage refresh + Ops projection publish.

Pipeline:
  1. Optional: refresh_coverage_ledger on local research DB
  2. export_ops_projection SQL
  3. If --apply-remote: wrangler d1 execute quant-ingest --remote --file=...

Removes the "human must remember export commands" sole path. Remote MCP still
never gains write tools; this script is an out-of-band publisher.

Fail-closed guard (GLM design):
  - Before full --apply-remote (non dry-run), probe local + remote COMPLETE counts.
  - If remote probe fails OR local < remote, refuse exit 3 unless --force-apply-remote.
  - Targeted reevaluation path is unaffected (not a full publish).
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
import re
import sqlite3
import subprocess
from datetime import datetime, timezone

ROOT = ensure_repo_root()

from scripts.export_ops_projection import render_projection_sql  # noqa: E402

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def count_local_complete(db_path: Path) -> int:
    """Count COMPLETE coverage_segments in a local SQLite ops/research DB.

    Raises sqlite3.Error if the table is missing — callers must surface that
    rather than silently treating an unprobed DB as zero (fail-closed).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM coverage_segments WHERE status = 'COMPLETE'"
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()

def count_remote_complete(
    *,
    database: str = "quant-ingest",
    wrangler_cwd: Path | None = None,
    timeout_sec: int = 120,
) -> int | None:
    """Query remote D1 COMPLETE count via wrangler. None if unreachable.

    Returns None for any transport / parse / non-zero exit failure so that
    enforce_complete_count_guard can apply fail-closed semantics.
    """
    cwd = wrangler_cwd or (ROOT / "platform" / "workers" / "quant-ops-mcp")
    wrangler_bin = (
        ROOT
        / "platform"
        / "workers"
        / "ingestion-premium"
        / "node_modules"
        / ".bin"
        / "wrangler"
    )
    config = ROOT / "platform" / "workers" / "ingestion-premium" / "wrangler.toml"
    use_local_bin = wrangler_bin.is_file()
    cmd: list[str] = []
    if use_local_bin:
        cmd.append(str(wrangler_bin))
    else:
        cmd.extend(["npx", "wrangler"])
    cmd.extend(
        [
            "d1",
            "execute",
            database,
            "--remote",
            f"--config={config}",
            "--json",
            "--command",
            "SELECT COUNT(*) AS c FROM coverage_segments WHERE status='COMPLETE'",
        ]
    )
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd if use_local_bin else ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"WARN: remote COMPLETE probe failed: {exc}", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(
            f"WARN: remote COMPLETE probe exit={proc.returncode}: "
            f"{(proc.stderr or proc.stdout)[:500]}",
            file=sys.stderr,
        )
        return None
    text = proc.stdout or ""
    idx = text.find("[")
    if idx < 0:
        return None
    try:
        payload = json.loads(text[idx:])
        if not isinstance(payload, list) or not payload:
            return None
        results = payload[0].get("results") or []
        if not results:
            return None
        return int(results[0].get("c", results[0].get("COUNT(*)", 0)))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, IndexError):
        m = re.search(r'"c"\s*:\s*(\d+)', text)
        return int(m.group(1)) if m else None

def enforce_complete_count_guard(
    *,
    local_complete: int,
    remote_complete: int | None,
    force: bool,
) -> str | None:
    """Return error message if full apply must be refused; else None.

    Fail-closed: unknown remote (None) is treated as refuse. ``force`` is the
    only override path and must be supplied explicitly by the operator.
    """
    if force:
        return None
    if remote_complete is None:
        return (
            "Refusing --apply-remote: could not read remote COMPLETE count "
            "(fail-closed). Use --force-apply-remote to override after manual check."
        )
    if local_complete < remote_complete:
        return (
            f"Refusing --apply-remote: local COMPLETE segments ({local_complete}) "
            f"fewer than remote ({remote_complete}). "
            "Full projection publish would risk destroying remote COMPLETE evidence. "
            "Use targeted reevaluation, or --force-apply-remote only after explicit review."
        )
    return None

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
        "--force-apply-remote",
        action="store_true",
        help=(
            "Override COMPLETE-count fail-closed guard for --apply-remote. "
            "Use only after confirming local evidence supersedes remote."
        ),
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

    # Fail-closed guard before spending time on full SQL export when apply is requested.
    # 対象: 完全 publish のみ (dry-run / targeted reeval は対象外)
    if args.apply_remote and not args.dry_run:
        local_n = count_local_complete(args.db)
        remote_n = count_remote_complete()
        guard_err = enforce_complete_count_guard(
            local_complete=local_n,
            remote_complete=remote_n,
            force=bool(args.force_apply_remote),
        )
        if guard_err:
            print(f"ERROR: {guard_err}", file=sys.stderr)
            print(
                f"guard_detail local_complete={local_n} remote_complete={remote_n} "
                f"force={bool(args.force_apply_remote)}",
                file=sys.stderr,
            )
            return 3
        if args.force_apply_remote and remote_n is not None and local_n < remote_n:
            print(
                f"WARN: --force-apply-remote with local COMPLETE {local_n} < remote {remote_n}",
                file=sys.stderr,
            )
        print(
            f"complete_count_guard ok local={local_n} remote={remote_n} "
            f"force={bool(args.force_apply_remote)}"
        )

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
        # D1 remote execute rejects explicit SQL BEGIN/COMMIT and fails the
        # whole import on duplicate-column ALTER (schema is migration-owned).
        def _keep_remote_line(line: str) -> bool:
            stripped = line.strip().upper()
            if stripped in {"BEGIN TRANSACTION;", "BEGIN;", "COMMIT;", "COMMIT"}:
                return False
            if stripped.startswith("ALTER TABLE ") and " ADD COLUMN " in stripped:
                return False
            return True

        remote_sql = (
            "\n".join(line for line in sql.splitlines() if _keep_remote_line(line))
            + "\n"
        )
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
        proc = subprocess.run(
            cmd, cwd=ROOT / "platform" / "workers" / "quant-ops-mcp"
        )
        if proc.returncode != 0:
            print("ERROR: remote apply failed", file=sys.stderr)
            return proc.returncode
        meta["applied_at"] = _now()
        meta["status"] = meta.get("status", "FRESH")
        meta["projection_status"] = meta["status"]
        args.meta_output.write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8"
        )
        print("remote projection applied")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
