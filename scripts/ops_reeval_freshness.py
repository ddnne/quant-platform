#!/usr/bin/env python3
"""Phase 6.3 — targeted remote freshness (no full publish, no segment rewrite).

Advances dataset_coverage.evaluated_at and rotates ops projection FRESH clock
on remote D1. Never touches coverage_segments / COMPLETE evidence.

Design intent: GLM Phase 6.3 Worker2. Live D1 schema alignment applied so
wrangler SQL matches quant-ingest (generation_id, not id).

Mass / READY / B0: NO-GO.
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
import uuid
from datetime import datetime, timezone

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
DATASETS = (
    "equities_master",
    "markets_calendar",
    "jsda_otc_bond_reference_prices",
    "jsda_corporate_bond_transactions",
    "jsda_tokyo_repo_rates",
)

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _sql_escape(value: str) -> str:
    return value.replace("'", "''")

def build_sql(now: str, gen: str, commit: str) -> str:
    lines: list[str] = []
    for ds in DATASETS:
        lines.append(
            f"UPDATE dataset_coverage SET evaluated_at='{_sql_escape(now)}' "
            f"WHERE dataset='{_sql_escape(ds)}';"
        )
    detail = _sql_escape(
        json.dumps(
            {
                "refresh_status": "ops_reeval_freshness",
                "note": "targeted freshness; coverage_segments untouched; Mass NO-GO",
            },
            ensure_ascii=False,
        )
    )
    sha = _sql_escape(commit)
    lines.append(
        "INSERT OR REPLACE INTO ops_projection_generation ("
        "generation_id, status, source_db_digest, generated_at, producer_commit_sha, "
        "contract_digest, registry_digest, coverage_policy_version, activated_at, detail_json"
        f") VALUES ('{_sql_escape(gen)}', 'ACTIVE', NULL, '{_sql_escape(now)}', '{sha}', "
        f"NULL, NULL, 'collection-coverage/v2', '{_sql_escape(now)}', '{detail}');"
    )
    lines.append(
        f"UPDATE ops_projection_generation SET status='RETIRED' "
        f"WHERE generation_id != '{_sql_escape(gen)}' AND status='ACTIVE';"
    )
    lines.append(
        f"UPDATE ops_projection_active SET generation_id='{_sql_escape(gen)}', "
        f"activated_at='{_sql_escape(now)}' WHERE singleton=1;"
    )
    meta_detail = _sql_escape(
        json.dumps(
            {
                "active_generation": gen,
                "max_age_seconds": 86400,
                "refresh_status": "ops_reeval_freshness",
                "complete_segments_untouched": True,
            },
            ensure_ascii=False,
        )
    )
    lines.append(
        "UPDATE ops_projection_metadata SET "
        f"generated_at='{_sql_escape(now)}', source_generation='{_sql_escape(now)}', "
        f"age_seconds=0, status='FRESH', projection_generation_id='{_sql_escape(gen)}', "
        f"detail_json='{meta_detail}' "
        "WHERE id=(SELECT id FROM ops_projection_metadata ORDER BY id DESC LIMIT 1);"
    )
    return "\n".join(lines) + "\n"

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not WRANGLER.is_file():
        print(f"ERROR: wrangler not found: {WRANGLER}", file=sys.stderr)
        return 2

    now = _now()
    gen = f"projgen-{uuid.uuid4().hex}"
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"

    sql = build_sql(now, gen, commit)
    print(f"ops_reeval_freshness gen={gen} now={now}")
    if args.dry_run:
        print(sql)
        return 0

    tmp = Path("/tmp") / f"ops_reeval_{uuid.uuid4().hex[:8]}.sql"
    tmp.write_text(sql, encoding="utf-8")
    cmd = [
        str(WRANGLER),
        "d1",
        "execute",
        DB_NAME,
        "--remote",
        f"--config={WRANGLER_CONFIG}",
        f"--file={tmp}",
    ]
    print("running:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), check=False)
    if proc.returncode != 0:
        print("ERROR: wrangler failed", file=sys.stderr)
        return proc.returncode

    meta_path = ROOT / "data" / "ops" / "projection_meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(
            {
                "status": "FRESH",
                "projection_status": "FRESH",
                "generated_at": now,
                "applied_at": now,
                "active_generation": gen,
                "source_generation": now,
                "age_seconds": 0,
                "publisher": "scripts/ops_reeval_freshness.py",
                "last_refresh_status": "ops_reeval_freshness",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {meta_path}")
    print("OK coverage_segments_untouched=1 mass=NO-GO")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
