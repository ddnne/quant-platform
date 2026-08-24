"""Process-isolation foundation for agents (Phase 6.2.3 §10).

This is NOT a production Cloudflare Sandbox/Container. It is a restricted
subprocess boundary for trusted offline tools:

  - closed tool-id → fixed entrypoint map (unknown tool ids rejected)
  - default map does not include sys.executable
  - python -c / python -m rejected; shell=True never used
  - secrets env vars are not inherited
  - timeout + output size caps
  - run() accepts only a factory-issued signed capability

AgentCapabilityRouter remains the in-process policy router. The signed
capability envelope is the same positive interface a future isolate runner
would verify. Real isolate deployment is a follow-on.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

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
    return _binary_name(path) in _FORBIDDEN_BINARY_NAMES


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
    """Restricted subprocess runner keyed by closed tool ids, not free argv."""

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

    @property
    def allowed_binaries(self) -> frozenset[str]:
        return frozenset(self._tool_entrypoints.values())

    @property
    def tool_entrypoints(self) -> Mapping[str, str]:
        return self._tool_entrypoints

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
        try:
            completed = subprocess.run(
                list(argv),
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                cwd=self.cwd,
                env=self._scrub_env(),
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise IsolationRejected(
                f"timeout after {self.timeout_seconds}s"
            ) from exc
        stdout = (completed.stdout or "")[: self.max_output_bytes]
        stderr = (completed.stderr or "")[: self.max_output_bytes]
        return IsolatedRunResult(
            returncode=int(completed.returncode),
            stdout=stdout,
            stderr=stderr,
            argv=tuple(argv),
            tool_id=tool_id,
        )


__all__ = [
    "DEFAULT_AUDIENCE",
    "DEFAULT_TOOL_ENTRYPOINTS",
    "IsolatedRunResult",
    "IsolationRejected",
    "ProcessIsolatedRunner",
    "SignedIsolationCapability",
    "issue_isolation_capability",
    "validate_isolated_argv",
    "verify_isolation_capability",
]
