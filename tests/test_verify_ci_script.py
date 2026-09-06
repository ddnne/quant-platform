"""Small structural safety net around the executable CI entrypoint.

Deployment-surface correctness is tested behaviorally by
test_cloudflare_binding_manifest.py; this module only guards shell safety and
the native Workers Builds hand-off.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_ci.sh"
WRAPPER = ROOT / "scripts" / "workers_builds_verify_ci.sh"
BOUNDED_JOBS = ROOT / "scripts" / "ci_bounded_jobs.sh"
DEPLOYMENT_ACCEPTANCE = (
    ROOT / "scripts" / "verify_cloudflare_deployment_acceptance.sh"
)
SECRET_INVENTORY = ROOT / "scripts" / "verify_cloudflare_secret_inventory.py"
ACTIVE_WORKERS = (
    "ingestion-jsda",
    "ingestion-premium",
    "ingestion-secrets",
    "quant-ops-mcp",
    "receipt-activation-observer",
    "receipt-evidence-authority",
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


def _write_executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _acceptance_fixture(tmp_path: Path) -> Path:
    fixture_root = tmp_path / "acceptance-repo"
    scripts = fixture_root / "scripts"
    scripts.mkdir(parents=True)
    copied = scripts / DEPLOYMENT_ACCEPTANCE.name
    shutil.copy2(DEPLOYMENT_ACCEPTANCE, copied)
    return fixture_root


def test_authoritative_ci_entrypoints_are_executable_shell() -> None:
    for path in (SCRIPT, WRAPPER, DEPLOYMENT_ACCEPTANCE, BOUNDED_JOBS):
        assert path.is_file()
        checked = _bash_syntax(path)
        assert checked.returncode == 0, checked.stderr
    for path in (SCRIPT, WRAPPER, DEPLOYMENT_ACCEPTANCE):
        assert os.access(path, os.X_OK)
    assert os.access(BOUNDED_JOBS, os.X_OK)


def test_all_active_workers_have_locked_required_scripts() -> None:
    for worker in ACTIVE_WORKERS:
        directory = ROOT / "platform" / "workers" / worker
        assert (directory / "package-lock.json").is_file()
        package = json.loads((directory / "package.json").read_text(encoding="utf-8"))
        scripts = package.get("scripts") or {}
        assert {"test", "typecheck", "types"} <= set(scripts)
        assert "--include-runtime false" in scripts["types"]


def test_deployment_acceptance_stops_at_the_open_finding_ledger_first() -> None:
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
    assert "finding ledger release gate blocked" in result.stderr
    assert "CLOUDFLARE_API_TOKEN is required" not in result.stderr


def test_deployment_acceptance_scrubs_credentials_before_first_repo_python(
    tmp_path: Path,
) -> None:
    fixture_root = _acceptance_fixture(tmp_path)
    fake_bin = tmp_path / "bin"
    _write_executable(
        fake_bin / "python3.11",
        """#!/bin/sh
if env | grep -q '^CLOUDFLARE_'; then
  echo 'cloudflare credential leaked to finding gate' >&2
  exit 97
fi
if [ -n "${UNRELATED_SECRET:-}" ]; then
  echo 'ambient environment leaked to finding gate' >&2
  exit 98
fi
echo 'finding ledger release gate blocked' >&2
exit 1
""",
    )
    environment = {
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "LANG": "C",
        "HOME": "/ambient/oauth-home-must-not-pass",
        "CLOUDFLARE_API_TOKEN": "captured-test-token",
        "CLOUDFLARE_ACCOUNT_ID": "captured-test-account",
        "CLOUDFLARE_API_KEY": "legacy-key-must-not-pass",
        "CLOUDFLARE_EMAIL": "legacy-email-must-not-pass",
        "UNRELATED_SECRET": "must-not-pass",
    }
    result = subprocess.run(
        [str(fixture_root / "scripts" / DEPLOYMENT_ACCEPTANCE.name)],
        cwd=fixture_root,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    assert "finding ledger release gate blocked" in result.stderr
    assert "leaked" not in result.stderr


def test_pending_acceptance_gives_credentials_only_to_live_commands(
    tmp_path: Path,
) -> None:
    fixture_root = _acceptance_fixture(tmp_path)
    scripts = fixture_root / "scripts"
    _write_executable(
        scripts / "verify_ci.sh",
        """#!/bin/sh
if env | grep -q '^CLOUDFLARE_' || [ -n "${UNRELATED_SECRET:-}" ]; then
  echo 'ambient environment leaked to verify_ci' >&2
  exit 91
fi
echo 'verify-ci-isolated'
""",
    )
    _write_executable(
        fixture_root / ".venv" / "bin" / "python",
        """#!/bin/sh
