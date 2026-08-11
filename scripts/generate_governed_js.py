#!/usr/bin/env python3
"""Generate quant-ops-mcp governed.js from Python coverage contracts (SoT)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_contracts.coverage import all_coverage_contracts  # noqa: E402


def main() -> int:
    ids = sorted(
        c.dataset_id
        for c in all_coverage_contracts()
        if c.governance_tier == "governed"
    )
    digest = "sha256:" + hashlib.sha256(
        json.dumps(ids, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    out = ROOT / "platform/workers/quant-ops-mcp/src/governed.js"
    body = (
        "/** AUTO-GENERATED from data_contracts coverage contracts.\n"
        " * DO NOT HAND-EDIT. Regenerate: python scripts/generate_governed_js.py\n"
        f" * membership_digest={digest}\n"
        " */\n"
        f"export const GOVERNED_DATASETS = Object.freeze({json.dumps(ids, indent=2)});\n\n"
        f"export const GOVERNED_MEMBERSHIP_DIGEST = {json.dumps(digest)};\n\n"
        "export const GOVERNED_DATASET_SET = new Set(GOVERNED_DATASETS);\n"
    )
    # fix double-escaped newlines from f-string construction
    body = body.replace("\\n", "\n")
    out.write_text(body)
    print(f"wrote {out} n={len(ids)} digest={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
