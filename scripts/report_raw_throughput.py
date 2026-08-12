#!/usr/bin/env python3
"""PRE/POST raw + coverage throughput report for Track A acceleration.

Aggregates (from a research-mirror DB — **not** CF SoT unless synced):
  * raw_retention_manifests counts / bytes / by dataset
  * jquants_records row counts + event_time span
  * coverage_segments COMPLETE / PARTIAL
  * dataset_coverage COMPLETE / STALE / PARTIAL
  * Track A focus metrics
  * optional projection_meta status
  * optional --baseline JSON for PRE→POST delta

Outputs JSON and/or Markdown. Never fabricates COMPLETE.

Usage:
  python scripts/report_raw_throughput.py
  python scripts/report_raw_throughput.py --format both --out-dir docs/proof
  python scripts/report_raw_throughput.py --baseline data/reports/throughput_pre.json
"""

from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap repo root onto sys.path before importing qp_paths (plain script runs).
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
import sqlite3
from datetime import datetime, timezone
from typing import Any

ROOT = repo_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.range_batch_scheduler import TRACK_A_DATASETS  # noqa: E402

REPORT_VERSION = "raw-throughput/v1"


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def _safe_count(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    try:
        return int(conn.execute(sql, params).fetchone()[0] or 0)
    except sqlite3.Error:
        return 0


def collect_metrics(db_path: Path, *, label: str = "snapshot") -> dict[str, Any]:
    """Collect throughput / coverage metrics from a sqlite path."""
    out: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "label": label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(db_path),
        "db_note": (
            "Local/research mirror metrics. Not CF control-plane SoT unless "
            "this file was synced from D1. Do not treat as sole evidence of COMPLETE."
        ),
        "raw_retention_manifests": {
            "total": 0,
            "complete": 0,
            "failed": 0,
            "sum_row_count": 0,
            "sum_raw_bytes": 0,
            "by_dataset": [],
        },
        "jquants_records": {
            "total": 0,
            "by_dataset": [],
        },
        "coverage_segments": {
            "total": 0,
            "by_status": {},
            "complete": 0,
            "partial": 0,
        },
        "dataset_coverage": {
            "total": 0,
            "complete": 0,
            "stale": 0,
            "partial": 0,
            "by_status": {},
            "stale_datasets": [],
            "complete_datasets": [],
        },
        "track_a": {},
        "projection": None,
        "errors": [],
    }

    if not db_path.is_file():
        out["errors"].append(f"db missing: {db_path}")
        return out

    conn = _connect_ro(db_path)
    try:
        # raw_retention_manifests
        if _table_exists(conn, "raw_retention_manifests"):
            out["raw_retention_manifests"]["total"] = _safe_count(
                conn, "SELECT COUNT(*) FROM raw_retention_manifests"
            )
            out["raw_retention_manifests"]["complete"] = _safe_count(
                conn,
                "SELECT COUNT(*) FROM raw_retention_manifests WHERE completeness='COMPLETE'",
            )
            out["raw_retention_manifests"]["failed"] = _safe_count(
                conn,
                "SELECT COUNT(*) FROM raw_retention_manifests WHERE completeness='FAILED'",
            )
            row = conn.execute(
                "SELECT COALESCE(SUM(row_count),0), COALESCE(SUM(raw_bytes),0) "
                "FROM raw_retention_manifests"
            ).fetchone()
            out["raw_retention_manifests"]["sum_row_count"] = int(row[0] or 0)
            out["raw_retention_manifests"]["sum_raw_bytes"] = int(row[1] or 0)
            by_ds = []
            for r in conn.execute(
                """
                SELECT dataset,
                       COUNT(*) AS n,
                       SUM(CASE WHEN completeness='COMPLETE' THEN 1 ELSE 0 END) AS n_ok,
                       COALESCE(SUM(row_count),0) AS rows,
                       COALESCE(SUM(raw_bytes),0) AS bytes
                FROM raw_retention_manifests
                GROUP BY dataset
                ORDER BY dataset
                """
            ):
                by_ds.append(
                    {
                        "dataset": r[0],
                        "manifests": int(r[1]),
                        "complete_manifests": int(r[2] or 0),
                        "row_count": int(r[3] or 0),
                        "raw_bytes": int(r[4] or 0),
                    }
                )
            out["raw_retention_manifests"]["by_dataset"] = by_ds
        else:
            out["errors"].append("table raw_retention_manifests missing")

        # jquants_records
        if _table_exists(conn, "jquants_records"):
            out["jquants_records"]["total"] = _safe_count(
                conn, "SELECT COUNT(*) FROM jquants_records"
            )
            rec_rows = []
            try:
                for r in conn.execute(
                    """
                    SELECT dataset, COUNT(*), MIN(event_time), MAX(event_time)
                    FROM jquants_records
                    GROUP BY dataset
                    ORDER BY dataset
                    """
                ):
                    rec_rows.append(
                        {
                            "dataset": r[0],
                            "rows": int(r[1]),
                            "event_time_min": r[2],
                            "event_time_max": r[3],
                        }
                    )
            except sqlite3.Error as exc:
                out["errors"].append(f"jquants_records groupby failed: {exc}")
            out["jquants_records"]["by_dataset"] = rec_rows
        else:
            out["errors"].append("table jquants_records missing")

        # coverage_segments
        if _table_exists(conn, "coverage_segments"):
            out["coverage_segments"]["total"] = _safe_count(
                conn, "SELECT COUNT(*) FROM coverage_segments"
            )
            by_status: dict[str, int] = {}
            for r in conn.execute(
                "SELECT status, COUNT(*) FROM coverage_segments GROUP BY status"
            ):
                by_status[str(r[0])] = int(r[1])
            out["coverage_segments"]["by_status"] = by_status
            out["coverage_segments"]["complete"] = by_status.get("COMPLETE", 0)
            out["coverage_segments"]["partial"] = by_status.get("PARTIAL", 0)
        else:
            out["errors"].append("table coverage_segments missing")

        # dataset_coverage
        if _table_exists(conn, "dataset_coverage"):
            out["dataset_coverage"]["total"] = _safe_count(
                conn, "SELECT COUNT(*) FROM dataset_coverage"
            )
            by_status = {}
            stale_list: list[str] = []
            complete_list: list[str] = []
            for r in conn.execute(
                "SELECT dataset, status FROM dataset_coverage ORDER BY dataset"
            ):
                ds, st = str(r[0]), str(r[1])
                by_status[st] = by_status.get(st, 0) + 1
                if st == "STALE":
                    stale_list.append(ds)
                if st == "COMPLETE":
                    complete_list.append(ds)
            out["dataset_coverage"]["by_status"] = by_status
            out["dataset_coverage"]["complete"] = by_status.get("COMPLETE", 0)
            out["dataset_coverage"]["stale"] = by_status.get("STALE", 0)
            out["dataset_coverage"]["partial"] = by_status.get("PARTIAL", 0)
            out["dataset_coverage"]["stale_datasets"] = stale_list
            out["dataset_coverage"]["complete_datasets"] = complete_list
        else:
            out["errors"].append("table dataset_coverage missing")

        # Track A focus
        rec_index = {
            r["dataset"]: r for r in out["jquants_records"].get("by_dataset", [])
        }
        raw_index = {
            r["dataset"]: r
            for r in out["raw_retention_manifests"].get("by_dataset", [])
        }
        track: dict[str, Any] = {}
        for ds in TRACK_A_DATASETS:
            entry: dict[str, Any] = {
                "dataset": ds,
                "complete_segments": 0,
                "total_segments": 0,
                "dataset_status": None,
                "records": rec_index.get(ds),
                "raw_manifests": raw_index.get(ds),
            }
            if _table_exists(conn, "coverage_segments"):
                r = conn.execute(
                    """
                    SELECT
                      SUM(CASE WHEN status='COMPLETE' THEN 1 ELSE 0 END),
                      COUNT(*)
                    FROM coverage_segments WHERE dataset=?
                    """,
                    (ds,),
                ).fetchone()
                entry["complete_segments"] = int(r[0] or 0) if r else 0
                entry["total_segments"] = int(r[1] or 0) if r else 0
            if _table_exists(conn, "dataset_coverage"):
                r = conn.execute(
                    "SELECT status FROM dataset_coverage WHERE dataset=? LIMIT 1",
                    (ds,),
                ).fetchone()
                entry["dataset_status"] = r[0] if r else None
            track[ds] = entry
        out["track_a"] = track
    finally:
        conn.close()

    # projection meta (optional file)
    proj_path = ROOT / "data" / "ops" / "projection_meta.json"
    if proj_path.is_file():
        try:
            meta = json.loads(proj_path.read_text(encoding="utf-8"))
            out["projection"] = {
                "status": meta.get("status") or meta.get("projection_status"),
                "active_generation": meta.get("active_generation"),
                "generated_at": meta.get("generated_at")
                or meta.get("projection_generated_at"),
                "path": str(proj_path),
            }
        except (OSError, json.JSONDecodeError) as exc:
            out["errors"].append(f"projection_meta read failed: {exc}")

    return out


