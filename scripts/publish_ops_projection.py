#!/usr/bin/env python3
"""Not a production publisher.

Cloud publication is ingestion-premium scheduled work against the dedicated
projection D1. Offline fixture rendering is scripts/export_ops_projection.py.
This CLI exists only to refuse leftover local-publisher entrypoints.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--meta-output", type=Path)
    parser.add_argument("--storage-hot-cutoff", default=None)
    parser.add_argument("--refresh-coverage", action="store_true")
    parser.add_argument("--otc-index-html", type=Path, default=None)
    parser.add_argument("--apply-remote", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.parse_args(argv)
    print(
        "ERROR: Mac-local publish_ops_projection.py is not a production "
        "authority. Cloud publication is ingestion-premium scheduled work. "
        "Offline fixture rendering is scripts/export_ops_projection.py.",
        file=sys.stderr,
    )
    return 7


if __name__ == "__main__":
    raise SystemExit(main())
