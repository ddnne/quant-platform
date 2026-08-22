#!/usr/bin/env python3
"""Record a daily_path_DD table into eval registry staging (R2/D1 is SoT).

Does not create wave proofs. Does not promote candidates.
"""
from __future__ import annotations

import argparse
import json
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
from research.cf_daily_path_job import FANOUT_VERSION
from research.daily_path_eval import git_sha
from research.eval_registry import (
    PROTOCOL_DAILY_PATH,
    d1_upsert_sql,
    dumps_manifest,
    manifest_from_window_rows,
    r2_cells_key,
    r2_manifest_key,
    write_manifest_local,
)

ROOT = ensure_repo_root()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job-id", required=True)
    p.add_argument("--table", type=Path, required=True, help="JSON array of window rows")
    p.add_argument("--staging-dir", type=Path, default=ROOT / "data" / "ops" / "research_eval")
    p.add_argument("--one-way-cost", type=float, default=0.001)
    p.add_argument("--notes", type=str, default="")
    p.add_argument("--put-r2", action="store_true")
    p.add_argument("--apply-d1", action="store_true")
    args = p.parse_args()
    rows = json.loads(args.table.read_text())
    if not isinstance(rows, list):
        raise SystemExit("table must be a JSON array")
    man = manifest_from_window_rows(
        job_id=str(args.job_id),
        protocol=PROTOCOL_DAILY_PATH,
        git_sha=git_sha(cwd=ROOT),
        rows=rows,
        one_way_cost=float(args.one_way_cost),
        factory_version=FANOUT_VERSION,
        notes=args.notes,
    )
    local = write_manifest_local(man, args.staging_dir)
    print("staged", local)
    sql_path = local.parent / "d1_upsert.sql"
    sql_path.write_text(d1_upsert_sql(man), encoding="utf-8")
    print("sql", sql_path)
    if args.put_r2:
        man_tmp = local
        cells_tmp = local.parent / "cells.json"
        wr = ROOT / "platform" / "workers" / "ingestion-premium" / "node_modules" / ".bin" / "wrangler"
        cfg = ROOT / "platform" / "workers" / "ingestion-premium" / "wrangler.toml"
        wr_bin = str(wr) if wr.is_file() else "npx"
        for key, path in (
            (r2_manifest_key(man.job_id), man_tmp),
            (r2_cells_key(man.job_id), cells_tmp),
        ):
            cmd = [wr_bin] if wr.is_file() else ["npx", "wrangler"]
            cmd += [
                "r2",
                "object",
                "put",
                f"quant-structured/{key}",
                f"--file={path}",
                f"--config={cfg}",
                "--remote",
            ]
            print("running", " ".join(cmd))
            rc = subprocess.call(cmd, cwd=str(ROOT / "platform" / "workers" / "ingestion-premium"))
            if rc != 0:
                return rc
    if args.apply_d1:
        cmd = [
            "npx",
            "wrangler",
            "d1",
            "execute",
            "quant-ingest",
            "--remote",
            f"--file={sql_path}",
        ]
        print("running", " ".join(cmd))
        rc = subprocess.call(cmd, cwd=str(ROOT / "platform" / "workers" / "quant-ops-mcp"))
        if rc != 0:
            return rc
    print(dumps_manifest(man)[:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
