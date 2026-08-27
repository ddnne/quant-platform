"""Focused replay compatibility for the retired strategy catalog."""
from __future__ import annotations

from research.catalog_compiler import assert_compiled_logic_id_sets
from research.unique_logic import all_unique_logic_specs, load_catalog_specs


def test_replay_identity_matches_legacy_python_specs() -> None:
    catalog = load_catalog_specs()
    catalog_ids = {str(spec["logic_id"]) for spec in catalog}
    python_ids = {str(spec["logic_id"]) for spec in all_unique_logic_specs()}
    identity = assert_compiled_logic_id_sets()
    assert catalog_ids == python_ids == identity["migration"] == identity["constants"]
    assert identity["yaml"] == set()
    assert all(spec.get("generation_enabled") is False for spec in catalog)
    assert all(spec.get("go") is not True for spec in catalog)
    assert all(spec.get("catalog_present") is False for spec in catalog)


def test_combo_replay_row_round_trip_preserves_closed_fields() -> None:
    from research.unique_logic.catalog import (
        catalog_spec,
        combo_row_from_yaml,
        spec_gates,
    )

    spec = catalog_spec("event_ta_up_positive_eps")
    assert spec is not None
    assert set(spec_gates(spec)) == {"ta_up", "positive_eps"}
    row = combo_row_from_yaml(spec)
    assert row["logic_id"] == spec["logic_id"]
    assert set((row.get("params") or {}).get("gates") or row.get("gates") or ()) == {
        "ta_up",
        "positive_eps",
    }
    assert row.get("go") is not True


def test_legacy_themes_only_reference_replay_ids() -> None:
    from research.unique_logic.catalog import economic_theme_ids
    from research.unique_logic.constants import RESEARCH_UNIQUE_LOGIC_IDS

    themes = economic_theme_ids()
    assert themes
    assert all(ids for ids in themes.values())
    referenced = set().union(*themes.values())
    assert referenced <= RESEARCH_UNIQUE_LOGIC_IDS


def test_product_worker_has_no_countable_legacy_catalog_ids() -> None:
    from research.unique_logic.worker_bodies import (
        combo_cs_gates_implemented,
        combo_worker_gates_ok,
        countable_thesis_ids,
        is_countable_spec,
        worker_implemented_logic_ids,
    )

    retired = {"logic_id": "event_cheap_iv_pead", "params": {"gates": ["cheap_iv"]}}
    assert worker_implemented_logic_ids() == frozenset()
    assert countable_thesis_ids() == frozenset()
    assert combo_cs_gates_implemented() == frozenset()
    assert combo_worker_gates_ok(retired) is False
    assert is_countable_spec(retired) is False


def test_normalize_gates_is_replay_parser_compatibility() -> None:
    from research.unique_logic.catalog import normalize_gates, spec_gates

    assert normalize_gates(None) == []
    assert normalize_gates("None") == []
    assert normalize_gates("ta_up,positive_eps") == ["ta_up", "positive_eps"]
    assert normalize_gates(["afterclose", "positive_eps"]) == [
        "afterclose",
        "positive_eps",
    ]
    assert spec_gates(None) == []
    assert spec_gates({"params": {}}) == []
