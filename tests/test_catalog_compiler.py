"""Immutable legacy-catalog replay artifact; never a runtime authority."""
from __future__ import annotations

import json

import pytest

from qp_paths import repo_root
from research.catalog_compiler import (
    COMPILER_VERSION,
    MANIFEST_NAME,
    MIGRATION_NAME,
    assert_legacy_catalog_artifact_frozen,
    catalog_artifact_dir,
    compile_catalog,
    compile_row,
)
from research.occupancy_guards import CatalogAndPlusNStoppedError

_FROZEN_CATALOG_DIGEST = (
    "sha256:6ad5ba57dfa41ed9a97e5895d9238040fbb5539b310a2ea4aa349172b6cb8c69"
)


def test_compile_row_is_deterministic_closed_data() -> None:
    spec = {
        "logic_id": "x",
        "evaluator": "research.unique_logic.event_combos.evaluate_combo_daily_mtm",
        "params": {"gates": ["afterclose", "uncrowded_margin"]},
    }
    assert compile_row(spec) == compile_row(spec)
    assert compile_row(spec)["semantic_hash"].startswith("sha256:")


def test_persisted_replay_artifact_matches_frozen_digest() -> None:
    pack = compile_catalog()
    dest = catalog_artifact_dir()
    manifest = json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (dest / MIGRATION_NAME).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert dest == repo_root() / "artifacts" / "replay" / "legacy_strategy_catalog"
    assert manifest == {
        "artifact_class": "immutable_legacy_replay",
        "digest": _FROZEN_CATALOG_DIGEST,
        "go": False,
        "n": len(rows),
        "runtime_import_allowed": False,
        "version": COMPILER_VERSION,
        "yaml_still_present": False,
    }
    assert pack["digest"] == manifest["digest"]
    assert pack["n"] == len(rows)
    assert [row["logic_id"] for row in rows] == [
        row["logic_id"] for row in pack["rows"]
    ]


def test_replay_freeze_does_not_emit_worker_catalog_source() -> None:
    freeze = assert_legacy_catalog_artifact_frozen()
    assert freeze["ok"] is True
    assert freeze["go"] is False
    assert freeze["n_manifest"] == freeze["n_compiled_rows"] == freeze["n_logic_ids"]
    assert freeze["manifest_digest"] == freeze["compiled_digest"]
    worker_catalog = (
        repo_root()
        / "platform"
        / "workers"
        / "research-mass-eval"
        / "src"
        / "catalog_ids.ts"
    )
    assert not worker_catalog.exists()


def test_replay_freeze_rejects_manifest_count_drift(tmp_path, monkeypatch) -> None:
    import research.catalog_compiler as compiler

    dest = tmp_path / "artifacts" / "replay" / "legacy_strategy_catalog"
    dest.mkdir(parents=True)
    (dest / MANIFEST_NAME).write_text(
        json.dumps(
            {
                "artifact_class": "immutable_legacy_replay",
                "digest": "sha256:x",
                "go": False,
                "n": 1,
                "runtime_import_allowed": False,
                "version": COMPILER_VERSION,
                "yaml_still_present": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(compiler, "catalog_artifact_dir", lambda root=None: dest)
    with pytest.raises(CatalogAndPlusNStoppedError, match="manifest n=1"):
        assert_legacy_catalog_artifact_frozen()


def test_surprise_with_flow_gate_is_not_flow_family() -> None:
    from research.catalog_family import classify_catalog_row

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
