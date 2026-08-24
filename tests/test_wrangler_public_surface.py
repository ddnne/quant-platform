"""Parse platform/workers wrangler.toml for public-surface topology.

Internal product workers must keep workers_dev false (and preview_urls false).
Documented exceptions may keep workers_dev true. Staging must use different
names and physically distinct binding IDs/resources.
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
    "research-mass-eval",
    "research-ai-gateway",
)

# workers_dev=true is allowed only with a documented reason (ADR).
WORKERS_DEV_TRUE_EXCEPTIONS = frozenset(
    {
        "quant-ops-mcp",  # GitHub OAuth callback host
        "ingestion-secrets",  # HUMAN Access/mTLS/Tunnel residual
        "ci-aggregate",  # not a public research API; Lane G will abolish
    }
)

PRODUCT_WORKERS = INTERNAL_PRODUCT + tuple(sorted(WORKERS_DEV_TRUE_EXCEPTIONS))

PRODUCTION_D1_ID = "be6fdcf8-40be-41fc-9535-7facd1fc2ffc"
PRODUCTION_KV_ID = "cbbfc9439c3e4a789fa103777d38f39e"
PRODUCTION_BUCKETS = frozenset({"quant-raw", "quant-structured"})
PRODUCTION_BINDING_IDS = frozenset({PRODUCTION_D1_ID, PRODUCTION_KV_ID}) | PRODUCTION_BUCKETS
STAGING_D1_ID = "d448d1c6-27c8-4aeb-8702-3e7a8b6bf2bb"
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
        if name in INTERNAL_PRODUCT:
            assert staging.get("workers_dev") is False, name
            assert staging.get("preview_urls") is False, name
        for banned in PRODUCTION_BINDING_IDS:
            assert banned not in _strings(staging), f"{staging_path} binds {banned}"
        env = staging.get("env") or {}
        assert "production" not in env, name

    for name in ("ingestion-jsda", "ingestion-premium", "quant-ops-mcp", "research-mass-eval"):
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
    secrets = _load(_staging_toml("ingestion-secrets"))
    assert secrets.get("workers_dev") is False
    assert secrets.get("preview_urls") is False
