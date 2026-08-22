#!/usr/bin/env python3
"""Plan + fetch official JSDA OTC archive PARTIAL days (not a wave runner).

Picks remaining official month_csv days that are still PARTIAL, newer-first,
n=50..100. Does not invent COMPLETE. Tip-wait stays unpublished.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
from _bootstrap import ensure_repo_root

ROOT = ensure_repo_root()
WORKER = "https://quant-platform-jsda-otc-probe-w80.taku-haga.workers.dev"
FULL_OK_MIN = 100_000


def code_to_day(code: str) -> str | None:
    if not code or not code.startswith("S") or len(code) != 7 or not code[1:].isdigit():
        return None
    yy, mm, dd = int(code[1:3]), int(code[3:5]), int(code[5:7])
    year = 2000 + yy if yy < 80 else 1900 + yy
    return f"{year:04d}-{mm:02d}-{dd:02d}"


def discover_year(year: int, cache: Path) -> list[dict]:
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.is_file():
        url = f"{WORKER}/discover?year={year}"
        proc = subprocess.run(
            ["curl", "-sS", "--max-time", "120", url],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise SystemExit(f"discover failed year={year} rc={proc.returncode}")
        cache.write_text(proc.stdout)
    data = json.loads(cache.read_text())
    out = []
    for ln in data.get("links") or []:
        if ln.get("kind") != "reference" or ln.get("path_style") != "month_csv":
            continue
        day = code_to_day(ln.get("code") or "")
        if not day:
            continue
        item = dict(ln)
        item["year"] = year
        item["day"] = day
        out.append(item)
    out.sort(key=lambda x: x["day"], reverse=True)
    return out


def write_full_ok(log: Path, items: list[dict]) -> Path:
    by_day = {}
    progress = log / "otc_download_progress.jsonl"
    if progress.exists():
        for ln in progress.read_text().splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            if r.get("status") == "OK" and int(r.get("size") or 0) > FULL_OK_MIN:
                by_day[r["day"]] = r
    out = []
    for item in items:
        rec = by_day.get(item["day"])
        if not rec:
            continue
        path = rec.get("path") or ""
        row = dict(item)
        row["size"] = rec["size"]
        row["path"] = path
        out.append(row)
    dest = log / "otc_full_ok.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    if len(out) != len(items):
        missing = [x["day"] for x in items if x["day"] not in by_day]
        raise SystemExit(f"missing FULL_OK days n={len(missing)} sample={missing[:8]}")
    return dest


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, default=2003)
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--log-dir", type=Path, default=ROOT / "data" / "ops" / "otc_official_backfill")
    p.add_argument("--db", type=Path, default=ROOT / "data" / "structured" / "ingestion.sqlite")
    p.add_argument("--before", type=str, default=None, help="only days < this (default: min COMPLETE)")
    p.add_argument("--fetch", action="store_true")
    p.add_argument("--make-full-ok", action="store_true")
    args = p.parse_args()
    if not (50 <= int(args.n) <= 100):
        raise SystemExit("--n must be 50..100")
    log = args.log_dir
    log.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    partial = {
        r[0]
        for r in con.execute(
            "SELECT segment_id FROM coverage_segments "
            "WHERE dataset='jsda_otc_bond_reference_prices' AND status='PARTIAL'"
        )
    }
    complete_span = con.execute(
        "SELECT MIN(segment_id), MAX(segment_id) FROM coverage_segments "
        "WHERE dataset='jsda_otc_bond_reference_prices' AND status='COMPLETE'"
    ).fetchone()
    complete_n = con.execute(
        "SELECT COUNT(*) FROM coverage_segments "
        "WHERE dataset='jsda_otc_bond_reference_prices' AND status='COMPLETE'"
    ).fetchone()[0]
    con.close()
    before = args.before or (complete_span[0] if complete_span and complete_span[0] else "9999-12-31")
    links = discover_year(int(args.year), log / f"otc_discover_{args.year}.json")
    pool = [x for x in links if x["day"] < before and x["day"] in partial]
    items = pool[: int(args.n)]
    (log / "otc_items.json").write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n")
    plan = {
        "kind": "jsda_otc_official_backfill",
        "year": int(args.year),
        "n": len(items),
        "before": before,
        "complete_pre": complete_n,
        "complete_span_pre": list(complete_span),
        "pool": len(pool),
        "remaining_after": len(pool) - len(items),
        "span": [items[0]["day"], items[-1]["day"]] if items else None,
        "gate": "FULL_OK_HISTORICAL http200 size>100000 parse_nz",
        "worker": WORKER,
        "order": "newer_first",
        "invent": False,
        "days": [x["day"] for x in items],
    }
    (log / "otc_plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(json.dumps({k: plan[k] for k in plan if k != "days"}, indent=2))
    if args.fetch:
        rc = subprocess.call(
            [
                "python3",
                str(ROOT / "scripts" / "jsda_otc_fetch_official.py"),
                "--log-dir",
                str(log),
                "--items",
                str(log / "otc_items.json"),
                "--repo",
                str(ROOT),
            ]
        )
        if rc != 0:
            return rc
    if args.make_full_ok or args.fetch:
        write_full_ok(log, items)
        print("wrote", log / "otc_full_ok.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
