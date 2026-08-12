#!/usr/bin/env python3
"""Re-eval dataset_coverage.observed_start/end from SUCCESS receipts (remote D1).

Why
---
High-volume Premium datasets use R2-only structured writes. D1
``jquants_records`` is hot-window only, so C4-driven ``observed_start`` can
stick at the hot floor (e.g. 2024-01-04) even after historical backfill
landed raw + receipts.

This script unions the receipt plane (SUCCESS + raw_row_count > 0) into
``dataset_coverage.observed_*`` without:
  * rewriting coverage_segments
  * claiming COMPLETE / Mass / READY
  * touching raw retention rows

Default dataset: equities_bars_daily.
"""

from __future__ import annotations

import sys
from pathlib import Path

for _parent in Path(__file__).resolve().parents:
    if (_parent / "qp_paths.py").is_file() and (_parent / "pyproject.toml").is_file():
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        break
else:
    raise RuntimeError("quant-platform repo root not found from script")

from qp_paths import repo_root
import argparse
import json
import subprocess
import tempfile
from datetime import datetime, timezone

ROOT = repo_root()
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
DB_NAME = "quant-ingest"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sql_escape(value: str) -> str:
    return value.replace("'", "''")


def _wrangler_json(command: str) -> list[dict]:
    cmd = [
        str(WRANGLER),
        "d1",
        "execute",
        DB_NAME,
        "--remote",
        f"--config={WRANGLER_CONFIG}",
        "--json",
        f"--command={command}",
    ]
    proc = subprocess.run(
        cmd, cwd=str(ROOT), check=False, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"wrangler failed rc={proc.returncode}: {proc.stderr[-500:]}"
        )
    payload = json.loads(proc.stdout)
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"unexpected wrangler json: {proc.stdout[:300]}")
    return payload


