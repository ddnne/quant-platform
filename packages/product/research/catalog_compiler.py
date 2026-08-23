"""Compile expanded YAML into a closed-DSL catalog artifact. Not GO.

Does not generate or exec Python. Does not delete YAML. Does not add YAML.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from qp_paths import repo_root
from research.unique_logic.catalog import load_catalog_specs, spec_gates


COMPILER_VERSION = "research_catalog_compiler/v1"
ARTIFACT_REL = Path("specs") / "research_catalog"
MANIFEST_NAME = "manifest.json"
MIGRATION_NAME = "migration.jsonl"


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


def _dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def catalog_artifact_dir(*, root: Path | None = None) -> Path:
    return (root or repo_root()) / ARTIFACT_REL


def manifest_payload(pack: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "digest": str(pack.get("digest") or ""),
        "go": False,
        "n": int(pack.get("n") or 0),
        "version": str(pack.get("version") or COMPILER_VERSION),
        "yaml_still_present": True,
    }


def migration_row(row: Mapping[str, Any]) -> dict[str, Any]:
    gates = row.get("gates")
    return {
        "evaluator": str(row.get("evaluator") or ""),
        "family_id": str(row.get("family_id") or ""),
        "gates": list(gates) if isinstance(gates, Sequence) and not isinstance(gates, (str, bytes)) else [],
        "logic_id": str(row.get("logic_id") or ""),
        "semantic_hash": str(row.get("semantic_hash") or ""),
        "template_id": str(row.get("template_id") or ""),
    }


def persist_catalog_artifacts(
    *,
    root: Path | None = None,
    pack: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write manifest + migration map from compile_catalog(). Not GO. YAML stays."""
    compiled = dict(pack) if pack is not None else compile_catalog()
    dest = catalog_artifact_dir(root=root)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / MANIFEST_NAME).write_text(_dumps(manifest_payload(compiled)) + "\n", encoding="utf-8")
    lines = [_dumps(migration_row(r)) for r in compiled.get("rows") or []]
    body = "\n".join(lines)
    (dest / MIGRATION_NAME).write_text(body + ("\n" if body else ""), encoding="utf-8")
    return compiled


def compile_catalog(
    specs: Sequence[Mapping[str, Any]] | None = None,
    *,
    persist: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    rows = [compile_row(s) for s in (specs if specs is not None else load_catalog_specs())]
    rows.sort(key=lambda r: str(r.get("logic_id") or ""))
    canonical = _dumps({"rows": rows, "version": COMPILER_VERSION})
    digest = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    pack = {
        "version": COMPILER_VERSION,
        "n": len(rows),
        "digest": digest,
        "rows": rows,
        "go": False,
        "not_a_pass": True,
        "yaml_still_present": True,
    }
    if persist:
        persist_catalog_artifacts(root=root, pack=pack)
    return pack


def main() -> None:
    persist_catalog_artifacts()


if __name__ == "__main__":
    main()
