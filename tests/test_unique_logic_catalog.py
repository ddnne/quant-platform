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

    from research.eval_flags import CATALOG_YAML_COUNT_AT_STOP
    from research.unique_logic.catalog import catalog_index, catalog_spec

    idx = catalog_index()
    freeze = int(CATALOG_YAML_COUNT_AT_STOP)
    assert idx["n"] == idx["n_compiled"] == freeze == 2254
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
    path = Path(str(spec.get("catalog_path") or ""))
    assert path.stem == lid
    assert path.is_file() is False
    assert catalog_spec("not_a_real_logic_id_zzz") is None


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



def test_factory_unique_eval_uses_package_dispatch() -> None:
    import inspect

    from research.unique_logic import dispatch as dispatch_mod
    from research.unique_logic.dispatch import evaluate_logic_daily_mtm

    src = inspect.getsource(evaluate_logic_daily_mtm)
    src += inspect.getsource(dispatch_mod._dispatch_body)
    assert "evaluate_logic_daily_mtm" in src
    assert "scripts.run_w" not in src
    assert evaluate_logic_daily_mtm.__module__ == "research.unique_logic.dispatch"


def test_yaml_dispatch_worker_event_ids_align() -> None:
    import inspect

    from research.cf_daily_path_job import CF_EVENT_DAILY_PATH_IDS
    from research.unique_logic.catalog import load_catalog_specs
    from research.unique_logic.constants import (
        CF_EVENT_DAILY_PATH_IDS as CONST_EVENT,
    )
    from research.unique_logic.dispatch import evaluate_logic_daily_mtm

    yaml_ids = {s["logic_id"] for s in load_catalog_specs()}
    assert set(CF_EVENT_DAILY_PATH_IDS) == set(CONST_EVENT)
    assert set(CF_EVENT_DAILY_PATH_IDS) <= yaml_ids
    src = inspect.getsource(evaluate_logic_daily_mtm)
    from research.unique_logic import dispatch as dispatch_mod
    from research.unique_logic.event_combos import COMBO_LOGIC_IDS

    src += inspect.getsource(dispatch_mod._dispatch_body)
    missing = [
        lid
        for lid in sorted(yaml_ids)
        if f'lid == "{lid}"' not in src and lid not in COMBO_LOGIC_IDS
    ]
    assert missing == []
    assert "COMBO_LOGIC_IDS" in src
    from research.unique_logic.constants import CF_NEW_THESIS_IDS

    assert "event_skip_monday" in yaml_ids
    assert "cs_not_month_end" in yaml_ids
    assert "event_skip_monday" in CF_NEW_THESIS_IDS
    from research.unique_logic.constants import (
        ALWAYS_ON_CS_STICKY,
        WORKER_ISOLATE_LIMIT_IDS,
        WORKER_ISOLATE_LIMIT_REASONS,
        WORKER_ISOLATE_LINEARIZED_OK,
        is_ungated_name_level_cs,
    )
    from research.unique_logic.event_combos import NEW_COMBO_LOGIC, spec_by_id

    ids = {s["logic_id"] for s in NEW_COMBO_LOGIC}
    assert "event_skip_monday" in ids
    parked = [s for s in NEW_COMBO_LOGIC if s["logic_id"] in WORKER_ISOLATE_LIMIT_IDS]
    assert parked == []
    assert set(WORKER_ISOLATE_LIMIT_REASONS) == set(WORKER_ISOLATE_LIMIT_IDS)
    assert WORKER_ISOLATE_LIMIT_IDS.isdisjoint(WORKER_ISOLATE_LINEARIZED_OK)
    assert WORKER_ISOLATE_LINEARIZED_OK
    for lid in WORKER_ISOLATE_LINEARIZED_OK:
        row = spec_by_id(lid)
        assert row.get("worker_isolate_limit") is False
    for spec in NEW_COMBO_LOGIC:
        if str(spec.get("kind") or "") == "cs":
            continue
        lid = str(spec["logic_id"])
        if lid in ALWAYS_ON_CS_STICKY:
            continue
        assert spec.get("always_on_cs_sticky") is False
        assert is_ungated_name_level_cs(
            kind=str(spec.get("kind") or ""),
            cs_gate=str(spec.get("cs_gate") or ""),
            logic_id=lid,
        ) is False



def test_sync_cf_new_thesis_ids_check() -> None:
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    r = subprocess.run(
        [sys.executable, str(repo / "scripts" / "sync_cf_new_thesis_ids.py"), "--check"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr


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



