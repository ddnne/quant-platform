"""Compile the retired catalog into an immutable replay artifact. Not GO.

This module is an audit/replay compatibility boundary.  It does not emit
Worker source and is not imported by the exact-four Pilot or Mass scheduler.
It does not generate or execute Python and does not add YAML.

v2 helpers classify active vs legacy identity without rewriting the v1
digest lock or migration.jsonl.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from qp_paths import repo_root
from research.unique_logic.catalog import (
    catalog_dir,
    compiled_migration_ids,
    load_catalog_specs,
    spec_gates,
)


COMPILER_VERSION = "research_catalog_compiler/v1"
SPLIT_VERSION = "research_catalog_compiler/v2"
ARTIFACT_REL = Path("artifacts") / "replay" / "legacy_strategy_catalog"
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
        "family": spec.get("family"),
        "family_id": family,
        "evaluator": evaluator,
        "gates": gates,
        "params": dict(params) if isinstance(params, Mapping) else {},
        "generation_enabled": bool(spec.get("generation_enabled")),
        "thesis": spec.get("thesis"),
        "signal_definition": spec.get("signal_definition"),
        "position_rule": spec.get("position_rule"),
        "datasets": list(spec.get("datasets") or []) if isinstance(spec.get("datasets"), list) else spec.get("datasets"),
        "semantic_hash": semantic_hash(spec),
    }


def _dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def catalog_artifact_dir(*, root: Path | None = None) -> Path:
    return (root or repo_root()) / ARTIFACT_REL


def yaml_files_present(*, root: Path | None = None) -> bool:
    return any(catalog_dir(root=root).glob("*.yaml"))


def manifest_payload(pack: Mapping[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    return {
        "artifact_class": "immutable_legacy_replay",
        "digest": str(pack.get("digest") or ""),
        "go": False,
        "n": int(pack.get("n") or 0),
        "runtime_import_allowed": False,
        "version": str(pack.get("version") or COMPILER_VERSION),
        "yaml_still_present": bool(
            pack.get("yaml_still_present", yaml_files_present(root=root))
        ),
    }


def migration_row(row: Mapping[str, Any]) -> dict[str, Any]:
    gates = row.get("gates")
    params = row.get("params") if isinstance(row.get("params"), Mapping) else {}
    return {
        "evaluator": str(row.get("evaluator") or ""),
        "family": row.get("family"),
        "family_id": str(row.get("family_id") or ""),
        "gates": list(gates) if isinstance(gates, Sequence) and not isinstance(gates, (str, bytes)) else [],
        "generation_enabled": bool(row.get("generation_enabled")),
        "logic_id": str(row.get("logic_id") or ""),
        "params": dict(params),
        "position_rule": row.get("position_rule"),
        "semantic_hash": str(row.get("semantic_hash") or ""),
        "signal_definition": row.get("signal_definition"),
        "template_id": str(row.get("template_id") or ""),
        "thesis": row.get("thesis"),
        "datasets": row.get("datasets"),
    }


def persist_catalog_artifacts(
    *,
    root: Path | None = None,
    pack: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write manifest + migration map from compile_catalog(). Not GO. Does not add YAML."""
    compiled = dict(pack) if pack is not None else compile_catalog()
    dest = catalog_artifact_dir(root=root)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / MANIFEST_NAME).write_text(
        _dumps(manifest_payload(compiled, root=root)) + "\n", encoding="utf-8"
    )
    lines = [_dumps(migration_row(r)) for r in compiled.get("rows") or []]
    body = "\n".join(lines)
    (dest / MIGRATION_NAME).write_text(body + ("\n" if body else ""), encoding="utf-8")
    return compiled


def compiled_logic_id_sets(*, root: Path | None = None) -> dict[str, set[str]]:
    """migration.jsonl stems, YAML stems (maybe empty), RESEARCH_UNIQUE_LOGIC_IDS."""
    from research.unique_logic.constants import RESEARCH_UNIQUE_LOGIC_IDS

    yaml_ids = {p.stem for p in catalog_dir(root=root).glob("*.yaml")}
    migrated = set(compiled_migration_ids(root=root))
    return {
        "migration": migrated,
        "yaml": yaml_ids,
        "constants": set(RESEARCH_UNIQUE_LOGIC_IDS),
    }


