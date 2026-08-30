"""Parse platform/workers wrangler.toml for public-surface topology.

Internal product workers must keep workers_dev false (and preview_urls false).
Documented exceptions may keep workers_dev true. Staging must use different
names and physically distinct binding IDs/resources. research-mass-eval
staging is the token-gated workers.dev exception; preview_urls stay false.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKERS_ROOT = ROOT / "platform" / "workers"

INTERNAL_PRODUCT = (
    "ingestion-premium",
    "ingestion-jsda",
    "research-ai-gateway",
)

# workers_dev=true is allowed only with a documented reason (ADR).
WORKERS_DEV_TRUE_EXCEPTIONS = frozenset(
    {
        "quant-ops-mcp",  # GitHub OAuth callback host
        "ingestion-secrets",  # Access-protected transition proxy
        "research-mass-eval",  # token-gated personal DRAFT Container
    }
)

PRODUCT_WORKERS = INTERNAL_PRODUCT + tuple(sorted(WORKERS_DEV_TRUE_EXCEPTIONS))

PRODUCTION_D1_ID = "be6fdcf8-40be-41fc-9535-7facd1fc2ffc"
PRODUCTION_KV_ID = "cbbfc9439c3e4a789fa103777d38f39e"
PRODUCTION_BUCKETS = frozenset({"quant-raw", "quant-structured"})
PRODUCTION_BINDING_IDS = frozenset({PRODUCTION_D1_ID, PRODUCTION_KV_ID}) | PRODUCTION_BUCKETS
STAGING_D1_ID = "d448d1c6-27c8-4aeb-8702-3e7a8b6bf2bb"
OPS_PROJECTION_D1_ID = "1b497e8a-5c69-4e19-ae2e-89a8f3185272"
OPS_QUOTA_D1_ID = "d2c4bddd-7970-495c-aa05-ff28cbc1f6b6"
OPS_PROJECTION_STAGING_D1_ID = "68ee96d5-766c-4832-836b-54c079bd6265"
OPS_QUOTA_STAGING_D1_ID = "a27f8ce9-82cb-4eec-abac-9c3385ce40e1"
STAGING_KV_ID = "4402f398df93412ebe6774d1bc603142"
STAGING_BUCKETS = frozenset({"quant-raw-staging", "quant-structured-staging"})


def _load(path: Path) -> dict[str, Any]:
    assert path.is_file(), path
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data, path
    return data


def _worker_toml(name: str) -> Path:
    return WORKERS_ROOT / name / "wrangler.toml"


def _staging_toml(name: str) -> Path:
    return WORKERS_ROOT / name / "wrangler.staging.toml"


def _strings(obj: Any) -> list[str]:
    out: list[str] = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            out.extend(_strings(value))
    elif isinstance(obj, list):
        for value in obj:
            out.extend(_strings(value))
    return out


def _env_production(cfg: dict[str, Any]) -> dict[str, Any] | None:
    env = cfg.get("env")
    if not isinstance(env, dict):
        return None
    prod = env.get("production")
    return prod if isinstance(prod, dict) else None


def test_product_worker_wrangler_files_exist_and_parse() -> None:
    found = sorted(p.parent.name for p in WORKERS_ROOT.glob("*/wrangler.toml"))
    for name in PRODUCT_WORKERS:
        assert name in found, name
        _load(_worker_toml(name))


def test_internal_product_workers_dev_and_preview_urls_false() -> None:
    for name in INTERNAL_PRODUCT:
        cfg = _load(_worker_toml(name))
        assert cfg.get("workers_dev") is False, name
        assert cfg.get("preview_urls") is False, name
        prod = _env_production(cfg)
        assert prod is not None, name
        assert prod.get("workers_dev") is False, f"{name} env.production"
        assert prod.get("preview_urls") is False, f"{name} env.production"


def test_documented_exceptions_keep_workers_dev_true() -> None:
    for name in WORKERS_DEV_TRUE_EXCEPTIONS:
        cfg = _load(_worker_toml(name))
        assert cfg.get("workers_dev") is True, name
        prod = _env_production(cfg)
        if prod is not None:
            assert prod.get("workers_dev") is True, f"{name} env.production"


def test_no_undocumented_workers_dev_true() -> None:
    for path in sorted(WORKERS_ROOT.glob("*/wrangler.toml")):
        name = path.parent.name
        cfg = _load(path)
        if cfg.get("workers_dev") is True:
            assert name in WORKERS_DEV_TRUE_EXCEPTIONS, name
        prod = _env_production(cfg)
        if prod is not None and prod.get("workers_dev") is True:
            assert name in WORKERS_DEV_TRUE_EXCEPTIONS, f"{name} env.production"


def test_production_wrangler_has_no_env_staging() -> None:
    for name in PRODUCT_WORKERS:
        cfg = _load(_worker_toml(name))
        env = cfg.get("env") or {}
        assert "staging" not in env, name


def test_staging_uses_distinct_names_and_resources() -> None:
    for name in PRODUCT_WORKERS:
        prod_cfg = _load(_worker_toml(name))
        staging_path = _staging_toml(name)
        staging = _load(staging_path)
        prod_name = str(prod_cfg["name"])
        staging_name = str(staging["name"])
        assert staging_name != prod_name, name
        assert staging_name.endswith("-staging"), staging_name
        if name == "research-mass-eval":
            assert staging.get("workers_dev") is True, name
        else:
            assert staging.get("workers_dev") is False, name
        assert staging.get("preview_urls") is False, name
        for banned in PRODUCTION_BINDING_IDS:
            assert banned not in _strings(staging), f"{staging_path} binds {banned}"
        env = staging.get("env") or {}
        assert "production" not in env, name

    for name in ("ingestion-jsda", "ingestion-premium"):
        staging = _load(_staging_toml(name))
        databases = staging.get("d1_databases") or []
        assert {row["database_id"] for row in databases} == {STAGING_D1_ID}, name
        assert {row["database_name"] for row in databases} == {"quant-ingest-staging"}, name

    r2_expected = {
        "ingestion-jsda": {"quant-raw-staging"},
        "ingestion-premium": STAGING_BUCKETS,
        "research-mass-eval": {"quant-structured-staging"},
    }
    for name, expected in r2_expected.items():
        staging = _load(_staging_toml(name))
        assert {row["bucket_name"] for row in staging["r2_buckets"]} == expected

    ops = _load(_staging_toml("quant-ops-mcp"))
    assert {row["id"] for row in ops["kv_namespaces"]} == {STAGING_KV_ID}
    assert {row["database_id"] for row in ops["d1_databases"]} == {
        OPS_PROJECTION_STAGING_D1_ID,
        OPS_QUOTA_STAGING_D1_ID,
    }
    assert {row["database_name"] for row in ops["d1_databases"]} == {
        "quant-ops-projection-staging",
        "quant-ops-quota-staging",
    }
    production_ops = _load(_worker_toml("quant-ops-mcp"))
    assert {row["database_id"] for row in production_ops["d1_databases"]} == {
        OPS_PROJECTION_D1_ID,
        OPS_QUOTA_D1_ID,
    }
    assert PRODUCTION_D1_ID not in _strings(production_ops["d1_databases"])
    secrets = _load(_staging_toml("ingestion-secrets"))
    assert secrets.get("workers_dev") is False
    assert secrets.get("preview_urls") is False


def test_research_mass_eval_staging_is_token_gated_workers_dev_only() -> None:
    production = _load(_worker_toml("research-mass-eval"))
    production_env = _env_production(production)
    assert production_env is not None
    staging = _load(_staging_toml("research-mass-eval"))

    assert production.get("workers_dev") is True
    assert production.get("preview_urls") is False
    assert production.get("secrets") == {"required": ["MASS_EVAL_TOKEN"]}
    assert production_env.get("workers_dev") is True
    assert production_env.get("preview_urls") is False
    assert production_env.get("secrets") == {"required": ["MASS_EVAL_TOKEN"]}
    assert production.get("route") is None
    assert production.get("routes") in (None, [])
    assert production_env.get("route") is None
    assert production_env.get("routes") in (None, [])

    assert staging["name"] == "quant-platform-research-mass-eval-staging"
    assert staging.get("workers_dev") is True
    assert staging.get("preview_urls") is False
    assert staging.get("secrets") == {"required": ["MASS_EVAL_TOKEN"]}
    assert staging.get("route") is None
    assert staging.get("routes") in (None, [])
    assert "env" not in staging or "production" not in (staging.get("env") or {})
