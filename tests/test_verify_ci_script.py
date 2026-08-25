"""Small structural safety net around the executable CI entrypoint.

Deployment-surface correctness is tested behaviorally by
test_cloudflare_binding_manifest.py; this module only guards shell safety and
the native Workers Builds hand-off.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_ci.sh"
WRAPPER = ROOT / "scripts" / "workers_builds_verify_ci.sh"
DEPLOYMENT_ACCEPTANCE = (
    ROOT / "scripts" / "verify_cloudflare_deployment_acceptance.sh"
)
SECRET_INVENTORY = ROOT / "scripts" / "verify_cloudflare_secret_inventory.py"
ACTIVE_WORKERS = (
    "ingestion-jsda",
    "ingestion-premium",
    "ingestion-secrets",
    "quant-ops-mcp",
    "research-ai-gateway",
    "research-mass-eval",
)


def _bash_syntax(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-n", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_authoritative_ci_entrypoints_are_executable_shell() -> None:
    for path in (SCRIPT, WRAPPER, DEPLOYMENT_ACCEPTANCE):
        assert path.is_file()
        assert os.access(path, os.X_OK)
        checked = _bash_syntax(path)
        assert checked.returncode == 0, checked.stderr


def test_all_active_workers_have_locked_required_scripts() -> None:
    for worker in ACTIVE_WORKERS:
        directory = ROOT / "platform" / "workers" / worker
        assert (directory / "package-lock.json").is_file()
        package = json.loads((directory / "package.json").read_text(encoding="utf-8"))
        scripts = package.get("scripts") or {}
        assert {"test", "typecheck", "types"} <= set(scripts)
        assert "--include-runtime false" in scripts["types"]


def test_ci_shell_has_no_skip_or_live_deploy_command() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    code_lines = [line.split("#", 1)[0] for line in source.splitlines()]
    for line in code_lines:
        assert "--legacy-peer-deps" not in line
        assert "VERIFY_NPM" not in line
        if "wrangler deploy" in line:
            assert "--dry-run" in line
        assert "git ls-files | grep -E" not in line
    assert "platform/workers/ci-aggregate" not in source
    assert "scripts/verify_secret_paths.py" in source


def test_deployment_acceptance_is_authenticated_read_only_and_fail_closed() -> None:
    source = DEPLOYMENT_ACCEPTANCE.read_text(encoding="utf-8")
    assert "verify_ci.sh" in source
    assert "verify_cloudflare_secret_inventory.py" in source
    assert "CLOUDFLARE_API_TOKEN" in source
    assert "CLOUDFLARE_ACCOUNT_ID" in source
    assert "wrangler deploy" not in source
    assert SECRET_INVENTORY.is_file()
    assert os.access(SECRET_INVENTORY, os.X_OK)
    result = subprocess.run(
        [str(DEPLOYMENT_ACCEPTANCE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", "")},
        check=False,
    )
    assert result.returncode != 0
    assert "CLOUDFLARE_API_TOKEN is required" in result.stderr


def test_workers_builds_wrapper_fails_closed_outside_cloudflare() -> None:
    result = subprocess.run(
        [str(WRAPPER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", "")},
        check=False,
    )
    assert result.returncode != 0
    assert "WORKERS_CI=1 is required" in result.stderr


def test_github_actions_remains_absent() -> None:
    listed = subprocess.run(
        ["git", "ls-files", ".github/workflows"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert listed.stdout.strip() == ""
