"""Load the legacy unique_logic replay catalog explicitly.

yaml_* names (unique_family_ids_from_yaml, yaml_combo_rows) are kept aliases;
unique_family_ids_from_catalog / combo_rows_from_catalog are the same objects.
YAML overlay replaces the compiled map only when QP_ALLOW_YAML_OVERLAY=1.

This module is not imported by the exact-four Pilot or the Mass scheduler.
The immutable rows live under ``artifacts/replay`` and exist only for audit,
replay, and migration compatibility.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from qp_paths import repo_root
from research.unique_logic.catalog_yaml_parse import parse_catalog_yaml

YAML_OVERLAY_ENV = "QP_ALLOW_YAML_OVERLAY"


class CatalogYamlOverlayError(ValueError):
    """YAML present without QP_ALLOW_YAML_OVERLAY=1. Does not replace compiled map."""


def yaml_overlay_allowed() -> bool:
    return os.environ.get(YAML_OVERLAY_ENV, "").strip() == "1"


def catalog_dir(*, root: Path | None = None) -> Path:
    return (root or repo_root()) / "specs" / "research_logics"


def themes_path(*, root: Path | None = None) -> Path:
    return (root or repo_root()) / "specs" / "research_themes.yaml"


@lru_cache(maxsize=8)
def _load_catalog_specs_cached(
    root_key: str, allow_overlay: bool
) -> tuple[dict[str, Any], ...]:
    root = Path(root_key)
    yaml_paths = sorted(catalog_dir(root=root).glob("*.yaml"))
    if yaml_paths and not allow_overlay:
        raise CatalogYamlOverlayError(
            f"catalog YAML overlay n={len(yaml_paths)} without {YAML_OVERLAY_ENV}=1; "
            "refusing to replace compiled map"
        )
    if yaml_paths:
        specs: list[dict[str, Any]] = []
        for path in yaml_paths:
            spec = parse_catalog_yaml(path.read_text(encoding="utf-8"))
            spec["catalog_path"] = str(path)
            spec["catalog"] = True
            spec["catalog_present"] = True
            if spec.get("logic_id"):
                specs.append(spec)
        if specs:
            return tuple(specs)
    return tuple(load_compiled_specs(root=root))


def load_catalog_specs(*, root: Path | None = None) -> list[dict[str, Any]]:
    return list(
        _load_catalog_specs_cached(
            str((root or repo_root()).resolve()), yaml_overlay_allowed()
        )
    )


@lru_cache(maxsize=8)
def _catalog_by_id_cached(
    root_key: str, allow_overlay: bool
) -> dict[str, dict[str, Any]]:
    return {
        str(spec["logic_id"]): spec
        for spec in _load_catalog_specs_cached(root_key, allow_overlay)
        if spec.get("logic_id")
    }


def catalog_index(*, root: Path | None = None) -> dict[str, Any]:
    """One-pass catalog lookup. Compiled map is load SoT."""
    root_key = str((root or repo_root()).resolve())
    by_id = _catalog_by_id_cached(root_key, yaml_overlay_allowed())
    records = combo_thesis_records(root=root)
    kinds: dict[str, int] = {}
    for rec in records:
        kind = str(rec.get("kind") or "")
        kinds[kind] = kinds.get(kind, 0) + 1
    compiled = compiled_migration_ids(root=root)
    yaml_still_present = any(catalog_dir(root=root).glob("*.yaml"))
    return {
        "by_id": by_id,
        "n": len(by_id) if yaml_still_present else len(compiled),
        "n_combo": len(records),
        "combo_ids": tuple(str(r["logic_id"]) for r in records),
        "combo_kind_counts": kinds,
        "n_compiled": len(compiled),
        "compiled_ids_match": compiled == set(by_id),
        "yaml_still_present": yaml_still_present,
        "go": False,
        "not_a_pass": True,
    }


def catalog_spec(logic_id: str, *, root: Path | None = None) -> dict[str, Any] | None:
    return _catalog_by_id_cached(
        str((root or repo_root()).resolve()), yaml_overlay_allowed()
    ).get(str(logic_id))


def load_compiled_specs(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Closed-DSL rows from the immutable legacy replay artifact."""
    path = (
        (root or repo_root())
        / "artifacts"
        / "replay"
        / "legacy_strategy_catalog"
        / "migration.jsonl"
    )
    specs: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        lid = str(row.get("logic_id") or "").strip()
        if not lid:
            continue
        params = row.get("params") if isinstance(row.get("params"), Mapping) else {}
        specs.append(
            {
                "logic_id": lid,
                "family": row.get("family"),
                "family_id": row.get("family_id"),
                "evaluator": row.get("evaluator"),
                "params": dict(params),
                "generation_enabled": bool(row.get("generation_enabled")),
                "thesis": row.get("thesis"),
                "signal_definition": row.get("signal_definition"),
                "position_rule": row.get("position_rule"),
                "datasets": row.get("datasets"),
                "catalog": True,
                "compiled": True,
                "catalog_present": False,
                "catalog_path": str(path),
            }
        )
    return specs


