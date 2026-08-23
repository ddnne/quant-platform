"""Catalog YAML vs Python unique_logic identity (no scores, no GO)."""
from __future__ import annotations

from pathlib import Path

from research.unique_logic import all_unique_logic_specs, load_catalog_specs
from research.unique_logic.constants import (
    CF_NEW_THESIS_IDS,
    COMBO_EVENT_GATES,
    PYTHON_ONLY_EVENT_GATES,
    WORKER_ISOLATE_LIMIT_IDS,
    WORKER_PYTHON_ONLY_GATE_POLICY,
    python_only_gate_logic_ids,
)

_YAML_DIR = Path(__file__).resolve().parents[1] / "specs" / "research_logics"


def test_catalog_yaml_parity_with_python_specs() -> None:
    """YAML stems == catalog == constants. One identity test; do not pin counts."""
    import inspect
    import re

    from research.unique_logic import catalog as catalog_mod
    from research.unique_logic import constants as constants_mod
    from research.unique_logic.catalog import (
        _COMBO_EVALUATOR,
        _yaml_combo_kind,
        unique_family_ids_from_yaml,
    )
    from research.unique_logic.constants import (
        ADAPTIVE_LOGIC_IDS,
        CF_NEW_CS_THESIS_IDS,
        CF_NEW_EVENT_THESIS_IDS,
        CS_LOGIC_IDS,
        EVENT_FILTER_LOGIC_IDS,
        EVENT_LOGIC_IDS,
        EVENT_SIDES_LOGIC_IDS,
        RESEARCH_UNIQUE_LOGIC_IDS,
    )
    from research.unique_logic.event_combos import NEW_COMBO_LOGIC

    catalog = load_catalog_specs()
    catalog_ids = {s["logic_id"] for s in catalog}
    py_ids = {s["logic_id"] for s in all_unique_logic_specs()}
    yaml_ids = {p.stem for p in _YAML_DIR.glob("*.yaml")}
    combo_ids = {s["logic_id"] for s in NEW_COMBO_LOGIC}

    assert catalog_ids == py_ids == yaml_ids == set(RESEARCH_UNIQUE_LOGIC_IDS)
    missing_combo_files = sorted(
        lid for lid in combo_ids if not (_YAML_DIR / f"{lid}.yaml").is_file()
    )
    assert missing_combo_files == []
    extra_yaml = sorted(yaml_ids - py_ids)
    assert extra_yaml == []
    assert set(CF_NEW_THESIS_IDS) <= catalog_ids
    assert WORKER_ISOLATE_LIMIT_IDS == frozenset()

    event: set[str] = set()
    cs: set[str] = set()
    surprise_xs: set[str] = set()
    for spec in catalog:
        assert spec.get("go") is not True
        assert spec.get("promote_as_main") is not True
        assert spec.get("generation_enabled") is False
        path = Path(spec["catalog_path"])
        assert path.stem == spec["logic_id"]
        assert path.is_file()
        lid = str(spec.get("logic_id") or "")
        if str(spec.get("evaluator") or "") != _COMBO_EVALUATOR:
            continue
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
    for spec in NEW_COMBO_LOGIC:
        assert spec.get("generation_enabled") is False
        assert spec.get("go") is not True

    families = unique_family_ids_from_yaml()
    assert set(families) == {
        "event",
        "event_filter",
        "event_sides",
        "adaptive",
        "cs",
    }
    assert families["event"] == EVENT_LOGIC_IDS
    assert families["event_filter"] == EVENT_FILTER_LOGIC_IDS
    assert families["event_sides"] == EVENT_SIDES_LOGIC_IDS
    assert families["adaptive"] == ADAPTIVE_LOGIC_IDS
    assert families["cs"] == CS_LOGIC_IDS
    original = (
        EVENT_LOGIC_IDS
        | EVENT_FILTER_LOGIC_IDS
        | EVENT_SIDES_LOGIC_IDS
        | ADAPTIVE_LOGIC_IDS
        | CS_LOGIC_IDS
    )
    assert yaml_ids - combo_ids == set(original)
    assert combo_ids == set(CF_NEW_THESIS_IDS)
    assert event | surprise_xs == set(CF_NEW_EVENT_THESIS_IDS)
    assert cs == set(CF_NEW_CS_THESIS_IDS)
    assert original.isdisjoint(CF_NEW_THESIS_IDS)
    assert original | set(CF_NEW_THESIS_IDS) == set(RESEARCH_UNIQUE_LOGIC_IDS)

    helper_src = inspect.getsource(catalog_mod.combo_thesis_ids_by_kind)
    helper_src += inspect.getsource(catalog_mod.unique_family_ids_from_yaml)
    helper_src += inspect.getsource(catalog_mod._unique_family_key)
    assert "from research.unique_logic.event_combos" not in helper_src
    assert "NEW_COMBO_LOGIC" not in helper_src
    assert "_combo_row" not in helper_src
    const_src = inspect.getsource(constants_mod)
    assert "unique_family_ids_from_yaml()" in const_src
    assert "combo_thesis_ids_by_kind()" in const_src
    assert "event_funding_tight_fade" not in const_src
    for lid in original:
        assert lid not in const_src
    from research.unique_logic import (
        adaptive as adaptive_mod,
        cross_section as cs_mod,
        cs_overlays as overlays_mod,
        event as event_mod,
        event_filters as filters_mod,
        event_sides as sides_mod,
    )

    for mod, flag in (
        (event_mod, "EVENT_LOGIC_IDS"),
        (filters_mod, "EVENT_FILTER_LOGIC_IDS"),
        (sides_mod, "EVENT_SIDES_LOGIC_IDS"),
        (adaptive_mod, "ADAPTIVE_LOGIC_IDS"),
        (cs_mod, "CS_LOGIC_IDS"),
        (overlays_mod, "CS_LOGIC_IDS"),
    ):
        header = inspect.getsource(mod).split("def ", 1)[0]
        assert flag in header
        quoted = {f'"{lid}"' for lid in original} | {f"'{lid}'" for lid in original}
        assert not any(q in header for q in quoted)
    for yml in _YAML_DIR.glob("*.yaml"):
        body = yml.read_text(encoding="utf-8")
        assert re.search(r"(?m)^go:\s*true\s*$", body) is None
        if yml.stem in original:
            assert re.search(r"(?m)^family:\s+\S+", body)
            assert re.search(r"(?m)^generation_enabled:\s*true\s*$", body) is None
        else:
            assert re.search(r"(?m)^family:", body) is None


