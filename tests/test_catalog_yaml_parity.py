"""Catalog YAML vs Python unique_logic identity (no scores, no GO)."""
from __future__ import annotations

from pathlib import Path

from research.unique_logic import all_unique_logic_specs, load_catalog_specs
from research.unique_logic.constants import (
    CF_NEW_THESIS_IDS,
    COMBO_EVENT_GATES,
    KNOWN_EVENT_GATES,
    PYTHON_ONLY_EVENT_GATES,
    WORKER_ISOLATE_LIMIT_IDS,
    WORKER_PYTHON_ONLY_GATE_POLICY,
    python_only_gate_logic_ids,
)

_YAML_DIR = Path(__file__).resolve().parents[1] / "specs" / "research_logics"


def test_catalog_yaml_parity_with_python_specs() -> None:
    from research.unique_logic.event_combos import NEW_COMBO_LOGIC

    catalog = load_catalog_specs()
    catalog_ids = {s["logic_id"] for s in catalog}
    py_ids = {s["logic_id"] for s in all_unique_logic_specs()}
    yaml_ids = {p.stem for p in _YAML_DIR.glob("*.yaml")}
    combo_ids = {s["logic_id"] for s in NEW_COMBO_LOGIC}

    assert catalog_ids == py_ids
    assert yaml_ids == py_ids
    missing_combo_files = sorted(
        lid for lid in combo_ids if not (_YAML_DIR / f"{lid}.yaml").is_file()
    )
    assert missing_combo_files == []
    extra_yaml = sorted(yaml_ids - py_ids)
    assert extra_yaml == []
    assert set(CF_NEW_THESIS_IDS) <= catalog_ids
    assert WORKER_ISOLATE_LIMIT_IDS == frozenset()

    for spec in catalog:
        assert spec.get("go") is not True
        assert spec.get("promote_as_main") is not True
        path = Path(spec["catalog_path"])
        assert path.stem == spec["logic_id"]
        assert path.is_file()
    for spec in all_unique_logic_specs():
        assert spec.get("go") is not True
        assert spec.get("promote_as_main") is not True


def test_combo_yaml_params_include_gates() -> None:
    from research.unique_logic.catalog import combo_row_from_yaml, parse_catalog_yaml
    from research.unique_logic.event_combos import combo_runtime_spec

    py = combo_runtime_spec("event_eqar_high_pead")
    assert py is not None
    path = _YAML_DIR / "event_eqar_high_pead.yaml"
    yml = parse_catalog_yaml(path.read_text(encoding="utf-8"))
    assert "gates" in (yml.get("params") or {})
    assert "cs_gate" in (yml.get("params") or {})
    assert "side" in (yml.get("params") or {})
    derived = combo_row_from_yaml(yml)
    py_p = py.get("params") or {}
    y_p = derived.get("params") or {}
    assert list(y_p.get("gates") or []) == list(py_p.get("gates") or [])
    assert y_p.get("cs_gate") == py_p.get("cs_gate")
    assert y_p.get("side") == py_p.get("side")
    assert derived.get("go") is False
    assert derived.get("generation_enabled") is False


def test_combo_yaml_gates_cs_gate_side_match_specs() -> None:
    from research.unique_logic.catalog import yaml_combo_rows
    from research.unique_logic.event_combos import (
        NEW_COMBO_LOGIC,
        assert_yaml_matches_specs,
        combo_runtime_spec,
    )

    assert_yaml_matches_specs()
    yaml_rows = yaml_combo_rows()
    yaml_ids = {r["logic_id"] for r in yaml_rows}
    py_ids = {s["logic_id"] for s in NEW_COMBO_LOGIC}
    assert py_ids == yaml_ids
    sample = NEW_COMBO_LOGIC[0]
    rt = combo_runtime_spec(sample["logic_id"])
    assert rt is not None
    assert rt["logic_id"] == sample["logic_id"]
    assert rt.get("go") is not True
    # Runtime dispatch walks YAML-derived NEW_COMBO_LOGIC.
    assert rt is sample
    import inspect

    from research.unique_logic import catalog as catalog_mod

    src = inspect.getsource(catalog_mod.yaml_combo_rows)
    assert "import NEW_COMBO_LOGIC" not in src
    assert "NEW_COMBO_LOGIC" not in src
    assert "_COMBO_EVALUATOR" in src


def test_unknown_event_gate_fail_closed_is_declared() -> None:
    import inspect

    import research.unique_logic.event_combos as event_combos

    # Runtime skip is covered in test_research_freezes; keep this source-level.
    assert "not_a_real_gate" not in KNOWN_EVENT_GATES
    src = inspect.getsource(event_combos)
    assert "if g not in KNOWN_EVENT_GATES" in src


def test_python_only_event_gates_skip_catalog() -> None:
    import re
    from pathlib import Path

    from research.unique_logic.event_combos import NEW_COMBO_LOGIC

    assert WORKER_PYTHON_ONLY_GATE_POLICY == "python_local_or_lid_branch"
    assert PYTHON_ONLY_EVENT_GATES.isdisjoint(COMBO_EVENT_GATES)

    catalog = python_only_gate_logic_ids()
    intersecting = frozenset(
        str(s["logic_id"])
        for s in NEW_COMBO_LOGIC
        if PYTHON_ONLY_EVENT_GATES.intersection(
            (s.get("params") or {}).get("gates") or ()
        )
    )
    assert catalog == intersecting
    assert catalog == frozenset(
        {
            "event_pre_mom_easy_funding",
            "event_pre_mom_steep_curve",
        }
    )

    src = (
        Path(__file__).resolve().parents[1]
        / "platform"
        / "workers"
        / "research-mass-eval"
        / "src"
        / "daily_path.ts"
    ).read_text(encoding="utf-8")
    m = re.search(
        r"const COMBO_EVENT_GATES = new Set\(\[(.*?)]\);",
        src,
        flags=re.S,
    )
    assert m, "Worker COMBO_EVENT_GATES"
    worker_gates = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert worker_gates.isdisjoint(PYTHON_ONLY_EVENT_GATES)
    assert worker_gates == set(COMBO_EVENT_GATES)
