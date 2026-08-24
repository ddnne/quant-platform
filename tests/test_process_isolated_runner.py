"""ProcessIsolatedRunner policy tests."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

from agents.isolated_runner import (
    DEFAULT_AUDIENCE,
    DEFAULT_TOOL_ENTRYPOINTS,
    IsolationRejected,
    MacOSSandboxExecBackend,
    ProcessIsolatedRunner,
    UnsafeOfflineTestBackend,
    issue_isolation_capability,
    validate_isolated_argv,
)

_SECRET = b"isolated-runner-test-hmac"
_HASH = "sha256:" + ("ab" * 32)
_HASH_B = "sha256:" + ("cd" * 32)
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


def _offline_runner(**kwargs: object) -> ProcessIsolatedRunner:
    params: dict[str, object] = {
        "backend": UnsafeOfflineTestBackend(),
        "allow_unsafe_offline": True,
    }
    params.update(kwargs)
    return _runner(**params)


def test_default_tool_map_excludes_sys_executable():
    runner = _runner()
    assert sys.executable not in runner.allowed_binaries
    assert sys.executable not in DEFAULT_TOOL_ENTRYPOINTS.values()
    assert "true" in runner.tool_entrypoints
    assert runner.tool_entrypoints["true"] == "/usr/bin/true"


def test_allowlisted_true_binary():
    runner = _offline_runner()
    cap = _cap()
    if not Path("/usr/bin/true").exists():
        pytest.skip("/usr/bin/true not present on this host")
    result = runner.run("true", capability=cap)
    assert result.returncode == 0
    assert result.tool_id == "true"
    assert result.argv[0] == "/usr/bin/true"
    assert result.backend == "unsafe-offline-test"
    assert result.os_isolated is False


def test_production_fails_closed_without_os_backend(
    monkeypatch: pytest.MonkeyPatch,
):
    from agents import isolated_runner as mod

    monkeypatch.setattr(mod, "_default_os_isolation_backend", lambda: None)
    runner = _runner()
    cap = _cap()

    def unexpected_subprocess(*_args: object, **_kwargs: object):
        raise AssertionError("host subprocess fallback must not run")

    monkeypatch.setattr(mod.subprocess, "run", unexpected_subprocess)
    with pytest.raises(IsolationRejected, match="no active OS sandbox backend"):
        runner.run("true", capability=cap)


def test_unsafe_offline_backend_requires_explicit_opt_in():
    with pytest.raises(IsolationRejected, match="allow_unsafe_offline"):
        _runner(backend=UnsafeOfflineTestBackend())


def test_macos_profile_is_deny_first_and_has_no_user_filesystem_allow():
    profile = MacOSSandboxExecBackend().profile_for_binary("/usr/bin/true")
    assert "(deny default)" in profile
    assert "(deny network*)" in profile
    assert "(deny process-fork)" in profile
    assert '(allow process-exec (literal "/usr/bin/true"))' in profile
    assert "/Users" not in profile
    assert "/private" not in profile


def test_macos_backend_executes_true_under_active_os_sandbox():
    backend = MacOSSandboxExecBackend()
    if not backend.is_available() or not Path("/usr/bin/true").exists():
        pytest.skip("active macOS sandbox-exec backend not present")
    result = _runner(backend=backend).run("true", capability=_cap())
    assert result.returncode == 0
    assert result.backend == "macos-sandbox-exec"
    assert result.os_isolated is True


def test_macos_backend_denies_arbitrary_filesystem_read():
    backend = MacOSSandboxExecBackend()
    stat_binary = Path("/usr/bin/stat")
    if not backend.is_available() or not stat_binary.exists():
        pytest.skip("active macOS sandbox-exec/stat not present")
    runner = _runner(
        backend=backend,
        tool_entrypoints={"stat": str(stat_binary)},
    )
    result = runner.run(
        "stat",
        args=["/etc/passwd"],
        capability=_cap(scope=frozenset({"stat"})),
    )
    assert result.returncode != 0
    assert "Operation not permitted" in result.stderr
    assert result.os_isolated is True


def test_macos_backend_denies_arbitrary_filesystem_write(tmp_path: Path):
    backend = MacOSSandboxExecBackend()
    touch_binary = Path("/usr/bin/touch")
    if not backend.is_available() or not touch_binary.exists():
        pytest.skip("active macOS sandbox-exec/touch not present")
    target = tmp_path / "sandbox-must-not-create-this"
    runner = _runner(
        backend=backend,
        tool_entrypoints={"touch": str(touch_binary)},
    )
    result = runner.run(
        "touch",
        args=[str(target)],
        capability=_cap(scope=frozenset({"touch"})),
    )
    assert result.returncode != 0
    assert not target.exists()
    assert result.os_isolated is True


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


def test_default_runner_rejects_sys_executable_and_python_c():
    runner = _runner()
    cap = _cap()
    with pytest.raises(IsolationRejected):
        runner.run(sys.executable, capability=cap)
    with pytest.raises(IsolationRejected):
        runner.run("python", args=["-c", "print(1)"], capability=cap)
    with pytest.raises(IsolationRejected):
        runner.run("python", args=["-m", "http.server"], capability=cap)
    with pytest.raises(IsolationRejected, match="python -c"):
        validate_isolated_argv([sys.executable, "-c", "print(1); import os"])
    with pytest.raises(IsolationRejected, match="python -c"):
        validate_isolated_argv(["/usr/bin/true", "-c", "print(1)"])
    with pytest.raises(IsolationRejected, match="python -m"):
        validate_isolated_argv([sys.executable, "-m", "http.server"])
    with pytest.raises(IsolationRejected, match="not allowlisted"):
        validate_isolated_argv([sys.executable])


def test_constructor_rejects_python_and_shell_entrypoints():
    with pytest.raises(IsolationRejected, match="not allowlisted"):
        _runner(tool_entrypoints={"py": sys.executable})
    with pytest.raises(IsolationRejected, match="not allowlisted"):
        _runner(tool_entrypoints={"sh": "/bin/sh"})
    with pytest.raises(IsolationRejected, match="not allowlisted"):
        _runner(tool_entrypoints={"curl": "/usr/bin/curl"})


def test_constructor_rejects_shell_symlink(tmp_path: Path):
    shell_link = tmp_path / "apparently-safe-tool"
    try:
        shell_link.symlink_to("/bin/sh")
    except OSError:
        pytest.skip("host does not permit symlink creation")
    with pytest.raises(IsolationRejected, match="not allowlisted"):
        _runner(tool_entrypoints={"safe": str(shell_link)})


def test_run_requires_verified_capability():
    runner = _runner()
    with pytest.raises(IsolationRejected, match="scope"):
        runner.run("true", capability=_cap(scope=frozenset({"other"})))
    with pytest.raises(IsolationRejected, match="not a signed"):
        runner.run("true", capability=None)
    with pytest.raises(IsolationRejected, match="not a signed"):
        runner.run(
            "true",
            capability={
                "audience": DEFAULT_AUDIENCE,
                "scope": ["true"],
                "plan_hash": _HASH,
                "snapshot_hash": _HASH,
            },
        )
    cap = _cap(plan_hash=_HASH_B, snapshot_hash=_HASH_B)
    with pytest.raises(IsolationRejected, match="plan_hash"):
        runner.run("true", capability=cap)


def test_capability_cannot_self_authorize_via_dataclass():
    assert not dataclasses.is_dataclass(type(_cap()))
    runner = _runner()
    with pytest.raises(IsolationRejected, match="issued"):
        from agents.signed_capability import SignedIsolationCapability

        runner.run(
            "true",
            capability=SignedIsolationCapability(
                audience=DEFAULT_AUDIENCE,
                scope=frozenset({"true"}),
                expires_at=_EXPIRES,
                plan_hash=_HASH,
                snapshot_hash=_HASH,
            ),
        )


def test_scrub_env_drops_secrets(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("QUANT_ISOLATION_HMAC_SECRET", "should-not-leak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws")
    env = _runner()._scrub_env()
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/tmp"
    assert "OPENAI_API_KEY" not in env
    assert "QUANT_ISOLATION_HMAC_SECRET" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert not any("SECRET" in k or "TOKEN" in k or "KEY" in k for k in env)


def test_runner_does_not_use_shell_true():
    import inspect

    from agents import isolated_runner as mod

    src = inspect.getsource(mod.ProcessIsolatedRunner.run)
    assert "shell=True" not in src
    assert "shell=False" in src