def test_combo_yaml_gates_cs_gate_side_match_specs() -> None:
    from research.unique_logic.catalog import yaml_combo_rows
    from research.unique_logic.event_combos import (
        NEW_COMBO_LOGIC,
        assert_yaml_matches_specs,
        spec_by_id,
    )

    assert_yaml_matches_specs()
    yaml_rows = yaml_combo_rows()
    yaml_ids = {r["logic_id"] for r in yaml_rows}
    py_ids = {s["logic_id"] for s in NEW_COMBO_LOGIC}
    assert py_ids == yaml_ids
    sample = NEW_COMBO_LOGIC[0]
    rt = spec_by_id(sample["logic_id"])
    assert rt is not None
    assert rt["logic_id"] == sample["logic_id"]
    assert rt.get("go") is not True
    # Runtime dispatch walks YAML-derived NEW_COMBO_LOGIC.
    assert rt is sample
    import inspect

    from research.unique_logic import catalog as catalog_mod

    src = inspect.getsource(catalog_mod.yaml_combo_rows)
    cached_src = inspect.getsource(catalog_mod._yaml_combo_rows_cached)
    assert "import NEW_COMBO_LOGIC" not in src
    assert "NEW_COMBO_LOGIC" not in src
    assert "NEW_COMBO_LOGIC" not in cached_src
    assert "_COMBO_EVALUATOR" in cached_src


# Frozen theme keys from the former constants.ECONOMIC_THEME_IDS block.
# Exact member counts are YAML-derived; do not pin integers here.
_PREVIOUS_THEME_KEYS = frozenset(
    {
        "surprise_funding",
        "margin_price_disagree",
        "repo_cs",
        "vol_conditional",
        "fundamentals",
        "fund_leverage_cross",
        "fund_flow_liq",
        "margin_surprise",
        "repo_event",
        "vol_fund_cross",
    }
)


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
    assert set(themes) == set(_PREVIOUS_THEME_KEYS)
    assert all(len(v) >= 1 for v in themes.values())
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


def test_python_only_event_gates_skip_catalog() -> None:
    from research.unique_logic.event_combos import NEW_COMBO_LOGIC

    assert WORKER_PYTHON_ONLY_GATE_POLICY == "python_local_or_lid_branch"
    assert PYTHON_ONLY_EVENT_GATES == frozenset()
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


def test_event_cheap_pb_gate_in_combo_and_yaml() -> None:
    """cheap_pb stays a COMBO event gate; YAML pead lists it. Not a CS reuse."""
    import re
    from pathlib import Path

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

    worker_src = (
        Path(__file__).resolve().parents[1]
        / "platform"
        / "workers"
        / "research-mass-eval"
        / "src"
    )
    src = (worker_src / "daily_path.ts").read_text(encoding="utf-8")
    # catalog_ids.ts COMBO_EVENT_GATES is generated; sync --check is the set SoT.

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


