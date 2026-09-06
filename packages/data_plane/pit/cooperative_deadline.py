"""Cooperative computation deadline. Not a thread killer and not a subprocess."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import monotonic
from typing import Any


class DeadlineExceeded(RuntimeError):
    """The computation must stop. No further reads or writes are allowed."""


_STATE = threading.local()


@dataclass
class CooperativeDeadline:
    """One injectable monotonic deadline plus an explicit cancel flag."""

    deadline_monotonic: float | None = None
    clock: Callable[[], float] = monotonic
    cancelled: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> None:
        self.cancelled.set()

    def expired(self) -> bool:
        if self.cancelled.is_set():
            return True
        if (
            self.deadline_monotonic is not None
            and self.clock() >= self.deadline_monotonic
        ):
            self.cancelled.set()
            return True
        return False

    def check(self) -> None:
        if self.expired():
            raise DeadlineExceeded("personal research deadline cancelled")


def bound_deadline() -> CooperativeDeadline | None:
    return getattr(_STATE, "deadline", None)


def check_deadline() -> None:
    deadline = bound_deadline()
    if deadline is not None:
        deadline.check()


class _NestedDeadline:
    """Child deadline cannot relax a parent absolute lifetime."""

    __slots__ = ("inner", "parent")

    def __init__(self, inner: CooperativeDeadline, parent: CooperativeDeadline) -> None:
        self.inner = inner
        self.parent = parent

    def cancel(self) -> None:
        self.inner.cancel()
        self.parent.cancel()

    def expired(self) -> bool:
        return self.parent.expired() or self.inner.expired()

    def check(self) -> None:
        if self.expired():
            raise DeadlineExceeded("personal research deadline cancelled")


@contextmanager
def install_deadline(deadline: CooperativeDeadline | None) -> Iterator[None]:
    previous = getattr(_STATE, "deadline", None)
    if deadline is None:
        yield
        return
    installed: Any = deadline
    if previous is not None:
        parent = previous.parent if isinstance(previous, _NestedDeadline) else previous
        installed = _NestedDeadline(deadline, parent)
    _STATE.deadline = installed
    try:
        if hasattr(installed, "check"):
            installed.check()
        else:
            deadline.check()
        yield
    finally:
        if previous is None:
            try:
                del _STATE.deadline
            except AttributeError:
                pass
        else:
            _STATE.deadline = previous


__all__ = [
    "CooperativeDeadline",
    "DeadlineExceeded",
    "bound_deadline",
    "check_deadline",
    "install_deadline",
]
