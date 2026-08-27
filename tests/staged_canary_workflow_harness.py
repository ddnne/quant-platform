"""Test-only access to the sealed staged-canary closure.

Production has no factory, backend selector, callback, or completion primitive.
Tests deliberately use Python closure reflection here, outside the product
package, to exercise the exact captured lease/start/commit functions without
adding an injectable production surface.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SealedCanaryWorkflowHarness:
    acquire: Callable[..., Any]
    start: Callable[..., Any]
    commit: Callable[..., Any]
    fail: Callable[..., Any]

    @classmethod
    def from_sealed_run(
        cls, sealed_run: Callable[..., Any]
    ) -> SealedCanaryWorkflowHarness:
        cells = sealed_run.__closure__
        if cells is None:
            raise AssertionError("production run is not closure sealed")
        captured = dict(zip(sealed_run.__code__.co_freevars, cells, strict=True))
        expected = {
            "acquire",
            "commit",
            "exact_uid_runner",
            "fail",
            "protected_binding_check",
            "root_check",
            "start",
        }
        if set(captured) != expected:
            raise AssertionError("sealed production workflow capture drifted")
        return cls(
            acquire=captured["acquire"].cell_contents,
            start=captured["start"].cell_contents,
            commit=captured["commit"].cell_contents,
            fail=captured["fail"].cell_contents,
        )

    def run(
        self,
        *,
        authority_id: str,
        environment: str,
        exact_runner: Callable[[Mapping[str, Any]], bytes],
    ) -> tuple[str, Mapping[str, Any]]:
        canary_id, token, challenge, prior = self.acquire(
            authority_id=authority_id,
            environment=environment,
        )
        if not token:
            return canary_id, prior
        try:
            self.start(canary_id=canary_id, token=token)
            raw = exact_runner(challenge)
            result = self.commit(
                canary_id=canary_id,
                token=token,
                challenge=challenge,
                runner_output=raw,
            )
        except BaseException as exc:
            self.fail(
                canary_id=canary_id,
                token=token,
                failure_class=type(exc).__name__,
            )
            raise
        return canary_id, result