def test_countable_thesis_ids_require_worker_body() -> None:
    from research.eval_summary import summarize_daily_path_cells
    from research.unique_logic.catalog import catalog_spec, load_catalog_specs
    from research.unique_logic.constants import (
        ALWAYS_ON_PARK_IDS,
        CANDIDATE_POLICY,
        CF_NEW_THESIS_IDS,
        COMBO_EVENT_GATES,
        NEAR_EMPTY_PARK_IDS,
        RESEARCH_UNIQUE_LOGIC_IDS,
        countable_thesis_ids,
        worker_implemented_logic_ids,
    )
    from research.unique_logic.near_duplicate import is_near_duplicate
    from research.unique_logic.worker_bodies import (
        combo_worker_gates_ok,
        is_countable_spec,
    )
    from tests.research_eval_util import _eval_complete_cell

    countable = countable_thesis_ids()
    implemented = worker_implemented_logic_ids()
    assert countable <= RESEARCH_UNIQUE_LOGIC_IDS
    assert implemented <= RESEARCH_UNIQUE_LOGIC_IDS
    assert countable <= implemented

    forged = {
        "logic_id": "event_forged_clone_not_a_real_gate",
        "params": {
            "gates": ["not_a_real_gate"],
            "cs_gate": None,
            "side": "orig",
        },
    }
    assert "not_a_real_gate" not in COMBO_EVENT_GATES
    assert is_countable_spec(forged) is False

    real = catalog_spec("event_eqar_high_pead")
    assert real is not None
    overlay = dict(real)
    overlay["params"] = dict(real.get("params") or {})
    overlay["params"]["gates"] = ["not_a_real_gate"]
    assert is_countable_spec(overlay) is False
    assert combo_worker_gates_ok(overlay) is False

    known = 0
    for spec in load_catalog_specs():
        lid = str(spec.get("logic_id") or "")
        if lid not in CF_NEW_THESIS_IDS:
            continue
        if is_near_duplicate(lid):
            assert lid not in countable
            continue
        if lid in NEAR_EMPTY_PARK_IDS:
            assert lid not in countable
            continue
        if lid in ALWAYS_ON_PARK_IDS:
            assert lid not in countable
            continue
        if combo_worker_gates_ok(spec):
            known += 1
            assert lid in countable
            assert is_countable_spec(spec) is True
    assert known >= 1
    assert "event_eqar_high_pead" in countable
    from research.unique_logic.worker_bodies import (
        CHEAP_PB_PRIMARY_GATE_CAP,
        CheapPbPrimaryCapError,
        assert_new_batch_cheap_pb_cap,
        countable_inventory_bias,
    )

    bias = countable_inventory_bias()
    assert bias["n_countable"] == len(countable)
    assert bias["go"] is False
    assert 0 <= float(bias["cheap_pb_primary_share"]) < CHEAP_PB_PRIMARY_GATE_CAP
    assert bias["cheap_pb_primary_cap"] == CHEAP_PB_PRIMARY_GATE_CAP
    ok_batch = [
        {"logic_id": "a", "params": {"gates": ["margin_up", "repo_3m_down"]}},
        {"logic_id": "b", "params": {"gates": ["ta_up", "overnight_easing"]}},
        {"logic_id": "c", "params": {"gates": ["cheap_iv", "uncrowded_margin"]}},
        {"logic_id": "d", "params": {"gates": ["eq_ar_rising", "steep_curve"]}},
        {"logic_id": "e", "params": {"gates": ["nky_vol_high_skip", "ta_up"]}},
        {"logic_id": "f", "params": {"gates": ["cheap_pb", "liq_high"]}},
    ]
    cap = assert_new_batch_cheap_pb_cap(ok_batch)
    assert cap["ok"] is True
    assert cap["cheap_pb_primary"] == 1
    over = ok_batch[:2] + [
        {"logic_id": "p1", "params": {"gates": ["cheap_pb", "ta_up"]}},
        {"logic_id": "p2", "params": {"gates": ["cheap_pb", "margin_up"]}},
        {"logic_id": "p3", "params": {"gates": ["cheap_pb", "repo_3m_down"]}},
    ]
    try:
        assert_new_batch_cheap_pb_cap(over)
        raise AssertionError("cap must reject")
    except CheapPbPrimaryCapError:
        pass

    assert "worker_body_missing" in CANDIDATE_POLICY["exclude"]
    assert "near_empty_parked" in CANDIDATE_POLICY["exclude"]
    assert "always_on_parked" in CANDIDATE_POLICY["exclude"]
    cells = [
        _eval_complete_cell(
            "xs_high_vol_fade", occupancy=0.20, eval_path="gated_cs"
        )
    ]
    row = summarize_daily_path_cells(cells, job_id="eval-test-worker-body")[
        "logics"
    ][0]
    assert "worker_body_missing" in row["flags"]
    assert row["candidate"] is False


def test_normalize_gates_and_spec_gates() -> None:
    from research.unique_logic.catalog import catalog_spec, normalize_gates, spec_gates

    assert normalize_gates(None) == []
    assert normalize_gates("None") == []
    assert normalize_gates("") == []
    assert normalize_gates("ta_up,positive_eps") == ["ta_up", "positive_eps"]
    assert normalize_gates(["afterclose", "positive_eps", "ta_up"]) == [
        "afterclose",
        "positive_eps",
        "ta_up",
    ]
    spec = catalog_spec("event_ta_up_positive_eps")
    assert spec is not None
    assert set(spec_gates(spec)) == {"ta_up", "positive_eps"}
    assert spec_gates(None) == []
    assert spec_gates({"params": {}}) == []
