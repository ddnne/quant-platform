"""JSON/catalog identity for the J-Quants secret-proxy allowlists.

Worker request/auth/upstream behavior is executed in the Workerd runtime suites
under ``platform/workers/ingestion-secrets/runtime``. These tests pin
the checked-in JSON contracts to the Python catalog sets — contract identity,
not Worker source greps.
"""

from __future__ import annotations

import json
from pathlib import Path

from ingestion.jquants.catalog import DATASETS, PREMIUM_CORE_DATASETS


ROOT = Path(__file__).parents[1]
CONTRACT_PATH = (
    ROOT / "packages" / "data_plane" / "data_contracts" / "jquants_premium_core.json"
)
ADDON_CONTRACT_PATH = (
    ROOT / "packages" / "data_plane" / "data_contracts" / "jquants_proxy_addons.json"
)


def _contract_paths() -> set[str]:
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    return {str(row["path"]) for row in payload["datasets"]}


def _addon_contract_paths() -> set[str]:
    payload = json.loads(ADDON_CONTRACT_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert len(payload["datasets"]) == 5
    assert all(str(row["path"]).startswith("/v2/") for row in payload["datasets"])
    return {str(row["path"]) for row in payload["datasets"]}


def test_secret_proxy_whitelist_source_is_exact_premium_contract():
    expected = {DATASETS[dataset_id]["path"] for dataset_id in PREMIUM_CORE_DATASETS}

    assert _contract_paths() == expected
    assert len(expected) == 23


def test_secret_proxy_preserves_exact_catalogued_addons_via_shared_contract():
    addon_paths = {
        str(spec["path"])
        for spec in DATASETS.values()
        if spec.get("group") == "addon"
    }
    assert addon_paths
    assert _addon_contract_paths() == addon_paths
    assert _contract_paths().isdisjoint(addon_paths)
