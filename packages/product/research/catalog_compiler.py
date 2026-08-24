"""Compile catalog specs into a closed-DSL artifact. Not GO.

Owns ``catalog_ids.ts`` emit. Python ``unique_logic.constants`` remain
policy SoT for Worker ID arrays. Does not generate or exec Python.
Does not add YAML. Compiled map is load SoT.

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
ARTIFACT_REL = Path("specs") / "research_catalog"
MANIFEST_NAME = "manifest.json"
MIGRATION_NAME = "migration.jsonl"
CATALOG_IDS_REL = (
    Path("platform") / "workers" / "research-mass-eval" / "src" / "catalog_ids.ts"
)


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
        "digest": str(pack.get("digest") or ""),
        "go": False,
        "n": int(pack.get("n") or 0),
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


def catalog_ids_ts_path(*, root: Path | None = None) -> Path:
    return (root or repo_root()) / CATALOG_IDS_REL


def _ts_array(name: str, ids: Sequence[str]) -> str:
    inner = ",\n".join(f'  "{lid}"' for lid in ids)
    return f"export const {name} = [\n{inner},\n] as const;"


def _ts_array_spread(name: str, ids: Sequence[str], spread: str) -> str:
    inner = ",\n".join(f'  "{lid}"' for lid in ids)
    return f"export const {name} = [\n{inner},\n  ...{spread},\n] as const;"


def _ts_set(name: str, ids: Sequence[str], *, exported: bool = False) -> str:
    inner = ",\n".join(f'  "{lid}"' for lid in ids)
    prefix = "export const" if exported else "const"
    return f"{prefix} {name} = new Set([\n{inner},\n]);"


def worker_catalog_id_arrays() -> dict[str, list[str]]:
    """Worker ID arrays from Python policy frozensets. Do not hand-edit TS."""
    from research.unique_logic.constants import (
        ADAPTIVE_LOGIC_IDS,
        CF_NEW_CS_THESIS_IDS,
        CF_NEW_EVENT_THESIS_IDS,
        COMBO_EVENT_GATES,
        CS_LOGIC_IDS,
        EVENT_FILTER_LOGIC_IDS,
        EVENT_LOGIC_IDS,
        EVENT_SIDES_LOGIC_IDS,
        PYTHON_ONLY_EVENT_GATES,
    )

    py_only = set(PYTHON_ONLY_EVENT_GATES) & set(COMBO_EVENT_GATES)
    if py_only:
        raise ValueError(
            "COMBO_EVENT_GATES must not include PYTHON_ONLY_EVENT_GATES: "
            f"{sorted(py_only)}"
        )
    overlap = set(CS_LOGIC_IDS) & set(CF_NEW_CS_THESIS_IDS)
    if overlap:
        raise ValueError(
            f"CS_LOGIC_IDS must stay off CF_NEW_CS_THESIS_IDS: {sorted(overlap)}"
        )
    event_prefix = (
        EVENT_LOGIC_IDS
        | EVENT_FILTER_LOGIC_IDS
        | EVENT_SIDES_LOGIC_IDS
        | ADAPTIVE_LOGIC_IDS
    )
    event_overlap = event_prefix & set(CF_NEW_EVENT_THESIS_IDS)
    if event_overlap:
        raise ValueError(
            "event-family prefix must stay off CF_NEW_EVENT_THESIS_IDS: "
            f"{sorted(event_overlap)}"
        )
    return {
        "event_ids": sorted(CF_NEW_EVENT_THESIS_IDS),
        "event_prefix_ids": sorted(event_prefix),
        "cs_ids": sorted(CF_NEW_CS_THESIS_IDS),
        "unique_cs_ids": sorted(CS_LOGIC_IDS),
        "gate_ids": sorted(COMBO_EVENT_GATES),
    }


def catalog_ids_ts_header() -> str:
    from research.eval_flags import CATALOG_YAML_COUNT_AT_STOP

    n = int(CATALOG_YAML_COUNT_AT_STOP)
    return "\n".join(
        [
            "/// Generated by research.catalog_compiler via scripts/sync_cf_new_thesis_ids.py. Do not edit by hand.",
            "/// Python research.unique_logic.constants is policy SoT for Worker ID arrays.",
            f"/// Compiler digest must match n={n}. yaml n=0 uses compiled n while CATALOG_AND_PLUS_N_STOPPED.",
            "/// Leftover unique-22 occupancy stays in daily_path.ts.",
        ]
    )


def catalog_ids_ts_source(
    arrays: Mapping[str, Sequence[str]] | None = None,
) -> str:
    """Emit catalog_ids.ts from Python policy frozensets. Compiler owns this."""
    data = dict(arrays) if arrays is not None else worker_catalog_id_arrays()
    parts = [
        catalog_ids_ts_header(),
        _ts_array("CF_UNIQUE_CS_LOGIC_IDS", list(data["unique_cs_ids"])),
        _ts_array("CF_NEW_EVENT_THESIS_IDS", list(data["event_ids"])),
        _ts_array("CF_NEW_CS_THESIS_IDS", list(data["cs_ids"])),
        _ts_array_spread(
            "CF_EVENT_LOGIC_IDS",
            list(data["event_prefix_ids"]),
            "CF_NEW_EVENT_THESIS_IDS",
        ),
        _ts_set("COMBO_EVENT_GATES", list(data["gate_ids"]), exported=True),
    ]
    return "\n\n".join(parts) + "\n"


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


def assert_catalog_ids_emit_frozen(*, root: Path | None = None) -> dict[str, Any]:
    """Compiler digest n must match freeze. n_logic_ids is compiled n, not yaml glob."""
    from research.eval_flags import CATALOG_AND_PLUS_N_STOPPED, CATALOG_YAML_COUNT_AT_STOP
    from research.occupancy_guards import CatalogAndPlusNStoppedError

    freeze_n = int(CATALOG_YAML_COUNT_AT_STOP)
    n_yaml = len(list(catalog_dir(root=root).glob("*.yaml")))
    dest = catalog_artifact_dir(root=root)
    manifest = json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
    n_digest = int(manifest.get("n") or 0)
    out: dict[str, Any] = {
        "stopped": bool(CATALOG_AND_PLUS_N_STOPPED),
        "n_yaml": n_yaml,
        "n_digest": n_digest,
        "freeze": freeze_n,
        "ok": True,
        "go": False,
        "not_a_pass": True,
    }
    if CATALOG_AND_PLUS_N_STOPPED and n_yaml > 0 and n_yaml != freeze_n:
        raise CatalogAndPlusNStoppedError(
            f"catalog yaml n={n_yaml} != freeze {freeze_n}; "
            "YAML count must not drift while CATALOG_AND_PLUS_N_STOPPED"
        )
    if CATALOG_AND_PLUS_N_STOPPED and n_digest != freeze_n:
        raise CatalogAndPlusNStoppedError(
            f"compiler digest n={n_digest} != freeze {freeze_n}; "
            "compiler digest must match n=2254 while CATALOG_AND_PLUS_N_STOPPED"
        )
    sets = assert_compiled_logic_id_sets(root=root)
    out["n_logic_ids"] = len(sets["migration"])
    return out


def active_logic_ids() -> frozenset[str]:
    """v2 split: countable Worker theses in the compiled map. Not GO."""
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
    """ExperimentPlan strategy_spec_ids. Not the 2092 active remainder."""
    from research.catalog_active import pilot_candidates as _ids

    return _ids()


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
        "yaml_still_present": yaml_files_present(root=root),
    }
    if persist:
        persist_catalog_artifacts(root=root, pack=pack)
    return pack


def main() -> None:
    persist_catalog_artifacts()


if __name__ == "__main__":
    main()
