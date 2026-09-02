"""Runtime plane capability and import-direction tests. Not AST spelling."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def test_product_mass_eval_has_no_json_post_capability() -> None:
    importlib.import_module("research.cf_mass_eval_job")
    module = importlib.import_module("research.cf_mass_eval_run")
    assert not hasattr(module, "post_json_object")
    assert not hasattr(module, "deploy_wrangler_worker")
    assert "post_json_object" not in vars(module)


def test_product_daily_path_eval_has_no_git_subprocess() -> None:
    module = importlib.import_module("research.daily_path_eval")
    assert not hasattr(module, "git_sha")
    assert "subprocess" not in vars(module)


def test_product_ready_manifest_cannot_open_publication_scope() -> None:
    module = importlib.import_module("research.ready_manifest")
    assert not hasattr(module, "publication_verifier_scope")
    assert "pit._ready_verifier_reads" not in vars(module)


def test_ordinary_product_caller_cannot_open_preready_storage(
    tmp_path: Path,
) -> None:
    import sqlite3

    from pit.query import connect_readonly
    from pit.errors import SnapshotNotReady

    path = tmp_path / "preready.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE local_snapshot_policy ("
        "singleton INTEGER PRIMARY KEY, require_manifest INTEGER, "
        "snapshot_ready INTEGER, publication_state TEXT)"
    )
    conn.execute(
        "INSERT INTO local_snapshot_policy VALUES (1, 1, 0, 'BUILDING')"
    )
    conn.commit()
    conn.close()
    with pytest.raises(SnapshotNotReady):
        connect_readonly(path)


def test_data_plane_does_not_import_product_research_runtime_compute() -> None:
    import pit
    import pit.query as query
    import ingestion.personal_history as personal_history

    assert not any(
        getattr(value, "__name__", "").startswith("research.")
        for value in vars(query).values()
    )
    assert not any(
        getattr(value, "__name__", "").startswith("research.")
        for value in vars(personal_history).values()
    )
    assert personal_history.__name__.startswith("ingestion")
    assert pit.__name__ == "pit"
