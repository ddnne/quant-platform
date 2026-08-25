"""Catalog compiled map is the unique_logic declaration path (not run_w copies)."""
from __future__ import annotations

from research.unique_logic.catalog import load_catalog_specs, parse_catalog_yaml


def test_event_sides_ls_variants_stay_registered() -> None:
    from research.unique_logic import event_sides
    from research.unique_logic.catalog import yaml_unique_rows
    from research.unique_logic.constants import (
        ADAPTIVE_LOGIC_IDS,
        CS_LOGIC_IDS,
        EVENT_SIDES_LOGIC_IDS,
        RESEARCH_UNIQUE_LOGIC_IDS,
    )
    from tests.research_eval_util import assert_unique_family_specs

    assert_unique_family_specs(
        list(event_sides.NEW_LS_VARIANTS), EVENT_SIDES_LOGIC_IDS
    )
    assert set(EVENT_SIDES_LOGIC_IDS) <= set(RESEARCH_UNIQUE_LOGIC_IDS)
    assert_unique_family_specs(
        yaml_unique_rows(logic_ids=sorted(ADAPTIVE_LOGIC_IDS)),
        ADAPTIVE_LOGIC_IDS,
    )
    assert_unique_family_specs(
        yaml_unique_rows(logic_ids=sorted(CS_LOGIC_IDS)),
        CS_LOGIC_IDS,
    )


def test_pri_gate_sets_are_combo_event_gates() -> None:
    from research.unique_logic.constants import (
        COMBO_EVENT_GATES,
        PRI_FLOW_GATES,
        PRI_FUND_GATES,
        PRI_RATE_GATES,
        PRI_VOL_GATES,
    )

    assert PRI_VOL_GATES <= COMBO_EVENT_GATES
    assert PRI_FLOW_GATES <= COMBO_EVENT_GATES
    assert PRI_RATE_GATES <= COMBO_EVENT_GATES
    assert PRI_FUND_GATES <= COMBO_EVENT_GATES
    assert not (PRI_VOL_GATES & PRI_FLOW_GATES)
    assert not (PRI_VOL_GATES & PRI_RATE_GATES)
    assert not (PRI_FLOW_GATES & PRI_RATE_GATES)
    assert "cheap_pb" not in PRI_FUND_GATES
    assert "roe_low" not in PRI_FUND_GATES


def test_unique_leftover_matches_yaml_unique_families() -> None:
    from research.unique_logic.catalog import unique_family_ids_from_yaml
    from research.unique_logic.worker_bodies import unique_leftover_logic_ids

    union = frozenset().union(*unique_family_ids_from_yaml().values())
    leftover = unique_leftover_logic_ids()
    assert leftover == union
    assert leftover


def test_catalog_aliases_match_yaml_named_helpers() -> None:
    from research.unique_logic.catalog import (
        combo_row_from_spec,
        combo_row_from_yaml,
        combo_rows_from_catalog,
        unique_family_ids_from_catalog,
        unique_family_ids_from_yaml,
        yaml_combo_rows,
    )

    assert unique_family_ids_from_catalog is unique_family_ids_from_yaml
    assert combo_rows_from_catalog is yaml_combo_rows
    assert combo_row_from_spec is combo_row_from_yaml
    assert unique_family_ids_from_catalog() == unique_family_ids_from_yaml()
    assert {r["logic_id"] for r in combo_rows_from_catalog()} == {
        r["logic_id"] for r in yaml_combo_rows()
    }


def test_usable_series_breakdown_has_tags() -> None:
    from research.unique_logic.worker_bodies import usable_series_breakdown

    empty = usable_series_breakdown({"mid_n_explore": {}, "liq_large": {}})
    assert empty["version"] == "usable-series/v1"
    assert empty["go"] is False
    assert "tag_counts" in empty and "family" in empty


def test_usable_inventory_read_has_n_ands_and_pri_series() -> None:
    from research.unique_logic.worker_bodies import usable_inventory_read

    empty = usable_inventory_read({"mid_n_explore": {}, "liq_large": {}})
    assert empty["version"] == "usable-read/v3"
    assert empty["go"] is False
    assert "n_ands" in empty and "pri_series" in empty


def test_cell_occupancy_prefers_occupancy_over_frac() -> None:
    from research.occupancy_guards import cell_occupancy, mean_occupancy_by_logic

    assert cell_occupancy(None) is None
    assert cell_occupancy({}) is None
    assert cell_occupancy({"occupancy": 0.4, "occupancy_frac": 0.1}) == 0.4
    assert cell_occupancy({"occupancy_frac": 0.2}) == 0.2
    means = mean_occupancy_by_logic(
        [
            {"logic_id": "a", "occupancy": 0.3, "occupancy_frac": 0.9},
            {"logic_id": "a", "occupancy_frac": 0.5},
        ]
    )
    assert means["a"] == 0.4


