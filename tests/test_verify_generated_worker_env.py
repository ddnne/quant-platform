from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_generated_worker_env import expected_types, write_check


def test_named_environment_binding_shapes_are_frozen() -> None:
    production = expected_types("quant-ops-mcp", "production")
    staging = expected_types("quant-ops-mcp", "staging")
    assert production["OPS_PROJECTION_DB"] == "D1Database"
    assert production["MCP_OBJECT"] == "DurableObjectNamespace<any>"
    assert production["OAUTH_AUTHORIZATION_SERVER"].startswith('"https://')
    assert "OAUTH_AUTHORIZATION_SERVER" not in staging


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
    assert "NoUnexpectedBindings" in assertion_text
    config = json.loads(tsconfig.read_text(encoding="utf-8"))
    assert config["compilerOptions"]["skipLibCheck"] is False
