from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import scripts.verify_generated_worker_env as verify
from scripts.verify_generated_worker_env import (
    active_worker_environments,
    expected_env_properties,
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


def test_every_active_worker_environment_is_covered_without_generic_erasure() -> None:
    rows = active_worker_environments()
    workers = {worker for worker, _environment in rows}
    assert workers == {
        "ingestion-jsda",
        "ingestion-premium",
        "receipt-evidence-authority",
        "ingestion-secrets",
        "quant-ops-mcp",
        "receipt-activation-observer",
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
    mass_staging = expected_types("research-mass-eval", "staging")
    gateway = expected_types("research-ai-gateway", "production")
    secrets = expected_types("ingestion-secrets", "production")
    observer = expected_types("receipt-activation-observer", "production")
    assert mass["AI_GATEWAY"] == "Service"
    assert mass["MASS_EVAL_TOKEN"] == "string"
    assert mass_staging["MASS_EVAL_TOKEN"] == "string"
    assert mass_staging["ENVIRONMENT"] == '"staging"'
    assert gateway["BUDGET_LEDGER"] == (
        'DurableObjectNamespace<import("./src/index").BudgetLedger>'
    )
    assert secrets["PROXY_RATE_LIMITER"] == "RateLimit"
    assert observer["JSDA_INGESTION"] == "Service"
    assert "JSDA_INGESTION" not in expected_types(
        "receipt-activation-observer", "base"
    )
    assert expected_types("ingestion-jsda", "production")["CF_VERSION_METADATA"] == (
        "WorkerVersionMetadata"
    )


def test_base_env_keeps_same_toml_production_bindings_optional() -> None:
    required, optional = expected_env_properties(
        "receipt-activation-observer", "base"
    )
    assert "JSDA_INGESTION" not in required
    assert optional["JSDA_INGESTION"] == "Service"
    assert "PREMIUM_RECEIPT_OPERATOR" not in optional
    mcp_required, mcp_optional = expected_env_properties("quant-ops-mcp", "base")
    assert mcp_required["OPS_PROJECTION_ENVIRONMENT"] == '"production"'
    assert mcp_required["OPS_PROJECTION_VERIFY_KEY_ID"] == (
        '"ops-projection-20260826-v2"'
    )
    assert mcp_optional == {}


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


@pytest.mark.toolchain
def test_write_check_typechecks_synthetic_env_and_rejects_binding_mismatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tsc = (
        verify.WORKER_ROOT
        / "ingestion-premium"
        / "node_modules"
        / "typescript"
        / "bin"
        / "tsc"
    )
    premium_modules = verify.WORKER_ROOT / "ingestion-premium" / "node_modules"
    assert tsc.is_file(), f"pinned TypeScript compiler missing (run npm ci): {tsc}"
    assert (premium_modules / "@cloudflare" / "workers-types").exists(), (
        f"pinned @cloudflare/workers-types missing (run npm ci): {premium_modules}"
    )

    worker = "synthetic-check-worker"
    worker_root = tmp_path / "workers"
    worker_dir = worker_root / worker
    src = worker_dir / "src"
    src.mkdir(parents=True)
    (src / "index.ts").write_text(
        'import { DurableObject } from "cloudflare:workers";\n'
        "export class Ledger extends DurableObject {}\n",
        encoding="utf-8",
    )
    (worker_dir / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {
                    "target": "ES2022",
                    "lib": ["ES2022"],
                    "module": "ES2022",
                    "moduleResolution": "bundler",
                    "strict": True,
                    "noEmit": True,
                    "isolatedModules": True,
                    "skipLibCheck": False,
                    "types": ["@cloudflare/workers-types"],
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (worker_dir / "node_modules").symlink_to(
        premium_modules.resolve(), target_is_directory=True
    )

    empty = {
        "d1_databases": [],
        "r2_buckets": [],
        "kv_namespaces": [],
        "queue_producers": [],
        "durable_objects": [],
        "services": [],
        "ratelimits": [],
        "vars": {},
    }
    shared = {
        **empty,
        "d1_databases": [{"binding": "DB"}],
        "durable_objects": [{"name": "LEDGER", "class_name": "Ledger"}],
    }
    manifest = tmp_path / "active_worker_bindings.json"
    manifest.write_text(
        json.dumps(
            {
                "workers": {
                    worker: {
                        "base": {**shared, "vars": {"ENVIRONMENT": "base"}},
                        "production": {
                            **shared,
                            "services": [
                                {"binding": "UPSTREAM", "entrypoint": "default"}
                            ],
                            "vars": {"ENVIRONMENT": "production"},
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    generated = worker_dir / "env.d.ts"
    base_env = (
        "interface __BaseEnv_Env {\n"
        "  DB: D1Database;\n"
        '  ENVIRONMENT: "base";\n'
        '  LEDGER: DurableObjectNamespace<import("./src/index").Ledger>;\n'
        "  UPSTREAM?: Service;\n"
        "}\n"
        "declare namespace Cloudflare { interface Env extends __BaseEnv_Env {} }\n"
        "interface Env extends __BaseEnv_Env {}\n"
    )
    generated.write_text(base_env, encoding="utf-8")
    assertion = tmp_path / "check" / "assert.ts"
    tsconfig = tmp_path / "check" / "tsconfig.json"
    assertion.parent.mkdir()

    monkeypatch.setattr(verify, "MANIFEST", manifest)
    monkeypatch.setattr(verify, "WORKER_ROOT", worker_root)

    def compile_check() -> subprocess.CompletedProcess[str]:
        node = shutil.which("node")
        assert node, "node executable missing; toolchain tests require Node after npm ci"
        return subprocess.run(
            [node, str(tsc), "--pretty", "false", "-p", str(tsconfig)],
            capture_output=True,
            text=True,
            timeout=60,
        )

    write_check(
        worker=worker,
        environment="base",
        generated_types=generated,
        assertion=assertion,
        tsconfig=tsconfig,
    )
    config = json.loads(tsconfig.read_text(encoding="utf-8"))
    assert config["compilerOptions"]["skipLibCheck"] is False
    success = compile_check()
    assert success.returncode == 0, f"{success.stdout}\n{success.stderr}"

    write_check(
        worker=worker,
        environment="production",
        generated_types=generated,
        assertion=assertion,
        tsconfig=tsconfig,
    )
    wrong_env = compile_check()
    wrong_env_out = f"{wrong_env.stdout}\n{wrong_env.stderr}"
    assert wrong_env.returncode != 0, wrong_env_out
    assert assertion.name in wrong_env_out
    assert "error TS" in wrong_env_out

    write_check(
        worker=worker,
        environment="base",
        generated_types=generated,
        assertion=assertion,
        tsconfig=tsconfig,
    )
    generated.write_text(
        base_env.replace("  UPSTREAM?: Service;\n", ""), encoding="utf-8"
    )
    missing = compile_check()
    missing_out = f"{missing.stdout}\n{missing.stderr}"
    assert missing.returncode != 0, missing_out
    assert assertion.name in missing_out
    assert "error TS" in missing_out

    generated.write_text(
        base_env.replace(
            "  UPSTREAM?: Service;\n", "  UPSTREAM?: Service;\n  EXTRA: string;\n"
        ),
        encoding="utf-8",
    )
    extra = compile_check()
    extra_out = f"{extra.stdout}\n{extra.stderr}"
    assert extra.returncode != 0, extra_out
    assert assertion.name in extra_out
    assert "error TS" in extra_out
