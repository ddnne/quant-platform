#!/usr/bin/env python3
"""Re-eval dataset_coverage.observed_* + C8 from SUCCESS receipts (remote D1).

Why
---
High-volume Premium datasets use R2-only structured writes. D1
``jquants_records`` is hot-window only, so C4/C8 from cold/hot facts can
stick on a residual max event_time (e.g. 2025-02-28) even after recent
raw + receipts landed on R2.

This script unions the receipt plane (SUCCESS + raw_row_count > 0) into
``dataset_coverage.observed_*`` and re-scores ``detail_json.checks`` C8
from that real ``receipt_end`` without:
  * rewriting coverage_segments
  * claiming COMPLETE / Mass / READY
  * inventing event times (only receipt segment_end + calendar lag)

Default dataset: equities_bars_daily.
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
import subprocess
import tempfile
from datetime import date, datetime, timezone

ROOT = ensure_repo_root()
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
DEFAULT_FRESHNESS_DAYS = 7


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


def _calendar_days_between(start: str, end: str) -> int | None:
    try:
        a = date.fromisoformat(str(start)[:10])
        b = date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    return (b - a).days


def _patch_detail_c8(
    detail: dict,
    *,
    dataset: str,
    receipt_start: str,
    receipt_end: str,
    receipt_n: object,
    receipt_sum_raw: object,
    reference: str,
    freshness_days: int,
) -> dict:
    """Rewrite C8 check + observed_window from real receipt evidence."""
    days = _calendar_days_between(receipt_end, reference)
    if days is None:
        raise ValueError(f"cannot lag-compare receipt_end={receipt_end!r} ref={reference!r}")
    if days <= freshness_days:
        c8_status = "pass"
        c8_detail = f"{days} day(s) since latest event_time"
    else:
        c8_status = "fail"
        c8_detail = f"stale: {days} day(s) > {freshness_days}"
    checks = list(detail.get("checks") or [])
    hot_latest = None
    new_checks: list[dict] = []
    found_c8 = False
    for row in checks:
        if not isinstance(row, dict):
            new_checks.append(row)
            continue
        if str(row.get("check_id") or "") != "C8":
            new_checks.append(row)
            continue
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        hot_latest = metrics.get("latest_event_time")
        found_c8 = True
        new_checks.append(
            {
                "check_id": "C8",
                "dataset": dataset,
                "detail": c8_detail,
                "metrics": {
                    "latest_event_time": receipt_end,
                    "reference": reference,
                    "max_days": freshness_days,
                    "days_lag": days,
                    "source": "receipt_observed_end",
                    "hot_latest_event_time": hot_latest,
                },
                "status": c8_status,
            }
        )
    if not found_c8:
        new_checks.append(
            {
                "check_id": "C8",
                "dataset": dataset,
                "detail": c8_detail,
                "metrics": {
                    "latest_event_time": receipt_end,
                    "reference": reference,
                    "max_days": freshness_days,
                    "days_lag": days,
                    "source": "receipt_observed_end",
                    "hot_latest_event_time": None,
                },
                "status": c8_status,
            }
        )
    detail = dict(detail)
    detail["checks"] = new_checks
    detail["observed_window"] = {
        "receipt_start": receipt_start,
        "receipt_end": receipt_end,
        "receipt_raw_rows": receipt_sum_raw,
        "receipt_n": receipt_n,
        "source": "receipt_union_hot",
    }
    detail["status_note"] = (
        f"PARTIAL: segment plane + receipt observed; C8 from receipt_end "
        f"{receipt_end} lag={days}d (source=receipt_observed_end); "
        f"hot_latest={hot_latest!s}; no COMPLETE claim"
    )
    detail["ops_reeval_observed_window"] = {
        "receipt_start": receipt_start,
        "receipt_end": receipt_end,
        "receipt_n": receipt_n,
        "receipt_sum_raw": receipt_sum_raw,
        "c8_status": c8_status,
        "c8_days_lag": days,
        "c8_reference": reference,
        "c8_max_days": freshness_days,
    }
    return detail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dataset",
        default="equities_bars_daily",
        help="Dataset id to re-eval (default equities_bars_daily)",
    )
    ap.add_argument(
        "--freshness-days",
        type=int,
        default=DEFAULT_FRESHNESS_DAYS,
        help=f"C8 max lag days (default {DEFAULT_FRESHNESS_DAYS})",
    )
    ap.add_argument(
        "--today",
        default=None,
        help="C8 reference date YYYY-MM-DD (default: today UTC)",
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
            f"evaluated_at, detail_json FROM dataset_coverage "
            f"WHERE dataset='{_sql_escape(ds)}'"
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

    reference = (args.today or datetime.now(timezone.utc).date().isoformat())[:10]
    raw_detail = pre.get("detail_json") or "{}"
    try:
        detail_obj = json.loads(raw_detail) if isinstance(raw_detail, str) else dict(raw_detail)
    except (TypeError, ValueError, json.JSONDecodeError):
        detail_obj = {}
    if not isinstance(detail_obj, dict):
        detail_obj = {}
    pre_c8 = None
    for row in detail_obj.get("checks") or []:
        if isinstance(row, dict) and row.get("check_id") == "C8":
            pre_c8 = {
                "status": row.get("status"),
                "detail": row.get("detail"),
                "metrics": row.get("metrics"),
            }
            break
    new_detail = _patch_detail_c8(
        detail_obj,
        dataset=ds,
        receipt_start=receipt_start,
        receipt_end=receipt_end,
        receipt_n=receipt.get("n_receipts"),
        receipt_sum_raw=receipt.get("sum_raw"),
        reference=reference,
        freshness_days=int(args.freshness_days),
    )
    post_c8 = None
    for row in new_detail.get("checks") or []:
        if isinstance(row, dict) and row.get("check_id") == "C8":
            post_c8 = {
                "status": row.get("status"),
                "detail": row.get("detail"),
                "metrics": row.get("metrics"),
            }
            break

    now = _now()
    report = {
        "dataset": ds,
        "pre": {
            "observed_start": pre_start,
            "observed_end": pre_end,
            "status": pre.get("status"),
            "row_count": pre.get("row_count"),
            "evaluated_at": pre.get("evaluated_at"),
            "c8": pre_c8,
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
            "c8": post_c8,
            "c8_reference": reference,
        },
        "note": (
            "observed_* + detail_json C8 from SUCCESS receipts raw_row_count>0; "
            "coverage_segments untouched; status not forced to COMPLETE"
        ),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if new_start >= "2024-01-01" and (
        pre_start_d is None or new_start[:10] >= str(pre_start_d)
    ):
        print(
            "WARN: planned observed_start still >= 2024-01-01; "
            "need more historical raw+receipt evidence",
            flush=True,
        )

    if args.dry_run:
        print("dry-run: no remote UPDATE")
        return 0

    detail_sql = _sql_escape(
        json.dumps(new_detail, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    sql = (
        f"UPDATE dataset_coverage SET "
        f"observed_start='{_sql_escape(new_start)}', "
        f"observed_end='{_sql_escape(new_end)}', "
        f"evaluated_at='{_sql_escape(now)}', "
        f"detail_json='{detail_sql}' "
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
            f"evaluated_at, detail_json FROM dataset_coverage "
            f"WHERE dataset='{_sql_escape(ds)}'"
        )
    )
    post_out = dict(post or {})
    raw_post_detail = post_out.pop("detail_json", None)
    post_c8_live = None
    if raw_post_detail:
        try:
            d = json.loads(raw_post_detail)
            for row in d.get("checks") or []:
                if isinstance(row, dict) and row.get("check_id") == "C8":
                    post_c8_live = {
                        "status": row.get("status"),
                        "detail": row.get("detail"),
                        "metrics": row.get("metrics"),
                    }
                    break
        except (TypeError, ValueError, json.JSONDecodeError):
            post_c8_live = {"error": "detail_json parse failed"}
    post_out["c8"] = post_c8_live
    print("POST", json.dumps(post_out, ensure_ascii=False))
    post_start = str((post or {}).get("observed_start") or "")[:10]
    if post_c8_live and post_c8_live.get("status") == "pass":
        print(f"OK detail_json C8 pass lag={post_c8_live.get('metrics', {}).get('days_lag')}")
    else:
        print(f"WARN detail_json C8 not pass: {post_c8_live!r}", flush=True)
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
