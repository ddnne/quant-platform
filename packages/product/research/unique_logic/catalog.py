"""Load unique_logic YAML from ``specs/research_logics``. Constrained schema."""
from __future__ import annotations

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
    return tuple(specs)


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
    """One-pass catalog lookup. YAML remains combo declaration SoT."""
    root_key = str((root or repo_root()).resolve())
    by_id = _catalog_by_id_cached(root_key)
    combo = [
        spec
        for spec in by_id.values()
        if str(spec.get("evaluator") or "") == _COMBO_EVALUATOR
    ]
    return {
        "by_id": by_id,
        "n": len(by_id),
        "n_combo": len(combo),
        "combo_ids": tuple(str(s["logic_id"]) for s in combo),
        "go": False,
        "not_a_pass": True,
    }


def catalog_spec(logic_id: str, *, root: Path | None = None) -> dict[str, Any] | None:
    return _catalog_by_id_cached(str((root or repo_root()).resolve())).get(str(logic_id))


_COMBO_EVALUATOR = "research.unique_logic.event_combos.evaluate_combo_daily_mtm"


def _yaml_combo_kind(spec: Mapping[str, Any], *, cs_gate: str | None) -> str:
    lid = str(spec.get("logic_id") or "")
    family = str(spec.get("family_id") or "")
    if cs_gate:
        return "cs"
    if family == "surprise_xs_rank" or lid.startswith("surprise_xs"):
        return "surprise_xs"
    return "event"


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

    gates_raw = params["gates"]
    if gates_raw in (None, "", "None"):
        gates: list[str] = []
    elif isinstance(gates_raw, str):
        gates = [
            x.strip()
            for x in gates_raw.split(",")
            if x.strip() and x.strip() != "None"
        ]
    else:
        gates = [
            str(x).strip()
            for x in list(gates_raw)
            if str(x).strip() and str(x).strip() != "None"
        ]

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


def yaml_combo_rows(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Combo runtime rows from catalog YAML. Filter by evaluator; do not import combo runtime."""
    rows: list[dict[str, Any]] = []
    for spec in load_catalog_specs(root=root):
        if str(spec.get("evaluator") or "") != _COMBO_EVALUATOR:
            continue
        rows.append(combo_row_from_yaml(spec))
    return rows


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
    """Non-combo YAML stems grouped by family (or evaluator module). Does not GO."""
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
    """Combo YAML stems grouped by ``_yaml_combo_kind``. Does not import combo runtime."""
    event: set[str] = set()
    cs: set[str] = set()
    surprise_xs: set[str] = set()
    for spec in load_catalog_specs(root=root):
        if str(spec.get("evaluator") or "") != _COMBO_EVALUATOR:
            continue
        lid = str(spec.get("logic_id") or "")
        if not lid:
            continue
        params = spec.get("params")
        cs_raw = params.get("cs_gate") if isinstance(params, Mapping) else None
        cs_gate = None if cs_raw in (None, "", "None") else str(cs_raw)
        kind = _yaml_combo_kind(spec, cs_gate=cs_gate)
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
