"""Behavioral checks for the frozen active-Worker deployment surface."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "cloudflare_binding_manifest.py"
SPEC = importlib.util.spec_from_file_location("cloudflare_binding_manifest", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
manifest_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest_module)


def test_frozen_manifest_equals_effective_wrangler_surfaces() -> None:
    frozen = json.loads(manifest_module.MANIFEST.read_text(encoding="utf-8"))
    assert frozen == manifest_module.build_manifest()
    assert set(frozen["workers"]) == set(manifest_module.ACTIVE_WORKERS)
    assert "ci-aggregate" not in frozen["workers"]


def test_manifest_is_fail_closed_for_toolchain_drift() -> None:
    manifest = manifest_module.build_manifest()
    drifted = copy.deepcopy(manifest)
    drifted["workers"]["ingestion-jsda"]["production"]["toolchain"][
        "wrangler"
    ] = "4.124.0"
    with pytest.raises(ValueError, match="wrangler must be exactly"):
        manifest_module.validate_manifest(drifted)


def test_staging_surfaces_are_private_and_have_no_production_secret_policy() -> None:
    manifest = manifest_module.build_manifest()
    for environments in manifest["workers"].values():
        staging = environments["staging"]
        assert staging["workers_dev"] is False
        assert staging["preview_urls"] is False
        assert staging["secret_names"] == []
        assert staging["name"].endswith("-staging")
