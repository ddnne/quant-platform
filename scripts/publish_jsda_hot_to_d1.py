#!/usr/bin/env python3
"""Publish JSDA hot-window facts from local research DB → remote D1. Does not invent rows."""

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
import tempfile
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

ROOT = ensure_repo_root()

DEFAULT_HOT_CUTOFF = "2026-07-01"
DEFAULT_DB = ROOT / "data" / "structured" / "ingestion.sqlite"
DEFAULT_WRANGLER_CWD = ROOT / "platform" / "workers" / "ingestion-premium"
DEFAULT_DATABASE = "quant-ingest"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sql_escape(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    s = str(value).replace("'", "''")
    return f"'{s}'"


def _batch_insert(
    table: str,
    columns: Sequence[str],
    rows: Iterable[tuple[Any, ...]],
    *,
    batch_size: int = 80,
) -> list[str]:
    """Build INSERT OR REPLACE batches (SQLite / D1 compatible)."""
    stmts: list[str] = []
    buf: list[tuple[Any, ...]] = []
    col_sql = ", ".join(columns)

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        values_sql = ",\n".join(
            "(" + ", ".join(_sql_escape(v) for v in row) + ")" for row in buf
        )
        stmts.append(
            f"INSERT OR REPLACE INTO {table} ({col_sql}) VALUES\n{values_sql};"
        )
        buf = []

    for row in rows:
        buf.append(row)
        if len(buf) >= batch_size:
            flush()
    flush()
    return stmts


def export_repo_hot_sql(
    conn: sqlite3.Connection,
    *,
    hot_cutoff: str,
) -> tuple[list[str], int]:
    """Export jsda_repo_rates rows with as_of_date >= hot_cutoff."""
    cols = [
        "source",
        "as_of_date",
        "tenor",
        "rate_type",
        "rate",
        "event_time",
        "available_at",
        "ingested_at",
        "raw_payload",
    ]
    cur = conn.execute(
        f"""
        SELECT source, as_of_date, tenor, rate_type, rate,
               event_time, available_at, ingested_at, raw_payload
        FROM jsda_repo_rates
        WHERE as_of_date >= ?
        ORDER BY as_of_date, tenor, rate_type
        """,
        (hot_cutoff,),
    )
    rows = list(cur.fetchall())
    stmts = [
        f"-- publish_jsda_hot_to_d1 generated_at={_now()}",
        f"-- table=jsda_repo_rates hot_cutoff={hot_cutoff} n={len(rows)}",
        f"-- policy=D1_hot_tip_only full_history_local_R2",
    ]
    stmts.append(
        f"DELETE FROM jsda_repo_rates WHERE as_of_date < {_sql_escape(hot_cutoff)};"
    )
    stmts.extend(_batch_insert("jsda_repo_rates", cols, rows))
    return stmts, len(rows)


def apply_remote(
    sql_path: Path,
    *,
    database: str,
    wrangler_cwd: Path,
    timeout_sec: int = 600,
) -> subprocess.CompletedProcess[str]:
    wrangler = (
        ROOT
        / "platform"
        / "workers"
        / "ingestion-premium"
        / "node_modules"
        / ".bin"
        / "wrangler"
    )
    cmd = [
        str(wrangler) if wrangler.is_file() else "npx",
    ]
    if not wrangler.is_file():
        cmd.extend(["wrangler"])
    cmd.extend(
        [
            "d1",
            "execute",
            database,
            "--remote",
            f"--file={sql_path}",
        ]
    )
    return subprocess.run(
        cmd,
        cwd=str(wrangler_cwd),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )


def probe_remote_repo_count(
    *,
    database: str,
    wrangler_cwd: Path,
) -> int | None:
    wrangler = (
        ROOT
        / "platform"
        / "workers"
        / "ingestion-premium"
        / "node_modules"
        / ".bin"
        / "wrangler"
    )
    base = [str(wrangler)] if wrangler.is_file() else ["npx", "wrangler"]
    r = subprocess.run(
        base
        + [
            "d1",
            "execute",
            database,
            "--remote",
            "--json",
            "--command",
            "SELECT COUNT(*) AS n FROM jsda_repo_rates",
        ],
        cwd=str(wrangler_cwd),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout)
        if isinstance(data, list) and data:
            res = data[0].get("results") or []
            if res:
                return int(res[0].get("n") or 0)
    except Exception:
        return None
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--hot-cutoff", default=DEFAULT_HOT_CUTOFF)
    p.add_argument("--out", type=Path, default=None, help="Write SQL file path")
    p.add_argument(
        "--apply-remote",
        action="store_true",
        help="Apply SQL to remote D1 via wrangler",
    )
    p.add_argument("--database", default=DEFAULT_DATABASE)
    p.add_argument("--wrangler-cwd", type=Path, default=DEFAULT_WRANGLER_CWD)
    p.add_argument("--dry-run", action="store_true", help="Export only (default)")
    args = p.parse_args(argv)

    if not args.db.is_file():
        print(f"ERROR: local DB missing: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        stmts, n = export_repo_hot_sql(conn, hot_cutoff=args.hot_cutoff)
    finally:
        conn.close()

    out = args.out or (
        ROOT / ".glm-logs" / "jsda_hot_d1" / f"jsda_repo_hot_{args.hot_cutoff}.sql"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(stmts) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "generated_at": _now(),
                "hot_cutoff": args.hot_cutoff,
                "table": "jsda_repo_rates",
                "rows": n,
                "sql_path": str(out),
                "policy": "D1_hot_tip_only",
                "full_history_plane": "local_research_db_and_r2",
            },
            indent=2,
        )
    )

    if not args.apply_remote:
        print("dry-run / export only (pass --apply-remote to write D1)")
        return 0

    if n == 0:
        print("ERROR: no hot rows to publish", file=sys.stderr)
        return 3

    pre = probe_remote_repo_count(
        database=args.database, wrangler_cwd=args.wrangler_cwd
    )
    print(f"remote PRE tokyo_repo_rows={pre}")

    proc = apply_remote(
        out, database=args.database, wrangler_cwd=args.wrangler_cwd
    )
    print(proc.stdout[-2000:] if proc.stdout else "")
    if proc.returncode != 0:
        print(proc.stderr[-2000:] if proc.stderr else "", file=sys.stderr)
        print(f"ERROR: wrangler exit {proc.returncode}", file=sys.stderr)
        return proc.returncode

    post = probe_remote_repo_count(
        database=args.database, wrangler_cwd=args.wrangler_cwd
    )
    print(f"remote POST tokyo_repo_rows={post}")
    if post is None or post < n:
        print(
            f"WARN: expected >= {n} hot rows on D1, got {post}",
            file=sys.stderr,
        )
        return 4
    print(
        json.dumps(
            {
                "ok": True,
                "pre": pre,
                "post": post,
                "hot_rows_exported": n,
                "note": "COMPLETE remains receipt-owned; D1 holds hot tip only",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    from _local_market_data_guard import require_local_market_data_opt_in

    require_local_market_data_opt_in()
    raise SystemExit(main())
