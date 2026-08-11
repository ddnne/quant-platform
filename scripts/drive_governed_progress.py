#!/usr/bin/env python3
"""Report governed COMPLETE progress (honest, no faking)."""
from __future__ import annotations
import json, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data_contracts import all_coverage_contracts

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
