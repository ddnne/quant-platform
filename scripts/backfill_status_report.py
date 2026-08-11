#!/usr/bin/env python3
"""Report Coverage V2 / inventory backfill status vs canonical contracts."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data_contracts.inventory import source_inventory
from data_contracts.coverage import all_coverage_contracts
from storage.sqlite_store import SqliteStore

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', type=Path, default=ROOT/'data/structured/ingestion.sqlite')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()
    inv = source_inventory()
    out = {
        'inventory': inv,
        'coverage_contracts': len(list(all_coverage_contracts())),
        'local_db': str(args.db),
        'local': {},
    }
    if args.db.exists():
        s = SqliteStore(args.db)
        c = s._conn
        out['local'] = {
            'dataset_coverage_rows': c.execute('select count(*) from dataset_coverage').fetchone()[0],
            'coverage_segments': c.execute('select count(*) from coverage_segments').fetchone()[0],
            'collection_receipts': c.execute('select count(*) from collection_receipts').fetchone()[0],
            'watermarks': c.execute('select count(*) from ingestion_watermarks').fetchone()[0],
            'jquants_records': c.execute('select count(*) from jquants_records').fetchone()[0],
            'validation_rows': c.execute('select count(*) from ingestion_validation').fetchone()[0],
        }
        gaps = list(c.execute(
            "select dataset,status from dataset_coverage where status != 'COMPLETE' order by dataset"
        ))
        out['local']['incomplete'] = [{'dataset': d, 'status': st} for d, st in gaps]
        s.close()
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"known endpoints: {inv['total_known_endpoints']} governed={inv['governed_count']}")
        print(f"coverage contracts: {out['coverage_contracts']}")
        print(f"local: {out['local']}")
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
