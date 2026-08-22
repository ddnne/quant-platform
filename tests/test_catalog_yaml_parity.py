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


def test_cf_new_thesis_ids_match_yaml_combo_kind() -> None:
    import inspect

    from research.unique_logic import catalog as catalog_mod
    from research.unique_logic import constants as constants_mod
    from research.unique_logic.catalog import (
        _COMBO_EVALUATOR,
        _yaml_combo_kind,
        load_catalog_specs,
    )
    from research.unique_logic.constants import (
        ADAPTIVE_LOGIC_IDS,
        CF_NEW_CS_THESIS_IDS,
        CF_NEW_EVENT_THESIS_IDS,
        CF_NEW_THESIS_IDS,
        CS_LOGIC_IDS,
        EVENT_FILTER_LOGIC_IDS,
        EVENT_LOGIC_IDS,
        EVENT_SIDES_LOGIC_IDS,
        RESEARCH_UNIQUE_LOGIC_IDS,
    )

    event: set[str] = set()
    cs: set[str] = set()
    surprise_xs: set[str] = set()
    yaml_ids: set[str] = set()
    combo_ids: set[str] = set()
    for spec in load_catalog_specs():
        lid = str(spec.get("logic_id") or "")
        yaml_ids.add(lid)
        if str(spec.get("evaluator") or "") != _COMBO_EVALUATOR:
            continue
        combo_ids.add(lid)
        params = spec.get("params")
        cs_raw = params.get("cs_gate") if isinstance(params, dict) else None
        cs_gate = None if cs_raw in (None, "", "None") else str(cs_raw)
        kind = _yaml_combo_kind(spec, cs_gate=cs_gate)
        if kind == "cs":
            cs.add(lid)
        elif kind == "surprise_xs":
            surprise_xs.add(lid)
        else:
            event.add(lid)

    original = (
        EVENT_LOGIC_IDS
        | EVENT_FILTER_LOGIC_IDS
        | EVENT_SIDES_LOGIC_IDS
        | ADAPTIVE_LOGIC_IDS
        | CS_LOGIC_IDS
    )
    assert len(original) == 22
    assert yaml_ids - combo_ids == set(original)
    assert combo_ids == set(CF_NEW_THESIS_IDS)
    assert event | surprise_xs == set(CF_NEW_EVENT_THESIS_IDS)
    assert cs == set(CF_NEW_CS_THESIS_IDS)
    assert len(CF_NEW_EVENT_THESIS_IDS) == 218
    assert len(CF_NEW_CS_THESIS_IDS) == 98
    assert len(CF_NEW_THESIS_IDS) == 316
    assert len(RESEARCH_UNIQUE_LOGIC_IDS) == 338
    assert yaml_ids == set(RESEARCH_UNIQUE_LOGIC_IDS)

    helper_src = inspect.getsource(catalog_mod.combo_thesis_ids_by_kind)
    assert "from research.unique_logic.event_combos" not in helper_src
    assert "_combo_row" not in helper_src
    assert "NEW_COMBO_LOGIC" not in helper_src
    const_src = inspect.getsource(constants_mod)
    assert "event_funding_tight_fade" not in const_src
    assert "overnight_tight_cs_fade" not in const_src


# Frozen keys/counts from the former constants.ECONOMIC_THEME_IDS block.
_PREVIOUS_THEME_COUNTS = {
    "surprise_funding": 4,
    "margin_price_disagree": 4,
    "repo_cs": 4,
    "vol_conditional": 4,
    "fundamentals": 10,
    "fund_leverage_cross": 33,
    "fund_flow_liq": 16,
    "margin_surprise": 11,
    "repo_event": 10,
    "vol_fund_cross": 15,
}