def compiled_migration_ids(*, root: Path | None = None) -> frozenset[str]:
    """IDs from the compiler migration map. Identity set vs constants."""
    return frozenset(
        str(s.get("logic_id") or "")
        for s in load_compiled_specs(root=root)
        if s.get("logic_id")
    )


_COMBO_EVALUATOR = "research.unique_logic.event_combos.evaluate_combo_daily_mtm"


def _yaml_combo_kind(spec: Mapping[str, Any], *, cs_gate: str | None) -> str:
    lid = str(spec.get("logic_id") or "")
    family = str(spec.get("family_id") or "")
    if cs_gate:
        return "cs"
    if family == "surprise_xs_rank" or lid.startswith("surprise_xs"):
        return "surprise_xs"
    return "event"


def normalize_gates(raw: Any) -> list[str]:
    """Comma-string or sequence → gate tokens. Empty / None / 'None' → []."""
    if raw in (None, "", "None"):
        return []
    if isinstance(raw, str):
        return [
            x.strip()
            for x in raw.split(",")
            if x.strip() and x.strip() != "None"
        ]
    return [
        str(x).strip()
        for x in list(raw)
        if str(x).strip() and str(x).strip() != "None"
    ]


def spec_gates(spec: Mapping[str, Any] | None) -> list[str]:
    """Gates from a catalog spec. params.gates then spec.gates. Missing → []."""
    if not isinstance(spec, Mapping):
        return []
    params = spec.get("params") if isinstance(spec.get("params"), Mapping) else {}
    raw = params.get("gates") if isinstance(params, Mapping) else None
    if raw is None:
        raw = spec.get("gates")
    return normalize_gates(raw)


