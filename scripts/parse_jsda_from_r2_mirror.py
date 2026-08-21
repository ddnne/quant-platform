#!/usr/bin/env python3
"""Parse JSDA raw (R2 mirror or local raw/jsda) via trusted issuer path.

Does not enable mass research. Does not fetch from network.
"""

from __future__ import annotations

import argparse
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
from _bootstrap import ensure_repo_root

ROOT = ensure_repo_root()

from ingestion.jsda.r2_parse import run_trusted_jsda_parse  # noqa: E402

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--raw-root",
        default=str(ROOT / "data" / "raw"),
        help="Root containing jsda/ content-addressed raw tree",
    )
    ap.add_argument(
        "--db",
        default=str(ROOT / "data" / "structured" / "ingestion.sqlite"),
    )
    ap.add_argument("--run-id", type=int, default=1)
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    try:
        result = run_trusted_jsda_parse(
            raw_root=Path(args.raw_root),
            conn=conn,
            run_id=args.run_id,
        )
    finally:
        conn.close()
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if not result.errors else 1

if __name__ == "__main__":
    raise SystemExit(main())