def test_economic_theme_ids_from_yaml() -> None:
    import inspect
    import re

    from research.unique_logic import catalog as catalog_mod
    from research.unique_logic import constants as constants_mod
    from research.unique_logic.catalog import (
        economic_theme_ids,
        parse_catalog_yaml,
        themes_path,
    )
    from research.unique_logic.constants import (
        ECONOMIC_THEME_IDS,
        RESEARCH_UNIQUE_LOGIC_IDS,
    )

    path = themes_path()
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    parsed = parse_catalog_yaml(text)
    assert parsed.get("go") is not True
    assert re.search(r"(?m)^go:\s*true\s*$", text) is None
    themes = economic_theme_ids()
    assert ECONOMIC_THEME_IDS == themes
    assert set(themes) == set(_PREVIOUS_THEME_COUNTS)
    assert {k: len(v) for k, v in themes.items()} == _PREVIOUS_THEME_COUNTS
    listed = set().union(*themes.values()) if themes else set()
    assert listed <= set(RESEARCH_UNIQUE_LOGIC_IDS)
    for theme, ids in themes.items():
        yaml_ids = {str(x) for x in parsed[theme]}
        assert yaml_ids == set(ids)
        assert ids <= RESEARCH_UNIQUE_LOGIC_IDS
    helper_src = inspect.getsource(catalog_mod.economic_theme_ids)
    assert "research_themes.yaml" in helper_src
    assert "Does not GO" in helper_src
    const_src = inspect.getsource(constants_mod)
    assert "economic_theme_ids()" in const_src
    assert "surprise_xs_tight_fade" not in const_src
    assert "event_on_impulse_pead" not in const_src
    for yml in _YAML_DIR.glob("*.yaml"):
        body = yml.read_text(encoding="utf-8")
        assert re.search(r"(?m)^theme:", body) is None
        assert re.search(r"(?m)^go:\s*true\s*$", body) is None


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
    assert catalog == frozenset()

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
    assert "pre_mom" in worker_gates
    easy_m = re.search(
        r'if \(lid === "event_pre_mom_easy_funding"\) \{.*?\}',
        src,
        flags=re.S,
    )
    steep_m = re.search(
        r'if \(lid === "event_pre_mom_steep_curve"\) \{.*?\}',
        src,
        flags=re.S,
    )
    assert easy_m and steep_m
    assert 'comboEventGateOk("pre_mom"' in easy_m.group(0)
    assert 'comboEventGateOk("pre_mom"' in steep_m.group(0)
    assert "momentumAt" not in easy_m.group(0)
    assert "momentumAt" not in steep_m.group(0)
    assert "params.side" in easy_m.group(0)
    assert "params.side" in steep_m.group(0)
    assert 'lid === "surprise_xs_month_start" && ev.entryDate.slice(8, 10) > "05"' in src
    assert 'lid === "surprise_xs_fy_end"' in src


def test_event_cheap_pb_gate_in_combo_and_yaml() -> None:
    """cheap_pb stays a COMBO event gate; YAML pead lists it. Not a CS reuse."""
    import re
    from pathlib import Path

    from research.eval_tracks import NEXT_RESEARCH_QUEUE
    from research.unique_logic.catalog import combo_row_from_yaml, parse_catalog_yaml
    from research.unique_logic.constants import CHEAP_PB_EVENT_VS_CS, COMBO_EVENT_GATES

    assert "cheap_pb" in COMBO_EVENT_GATES
    assert CHEAP_PB_EVENT_VS_CS == "event_bars_x_fins_not_csfundsnaps"

    yml = parse_catalog_yaml(
        (_YAML_DIR / "event_cheap_pb_pead.yaml").read_text(encoding="utf-8")
    )
    params = yml.get("params") or {}
    assert "gates" in params
    gates_raw = params["gates"]
    if isinstance(gates_raw, str):
        yaml_gates = [x.strip() for x in gates_raw.split(",") if x.strip()]
    else:
        yaml_gates = [str(x).strip() for x in list(gates_raw or []) if str(x).strip()]
    assert "cheap_pb" in yaml_gates
    derived = combo_row_from_yaml(yml)
    derived_gates = list(
        (derived.get("params") or {}).get("gates") or derived.get("gates") or []
    )
    assert "cheap_pb" in derived_gates

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
    assert "cheap_pb" in worker_gates

    event_block = re.search(
        r'if \(gate === "cheap_pb"\) \{.*?return med !== null && pb < med;',
        src,
        flags=re.S,
    )
    assert event_block, "comboEventGateOk cheap_pb body"
    body = event_block.group(0)
    assert "bars" in body and "fins" in body
    assert "ev.bps" in body
    assert "reverse().find" in body
    assert "extras?.cheapPb" not in body
    assert any(q.get("id") == "cheap_pb_event_reuse" for q in NEXT_RESEARCH_QUEUE)
