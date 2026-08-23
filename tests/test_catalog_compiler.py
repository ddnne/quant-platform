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
    assert_catalog_ids_emit_frozen,
    assert_compiled_logic_id_sets,
    catalog_artifact_dir,
    catalog_ids_ts_path,
    catalog_ids_ts_source,
    compile_catalog,
    compile_row,
)
from research.eval_flags import CATALOG_AND_PLUS_N_STOPPED, CATALOG_YAML_COUNT_AT_STOP
from research.unique_logic.catalog import catalog_dir
from research.unique_logic.constants import RESEARCH_UNIQUE_LOGIC_IDS


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


def test_yaml_stems_lock_to_compiled_migration_ids() -> None:
    """compiled migration.jsonl == YAML == RESEARCH_UNIQUE_LOGIC_IDS. One identity pass."""
    sets = assert_compiled_logic_id_sets()
    assert sets["migration"] == sets["yaml"] == sets["constants"] == set(
        RESEARCH_UNIQUE_LOGIC_IDS
    )
    assert len(sets["yaml"]) == int(CATALOG_YAML_COUNT_AT_STOP) == 2254
    assert catalog_dir().is_dir()
    assert any(catalog_dir().glob("*.yaml"))


def test_compiler_source_does_not_exec_or_eval() -> None:
    import research.catalog_compiler as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"exec", "eval"}
    assert "exec(" not in src
    assert "eval(" not in src


def test_catalog_ids_emit_owned_by_compiler() -> None:
    freeze = assert_catalog_ids_emit_frozen()
    assert freeze["ok"] is True
    assert freeze["go"] is False
    assert CATALOG_AND_PLUS_N_STOPPED is True
    assert freeze["n_yaml"] == freeze["n_digest"] == freeze["freeze"] == 2254
    path = catalog_ids_ts_path()
    generated = catalog_ids_ts_source()
    assert path.read_text(encoding="utf-8") == generated
    header = generated.split("export const", 1)[0]
    assert "research.catalog_compiler" in header
    assert "n=2254" in header
    assert "CATALOG_AND_PLUS_N_STOPPED" in header
    assert "Do not edit by hand" in header
    script = Path(__file__).resolve().parents[1] / "scripts" / "sync_cf_new_thesis_ids.py"
    script_src = script.read_text(encoding="utf-8")
    assert "from research.catalog_compiler import" in script_src
    assert "catalog_ids_ts_source" in script_src
    assert "assert_catalog_ids_emit_frozen" in script_src
    assert "def _catalog_ids_source" not in script_src


def test_catalog_ids_emit_fails_if_yaml_count_drifts(monkeypatch) -> None:
    import research.eval_flags as flags
    from research.occupancy_guards import CatalogAndPlusNStoppedError

    monkeypatch.setattr(flags, "CATALOG_YAML_COUNT_AT_STOP", 0)
    try:
        assert_catalog_ids_emit_frozen()
        raise AssertionError("yaml count drift must fail while stopped")
    except CatalogAndPlusNStoppedError as exc:
        assert "YAML count must not drift" in str(exc)


def test_catalog_ids_emit_fails_if_digest_n_drifts(tmp_path, monkeypatch) -> None:
    import research.catalog_compiler as mod
    from research.occupancy_guards import CatalogAndPlusNStoppedError

    dest = tmp_path / "research_catalog"
    dest.mkdir()
    (dest / MANIFEST_NAME).write_text(
        '{"digest":"sha256:x","go":false,"n":1,"version":"research_catalog_compiler/v1","yaml_still_present":true}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "catalog_artifact_dir", lambda root=None: dest)
    try:
        assert_catalog_ids_emit_frozen()
        raise AssertionError("compiler digest n drift must fail while stopped")
    except CatalogAndPlusNStoppedError as exc:
        assert "compiler digest n=1" in str(exc)