def assert_compiled_logic_id_sets(*, root: Path | None = None) -> dict[str, set[str]]:
    """compiled migration.jsonl == RESEARCH_UNIQUE_LOGIC_IDS. YAML if present must match."""
    sets = compiled_logic_id_sets(root=root)
    core_ok = sets["migration"] == sets["constants"]
    yaml_ok = not sets["yaml"] or sets["yaml"] == sets["migration"]
    if not (core_ok and yaml_ok):
        only_m = sorted(sets["migration"] - sets["yaml"] - sets["constants"])
        only_y = sorted(sets["yaml"] - sets["migration"] - sets["constants"])
        only_c = sorted(sets["constants"] - sets["migration"] - sets["yaml"])
        raise ValueError(
            "compiled migration.jsonl logic_id set != RESEARCH_UNIQUE_LOGIC_IDS: "
            f"n_migration={len(sets['migration'])} n_yaml={len(sets['yaml'])} "
            f"n_constants={len(sets['constants'])} "
            f"only_migration={only_m[:8]} only_yaml={only_y[:8]} only_constants={only_c[:8]}"
        )
    return sets


def assert_legacy_catalog_artifact_frozen(
    *, root: Path | None = None
) -> dict[str, Any]:
    """Verify the immutable replay artifact without emitting runtime source."""
    from research.eval_flags import CATALOG_AND_PLUS_N_STOPPED
    from research.occupancy_guards import CatalogAndPlusNStoppedError

    n_yaml = len(list(catalog_dir(root=root).glob("*.yaml")))
    dest = catalog_artifact_dir(root=root)
    manifest = json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
    n_manifest = int(manifest.get("n") or 0)
    compiled = compile_catalog(root=root)
    sets = assert_compiled_logic_id_sets(root=root)
    n_logic_ids = len(sets["migration"])
    out: dict[str, Any] = {
        "stopped": bool(CATALOG_AND_PLUS_N_STOPPED),
        "n_yaml": n_yaml,
        "n_manifest": n_manifest,
        "n_compiled_rows": int(compiled["n"]),
        "n_logic_ids": n_logic_ids,
        "manifest_digest": str(manifest.get("digest") or ""),
        "compiled_digest": str(compiled["digest"]),
        "ok": True,
        "go": False,
        "not_a_pass": True,
    }
    if CATALOG_AND_PLUS_N_STOPPED and n_yaml > 0:
        raise CatalogAndPlusNStoppedError(
            f"catalog yaml n={n_yaml}; legacy rows must remain in the replay artifact"
        )
    if manifest.get("artifact_class") != "immutable_legacy_replay":
        raise CatalogAndPlusNStoppedError("legacy replay artifact_class invalid")
    if manifest.get("runtime_import_allowed") is not False:
        raise CatalogAndPlusNStoppedError("legacy replay runtime import must be disabled")
    if manifest.get("yaml_still_present", True) is not False:
        raise CatalogAndPlusNStoppedError("legacy replay manifest still permits YAML")
    if manifest.get("go") is not False:
        raise CatalogAndPlusNStoppedError("legacy replay artifact must never be GO")
    if n_manifest != n_logic_ids or n_manifest != int(compiled["n"]):
        raise CatalogAndPlusNStoppedError(
            f"legacy replay manifest n={n_manifest} != migration n={n_logic_ids} "
            f"or compiled rows n={compiled['n']}"
        )
    if str(manifest.get("digest") or "") != str(compiled["digest"]):
        raise CatalogAndPlusNStoppedError(
            "legacy replay manifest digest does not match canonical rows"
        )
    return out


def active_logic_ids() -> frozenset[str]:
    """v2 split compatibility: empty after product-runtime retirement."""
    from research.catalog_active import active_logic_ids as _ids

    return _ids()


def legacy_logic_ids() -> frozenset[str]:
    """v2 split: compiled identity remainder. Replay/lineage only."""
    from research.catalog_active import legacy_logic_ids as _ids

    return _ids()


def catalog_kind(logic_id: str) -> str:
    """v2 split: ``active`` or ``legacy``. Unknown IDs fail closed."""
    from research.catalog_active import catalog_kind as _kind

    return _kind(logic_id)


def pilot_candidates() -> frozenset[str]:
    """ExperimentPlan strategy_spec_ids, separate from the replay artifact."""
    from research.catalog_active import pilot_candidates as _ids

    return _ids()


def compile_catalog(
    specs: Sequence[Mapping[str, Any]] | None = None,
    *,
    persist: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    source = specs if specs is not None else load_catalog_specs(root=root)
    rows = [compile_row(s) for s in source]
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
        "yaml_still_present": yaml_files_present(root=root),
    }
    if persist:
        persist_catalog_artifacts(root=root, pack=pack)
    return pack


def main() -> None:
    persist_catalog_artifacts()


if __name__ == "__main__":
    main()
