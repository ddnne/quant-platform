"""Process-isolation foundation for agents (Phase 6.2.3 §10).

This is NOT yet a production Cloudflare Sandbox/Container. It provides a
restricted subprocess boundary for trusted offline tools with:
  - no inherited secrets env vars (allowlist only)
  - no shell=True
  - timeout + output size caps
  - closed argv (no free-form shell strings)

AgentCapabilityRouter remains the in-process policy router. Real isolate
deployment is a follow-on when LLM tools are connected.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


class IsolationRejected(RuntimeError):
    """Raised when isolation policy forbids an execution."""


@dataclass(frozen=True)
class IsolatedRunResult:
    returncode: int
    stdout: str
    stderr: str
    argv: tuple[str, ...]


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


class ProcessIsolatedRunner:
    """Restricted subprocess runner for closed argv tool invocations."""

    def __init__(
        self,
        *,
        allowed_binaries: Sequence[str] | None = None,
        timeout_seconds: float = 30.0,
        max_output_bytes: int = 256_000,
        cwd: str | Path | None = None,
    ) -> None:
        self.allowed_binaries = frozenset(
            allowed_binaries
            or (
                sys.executable,
                "/usr/bin/true",
                "/bin/true",
            )
        )
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.cwd = str(cwd) if cwd else None

    def _scrub_env(self) -> dict[str, str]:
        clean: dict[str, str] = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "HOME": "/tmp",
        }
        # Optionally keep TZ for determinism of timestamps in tests.
        if "TZ" in os.environ:
            clean["TZ"] = os.environ["TZ"]
        return clean

    def run(self, argv: Sequence[str]) -> IsolatedRunResult:
        if not argv:
            raise IsolationRejected("empty argv")
        binary = str(argv[0])
        if binary not in self.allowed_binaries:
            raise IsolationRejected(f"binary not allowlisted: {binary}")
        if any(not isinstance(a, str) for a in argv):
            raise IsolationRejected("argv must be strings")
        # Forbid shell metacharacters being smuggled as a single shell string.
        joined = " ".join(argv)
        for bad in (";", "&&", "||", "|", "`", "$(", "\n"):
            if bad in joined:
                raise IsolationRejected(f"forbidden token in argv: {bad!r}")
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
        )


__all__ = [
    "IsolatedRunResult",
    "IsolationRejected",
    "ProcessIsolatedRunner",
]