case "$1" in
  *receipt_authority_pending_gate.py)
    if env | grep -q '^CLOUDFLARE_' || [ -n "${UNRELATED_SECRET:-}" ]; then
      echo 'credential leaked to pending source gate' >&2
      exit 92
    fi
    echo 'pending-gate-isolated'
    ;;
  *verify_cloudflare_secret_inventory.py|*receipt_authority_pending_live_acceptance.py)
    if [ "${CLOUDFLARE_API_TOKEN:-}" != 'captured-test-token' ] || \
       [ "${CLOUDFLARE_ACCOUNT_ID:-}" != 'captured-test-account' ]; then
      echo 'explicit live credential missing' >&2
      exit 93
    fi
    if [ -n "${CLOUDFLARE_API_KEY:-}" ] || \
       [ -n "${CLOUDFLARE_EMAIL:-}" ] || \
       [ -n "${UNRELATED_SECRET:-}" ] || \
       [ "${HOME:-}" = '/ambient/oauth-home-must-not-pass' ]; then
      echo 'ambient credential leaked to live command' >&2
      exit 94
    fi
    echo 'live-command-minimum-env'
    ;;
  *)
    echo "unexpected fixture command: $1" >&2
    exit 95
    ;;
esac
""",
    )
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C",
        "HOME": "/ambient/oauth-home-must-not-pass",
        "CLOUDFLARE_API_TOKEN": "captured-test-token",
        "CLOUDFLARE_ACCOUNT_ID": "captured-test-account",
        "CLOUDFLARE_API_KEY": "legacy-key-must-not-pass",
        "CLOUDFLARE_EMAIL": "legacy-email-must-not-pass",
        "UNRELATED_SECRET": "must-not-pass",
    }
    result = subprocess.run(
        [
            str(fixture_root / "scripts" / DEPLOYMENT_ACCEPTANCE.name),
            "--pending-receipt-authority",
            "staging",
            "--expected-source-sha",
            "a" * 40,
        ],
        cwd=fixture_root,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "verify-ci-isolated" in result.stdout
    assert "pending-gate-isolated" in result.stdout
    assert result.stdout.count("live-command-minimum-env") == 2
    assert "receipt authority PENDING deployment acceptance: ok" in result.stdout


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


def _bounded_driver(tmp_path: Path) -> Path:
    driver = tmp_path / "bounded_driver.sh"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    runner = tmp_path / "lane_job.sh"
    runner.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
name="$(basename "$1")"
mkdir "{tmp_path}/running/$name"
ls -1 "{tmp_path}/running" | wc -l | tr -d ' ' >> "{tmp_path}/peaks"
sleep 0.2
echo "job $name"
rmdir "{tmp_path}/running/$name"
case "$name" in
  fail-*) exit 7 ;;
esac
""",
        encoding="utf-8",
    )
    runner.chmod(0o755)
    (tmp_path / "running").mkdir()
    driver.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
if ! bash "{BOUNDED_JOBS}" 2 "{log_dir}" "" "worker lane" "{runner}" "$@"; then
  exit 1
fi
""",
        encoding="utf-8",
    )
    driver.chmod(0o755)
    return driver


def test_bounded_jobs_succeed_with_at_most_two_concurrent(tmp_path: Path) -> None:
    driver = _bounded_driver(tmp_path)
    names = ["ok-a", "ok-b", "ok-c", "ok-d"]
    result = subprocess.run(
        [str(driver), *names],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert [line for line in result.stdout.splitlines() if line.startswith("job ")] == [
        "job ok-a",
        "job ok-b",
        "job ok-c",
        "job ok-d",
    ]
    peaks = [
        int(line)
        for line in (tmp_path / "peaks").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert peaks
    assert max(peaks) <= 2


def test_bounded_jobs_propagate_intermediate_command_failure(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    runner = tmp_path / "intermediate_fail.sh"
    runner.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
false
echo UNEXPECTED_AFTER_FAILURE
""",
        encoding="utf-8",
    )
    runner.chmod(0o755)
    parent = tmp_path / "parent.sh"
    parent.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
if ! bash "{BOUNDED_JOBS}" 2 "{log_dir}" "" "probe" "{runner}" lane; then
  echo FAILED
else
  echo PASSED
fi
""",
        encoding="utf-8",
    )
    parent.chmod(0o755)
    result = subprocess.run(
        [str(parent)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert "UNEXPECTED_AFTER_FAILURE" not in combined
    assert "FAILED" in result.stdout
    assert "PASSED" not in result.stdout
    assert "probe failed: lane" in result.stderr
    assert result.returncode == 0


def test_bounded_jobs_run_all_and_aggregate_failures(tmp_path: Path) -> None:
    driver = _bounded_driver(tmp_path)
    names = ["ok-a", "fail-b", "ok-c", "fail-d", "ok-e"]
    result = subprocess.run(
        [str(driver), *names],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    stdout_jobs = [
        line for line in result.stdout.splitlines() if line.startswith("job ")
    ]
    assert stdout_jobs == [
        "job ok-a",
        "job fail-b",
        "job ok-c",
        "job fail-d",
        "job ok-e",
    ]
    assert "worker lane failed: fail-b" in result.stderr
    assert "worker lane failed: fail-d" in result.stderr
    assert "worker lane failed: ok-a" not in result.stderr
    peaks = [
        int(line)
        for line in (tmp_path / "peaks").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert max(peaks) <= 2
