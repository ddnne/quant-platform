"""Catalog compiler is closed-DSL data only. Does not delete YAML. Not GO."""
from __future__ import annotations

from research.catalog_compiler import compile_catalog, compile_row
from research.eval_flags import CATALOG_YAML_COUNT_AT_STOP
from research.unique_logic.catalog import catalog_dir


def test_compiler_row_count_matches_yaml_freeze() -> None:
    n_yaml = len(list(catalog_dir().glob("*.yaml")))
    pack = compile_catalog()
    assert n_yaml == int(CATALOG_YAML_COUNT_AT_STOP)
    assert pack["n"] == n_yaml
    assert pack["digest"].startswith("sha256:")
    assert pack["yaml_still_present"] is True
    assert pack["go"] is False
    ids = [r["logic_id"] for r in pack["rows"]]
    assert len(ids) == len(set(ids))
    assert all(r["semantic_hash"].startswith("sha256:") for r in pack["rows"])


def test_compiler_does_not_exec_and_is_stable() -> None:
    a = compile_row(
        {
            "logic_id": "x",
            "evaluator": "research.unique_logic.event_combos.evaluate_combo_daily_mtm",
            "params": {"gates": ["afterclose", "uncrowded_margin"]},
        }
    )
    b = compile_row(
        {
            "logic_id": "x",
            "evaluator": "research.unique_logic.event_combos.evaluate_combo_daily_mtm",
            "params": {"gates": ["afterclose", "uncrowded_margin"]},
        }
    )
    assert a["semantic_hash"] == b["semantic_hash"]
    assert "exec" not in a["evaluator"]
