#!/usr/bin/env python3
"""Fail closed if quant-ops-mcp governed.js drifts from Coverage Contract.

Implements Phase 6.2.2 §9: generated membership embeds source digest and
build/deploy must fail on drift.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_contracts.coverage import all_coverage_contracts  # noqa: E402

GOVERNED_JS = ROOT / "platform/workers/quant-ops-mcp/src/governed.js"


def expected_membership() -> tuple[list[str], str]:
    ids = sorted(
        c.dataset_id
        for c in all_coverage_contracts()
        if c.governance_tier == "governed"
    )
    digest = "sha256:" + hashlib.sha256(
        json.dumps(ids, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    return ids, digest


def parse_generated(path: Path) -> tuple[list[str], str]:
    text = path.read_text(encoding="utf-8")
    dig_m = re.search(r"membership_digest=(sha256:[0-9a-f]+)", text)
    if not dig_m:
        dig_m = re.search(
            r"GOVERNED_MEMBERSHIP_DIGEST\s*=\s*\"(sha256:[0-9a-f]+)\"", text
        )
    if not dig_m:
        raise SystemExit(f"no membership digest in {path}")
    arr_m = re.search(
        r"GOVERNED_DATASETS\s*=\s*Object\.freeze\((\[[\s\S]*?\])\)", text
    )
    if not arr_m:
        raise SystemExit(f"no GOVERNED_DATASETS array in {path}")
    ids = json.loads(arr_m.group(1))
    if not isinstance(ids, list):
        raise SystemExit("GOVERNED_DATASETS is not a list")
    return [str(x) for x in ids], dig_m.group(1)


def main() -> int:
    if not GOVERNED_JS.is_file():
        print(f"FAIL missing {GOVERNED_JS}", file=sys.stderr)
        return 2
    exp_ids, exp_digest = expected_membership()
    got_ids, got_digest = parse_generated(GOVERNED_JS)
    errors: list[str] = []
    if got_ids != exp_ids:
        errors.append(
            f"dataset membership drift missing={sorted(set(exp_ids)-set(got_ids))} "
            f"extra={sorted(set(got_ids)-set(exp_ids))}"
        )
    if got_digest != exp_digest:
        errors.append(f"digest drift got={got_digest} expected={exp_digest}")
    if errors:
        print("FAIL governed.js drift:", file=sys.stderr)
        for e in errors:
            print(" -", e, file=sys.stderr)
        print(
            "Regenerate: python scripts/generate_governed_js.py",
            file=sys.stderr,
        )
        return 1
    print(f"OK governed.js matches coverage n={len(exp_ids)} {exp_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
