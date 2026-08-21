#!/usr/bin/env python3
"""Report governed COMPLETE progress (honest, no faking)."""
from __future__ import annotations

import json
import sqlite3
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
from _bootstrap import ensure_repo_root

from data_contracts import all_coverage_contracts

ROOT = ensure_repo_root()

def main():
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT/"data/structured/ingestion.sqlite"
    governed = sorted(p.dataset_id for p in all_coverage_contracts() if p.governance_tier=="governed")
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    rows = {r["dataset"]: dict(r) for r in c.execute("select * from dataset_coverage")}
    complete = [d for d in governed if rows.get(d,{}).get("status")=="COMPLETE"]
    partial = [d for d in governed if d not in complete]
    rc = c.execute("select count(*) from collection_receipts").fetchone()[0]
    out = {
        "governed_total": len(governed),
        "complete_count": len(complete),
        "complete": complete,
        "partial_or_missing": partial,
        "receipts": rc,
        "ready_go": len(complete)==len(governed) and len(governed)>0,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out["ready_go"] else 1
if __name__=="__main__":
    raise SystemExit(main())
