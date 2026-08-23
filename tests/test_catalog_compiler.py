"""Catalog compiler is closed-DSL data only. Does not add YAML. Not GO."""
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
    catalog_artifact_dir,
    catalog_ids_ts_path,
    catalog_ids_ts_source,
    compile_catalog,
    compile_row,
)
from research.eval_flags import CATALOG_AND_PLUS_N_STOPPED, CATALOG_YAML_COUNT_AT_STOP

# Freeze digest for compiled n=2254. Do not retune. Identity set-equality is
# tests/test_catalog_yaml_parity.py (compiler == constants == catalog_ids.ts).
_FROZEN_CATALOG_DIGEST = (
    "sha256:6ad5ba57dfa41ed9a97e5895d9238040fbb5539b310a2ea4aa349172b6cb8c69"
)


def test_compiler_row_count_matches_yaml_freeze() -> None:
    pack = compile_catalog()
    assert pack["n"] == int(CATALOG_YAML_COUNT_AT_STOP)
    assert pack["digest"] == _FROZEN_CATALOG_DIGEST
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
    assert manifest["n"] == pack["n"]
    assert manifest["digest"] == pack["digest"] == _FROZEN_CATALOG_DIGEST
    assert manifest["version"] == pack["version"] == COMPILER_VERSION
    assert pack["yaml_still_present"] is manifest["yaml_still_present"]
    assert manifest["go"] is False
    assert pack["go"] is False
    assert (repo_root() / "specs" / "research_catalog").is_dir()

    raw = (dest / MIGRATION_NAME).read_text(encoding="utf-8")
    migrated = [json.loads(line) for line in raw.splitlines() if line.strip()]
    assert len(migrated) == pack["n"]
    keys = {
        "evaluator",
        "family",
        "family_id",
        "gates",
        "generation_enabled",
        "logic_id",
        "params",
        "position_rule",
        "semantic_hash",
        "signal_definition",
        "template_id",
        "thesis",
        "datasets",
    }
    assert [r["logic_id"] for r in migrated] == [r["logic_id"] for r in pack["rows"]]
    for persisted, live in zip(migrated, pack["rows"], strict=True):
        assert set(persisted) == keys
        assert persisted["template_id"] == live["template_id"]
        assert persisted["family_id"] == live["family_id"]
        assert persisted["evaluator"] == live["evaluator"]
        assert persisted["gates"] == live["gates"]
        assert persisted["semantic_hash"] == live["semantic_hash"]
        assert persisted["params"] == live["params"]
        assert persisted["generation_enabled"] == live["generation_enabled"]


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
    assert freeze["n_digest"] == freeze["freeze"] == freeze["n_logic_ids"] == 2254
    assert freeze["n_yaml"] == 0
    dest = catalog_artifact_dir()
    manifest = json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["digest"] == _FROZEN_CATALOG_DIGEST
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
        raise AssertionError("yaml/digest count drift must fail while stopped")
    except CatalogAndPlusNStoppedError as exc:
        msg = str(exc)
        assert "must not drift" in msg or "compiler digest n=" in msg


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


def test_surprise_with_flow_gate_is_not_flow_family() -> None:
    from research.catalog_family import catalog_family_report, classify_catalog_row

    row = classify_catalog_row(
        {
            "logic_id": "surprise_xs_crowded_margin",
            "evaluator": "research.unique_logic.event_combos.evaluate_combo_daily_mtm",
            "params": {"gates": ["crowded_margin", "liq_high"]},
        }
    )
    assert row["primary_hypothesis"] == "surprise_xs"
    assert row["flow_family"] is False
    assert "flow_gate" in row["gate_tags"]
    assert row["go"] is False
    rep = catalog_family_report()
    assert rep["go"] is False
    assert rep["not_a_pass"] is True
