"""Test-only Controlled runtime incapable of satisfying the live loader."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Callable, Mapping

from execution.controlled_execution_runtime_v2 import ControlledExecutionRuntimeV2


class _TestAttempt:
    def __init__(
        self,
        executor: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        context: Mapping[str, Any],
        settlements: list[str],
        snapshot_failure_check: int | None,
    ) -> None:
        self._executor = executor
        self._context = MappingProxyType(dict(context))
        self._settlements = settlements
        self._snapshot_failure_check = snapshot_failure_check
        self._invoked = False
        self.snapshot_reverification_count = 0

    @property
    def context(self) -> Mapping[str, Any]:
        return self._context

    def invoke(self) -> Mapping[str, Any]:
        if self._invoked:
            raise RuntimeError("test Controlled provider called more than once")
        self._invoked = True
        return self._executor(self._context)

    def reverify_snapshot(self) -> None:
        if not self._invoked:
            raise RuntimeError("test snapshot reverified before provider call")
        self.snapshot_reverification_count += 1
        if self.snapshot_reverification_count == self._snapshot_failure_check:
            raise RuntimeError("test pinned snapshot drifted")

    def settle(self, *, outcome: str, error: BaseException | None = None) -> None:
        del error
        self._settlements.append(outcome)


class TestControlledExecutionRuntimeV2(ControlledExecutionRuntimeV2):
    """Test distribution only; live activation requires the exact base type."""

    __test__ = False
    __slots__ = (
        "_executor",
        "_snapshot_failure_check",
        "settlements",
        "attempts",
    )

    def __init__(
        self,
        executor: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        *,
        snapshot_failure_check: int | None = None,
    ) -> None:
        self._executor = executor
        self._snapshot_failure_check = snapshot_failure_check
        self.settlements: list[str] = []
        self.attempts: list[_TestAttempt] = []

    def begin(self, context: Mapping[str, Any]) -> _TestAttempt:
        attempt = _TestAttempt(
            self._executor,
            context,
            self.settlements,
            self._snapshot_failure_check,
        )
        self.attempts.append(attempt)
        return attempt


def make_test_controlled_execution_runtime(
    executor: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    *,
    snapshot_failure_check: int | None = None,
) -> TestControlledExecutionRuntimeV2:
    return TestControlledExecutionRuntimeV2(
        executor,
        snapshot_failure_check=snapshot_failure_check,
    )


__all__ = ["make_test_controlled_execution_runtime"]
