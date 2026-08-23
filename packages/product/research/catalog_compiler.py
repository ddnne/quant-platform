"""Compile expanded YAML into a closed-DSL catalog artifact. Not GO.

Does not generate or exec Python. Does not delete YAML. Does not add YAML.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from research.unique_logic.catalog import load_catalog_specs, spec_gates


COMPILER_VERSION = "research_catalog_compiler/v1"


def semantic_hash(spec: Mapping[str, Any]) -> str:
    payload = {
        "evaluator": str(spec.get("evaluator") or ""),
        "family_id": str(spec.get("family_id") or ""),
        "gates": list(spec_gates(spec)),
        "params": spec.get("params") if isinstance(spec.get("params"), Mapping) else {},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def compile_row(spec: Mapping[str, Any]) -> dict[str, Any]:
    gates = spec_gates(spec)
    lid = str(spec.get("logic_id") or "")
    evaluator = str(spec.get("evaluator") or "")
    family = str(spec.get("family_id") or "")
    template_id = family or evaluator.rsplit(".", 1)[-1] or "unknown"
    params = spec.get("params") if isinstance(spec.get("params"), Mapping) else {}
    return {
        "logic_id": lid,
        "template_id": template_id,
        "family_id": family,
        "evaluator": evaluator,
        "gates": gates,
        "params": dict(params) if isinstance(params, Mapping) else {},
        "generation_enabled": bool(spec.get("generation_enabled")),
        "semantic_hash": semantic_hash(spec),
    }


def compile_catalog(
    specs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = [compile_row(s) for s in (specs if specs is not None else load_catalog_specs())]
    rows.sort(key=lambda r: str(r.get("logic_id") or ""))
    canonical = json.dumps(
        {"version": COMPILER_VERSION, "rows": rows},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "version": COMPILER_VERSION,
        "n": len(rows),
        "digest": digest,
        "rows": rows,
        "go": False,
        "not_a_pass": True,
        "yaml_still_present": True,
    }
