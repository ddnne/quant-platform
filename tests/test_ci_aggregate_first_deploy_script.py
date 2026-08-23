"""Guard scripts/ci_aggregate_first_deploy.sh as print-only first-create helper."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_aggregate_first_deploy.sh"

_LIVE_SECRET_MARKERS = (
    "ghp_",
    "github_pat_",
    "gho_",
    "ghu_",
    "ghs_",
    "glpat-",
    "sk_live",
    "sk-ant-",
    "AKIA",
    "CLOUDFLARE_API_TOKEN=",
    "CF_API_TOKEN=",
)


def _src() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _assert_no_live_secret(text: str, where: str) -> None:
    for marker in _LIVE_SECRET_MARKERS:
        assert marker not in text, f"{where} must not contain live secret marker {marker}"
    assert not re.search(r"CI_LANE_TOKEN\s*=\s*\S+", text), (
        f"{where} must not assign a CI_LANE_TOKEN value"
    )
    assert not re.search(r"GITHUB_STATUS_TOKEN\s*=\s*\S+", text), (
        f"{where} must not assign a GITHUB_STATUS_TOKEN value"
    )


def _run(*args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("CONFIRM_CI_AGGREGATE_CREATE", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_script_exists_executable_and_pins_operator_commands() -> None:
    assert SCRIPT.is_file(), SCRIPT
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"
    src = _src()
    assert "wrangler deploy" in src
    assert "CI_LANE_TOKEN" in src
    assert "npx wrangler deploy --dry-run" in src
    assert "cd platform/workers/ci-aggregate" in src
    assert "secret put CI_LANE_TOKEN" in src
    assert "secret put GITHUB_STATUS_TOKEN" in src
    assert "CONFIRM_CI_AGGREGATE_CREATE" in src
    _assert_no_live_secret(src, str(SCRIPT))


def test_script_does_not_exec_wrangler() -> None:
    src = _src()
    in_heredoc = False
    for i, line in enumerate(src.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("cat <<"):
            in_heredoc = True
            continue
        if in_heredoc and stripped == "EOF":
            in_heredoc = False
            continue
        if in_heredoc:
            continue
        code = line.split("#", 1)[0]
        assert not re.search(r"\bnpx\s+wrangler\b", code), (
            f"{SCRIPT}:{i} must not exec npx wrangler"
        )
        assert not re.search(r"(^|[;&|`(])\s*wrangler\s", code), (
            f"{SCRIPT}:{i} must not exec wrangler"
        )


def test_default_is_print_only_dry_run_first() -> None:
    proc = _run()
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "cd platform/workers/ci-aggregate" in out
    assert "npx wrangler deploy --dry-run" in out
    dry = out.index("npx wrangler deploy --dry-run")
    live_comment = out.index("# npx wrangler deploy")
    secret_comment = out.index("# npx wrangler secret put CI_LANE_TOKEN")
    assert dry < live_comment < secret_comment
    _assert_no_live_secret(out, "default stdout")
    _assert_no_live_secret(proc.stderr, "default stderr")


def test_refuses_apply_without_confirm() -> None:
    proc = _run("--apply")
    assert proc.returncode != 0
    err = proc.stderr
    assert "CONFIRM_CI_AGGREGATE_CREATE" in err
    assert "refusing --apply" in err
    assert "wrangler deploy" not in proc.stdout


def test_refuses_apply_unless_confirm_is_exactly_one() -> None:
    for value in ("", "0", "yes", "true"):
        proc = _run("--apply", extra_env={"CONFIRM_CI_AGGREGATE_CREATE": value})
        assert proc.returncode != 0, value
        assert "CONFIRM_CI_AGGREGATE_CREATE" in proc.stderr
        assert proc.stdout == ""


def test_confirmed_apply_is_still_print_only() -> None:
    proc = _run("--apply", extra_env={"CONFIRM_CI_AGGREGATE_CREATE": "1"})
    assert proc.returncode == 0, proc.stderr
    assert "npx wrangler deploy --dry-run" in proc.stdout
    assert "# npx wrangler secret put CI_LANE_TOKEN" in proc.stdout
    assert "does not wrangler deploy" in proc.stderr
    _assert_no_live_secret(proc.stdout, "confirmed-apply stdout")
    _assert_no_live_secret(proc.stderr, "confirmed-apply stderr")
