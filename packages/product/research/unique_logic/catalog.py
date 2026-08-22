"""Load unique_logic declarations from ``specs/research_logics/*.yaml``.

YAML catalog is the declaration source of truth (gates, cs_gate, side).
``event_combos._SPECS`` remains the typed runtime table; do not delete it.
Runtime dispatch still uses Python rows so gates stay typed.
Scores live in R2/D1, not markdown.
The schema is intentionally small (no general YAML dependency).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from qp_paths import repo_root


def catalog_dir(*, root: Path | None = None) -> Path:
    return (root or repo_root()) / "specs" / "research_logics"


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
            if key == "datasets":
                items: list[Any] = []
                while i < n:
                    ln = lines[i]
                    if not ln.strip() or ln.lstrip().startswith("#"):
                        i += 1
                        continue
                    if not ln.startswith(" "):
                        break
                    if ln.strip().startswith("-"):
                        items.append(_parse_scalar(ln.strip()[1:]))
                    i += 1
                data[key] = items
                continue
            data[key] = None
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


def load_catalog_specs(*, root: Path | None = None) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for path in sorted(catalog_dir(root=root).glob("*.yaml")):
        spec = parse_catalog_yaml(path.read_text(encoding="utf-8"))
        spec["catalog_path"] = str(path)
        spec["catalog"] = True
        if spec.get("logic_id"):
            specs.append(spec)
    return specs


def catalog_spec(logic_id: str, *, root: Path | None = None) -> dict[str, Any] | None:
    lid = str(logic_id)
    for spec in load_catalog_specs(root=root):
        if str(spec.get("logic_id")) == lid:
            return spec
    return None


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
    """Map catalog YAML to the same keys as ``event_combos._combo_row``.

    YAML is the declaration SoT. Missing ``params.gates`` / ``cs_gate`` /
    ``side`` fail closed. Does not GO.
    """
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
    row = _combo_row(raw)
    row["go"] = False
    row["generation_enabled"] = False
    row["promote_as_main"] = False
    row["headline"] = False
    return row


def yaml_combo_rows(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Combo rows from catalog YAML (declaration SoT; not runtime dispatch)."""
    from research.unique_logic.event_combos import NEW_COMBO_LOGIC

    combo_ids = {str(s["logic_id"]) for s in NEW_COMBO_LOGIC}
    rows: list[dict[str, Any]] = []
    for spec in load_catalog_specs(root=root):
        evaluator = str(spec.get("evaluator") or "")
        lid = str(spec.get("logic_id") or "")
        if evaluator != _COMBO_EVALUATOR and lid not in combo_ids:
            continue
        rows.append(combo_row_from_yaml(spec))
    return rows


def combo_yaml_text(spec: Mapping[str, Any]) -> str:
    """Constrained catalog YAML for a combo thesis (no generic YAML lib)."""
    lid = str(spec["logic_id"])
    thesis = " ".join(str(spec.get("thesis") or "").split())
    main_pool = bool(spec.get("main_pool", True)) and not spec.get(
        "data_requirement_unmet"
    )
    notes = "combo thesis; occupancy-gated; CF daily_path is SoT"
    if spec.get("near_duplicate"):
        notes = "combo thesis; parked near-duplicate / gate permutation; CF daily_path is SoT"
    elif spec.get("always_on_cs_sticky"):
        notes = "combo thesis; parked always_on CS sticky; CF daily_path is SoT"
    elif spec.get("data_requirement_unmet") or not main_pool:
        notes = "combo thesis; data_requirement_unmet on small shards; CF daily_path is SoT"
    params = dict(spec.get("params") or {})
    cs_gate = params.get("cs_gate")
    cs_s = "None" if cs_gate in (None, "None", "") else str(cs_gate)
    gates_raw = params.get("gates")
    if gates_raw is None:
        gates_raw = spec.get("gates") or ()
    if isinstance(gates_raw, str):
        gates_txt = gates_raw.strip()
    else:
        gates_txt = ",".join(str(x) for x in list(gates_raw) if str(x).strip())
    datasets = list(spec.get("datasets") or (
        "equities_bars_daily",
        "fins_summary",
        "jsda_tokyo_repo_rates",
        "markets_calendar",
    ))
    ds = "\n".join(f"  - {d}" for d in datasets)
    return (
        f"logic_id: {lid}\n"
        f"family_id: {spec.get('family_id') or 'event_calendar_gate'}\n"
        "axis: mixed\n"
        "headline: false\n"
        "generation_enabled: false\n"
        "promote_as_main: false\n"
        "go: false\n"
        f"main_pool: {'true' if main_pool else 'false'}\n"
        f"thesis: >\n  {thesis}\n"
        f"signal_definition: >\n  {thesis}\n"
        f"datasets:\n{ds}\n"
        "params:\n"
        f"  post_hold_days: {int(params.get('post_hold_days') or 5)}\n"
        f"  hold_days: {int(params.get('hold_days') or 10)}\n"
        f"  momentum_n: {int(params.get('momentum_n') or 5)}\n"
        f"  min_hist: {int(params.get('min_hist') or 20)}\n"
        f"  mode: {lid}\n"
        f"  side: {params.get('side') or spec.get('side') or 'orig'}\n"
        f"  gates: {gates_txt}\n"
        f"  cs_gate: {cs_s}\n"
        f"  entry_shift: {int(params.get('entry_shift') or 0)}\n"
        f"  hold_tail_days: {int(params.get('hold_tail_days') or 0)}\n"
        "evaluator: research.unique_logic.event_combos.evaluate_combo_daily_mtm\n"
        f"notes: {notes}\n"
    )


def write_missing_combo_yaml(*, root: Path | None = None) -> list[str]:
    """Create catalog YAML for combo specs that have no file yet."""
    from research.unique_logic.event_combos import NEW_COMBO_LOGIC

    d = catalog_dir(root=root)
    d.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    existing = {p.stem for p in d.glob("*.yaml")}
    for spec in NEW_COMBO_LOGIC:
        lid = str(spec["logic_id"])
        path = d / f"{lid}.yaml"
        if lid in existing and not (
            spec.get("near_duplicate")
            or spec.get("data_requirement_unmet")
            or spec.get("always_on_cs_sticky")
            or spec.get("worker_isolate_limit")
            or "\n  gates:" not in path.read_text(encoding="utf-8")
        ):
            continue
        path.write_text(combo_yaml_text(spec), encoding="utf-8")
        written.append(lid)
    return written
