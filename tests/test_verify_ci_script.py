"""Guard scripts/verify_ci.sh as authoritative CI (no skips, no live deploy)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_ci.sh"

WORKERS = (
    "ingestion-jsda",
    "ingestion-premium",
    "ingestion-secrets",
    "quant-ops-mcp",
    "research-ai-gateway",
    "research-mass-eval",
    "ci-aggregate",
)

SKIP_FLAGS = (
    "VERIFY_NPM_CI",
    "VERIFY_NPM_TYPECHECK",
    "VERIFY_NPM_BUILD",
    "VERIFY_CREATE_VENV",
)


def _src() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _code_lines(src: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for i, line in enumerate(src.splitlines(), start=1):
        out.append((i, line.split("#", 1)[0]))
    return out


def test_verify_ci_script_exists_executable_and_covers_required_steps() -> None:
    assert SCRIPT.is_file(), SCRIPT
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"
    src = _src()
    assert "legacy-peer-deps" in src
    assert ".venv" in src
    assert "3.11" in src
    assert "sys.version_info" in src
    assert "do not silently use system python" in src
    assert "pip install -e" in src
    assert ".[dev]" in src
    assert "pytest tests/" in src
    assert "compile_catalog" in src
    assert "assert_catalog_ids_emit_frozen" in src
    assert "catalog_ids" in src
    assert "specs/evaluation_ir/golden.jsonl" in src
    assert "specs/evaluation_ir/schema.json" in src
    assert "evaluation_ir.py" in src
    assert "evaluation_ir.ts" in src
    assert len(WORKERS) == 7
    assert "package-lock.json" in src
    assert "npm ci" in src
    assert "npm test" in src
    assert "npm run typecheck" in src
    assert "wrangler deploy --dry-run" in src
    assert "wrangler types --check" in src
    assert "npm run types" in src
    assert "wrangler types" in src
    assert "git ls-files" in src
    assert ".env" in src
    assert ".pem" in src
    assert "commit generated types" in src
    for name in WORKERS:
        assert name in src, f"{SCRIPT} must cover worker {name}"
    for flag in SKIP_FLAGS:
        assert flag not in src, f"{SCRIPT} must not define skip flag {flag}"


def test_verify_ci_bans_legacy_peer_deps_skips_and_live_deploy() -> None:
    src = _src()
    for i, code in _code_lines(src):
        assert "--legacy-peer-deps" not in code, (
            f"{SCRIPT}:{i} must not pass --legacy-peer-deps"
        )
        assert "VERIFY_NPM" not in code, (
            f"{SCRIPT}:{i} must not use VERIFY_* skip flags"
        )
        if "node_modules" in code:
            assert "skip" not in code.lower(), (
                f"{SCRIPT}:{i} must not skip missing node_modules"
            )
        if "wrangler deploy" in code:
            assert "--dry-run" in code, (
                f"{SCRIPT}:{i} must not live wrangler deploy"
            )
        if "python3" in code or "python3." in code:
            # Error text / comments may mention python3.11 for create instructions;
            # executable code must not fall back to system python.
            stripped = code.strip()
            if stripped and not stripped.startswith("echo "):
                assert ".venv" in src
                assert "command -v" not in code or "npm" in code, (
                    f"{SCRIPT}:{i} must not silently use system python"
                )
