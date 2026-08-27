from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_generated_worker_env import (
    active_worker_environments,
    expected_types,
    write_check,
)


def test_named_environment_binding_shapes_are_frozen() -> None:
    production = expected_types("quant-ops-mcp", "production")
    staging = expected_types("quant-ops-mcp", "staging")
    assert production["OPS_PROJECTION_DB"] == "D1Database"
    assert production["MCP_OBJECT"] == (
        'DurableObjectNamespace<import("./src/index").QuantOpsMcpAgent>'
    )
    assert production["OAUTH_AUTHORIZATION_SERVER"].startswith('"https://')
    assert production["GITHUB_CLIENT_SECRET"] == "string"
    assert production["STATE_SECRET"] == "string"
    assert "OAUTH_AUTHORIZATION_SERVER" not in staging
    assert "GITHUB_CLIENT_SECRET" not in staging


def test_check_generation_rejects_non_wrangler_declaration(tmp_path: Path) -> None:
    generated = tmp_path / "env.d.ts"
    generated.write_text("interface Env {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="generated Env surface"):
        write_check(
            worker="quant-ops-mcp",
            environment="production",
            generated_types=generated,
            assertion=tmp_path / "assert.ts",
            tsconfig=tmp_path / "tsconfig.json",
        )


def test_check_generation_pins_exact_named_environment(tmp_path: Path) -> None:
    generated = tmp_path / "env.d.ts"
    generated.write_text(
        "interface __BaseEnv_Env { DB: D1Database; }\n"
        "declare namespace Cloudflare { interface Env extends __BaseEnv_Env {} }\n"
        "interface Env extends __BaseEnv_Env {}\n",
        encoding="utf-8",
    )
    assertion = tmp_path / "assert.ts"
    tsconfig = tmp_path / "tsconfig.json"
    write_check(
        worker="ingestion-premium",
        environment="production",
        generated_types=generated,
        assertion=assertion,
        tsconfig=tsconfig,
    )
    assertion_text = assertion.read_text(encoding="utf-8")
    assert 'readonly "DB": D1Database;' in assertion_text
    assert 'readonly "RAW_BUCKET": R2Bucket;' in assertion_text
    assert 'readonly "JQUANTS_API_KEY": string;' in assertion_text
    assert "NoUnexpectedBindings" in assertion_text
    assert 'import("./src/index")' not in assertion_text
    assert "DurableObjectNamespace" not in assertion_text
    config = json.loads(tsconfig.read_text(encoding="utf-8"))
    assert config["compilerOptions"]["skipLibCheck"] is False


def test_every_active_worker_environment_is_covered_without_generic_erasure() -> None:
    rows = active_worker_environments()
    workers = {worker for worker, _environment in rows}
    assert workers == {
        "ingestion-jsda",
        "ingestion-premium",
        "receipt-evidence-authority",
        "ingestion-secrets",
        "quant-ops-mcp",
        "research-ai-gateway",
        "research-mass-eval",
    }
    assert {environment for _worker, environment in rows} == {
        "base",
        "production",
        "staging",
    }
    for worker, environment in rows:
        expected = expected_types(worker, environment)
        for type_name in expected.values():
            assert "any" not in type_name
            assert type_name not in {
                "unknown",
                "object",
                "Fetcher",
                "Record<string, unknown>",
            }


def test_typed_service_and_durable_object_refinements_are_required() -> None:
    mass = expected_types("research-mass-eval", "production")
    gateway = expected_types("research-ai-gateway", "production")
    secrets = expected_types("ingestion-secrets", "production")
    assert mass["AI_GATEWAY"] == "Service"
    assert gateway["BUDGET_LEDGER"] == (
        'DurableObjectNamespace<import("./src/index").BudgetLedger>'
    )
    assert secrets["PROXY_RATE_LIMITER"] == "RateLimit"
    assert expected_types("ingestion-jsda", "production")["CF_VERSION_METADATA"] == (
        "WorkerVersionMetadata"
    )


def test_generic_fetcher_or_do_erasure_is_rejected(tmp_path: Path) -> None:
    generated = tmp_path / "env.d.ts"
    generated.write_text(
        "interface __BaseEnv_Env { AI_GATEWAY: Fetcher; }\n"
        "declare namespace Cloudflare { interface Env extends __BaseEnv_Env {} }\n"
        "interface Env extends __BaseEnv_Env {}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="typed Service binding"):
        write_check(
            worker="research-mass-eval",
            environment="production",
            generated_types=generated,
            assertion=tmp_path / "assert.ts",
            tsconfig=tmp_path / "tsconfig.json",
        )
    generated.write_text(
        "interface __BaseEnv_Env { BUDGET_LEDGER: DurableObjectNamespace<any>; }\n"
        "declare namespace Cloudflare { interface Env extends __BaseEnv_Env {} }\n"
        "interface Env extends __BaseEnv_Env {}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Durable Object class"):
        write_check(
            worker="research-ai-gateway",
            environment="production",
            generated_types=generated,
            assertion=tmp_path / "assert.ts",
            tsconfig=tmp_path / "tsconfig.json",
        )


def test_durable_object_import_is_relative_to_temp_assertion(tmp_path: Path) -> None:
    generated = tmp_path / "types" / "env.d.ts"
    assertion = tmp_path / "types" / "assert.ts"
    tsconfig = tmp_path / "types" / "tsconfig.json"
    generated.parent.mkdir()
    generated.write_text(
        "interface __BaseEnv_Env { MCP_OBJECT: DurableObjectNamespace<never>; }\n"
        "declare namespace Cloudflare { interface Env extends __BaseEnv_Env {} }\n"
        "interface Env extends __BaseEnv_Env {}\n",
        encoding="utf-8",
    )
    write_check(
        worker="quant-ops-mcp",
        environment="production",
        generated_types=generated,
        assertion=assertion,
        tsconfig=tsconfig,
    )
    text = assertion.read_text(encoding="utf-8")
    assert 'import("./src/index")' not in text
    assert 'DurableObjectNamespace<import("' in text
    assert "platform/workers/quant-ops-mcp/src/index" in text
