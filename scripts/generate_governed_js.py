#!/usr/bin/env python3
"""Generate quant-ops-mcp governed.js from Python coverage contracts (SoT)."""
from __future__ import annotations

import hashlib
import json
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

from ops.projection_contract_snapshot import ProjectionContractSnapshot  # noqa: E402
from storage.receipt_policy import (  # noqa: E402
    receipt_source_for_canonical_source,
)


def governed_contract() -> tuple[list[str], dict[str, str], str, str]:
    """Derive Worker membership and routes from one retained contract snapshot."""
    snapshot = ProjectionContractSnapshot.capture(ROOT)
    ids = sorted(snapshot.coverage_dataset_ids)
    sources: dict[str, str] = {}
    for row in snapshot.source_inventory:
        dataset_id = row.get("dataset_id")
        canonical_source = row.get("source")
        if type(dataset_id) is not str or not dataset_id:
            raise RuntimeError("canonical source inventory has an invalid dataset_id")
        if dataset_id in sources:
            raise RuntimeError(
                f"canonical source inventory contains duplicate dataset {dataset_id}"
            )
        if type(canonical_source) is not str or not canonical_source:
            raise RuntimeError(
                f"canonical source inventory has no source for {dataset_id}"
            )
        sources[dataset_id] = receipt_source_for_canonical_source(canonical_source)
    membership_digest = "sha256:" + hashlib.sha256(
        json.dumps(ids, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    source_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            sources,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    return ids, sources, membership_digest, source_digest


def render_governed_js(
    contract: tuple[list[str], dict[str, str], str, str] | None = None,
) -> str:
    """Render the byte-exact generated Worker authority artifact."""
    ids, sources, digest, source_digest = contract or governed_contract()
    return (
        "/** AUTO-GENERATED from one retained canonical + Coverage snapshot.\n"
        " * DO NOT HAND-EDIT. Regenerate: python scripts/generate_governed_js.py\n"
        f" * membership_digest={digest}\n"
        f" * receipt_source_digest={source_digest}\n"
        " */\n"
        f"export const GOVERNED_DATASETS = Object.freeze({json.dumps(ids, indent=2)});\n\n"
        f"export const GOVERNED_MEMBERSHIP_DIGEST = {json.dumps(digest)};\n\n"
        "export const GOVERNED_DATASET_SET = new Set(GOVERNED_DATASETS);\n\n"
        "/** @type {Readonly<Record<string, \"jquants\" | \"jsda\">>} */\n"
        "export const CANONICAL_RECEIPT_SOURCE_BY_DATASET = Object.freeze("
        f"{json.dumps(sources, indent=2, sort_keys=True)});\n\n"
        "export const CANONICAL_RECEIPT_SOURCE_DIGEST = "
        f"{json.dumps(source_digest)};\n\n"
        "export const CANONICAL_JSDA_DATASET_SET = new Set(\n"
        "  Object.entries(CANONICAL_RECEIPT_SOURCE_BY_DATASET)\n"
        "    .filter(([, source]) => source === \"jsda\")\n"
        "    .map(([dataset]) => dataset),\n"
        ");\n"
    )


def main() -> int:
    contract = governed_contract()
    ids, _sources, digest, source_digest = contract
    out = ROOT / "platform/workers/quant-ops-mcp/src/governed.js"
    out.write_text(render_governed_js(contract), encoding="utf-8")
    print(
        f"wrote {out} n={len(ids)} digest={digest} "
        f"receipt_source_digest={source_digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
