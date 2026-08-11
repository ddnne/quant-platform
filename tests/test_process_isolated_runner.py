"""ProcessIsolatedRunner policy tests."""

from __future__ import annotations

import sys

import pytest

from agents.isolated_runner import IsolationRejected, ProcessIsolatedRunner


def test_allowlisted_true_binary():
    runner = ProcessIsolatedRunner(allowed_binaries=(sys.executable, "/usr/bin/true", "/bin/true"))
    # Use python -c is NOT allowlisted unless executable alone with safe argv
    # /usr/bin/true or /bin/true
    for bin_path in ("/usr/bin/true", "/bin/true"):
        try:
            result = runner.run([bin_path])
            assert result.returncode == 0
            return
        except FileNotFoundError:
            continue
    # Fallback: python -c not allowed; just assert rejection for shell
    with pytest.raises(IsolationRejected):
        runner.run(["/bin/sh", "-c", "echo hi"])


def test_rejects_shell_metacharacters():
    runner = ProcessIsolatedRunner(allowed_binaries=(sys.executable,))
    with pytest.raises(IsolationRejected):
        runner.run([sys.executable, "-c", "print(1); import os"])


def test_rejects_unknown_binary():
    runner = ProcessIsolatedRunner(allowed_binaries=(sys.executable,))
    with pytest.raises(IsolationRejected, match="not allowlisted"):
        runner.run(["/usr/bin/curl", "https://example.com"])