def combo_row_from_yaml(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Map a catalog spec to ``event_combos._combo_row`` keys. Missing gates/cs_gate/side fail closed."""
    from research.unique_logic.event_combos import _combo_row

    lid = str(spec.get("logic_id") or "")
    params = spec.get("params")
    if not isinstance(params, Mapping):
        raise ValueError(f"{lid}: catalog params missing")
    missing = [k for k in ("gates", "cs_gate", "side") if k not in params]
    if missing:
        raise ValueError(f"{lid}: catalog params missing {', '.join(missing)}")

    gates = normalize_gates(params["gates"])

    cs_raw = params["cs_gate"]
    cs_gate = None if cs_raw in (None, "", "None") else str(cs_raw)
    side = str(params.get("side") or spec.get("side") or "orig")
    raw: dict[str, Any] = {
        "logic_id": lid,
        "family_id": spec.get("family_id"),
        "thesis": spec.get("thesis"),
        "kind": _yaml_combo_kind(spec, cs_gate=cs_gate),
        "gates": tuple(gates),
        "side": side,
    }
    if cs_gate is not None:
        raw["cs_gate"] = cs_gate
    entry_shift = int(params.get("entry_shift") or 0)
    hold_tail_days = int(params.get("hold_tail_days") or 0)
    if entry_shift:
        raw["entry_shift"] = entry_shift
    if hold_tail_days:
        raw["hold_tail_days"] = hold_tail_days
    if spec.get("main_pool") is False:
        raw["main_pool"] = False
    return _combo_row(raw)


combo_row_from_spec = combo_row_from_yaml  # YAML gone; yaml_* name kept alias; compiled catalog is SoT


@lru_cache(maxsize=8)
def _yaml_combo_rows_cached(
    root_key: str, allow_overlay: bool
) -> tuple[dict[str, Any], ...]:
    """Runtime combo rows from catalog specs (compiled load SoT)."""
    return tuple(
        combo_row_from_yaml(spec)
        for spec in _load_catalog_specs_cached(root_key, allow_overlay)
        if str(spec.get("evaluator") or "") == _COMBO_EVALUATOR
    )


def yaml_combo_rows(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Combo runtime rows from catalog specs. Filter by evaluator; do not import combo runtime."""
    return list(
        _yaml_combo_rows_cached(
            str((root or repo_root()).resolve()), yaml_overlay_allowed()
        )
    )


combo_rows_from_catalog = yaml_combo_rows  # YAML gone; yaml_* name kept alias; compiled catalog is SoT


@lru_cache(maxsize=8)
def _combo_thesis_records_cached(
    root_key: str, allow_overlay: bool
) -> tuple[dict[str, Any], ...]:
    """Compact combo table from catalog specs. Invalidate via cache_clear."""
    out: list[dict[str, Any]] = []
    for spec in _load_catalog_specs_cached(root_key, allow_overlay):
        if str(spec.get("evaluator") or "") != _COMBO_EVALUATOR:
            continue
        params = spec.get("params") if isinstance(spec.get("params"), Mapping) else {}
        gates = spec_gates(spec)
        cs_raw = params.get("cs_gate") if isinstance(params, Mapping) else None
        cs_gate = None if cs_raw in (None, "", "None") else str(cs_raw)
        lid = str(spec.get("logic_id") or "")
        out.append(
            {
                "logic_id": lid,
                "kind": _yaml_combo_kind(spec, cs_gate=cs_gate),
                "gates": list(gates or []),
                "cs_gate": cs_gate,
                "side": str(params.get("side") or "orig"),
                "go": False,
            }
        )
    return tuple(out)


def combo_thesis_records(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Compact combo table rows from catalog specs (compiled load SoT)."""
    return list(
        _combo_thesis_records_cached(
            str((root or repo_root()).resolve()), yaml_overlay_allowed()
        )
    )


def clear_catalog_caches() -> None:
    """Drop YAML/combo caches after catalog writes. Not a second SoT."""
    _load_catalog_specs_cached.cache_clear()
    _catalog_by_id_cached.cache_clear()
    _combo_thesis_records_cached.cache_clear()
    _yaml_combo_rows_cached.cache_clear()
    try:
        from research.unique_logic.event_combos import clear_combo_runtime_cache
    except ImportError:
        pass
    else:
        clear_combo_runtime_cache()
    try:
        from research.combo_basket_catalog import clear_basket_caches
    except ImportError:
        pass
    else:
        clear_basket_caches()


def write_combo_thesis_jsonl(
    path: Path | str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Dump compact combo rows. Not a second SoT."""
    import json

    rows = combo_thesis_records(root=root)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for rec in rows:
            fh.write(json.dumps(rec, ensure_ascii=True, sort_keys=True) + "\n")
    return {
        "path": str(out),
        "n": len(rows),
        "go": False,
        "not_a_pass": True,
    }


def unique_row_from_yaml(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Map a catalog spec to an original-unique runtime row. Does not GO."""
    lid = str(spec.get("logic_id") or "")
    if not lid:
        raise ValueError("YAML unique row missing logic_id")
    params = spec.get("params")
    row = dict(spec)
    row["logic_id"] = lid
    row["params"] = dict(params) if isinstance(params, Mapping) else {}
    row["catalog"] = True
    row["catalog_map"] = None
    row["new_unique_logic"] = True
    row["go"] = False
    row["generation_enabled"] = False
    row["promote_as_main"] = False
    if not row.get("kind"):
        row["kind"] = lid
    if not row.get("position_rule"):
        row["position_rule"] = str(row.get("signal_definition") or "")
    return row


def yaml_unique_rows(
    *,
    evaluator: str | None = None,
    logic_ids: Sequence[str] | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Original unique runtime rows from catalog specs. Filter by evaluator/logic_ids; combo excluded unless requested."""
    want = list(logic_ids) if logic_ids is not None else None
    want_set = set(want) if want is not None else None
    by_id: dict[str, dict[str, Any]] = {}
    for spec in load_catalog_specs(root=root):
        ev = str(spec.get("evaluator") or "")
        lid = str(spec.get("logic_id") or "")
        if evaluator is not None:
            if ev != evaluator:
                continue
        elif ev == _COMBO_EVALUATOR:
            continue
        if want_set is not None and lid not in want_set:
            continue
        by_id[lid] = unique_row_from_yaml(spec)
    if want is not None:
        missing = [lid for lid in want if lid not in by_id]
        if missing:
            raise ValueError(
                "yaml_unique_rows missing ids: " + ", ".join(missing[:40])
            )
        return [by_id[lid] for lid in want]
    return list(by_id.values())


_UNIQUE_FAMILY_KEYS: tuple[str, ...] = (
    "event",
    "event_filter",
    "event_sides",
    "adaptive",
    "cs",
)
_EVALUATOR_MODULE_TO_FAMILY: dict[str, str] = {
    "event": "event",
    "event_filters": "event_filter",
    "event_sides": "event_sides",
    "adaptive": "adaptive",
    "cross_section": "cs",
    "cs_overlays": "cs",
}


def _unique_family_key(spec: Mapping[str, Any]) -> str:
    """Family for a non-combo catalog row: explicit ``family:`` else evaluator module."""
    lid = str(spec.get("logic_id") or "")
    explicit = spec.get("family")
    if explicit not in (None, ""):
        fam = str(explicit).strip()
        if fam not in _UNIQUE_FAMILY_KEYS:
            raise ValueError(f"{lid}: unknown family {fam!r}")
        return fam
    ev = str(spec.get("evaluator") or "")
    parts = ev.split(".")
    if (
        len(parts) >= 4
        and parts[0] == "research"
        and parts[1] == "unique_logic"
    ):
        fam = _EVALUATOR_MODULE_TO_FAMILY.get(parts[2])
        if fam:
            return fam
    raise ValueError(f"{lid}: unique YAML needs family: or module evaluator")


def unique_family_ids_from_yaml(*, root: Path | None = None) -> dict[str, frozenset[str]]:
    """Non-combo catalog rows grouped by family (or evaluator module). Does not GO."""
    buckets: dict[str, set[str]] = {k: set() for k in _UNIQUE_FAMILY_KEYS}
    for spec in load_catalog_specs(root=root):
        if str(spec.get("evaluator") or "") == _COMBO_EVALUATOR:
            continue
        lid = str(spec.get("logic_id") or "")
        if not lid:
            continue
        buckets[_unique_family_key(spec)].add(lid)
    return {k: frozenset(v) for k, v in buckets.items()}


unique_family_ids_from_catalog = unique_family_ids_from_yaml  # YAML gone; yaml_* name kept alias; compiled catalog is SoT


def combo_thesis_ids_by_kind(*, root: Path | None = None) -> dict[str, frozenset[str]]:
    """Combo catalog rows grouped by kind. Uses compact records, not runtime rows."""
    event: set[str] = set()
    cs: set[str] = set()
    surprise_xs: set[str] = set()
    for rec in combo_thesis_records(root=root):
        kind = str(rec.get("kind") or "")
        lid = str(rec.get("logic_id") or "")
        if not lid:
            continue
        if kind == "cs":
            cs.add(lid)
        elif kind == "surprise_xs":
            surprise_xs.add(lid)
        else:
            event.add(lid)
    return {
        "event": frozenset(event),
        "cs": frozenset(cs),
        "surprise_xs": frozenset(surprise_xs),
    }


_THEME_RESERVED = frozenset(
    {"go", "promote_as_main", "generation_enabled", "headline"}
)


@lru_cache(maxsize=8)
def _economic_theme_ids_cached(root_key: str) -> dict[str, frozenset[str]]:
    path = themes_path(root=Path(root_key))
    data = parse_catalog_yaml(path.read_text(encoding="utf-8"))
    for flag in _THEME_RESERVED:
        if data.get(flag) is True:
            raise ValueError(f"research_themes.yaml must not set {flag}: true")
    out: dict[str, frozenset[str]] = {}
    for key, val in data.items():
        if key in _THEME_RESERVED:
            continue
        if not isinstance(val, list):
            raise ValueError(f"research_themes.yaml {key}: expected list of logic_ids")
        ids = [str(x).strip() for x in val if str(x).strip()]
        if not ids:
            raise ValueError(f"research_themes.yaml {key}: empty theme")
        out[str(key)] = frozenset(ids)
    return out


def economic_theme_ids(*, root: Path | None = None) -> dict[str, frozenset[str]]:
    """theme_id → logic_ids from ``specs/research_themes.yaml``. Does not GO."""
    return dict(_economic_theme_ids_cached(str((root or repo_root()).resolve())))
