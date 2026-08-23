"""Catalog compiler is closed-DSL data only. Does not delete YAML. Not GO."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from qp_paths import repo_root
from research.catalog_compiler import (
    COMPILER_VERSION,
    MANIFEST_NAME,
    MIGRATION_NAME,
    catalog_artifact_dir,
    compile_catalog,
    compile_row,
)
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


def test_persisted_artifacts_match_live_digest() -> None:
    pack = compile_catalog()
    dest = catalog_artifact_dir()
    manifest = json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
    n_yaml = len(list(catalog_dir().glob("*.yaml")))
    assert n_yaml == int(CATALOG_YAML_COUNT_AT_STOP) == 2254
    assert pack["n"] == n_yaml
    assert manifest["n"] == pack["n"]
    assert manifest["digest"] == pack["digest"]
    assert manifest["version"] == pack["version"] == COMPILER_VERSION
    assert manifest["yaml_still_present"] is True
    assert pack["yaml_still_present"] is True
    assert manifest["go"] is False
    assert pack["go"] is False
    assert (repo_root() / "specs" / "research_logics").is_dir()
    assert n_yaml > 0

    raw = (dest / MIGRATION_NAME).read_text(encoding="utf-8")
    migrated = [json.loads(line) for line in raw.splitlines() if line.strip()]
    assert len(migrated) == pack["n"]
    keys = {"evaluator", "family_id", "gates", "logic_id", "semantic_hash", "template_id"}
    assert [r["logic_id"] for r in migrated] == [r["logic_id"] for r in pack["rows"]]
    for persisted, live in zip(migrated, pack["rows"], strict=True):
        assert set(persisted) == keys
        assert persisted["template_id"] == live["template_id"]
        assert persisted["family_id"] == live["family_id"]
        assert persisted["evaluator"] == live["evaluator"]
        assert persisted["gates"] == live["gates"]
        assert persisted["semantic_hash"] == live["semantic_hash"]


def test_compiler_source_does_not_exec_or_eval() -> None:
    import research.catalog_compiler as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"exec", "eval"}
    assert "exec(" not in src
    assert "eval(" not in src
