"""Load unique_logic catalog (YAML if present, else compiled migration.jsonl)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from qp_paths import repo_root


def catalog_dir(*, root: Path | None = None) -> Path:
    return (root or repo_root()) / "specs" / "research_logics"


def themes_path(*, root: Path | None = None) -> Path:
    return (root or repo_root()) / "specs" / "research_themes.yaml"


def _parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if s in {"true", "True"}:
        return True
    if s in {"false", "False"}:
        return False
    if s in {"null", "None", "~", ""}:
        return None if s != "" else ""
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def parse_catalog_yaml(text: str) -> dict[str, Any]:
    """Parse the constrained catalog schema (scalars, folded text, lists, params map)."""
    data: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent != 0:
            i += 1
            continue
        if raw.rstrip().endswith(":") and raw.strip()[:-1].strip() and ":" not in raw.strip()[:-1]:
            key = raw.strip()[:-1]
            i += 1
            if key == "params":
                params: dict[str, Any] = {}
                while i < n:
                    ln = lines[i]
                    if not ln.strip() or ln.lstrip().startswith("#"):
                        i += 1
                        continue
                    if not ln.startswith(" "):
                        break
                    if ":" in ln:
                        k, _, rest = ln.strip().partition(":")
                        key_p = k.strip()
                        val = _parse_scalar(rest)
                        if key_p == "gates":
                            if val in (None, "", "None"):
                                params[key_p] = []
                            elif isinstance(val, str):
                                params[key_p] = [
                                    x.strip()
                                    for x in val.split(",")
                                    if x.strip() and x.strip() != "None"
                                ]
                            else:
                                params[key_p] = [str(val)]
                        else:
                            params[key_p] = val
                    i += 1
                data[key] = params
                continue
            items: list[Any] = []
            saw_list = False
            while i < n:
                ln = lines[i]
                if not ln.strip() or ln.lstrip().startswith("#"):
                    i += 1
                    continue
                if not ln.startswith(" "):
                    break
                if ln.strip().startswith("-"):
                    saw_list = True
                    items.append(_parse_scalar(ln.strip()[1:]))
                i += 1
            data[key] = items if saw_list else None
            continue
        if ":" in raw:
            key, _, rest = raw.partition(":")
            key = key.strip()
            rest = rest.strip()
            if rest in {">", "|"}:
                buf: list[str] = []
                i += 1
                while i < n:
                    ln = lines[i]
                    if not ln.strip():
                        i += 1
                        continue
                    if not ln.startswith(" "):
                        break
                    buf.append(ln.strip())
                    i += 1
                data[key] = " ".join(buf)
                continue
            data[key] = _parse_scalar(rest)
        i += 1
    return data


@lru_cache(maxsize=8)
def _load_catalog_specs_cached(root_key: str) -> tuple[dict[str, Any], ...]:
    specs: list[dict[str, Any]] = []
    for path in sorted(catalog_dir(root=Path(root_key)).glob("*.yaml")):
        spec = parse_catalog_yaml(path.read_text(encoding="utf-8"))
        spec["catalog_path"] = str(path)
        spec["catalog"] = True
        if spec.get("logic_id"):
            specs.append(spec)
    if specs:
        return tuple(specs)
    return tuple(load_compiled_specs(root=Path(root_key)))


def load_catalog_specs(*, root: Path | None = None) -> list[dict[str, Any]]:
    return list(_load_catalog_specs_cached(str((root or repo_root()).resolve())))


@lru_cache(maxsize=8)
def _catalog_by_id_cached(root_key: str) -> dict[str, dict[str, Any]]:
    return {
        str(spec["logic_id"]): spec
        for spec in _load_catalog_specs_cached(root_key)
        if spec.get("logic_id")
    }


def catalog_index(*, root: Path | None = None) -> dict[str, Any]:
    """One-pass catalog lookup. Compiled map is load SoT when YAML is absent."""
    root_key = str((root or repo_root()).resolve())
    by_id = _catalog_by_id_cached(root_key)
    records = combo_thesis_records(root=root)
    kinds: dict[str, int] = {}
    for rec in records:
        kind = str(rec.get("kind") or "")
        kinds[kind] = kinds.get(kind, 0) + 1
    compiled = compiled_migration_ids(root=root)
    return {
        "by_id": by_id,
        "n": len(by_id),
        "n_combo": len(records),
        "combo_ids": tuple(str(r["logic_id"]) for r in records),
        "combo_kind_counts": kinds,
        "n_compiled": len(compiled),
        "compiled_ids_match": compiled == set(by_id),
        "go": False,
        "not_a_pass": True,
    }


def catalog_spec(logic_id: str, *, root: Path | None = None) -> dict[str, Any] | None:
    return _catalog_by_id_cached(str((root or repo_root()).resolve())).get(str(logic_id))


def load_compiled_specs(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Closed-DSL rows from the compiler map. Load SoT when YAML is absent."""
    path = (root or repo_root()) / "specs" / "research_catalog" / "migration.jsonl"
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
                "catalog_path": str(catalog_dir(root=root) / f"{lid}.yaml"),
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
    """Map catalog YAML to ``event_combos._combo_row`` keys. Missing gates/cs_gate/side fail closed."""
    from research.unique_logic.event_combos import _combo_row

    lid = str(spec.get("logic_id") or "")
    params = spec.get("params")
    if not isinstance(params, Mapping):
        raise ValueError(f"{lid}: YAML params missing")
    missing = [k for k in ("gates", "cs_gate", "side") if k not in params]
    if missing:
        raise ValueError(f"{lid}: YAML params missing {', '.join(missing)}")

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


@lru_cache(maxsize=8)
def _yaml_combo_rows_cached(root_key: str) -> tuple[dict[str, Any], ...]:
    """Runtime combo rows from catalog specs (compiled when YAML is absent)."""
    return tuple(
        combo_row_from_yaml(spec)
        for spec in _load_catalog_specs_cached(root_key)
        if str(spec.get("evaluator") or "") == _COMBO_EVALUATOR
    )


def yaml_combo_rows(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Combo runtime rows from catalog specs. Filter by evaluator; do not import combo runtime."""
    return list(_yaml_combo_rows_cached(str((root or repo_root()).resolve())))


@lru_cache(maxsize=8)
def _combo_thesis_records_cached(root_key: str) -> tuple[dict[str, Any], ...]:
    """Compact combo table from catalog specs. Invalidate via cache_clear."""
    out: list[dict[str, Any]] = []
    for spec in _load_catalog_specs_cached(root_key):
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
    """Compact combo table rows from catalog specs (compiled when YAML is absent)."""
    return list(
        _combo_thesis_records_cached(str((root or repo_root()).resolve()))
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
        "yaml_remains_sot": True,
    }


def unique_row_from_yaml(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Map catalog YAML to an original-unique runtime row. Does not GO."""
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
    """Original unique runtime rows from catalog YAML. Filter by evaluator/logic_ids; combo excluded unless requested."""
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
    """Family for a non-combo YAML: explicit ``family:`` else evaluator module."""
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
