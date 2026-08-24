"""Fail-closed process isolation for agent tools (Phase 6.2.3 §10).

Production execution requires an active OS isolation backend. On macOS the
default backend uses ``sandbox-exec`` with a deny-first Seatbelt profile. On
hosts without a supported backend, :meth:`ProcessIsolatedRunner.run` refuses
execution. There is no silent fallback to a normal host subprocess.

An explicitly injected :class:`UnsafeOfflineTestBackend` preserves local unit
and offline tests, but it must also be enabled with ``allow_unsafe_offline`` and
results truthfully report that they were not OS-isolated.

Both paths retain the positive capability boundary:

  - closed tool-id → fixed entrypoint map (unknown tool ids rejected)
  - default map does not include sys.executable
  - python -c / python -m rejected; shell=True never used
  - secrets env vars and stdin are not inherited
  - timeout + output size caps
  - run() accepts only a factory-issued signed capability

AgentCapabilityRouter remains the in-process policy router. The signed
capability envelope is the positive interface any future container/Cloudflare
isolate backend must verify. This module does not claim an isolate where none
is active.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence

from .signed_capability import (
    DEFAULT_AUDIENCE,
    IsolationRejected,
    SignedIsolationCapability,
    issue_isolation_capability,
    verify_isolation_capability,
)

# Closed allowlist. Not sys.executable. Not a shell or HTTP client.
DEFAULT_TOOL_ENTRYPOINTS: Mapping[str, str] = MappingProxyType(
    {
        "true": "/usr/bin/true",
    }
)

_FORBIDDEN_BINARY_NAMES = frozenset(
    {
        "python",
        "python3",
        "sh",
        "bash",
        "zsh",
        "dash",
        "csh",
        "ksh",
        "fish",
        "env",
        "curl",
        "wget",
        "nc",
        "ncat",
        "perl",
        "ruby",
        "node",
        "nodejs",
        "deno",
        "lua",
        "php",
        "osascript",
        "swift",
        "java",
        "jshell",
    }
)

# Env keys never passed into the child.
_SECRET_ENV_PREFIXES = (
    "AWS_",
    "AZURE_",
    "OPENAI_",
    "ANTHROPIC_",
    "JQUANTS_",
    "QUANT_",
    "GITHUB_",
    "INGESTION_",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "API_KEY",
)


@dataclass(frozen=True)
class IsolatedRunResult:
    returncode: int
    stdout: str
    stderr: str
    argv: tuple[str, ...]
    tool_id: str
    backend: str
    os_isolated: bool


class IsolationBackend(Protocol):
    """Trusted launcher abstraction for an OS sandbox or explicit test path."""

    name: str
    is_os_sandbox: bool

    def ensure_active(
        self,
        *,
        env: Mapping[str, str],
        timeout_seconds: float,
    ) -> None:
        """Raise unless the backend can enforce its declared boundary now."""

    def wrap_argv(self, argv: Sequence[str]) -> tuple[str, ...]:
        """Return the trusted launcher argv for one closed tool invocation."""


@dataclass(frozen=True)
class UnsafeOfflineTestBackend:
    """Explicit non-isolating backend for offline tests only.

    This class deliberately does not claim OS isolation. Production callers
    must never opt into it.
    """

    name: str = "unsafe-offline-test"
    is_os_sandbox: bool = False

    def ensure_active(
        self,
        *,
        env: Mapping[str, str],
        timeout_seconds: float,
    ) -> None:
        del env, timeout_seconds

    def wrap_argv(self, argv: Sequence[str]) -> tuple[str, ...]:
        return tuple(argv)


@dataclass(frozen=True)
class MacOSSandboxExecBackend:
    """macOS Seatbelt launcher with network/write/fork default-deny policy."""

    sandbox_exec_path: str = "/usr/bin/sandbox-exec"
    name: str = "macos-sandbox-exec"
    is_os_sandbox: bool = True

    @staticmethod
    def _profile_literal(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def is_available(self) -> bool:
        return (
            sys.platform == "darwin"
            and os.path.isfile(self.sandbox_exec_path)
            and os.access(self.sandbox_exec_path, os.X_OK)
        )

    def profile_for_binary(self, binary: str) -> str:
        """Build a deny-first profile allowing only loader reads and one exec."""
        paths = sorted({binary, os.path.realpath(binary)})
        exec_rules = " ".join(
            f"(literal {self._profile_literal(path)})" for path in paths
        )
        return "\n".join(
            (
                "(version 1)",
                "(deny default)",
                "(deny network*)",
                "(deny process-fork)",
                f"(allow process-exec {exec_rules})",
                "(allow sysctl-read)",
                "(allow file-read*",
                '  (literal "/")',
                *(f"  (literal {self._profile_literal(path)})" for path in paths),
                '  (subpath "/usr/lib")',
                '  (subpath "/System/Library")',
                ")",
            )
        )

    def wrap_argv(self, argv: Sequence[str]) -> tuple[str, ...]:
        if not argv:
            raise IsolationRejected("empty backend argv")
        profile = self.profile_for_binary(str(argv[0]))
        return (self.sandbox_exec_path, "-p", profile, *argv)

    def ensure_active(
        self,
        *,
        env: Mapping[str, str],
        timeout_seconds: float,
    ) -> None:
        if not self.is_available():
            raise IsolationRejected("macOS sandbox-exec backend is unavailable")
        probe_binary = "/usr/bin/true"
        if not os.path.isfile(probe_binary):
            raise IsolationRejected("macOS sandbox activation probe is unavailable")
        probe = (
            self.sandbox_exec_path,
            "-p",
            self.profile_for_binary(probe_binary),
            probe_binary,
        )
        try:
            completed = subprocess.run(
                probe,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=max(0.1, min(float(timeout_seconds), 5.0)),
                env=dict(env),
                stdin=subprocess.DEVNULL,
                close_fds=True,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise IsolationRejected(
                "macOS sandbox backend activation probe failed"
            ) from exc
        if completed.returncode != 0:
            raise IsolationRejected(
                "macOS sandbox backend activation probe failed "
                f"(returncode={completed.returncode})"
            )


def _default_os_isolation_backend() -> IsolationBackend | None:
    backend = MacOSSandboxExecBackend()
    return backend if backend.is_available() else None


def _binary_name(path: str) -> str:
    return Path(path).name.lower()


def _is_python_binary(path: str) -> bool:
    name = _binary_name(path)
    if name.startswith("python"):
        return True
    try:
        if os.path.realpath(path) == os.path.realpath(sys.executable):
            return True
    except OSError:
        pass
    return path == sys.executable


def _is_forbidden_binary(path: str) -> bool:
    if _is_python_binary(path):
        return True
    names = {_binary_name(path)}
    try:
        names.add(_binary_name(os.path.realpath(path)))
    except OSError:
        pass
    return not names.isdisjoint(_FORBIDDEN_BINARY_NAMES)


def _is_secret_env_key(key: str) -> bool:
    upper = key.upper()
    if any(tok in upper for tok in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")):
        return True
    return any(upper.startswith(prefix) for prefix in _SECRET_ENV_PREFIXES)


def validate_isolated_argv(argv: Sequence[str]) -> None:
    """Reject empty/non-string argv, python -c/-m, shells, and metacharacters."""
    if not argv:
        raise IsolationRejected("empty argv")
    if any(not isinstance(a, str) for a in argv):
        raise IsolationRejected("argv must be strings")
    binary = str(argv[0])
    python = _is_python_binary(binary)
    for a in argv[1:]:
        if a == "-c" or a.startswith("-c"):
            raise IsolationRejected("python -c is forbidden")
        if python and (a == "-m" or a.startswith("-m") or a == "-"):
            raise IsolationRejected("python -m is forbidden")
    if _is_forbidden_binary(binary):
        raise IsolationRejected(f"binary not allowlisted: {binary}")
    joined = " ".join(argv)
    for bad in (";", "&&", "||", "|", "`", "$(", "\n"):
        if bad in joined:
            raise IsolationRejected(f"forbidden token in argv: {bad!r}")


class ProcessIsolatedRunner:
    """Closed tool runner that requires real OS isolation in production."""

    def __init__(
        self,
        *,
        tool_entrypoints: Mapping[str, str] | None = None,
        timeout_seconds: float = 30.0,
        max_output_bytes: int = 256_000,
        cwd: str | Path | None = None,
        audience: str = DEFAULT_AUDIENCE,
        plan_hash: str,
        snapshot_hash: str,
        hmac_secret: bytes | None = None,
        backend: IsolationBackend | None = None,
        allow_unsafe_offline: bool = False,
    ) -> None:
        source = (
            tool_entrypoints
            if tool_entrypoints is not None
            else DEFAULT_TOOL_ENTRYPOINTS
        )
        mapping = dict(source)
        if not mapping:
            raise IsolationRejected("tool entrypoint map is empty")
        for tool_id, path in mapping.items():
            if not isinstance(tool_id, str) or not tool_id.strip():
                raise IsolationRejected("invalid tool id")
            if not isinstance(path, str) or not path.startswith("/"):
                raise IsolationRejected(
                    f"entrypoint for {tool_id!r} must be an absolute path"
                )
            if any(ord(char) < 32 for char in path):
                raise IsolationRejected(f"entrypoint for {tool_id!r} is invalid")
            if _is_forbidden_binary(path):
                raise IsolationRejected(f"binary not allowlisted: {path}")
        if tool_entrypoints is None and sys.executable in mapping.values():
            raise IsolationRejected("default tool map must not include sys.executable")
        self._tool_entrypoints = MappingProxyType(mapping)
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.cwd = str(cwd) if cwd else None
        self.audience = str(audience)
        self.plan_hash = str(plan_hash)
        self.snapshot_hash = str(snapshot_hash)
        self._hmac_secret = hmac_secret
        self._backend = (
            backend if backend is not None else _default_os_isolation_backend()
        )
        self._allow_unsafe_offline = bool(allow_unsafe_offline)
        if (
            self._backend is not None
            and not self._backend.is_os_sandbox
            and not self._allow_unsafe_offline
        ):
            raise IsolationRejected(
                "non-isolating backend requires explicit allow_unsafe_offline=True"
            )

    @property
    def allowed_binaries(self) -> frozenset[str]:
        return frozenset(self._tool_entrypoints.values())

    @property
    def tool_entrypoints(self) -> Mapping[str, str]:
        return self._tool_entrypoints

    @property
    def backend_name(self) -> str | None:
        """Configured backend name; availability is verified again on every run."""
        return self._backend.name if self._backend is not None else None

    def _scrub_env(self) -> dict[str, str]:
        clean: dict[str, str] = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "HOME": "/tmp",
        }
        tz = os.environ.get("TZ")
        if tz is not None and not _is_secret_env_key("TZ"):
            clean["TZ"] = tz
        if any(_is_secret_env_key(k) for k in clean):
            raise IsolationRejected("refusing to pass secret-like env into isolate")
        return clean

    def run(
        self,
        tool_id: str,
        args: Sequence[str] = (),
        *,
        capability: object,
    ) -> IsolatedRunResult:
        if not isinstance(tool_id, str) or not tool_id.strip():
            raise IsolationRejected("empty tool id")
        if tool_id not in self._tool_entrypoints:
            raise IsolationRejected(f"unknown tool id: {tool_id}")
        verify_isolation_capability(
            capability,
            audience=self.audience,
            tool_id=tool_id,
            plan_hash=self.plan_hash,
            snapshot_hash=self.snapshot_hash,
            hmac_secret=self._hmac_secret,
        )
        if any(not isinstance(a, str) for a in args):
            raise IsolationRejected("argv must be strings")
        binary = self._tool_entrypoints[tool_id]
        argv = [binary, *args]
        validate_isolated_argv(argv)
        backend = self._backend
        if backend is None:
            raise IsolationRejected(
                "no active OS sandbox backend; production execution denied"
            )
        if not backend.is_os_sandbox and not self._allow_unsafe_offline:
            raise IsolationRejected("non-isolating backend denied")
        clean_env = self._scrub_env()
        backend.ensure_active(
            env=clean_env,
            timeout_seconds=self.timeout_seconds,
        )
        execution_argv = backend.wrap_argv(argv)
        if not execution_argv:
            raise IsolationRejected("isolation backend produced empty argv")
        try:
            completed = subprocess.run(
                list(execution_argv),
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                cwd=self.cwd,
                env=clean_env,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise IsolationRejected(
                f"isolated execution failed or timed out after {self.timeout_seconds}s"
            ) from exc
        stdout = (completed.stdout or "")[: self.max_output_bytes]
        stderr = (completed.stderr or "")[: self.max_output_bytes]
        return IsolatedRunResult(
            returncode=int(completed.returncode),
            stdout=stdout,
            stderr=stderr,
            argv=tuple(argv),
            tool_id=tool_id,
            backend=backend.name,
            os_isolated=backend.is_os_sandbox,
        )


__all__ = [
    "DEFAULT_AUDIENCE",
    "DEFAULT_TOOL_ENTRYPOINTS",
    "IsolationBackend",
    "IsolatedRunResult",
    "IsolationRejected",
    "MacOSSandboxExecBackend",
    "ProcessIsolatedRunner",
    "SignedIsolationCapability",
    "UnsafeOfflineTestBackend",
    "issue_isolation_capability",
    "validate_isolated_argv",
    "verify_isolation_capability",
]