def test_spec_by_id_survives_catalog_cache_clear() -> None:
    from research.unique_logic.catalog import clear_catalog_caches, combo_thesis_records
    from research.unique_logic.event_combos import spec_by_id

    rows = combo_thesis_records()
    lid = str(rows[0]["logic_id"])
    clear_catalog_caches()
    spec = spec_by_id(lid)
    assert spec is not None
    assert spec["logic_id"] == lid
    assert spec.get("go") is False


def test_combo_thesis_records_are_cached() -> None:
    from research.unique_logic.catalog import (
        _combo_thesis_records_cached,
        clear_catalog_caches,
        combo_thesis_records,
    )

    clear_catalog_caches()
    n = len(combo_thesis_records())
    assert n >= 1
    combo_thesis_records()
    info = _combo_thesis_records_cached.cache_info()
    assert info.hits >= 1
    assert info.currsize >= 1


def test_combo_thesis_records_are_compact_table_rows() -> None:
    import json
    from pathlib import Path

    from research.unique_logic.catalog import (
        combo_thesis_records,
        write_combo_thesis_jsonl,
    )

    rows = combo_thesis_records()
    assert rows
    rec = rows[0]
    assert rec["go"] is False
    assert "logic_id" in rec and "gates" in rec and "kind" in rec
    assert rec["kind"] in {"event", "surprise_xs", "cs"}
    path = Path("/tmp/combo_thesis_records_test.jsonl")
    dump = write_combo_thesis_jsonl(path)
    assert dump["n"] == len(rows)
    assert "yaml_remains_sot" not in dump
    assert dump["go"] is False
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert first["logic_id"] and first["go"] is False


def test_catalog_index_is_one_pass_lookup() -> None:
    from pathlib import Path

    from research.unique_logic.catalog import catalog_index, catalog_spec

    idx = catalog_index()
    assert idx["n"] == idx["n_compiled"]
    assert idx["compiled_ids_match"] is True
    assert idx["yaml_still_present"] is False
    assert idx["n_combo"] >= 1
    assert idx["go"] is False
    assert idx["combo_kind_counts"].get("event", 0) >= 1
    assert idx["combo_kind_counts"].get("surprise_xs", 0) >= 1
    lid = idx["combo_ids"][0]
    spec = catalog_spec(lid)
    assert spec is not None
    assert spec["logic_id"] == lid
    assert spec.get("compiled") is True
    assert spec.get("catalog_present") is False
    path_raw = spec.get("catalog_path")
    if path_raw:
        path = Path(str(path_raw))
        assert path.name == "migration.jsonl"
        assert path.is_file()
    assert catalog_spec("not_a_real_logic_id_zzz") is None


def test_yaml_overlay_fail_closed_without_env(monkeypatch, tmp_path) -> None:
    from research.unique_logic.catalog import (
        YAML_OVERLAY_ENV,
        CatalogYamlOverlayError,
        clear_catalog_caches,
        load_catalog_specs,
        yaml_overlay_allowed,
    )

    logics = tmp_path / "specs" / "research_logics"
    logics.mkdir(parents=True)
    (logics / "stray_overlay.yaml").write_text(
        "logic_id: stray_overlay\ngo: false\n",
        encoding="utf-8",
    )
    monkeypatch.delenv(YAML_OVERLAY_ENV, raising=False)
    clear_catalog_caches()
    assert yaml_overlay_allowed() is False
    try:
        load_catalog_specs(root=tmp_path)
        raise AssertionError("stray YAML must fail closed without overlay env")
    except CatalogYamlOverlayError as exc:
        msg = str(exc)
        assert YAML_OVERLAY_ENV in msg
        assert "compiled" in msg
    monkeypatch.setenv(YAML_OVERLAY_ENV, "true")
    clear_catalog_caches()
    try:
        load_catalog_specs(root=tmp_path)
        raise AssertionError("QP_ALLOW_YAML_OVERLAY must be 1")
    except CatalogYamlOverlayError:
        pass
    finally:
        clear_catalog_caches()