def _first_row(payload: list[dict]) -> dict | None:
    results = payload[0].get("results") or []
    return results[0] if results else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dataset",
        default="equities_bars_daily",
        help="Dataset id to re-eval (default equities_bars_daily)",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not WRANGLER.is_file():
        print(f"ERROR: wrangler not found: {WRANGLER}", file=sys.stderr)
        return 2

    ds = args.dataset.strip()
    if not ds or "'" in ds:
        print("ERROR: invalid dataset", file=sys.stderr)
        return 2

    pre = _first_row(
        _wrangler_json(
            "SELECT dataset, status, observed_start, observed_end, row_count, "
            f"evaluated_at FROM dataset_coverage WHERE dataset='{_sql_escape(ds)}'"
        )
    )
    if pre is None:
        print(f"ERROR: no dataset_coverage row for {ds}", file=sys.stderr)
        return 3

    receipt = _first_row(
        _wrangler_json(
            "SELECT MIN(segment_start) AS receipt_start, "
            "MAX(segment_end) AS receipt_end, "
            "COUNT(*) AS n_receipts, SUM(raw_row_count) AS sum_raw "
            "FROM collection_receipts "
            f"WHERE dataset='{_sql_escape(ds)}' AND status='SUCCESS' "
            "AND raw_row_count > 0"
        )
    )
    if receipt is None or not receipt.get("receipt_start"):
        print(
            f"ERROR: no SUCCESS receipts with raw_row_count>0 for {ds}",
            file=sys.stderr,
        )
        return 4

    receipt_start = str(receipt["receipt_start"])[:10]
    receipt_end = str(receipt["receipt_end"])[:10]
    pre_start = pre.get("observed_start")
    pre_end = pre.get("observed_end")
    pre_start_d = str(pre_start)[:10] if pre_start else None
    pre_end_d = str(pre_end)[:10] if pre_end else None

    new_start = receipt_start
    if pre_start_d and pre_start_d < new_start:
        # Keep even earlier hot-window evidence if present (unlikely).
        new_start = pre_start if pre_start_d == str(pre_start)[:10] else pre_start_d
        if pre_start_d < receipt_start:
            new_start = (
                str(pre_start)
                if pre_start and str(pre_start)[:10] == pre_start_d
                else pre_start_d
            )
    else:
        new_start = receipt_start

    new_end = receipt_end
    if pre_end_d and pre_end_d > receipt_end:
        new_end = (
            str(pre_end)
            if pre_end and str(pre_end)[:10] == pre_end_d
            else pre_end_d
        )

    # Recompute with pure date merge for clarity.
    starts = [x for x in (pre_start_d, receipt_start) if x]
    ends = [x for x in (pre_end_d, receipt_end) if x]
    new_start = min(starts)
    new_end = max(ends)
    # Prefer full hot timestamp when same day wins.
    if pre_start and str(pre_start)[:10] == new_start:
        new_start = str(pre_start)
    if pre_end and str(pre_end)[:10] == new_end:
        new_end = str(pre_end)

    now = _now()
    report = {
        "dataset": ds,
        "pre": {
            "observed_start": pre_start,
            "observed_end": pre_end,
            "status": pre.get("status"),
            "row_count": pre.get("row_count"),
            "evaluated_at": pre.get("evaluated_at"),
        },
        "receipt_window": {
            "start": receipt_start,
            "end": receipt_end,
            "n_receipts": receipt.get("n_receipts"),
            "sum_raw": receipt.get("sum_raw"),
        },
        "post_planned": {
            "observed_start": new_start,
            "observed_end": new_end,
            "evaluated_at": now,
        },
        "note": (
            "observed_* from SUCCESS receipts raw_row_count>0 union hot window; "
            "coverage_segments untouched; no COMPLETE claim"
        ),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if new_start >= "2024-01-01" and (
        pre_start_d is None or new_start[:10] >= str(pre_start_d)
    ):
        # Not a hard fail — still apply if receipt evidence exists, but warn.
        print(
            "WARN: planned observed_start still >= 2024-01-01; "
            "need more historical raw+receipt evidence",
            flush=True,
        )

    if args.dry_run:
        print("dry-run: no remote UPDATE")
        return 0

    detail_note = _sql_escape(
        json.dumps(
            {
                "ops_reeval_observed_window": True,
                "receipt_start": receipt_start,
                "receipt_end": receipt_end,
                "receipt_n": receipt.get("n_receipts"),
                "receipt_sum_raw": receipt.get("sum_raw"),
                "pre_observed_start": pre_start,
                "pre_observed_end": pre_end,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    sql = (
        f"UPDATE dataset_coverage SET "
        f"observed_start='{_sql_escape(new_start)}', "
        f"observed_end='{_sql_escape(new_end)}', "
        f"evaluated_at='{_sql_escape(now)}' "
        f"WHERE dataset='{_sql_escape(ds)}';\n"
    )
    # Append a small note into detail_json without wiping existing keys when
    # SQLite json1 is available; fall back to leave detail_json alone on error.
    sql += (
        f"UPDATE dataset_coverage SET detail_json = "
        f"CASE WHEN detail_json IS NULL OR detail_json = '' THEN '{detail_note}' "
        f"ELSE detail_json END "
        f"WHERE dataset='{_sql_escape(ds)}';\n"
    )

    with tempfile.NamedTemporaryFile(
        "w", suffix=".sql", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(sql)
        tmp_path = tmp.name

    cmd = [
        str(WRANGLER),
        "d1",
        "execute",
        DB_NAME,
        "--remote",
        f"--config={WRANGLER_CONFIG}",
        f"--file={tmp_path}",
    ]
    print("running:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT), check=False)
    if proc.returncode != 0:
        print("ERROR: wrangler UPDATE failed", file=sys.stderr)
        return proc.returncode

    post = _first_row(
        _wrangler_json(
            "SELECT dataset, status, observed_start, observed_end, row_count, "
            f"evaluated_at FROM dataset_coverage WHERE dataset='{_sql_escape(ds)}'"
        )
    )
    print("POST", json.dumps(post, ensure_ascii=False))
    post_start = str((post or {}).get("observed_start") or "")[:10]
    if post_start and post_start < "2024-01-01":
        print(f"OK observed_start moved to {post_start} (< 2024-01-01)")
        return 0
    print(
        f"WARN post observed_start={post_start!r} not yet < 2024-01-01",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
