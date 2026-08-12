#!/usr/bin/env python3
"""Parse JSDA raw (R2 mirror or local raw/jsda) via trusted issuer path.

Does not enable mass research. Does not fetch from network.
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

ROOT = repo_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