def test_yaml_overlay_opt_in_replaces_compiled(monkeypatch, tmp_path) -> None:
    from research.unique_logic.catalog import (
        YAML_OVERLAY_ENV,
        clear_catalog_caches,
        combo_row_from_spec,
        combo_row_from_yaml,
        combo_rows_from_catalog,
        load_catalog_specs,
        parse_catalog_yaml,
        unique_family_ids_from_catalog,
        unique_family_ids_from_yaml,
        yaml_combo_rows,
    )

    logics = tmp_path / "specs" / "research_logics"
    logics.mkdir(parents=True)
    (logics / "stray_overlay.yaml").write_text(
        "logic_id: stray_overlay\n"
        "family: event\n"
        "go: false\n"
        "evaluator: research.unique_logic.event.evaluate_event_daily_mtm\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(YAML_OVERLAY_ENV, "1")
    clear_catalog_caches()
    try:
        specs = load_catalog_specs(root=tmp_path)
        assert [s["logic_id"] for s in specs] == ["stray_overlay"]
        assert specs[0].get("catalog_present") is True
        assert specs[0].get("compiled") is not True
        parsed = parse_catalog_yaml(
            "logic_id: from_text\ngo: false\nparams:\n  hold_days: 3\n"
        )
        assert parsed["logic_id"] == "from_text"
        assert parsed["params"]["hold_days"] == 3
        assert combo_rows_from_catalog is yaml_combo_rows
        assert unique_family_ids_from_catalog is unique_family_ids_from_yaml
        assert combo_row_from_spec is combo_row_from_yaml
    finally:
        clear_catalog_caches()


def test_parse_catalog_yaml_folded_and_params() -> None:
    spec = parse_catalog_yaml(
        """
logic_id: overnight_level_cs_tilt
headline: true
go: false
thesis: >
  Tight overnight level should be faded.
datasets:
  - jsda_tokyo_repo_rates
  - equities_bars_daily
params:
  hold_days: 10
  momentum_n: 5
  gates: eq_ar_high,pead
evaluator: research.unique_logic.cs_overlays.evaluate_overnight_level_cs_tilt_daily_mtm
"""
    )
    assert spec["logic_id"] == "overnight_level_cs_tilt"
    assert spec["headline"] is True
    assert spec["go"] is False
    assert "overnight" in spec["thesis"]
    assert spec["datasets"] == ["jsda_tokyo_repo_rates", "equities_bars_daily"]
    assert spec["params"]["hold_days"] == 10
    assert spec["params"]["momentum_n"] == 5
    assert spec["params"]["gates"] == ["eq_ar_high", "pead"]


def test_parse_catalog_yaml_theme_list_map() -> None:
    spec = parse_catalog_yaml(
        """
go: false
surprise_funding:
  - surprise_xs_tight_fade
  - event_on_impulse_pead
repo_cs:
  - cs_on_impulse
"""
    )
    assert spec["go"] is False
    assert spec["surprise_funding"] == [
        "surprise_xs_tight_fade",
        "event_on_impulse_pead",
    ]
    assert spec["repo_cs"] == ["cs_on_impulse"]


def test_economic_theme_yaml_rejects_go() -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from research.unique_logic.catalog import economic_theme_ids

    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "specs").mkdir()
        (root / "specs" / "research_themes.yaml").write_text(
            "go: true\nsurprise_funding:\n  - event_on_impulse_pead\n",
            encoding="utf-8",
        )
        try:
            economic_theme_ids(root=root)
        except ValueError as exc:
            assert "go" in str(exc)
        else:
            raise AssertionError("research_themes.yaml go: true must fail")


def test_combo_row_from_yaml_requires_gates_cs_gate_side() -> None:
    from research.unique_logic.catalog import combo_row_from_yaml, parse_catalog_yaml

    spec = parse_catalog_yaml(
        """
logic_id: event_eqar_high_pead
family_id: event_calendar_gate
go: false
generation_enabled: false
thesis: >
  PEAD only when EqAR is above the name PIT median.
params:
  side: orig
  gates: eq_ar_high
  cs_gate: None
evaluator: research.unique_logic.event_combos.evaluate_combo_daily_mtm
"""
    )
    row = combo_row_from_yaml(spec)
    assert row["logic_id"] == "event_eqar_high_pead"
    assert row["params"]["gates"] == ["eq_ar_high"]
    assert row["params"]["cs_gate"] is None
    assert row["params"]["side"] == "orig"
    assert row["go"] is False
    assert row["generation_enabled"] is False
    missing = parse_catalog_yaml(
        """
logic_id: event_eqar_high_pead
params:
  side: orig
evaluator: research.unique_logic.event_combos.evaluate_combo_daily_mtm
"""
    )
    try:
        combo_row_from_yaml(missing)
    except ValueError as exc:
        assert "gates" in str(exc)
        assert "cs_gate" in str(exc)
    else:
        raise AssertionError("missing YAML params.gates/cs_gate must fail")


def test_dispatch_unknown_logic_is_incomplete() -> None:
    from research.unique_logic.dispatch import evaluate_logic_daily_mtm

    pack = evaluate_logic_daily_mtm(
        {"logic_id": "not_a_real_logic"},
        bars={},
        overnight={},
        curve={},
        events={},
        margin_by_code={},
        topix_by_date={},
        one_way_cost=0.001,
    )
    assert pack["daily_path_complete"] is False
    assert pack["status"] == "unknown_logic"



def test_mf_value_mom_rate_is_unique_not_alias() -> None:
    from pathlib import Path

    from research.unique_logic.constants import (
        MF_VALUE_MOM_RATE_DELEGATES,
        MF_VALUE_MOM_RATE_PATH,
    )

    assert MF_VALUE_MOM_RATE_DELEGATES is False
    assert MF_VALUE_MOM_RATE_PATH == "unique_rate_gated_value_mom"
    from research.unique_logic.constants import MF_VALUE_MOM_RATE_PARKED_ALWAYS_ON

    assert MF_VALUE_MOM_RATE_PARKED_ALWAYS_ON is False



def test_unique_logic_cli_is_retired() -> None:
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "research.unique_logic"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode != 0
    blob = (r.stderr or "") + (r.stdout or "")
    assert "retired" in blob
    assert "Does not GO" in blob


