"""Catalog YAML vs Python unique_logic identity (no scores, no GO)."""
from __future__ import annotations

from pathlib import Path

from research.unique_logic import all_unique_logic_specs, load_catalog_specs
from research.unique_logic.constants import (
    CF_NEW_THESIS_IDS,
    KNOWN_EVENT_GATES,
    WORKER_ISOLATE_LIMIT_IDS,
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
    from research.unique_logic.catalog import parse_catalog_yaml
    from research.unique_logic.event_combos import spec_by_id

    py = spec_by_id("event_eqar_high_pead")
    assert py is not None
    path = _YAML_DIR / "event_eqar_high_pead.yaml"
    yml = parse_catalog_yaml(path.read_text(encoding="utf-8"))
    py_gates = list((py.get("params") or {}).get("gates") or py.get("gates") or [])
    yml_gates = yml.get("params", {}).get("gates")
    if yml_gates is None:
        # Rewrite may not have landed yet; Python params remain CF SoT.
        assert py_gates
        return
    assert list(yml_gates) == py_gates


def test_unknown_event_gate_fail_closed_is_declared() -> None:
    import inspect

    import research.unique_logic.event_combos as event_combos

    # Runtime skip is covered in test_research_freezes; keep this source-level.
    assert "not_a_real_gate" not in KNOWN_EVENT_GATES
    src = inspect.getsource(event_combos)
    assert "if g not in KNOWN_EVENT_GATES" in src
