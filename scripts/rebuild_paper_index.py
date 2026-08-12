#!/usr/bin/env python3
"""Rebuild the paper experiment index from immutable result JSON files."""

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

ROOT = repo_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.paper import JsonPaperStore  # noqa: E402

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the SQLite paper index from immutable JSON"
    )
    parser.add_argument("--root", default="data/paper")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    store = JsonPaperStore(args.root)
    count = store.rebuild_index()
    result = {"index": str(store.index_path), "records": count, "status": "rebuilt"}
    print(json.dumps(result, sort_keys=True) if args.json else result)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
