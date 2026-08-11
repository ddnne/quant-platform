"""Static security contract for the Cloudflare J-Quants secret proxy.

The Worker is TypeScript and deploys separately, so these offline tests pin
the cross-runtime authority boundary without duplicating the allowed paths:
the checked-in Premium JSON contract is the sole whitelist source.
"""

from __future__ import annotations

import json
from pathlib import Path

from ingestion.jquants.catalog import DATASETS, PREMIUM_CORE_DATASETS


ROOT = Path(__file__).parents[1]
CONTRACT_PATH = ROOT / "data_contracts" / "jquants_premium_core.json"
ADDON_CONTRACT_PATH = ROOT / "data_contracts" / "jquants_proxy_addons.json"
WORKER_PATH = (
    ROOT / "platform" / "workers" / "ingestion-secrets" / "src" / "index.ts"
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
    source = WORKER_PATH.read_text(encoding="utf-8")
    expected = {DATASETS[dataset_id]["path"] for dataset_id in PREMIUM_CORE_DATASETS}

    assert _contract_paths() == expected
    assert len(expected) == 23
    assert (
        'import premiumContract from '
        '"../../../../data_contracts/jquants_premium_core.json"'
    ) in source
    assert "...premiumContract.datasets, ...addonProxyContract.datasets" in source
    assert "JQUANTS_PROXY_PATHS.has(body.path)" in source
    assert 'path.startsWith("/v2/")' not in source


def test_secret_proxy_preserves_exact_catalogued_addons_via_shared_contract():
    source = WORKER_PATH.read_text(encoding="utf-8")
    addon_paths = {
        str(spec["path"])
        for spec in DATASETS.values()
        if spec.get("group") == "addon"
    }
    assert addon_paths
    assert _addon_contract_paths() == addon_paths
    assert _contract_paths().isdisjoint(addon_paths)
    assert (
        'import addonProxyContract from '
        '"../../../../data_contracts/jquants_proxy_addons.json"'
    ) in source


def test_secret_proxy_upstream_is_fixed_get_and_response_is_streamed():
    source = WORKER_PATH.read_text(encoding="utf-8")

    assert 'value.method !== undefined && value.method !== "GET"' in source
    assert 'method: "GET"' in source
    assert "method: body.method" not in source
    assert "body.method ||" not in source
    assert 'redirect: "manual"' in source
    assert "new Response(upstream.body" in source
    assert "await upstream.text()" not in source


def test_secret_proxy_auth_is_required_before_forwarding():
    source = WORKER_PATH.read_text(encoding="utf-8")
    auth_check = source.index("await tokenMatches")
    whitelist_check = source.index("JQUANTS_PROXY_PATHS.has(body.path)")
    upstream_fetch = source.index("await fetch(target.toString()")

    assert auth_check < whitelist_check < upstream_fetch
    assert "crypto.subtle.timingSafeEqual" in source