def delta_metrics(pre: MappingLike, post: MappingLike) -> dict[str, Any]:
    """Compute numeric deltas for key counters."""

    def g(d: Any, *path: str, default: int = 0) -> int:
        cur = d
        for p in path:
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
        try:
            return int(cur)
        except (TypeError, ValueError):
            return default

    return {
        "raw_manifests_total": g(post, "raw_retention_manifests", "total")
        - g(pre, "raw_retention_manifests", "total"),
        "raw_manifests_complete": g(post, "raw_retention_manifests", "complete")
        - g(pre, "raw_retention_manifests", "complete"),
        "jquants_records_total": g(post, "jquants_records", "total")
        - g(pre, "jquants_records", "total"),
        "complete_segments": g(post, "coverage_segments", "complete")
        - g(pre, "coverage_segments", "complete"),
        "complete_datasets": g(post, "dataset_coverage", "complete")
        - g(pre, "dataset_coverage", "complete"),
        "stale_datasets": g(post, "dataset_coverage", "stale")
        - g(pre, "dataset_coverage", "stale"),
        "note": "Positive delta = growth. COMPLETE never auto-claimed by this report.",
    }


# typing alias without importing Mapping only for runtime simplicity
MappingLike = dict[str, Any]


def to_markdown(report: dict[str, Any]) -> str:
    """Human-readable Markdown summary."""
    lines: list[str] = []
    lines.append(f"# Raw throughput report ({report.get('label', 'snapshot')})")
    lines.append("")
    lines.append(f"- generated_at: `{report.get('generated_at')}`")
    lines.append(f"- db: `{report.get('db_path')}`")
    lines.append(f"- note: {report.get('db_note')}")
    lines.append("")
    raw = report.get("raw_retention_manifests") or {}
    lines.append("## raw_retention_manifests")
    lines.append("")
    lines.append(f"| metric | value |")
    lines.append(f"|--------|------:|")
    lines.append(f"| total | {raw.get('total', 0)} |")
    lines.append(f"| COMPLETE | {raw.get('complete', 0)} |")
    lines.append(f"| FAILED | {raw.get('failed', 0)} |")
    lines.append(f"| sum_row_count | {raw.get('sum_row_count', 0)} |")
    lines.append(f"| sum_raw_bytes | {raw.get('sum_raw_bytes', 0)} |")
    lines.append("")
    segs = report.get("coverage_segments") or {}
    ds = report.get("dataset_coverage") or {}
    lines.append("## coverage")
    lines.append("")
    lines.append(f"| metric | value |")
    lines.append(f"|--------|------:|")
    lines.append(f"| complete_segments | {segs.get('complete', 0)} |")
    lines.append(f"| partial_segments | {segs.get('partial', 0)} |")
    lines.append(f"| complete_datasets | {ds.get('complete', 0)} |")
    lines.append(f"| stale_datasets | {ds.get('stale', 0)} |")
    lines.append(
        f"| complete_dataset_ids | {', '.join(ds.get('complete_datasets') or []) or '—'} |"
    )
    lines.append(
        f"| stale_dataset_ids | {', '.join(ds.get('stale_datasets') or []) or '—'} |"
    )
    lines.append("")
    proj = report.get("projection")
    if proj:
        lines.append("## projection")
        lines.append("")
        lines.append(f"- status: **{proj.get('status')}**")
        lines.append(f"- generation: `{proj.get('active_generation')}`")
        lines.append("")
    lines.append("## Track A focus")
    lines.append("")
    lines.append(
        "| dataset | status | complete/total segs | records | event_time span |"
    )
    lines.append(
        "|---------|--------|--------------------:|--------:|-----------------|"
    )
    for ds_id, entry in (report.get("track_a") or {}).items():
        rec = entry.get("records") or {}
        span = "—"
        if rec:
            span = f"{rec.get('event_time_min')} → {rec.get('event_time_max')}"
        lines.append(
            f"| {ds_id} | {entry.get('dataset_status')} | "
            f"{entry.get('complete_segments')}/{entry.get('total_segments')} | "
            f"{(rec or {}).get('rows', 0)} | {span} |"
        )
    lines.append("")
    if report.get("pre_post_delta"):
        lines.append("## PRE→POST delta")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(report["pre_post_delta"], indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")
    if report.get("errors"):
        lines.append("## errors")
        lines.append("")
        for e in report["errors"]:
            lines.append(f"- {e}")
        lines.append("")
    lines.append("---")
    lines.append(
        "Evidence closure: COMPLETE only with raw+structured. "
        "This report never forges COMPLETE/READY/Mass."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data/structured/ingestion.sqlite",
        help="Research-mirror sqlite (not CF SoT unless synced)",
    )
    ap.add_argument("--label", default="snapshot", help="PRE / POST / snapshot label")
    ap.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Prior report JSON for PRE→POST delta",
    )
    ap.add_argument(
        "--format",
        choices=["json", "markdown", "both"],
        default="both",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="If set, write report files here",
    )
    ap.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help="Explicit JSON output path",
    )
    ap.add_argument(
        "--out-md",
        type=Path,
        default=None,
        help="Explicit Markdown output path",
    )
    args = ap.parse_args(argv)

    report = collect_metrics(args.db, label=args.label)
    if args.baseline and args.baseline.is_file():
        try:
            pre = json.loads(args.baseline.read_text(encoding="utf-8"))
            report["baseline_path"] = str(args.baseline)
            report["pre_post_delta"] = delta_metrics(pre, report)
        except (OSError, json.JSONDecodeError) as exc:
            report.setdefault("errors", []).append(f"baseline load failed: {exc}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_json = args.out_json
    out_md = args.out_md
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        if out_json is None:
            out_json = args.out_dir / f"raw_throughput_{args.label}_{stamp}.json"
        if out_md is None and args.format in ("markdown", "both"):
            out_md = args.out_dir / f"raw_throughput_{args.label}_{stamp}.md"

    if args.format in ("json", "both"):
        text = json.dumps(report, indent=2, ensure_ascii=False)
        if out_json:
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text(text + "\n", encoding="utf-8")
            print(f"wrote {out_json}", flush=True)
        else:
            print(text)

    if args.format in ("markdown", "both"):
        md = to_markdown(report)
        if out_md:
            out_md.parent.mkdir(parents=True, exist_ok=True)
            out_md.write_text(md, encoding="utf-8")
            print(f"wrote {out_md}", flush=True)
        elif args.format == "markdown":
            print(md)

    # Always print one-line summary
    segs = report.get("coverage_segments") or {}
    ds = report.get("dataset_coverage") or {}
    raw = report.get("raw_retention_manifests") or {}
    print(
        f"SUMMARY label={report.get('label')} raw_manifests={raw.get('total', 0)} "
        f"complete_segs={segs.get('complete', 0)} complete_ds={ds.get('complete', 0)} "
        f"stale_ds={ds.get('stale', 0)} "
        f"stale={','.join(ds.get('stale_datasets') or []) or '—'} "
        f"proj={(report.get('projection') or {}).get('status')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
