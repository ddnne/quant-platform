"""ProcessIsolatedRunner policy tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agents.isolated_runner import (
    DEFAULT_AUDIENCE,
    DEFAULT_TOOL_ENTRYPOINTS,
    IsolationRejected,
    ProcessIsolatedRunner,
    issue_isolation_capability,
)

_SECRET = b"isolated-runner-test-hmac"
_HASH = "sha256:" + ("ab" * 32)
_EXPIRES = "2099-01-01T00:00:00+00:00"


def _cap(**kwargs: object):
    params: dict[str, object] = {
        "audience": DEFAULT_AUDIENCE,
        "scope": frozenset({"true"}),
        "expires_at": _EXPIRES,
        "plan_hash": _HASH,
        "snapshot_hash": _HASH,
        "hmac_secret": _SECRET,
    }
    params.update(kwargs)
    return issue_isolation_capability(**params)  # type: ignore[arg-type]


def _runner(**kwargs: object) -> ProcessIsolatedRunner:
    params: dict[str, object] = {
        "plan_hash": _HASH,
        "snapshot_hash": _HASH,
        "hmac_secret": _SECRET,
    }
    params.update(kwargs)
    return ProcessIsolatedRunner(**params)  # type: ignore[arg-type]


def test_default_tool_map_excludes_sys_executable():
    runner = _runner()
    assert sys.executable not in runner.allowed_binaries
    assert sys.executable not in DEFAULT_TOOL_ENTRYPOINTS.values()
    assert "true" in runner.tool_entrypoints
    assert runner.tool_entrypoints["true"] == "/usr/bin/true"


def test_allowlisted_true_binary():
    runner = _runner()
    cap = _cap()
    if not Path("/usr/bin/true").exists():
        pytest.skip("/usr/bin/true not present on this host")
    result = runner.run("true", capability=cap)
    assert result.returncode == 0
    assert result.tool_id == "true"
    assert result.argv[0] == "/usr/bin/true"


def test_rejects_shell_metacharacters():
    runner = _runner()
    cap = _cap()
    with pytest.raises(IsolationRejected, match="forbidden token"):
        runner.run("true", args=["foo; rm -rf /"], capability=cap)


def test_rejects_unknown_binary_and_unknown_tool_id():
    runner = _runner()
    cap = _cap()
    with pytest.raises(IsolationRejected, match="unknown tool id"):
        runner.run("/usr/bin/curl", capability=cap)
    with pytest.raises(IsolationRejected, match="unknown tool id"):
        runner.run("curl", capability=cap)
