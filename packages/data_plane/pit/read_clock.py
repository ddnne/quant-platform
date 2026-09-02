"""Closed two-clock PIT read context owned by the snapshot adapter.

Decision visibility is ``event_time`` / ``available_at`` versus ``decision_at``.
Observation visibility is ``ingested_at`` versus the snapshot's immutable
``observed_through``. Callers never supply an arbitrary observation cutoff.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from typing import Any, Iterator
from contextlib import contextmanager

from ingestion.common.timeutil import now_iso

from .errors import InvalidAsOf, PitError
from .query import normalize_as_of

_STATE = threading.local()
DRAFT_OBSERVATION_LABEL = "draft_bind_observation_cutoff"
SNAPSHOT_OBSERVATION_LABEL = "immutable_snapshot_observed_through"


@dataclass(frozen=True, slots=True)
class PitReadClock:
    """Adapter-owned decision and observation cutoffs. Not a caller capability."""

    decision_at: str
    observed_through: str
    observation_label: str
    promotable: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_at", normalize_as_of(self.decision_at))
        object.__setattr__(
            self, "observed_through", normalize_as_of(self.observed_through)
        )
        if not self.observation_label:
            raise PitError("read clock observation label is required")
        if self.promotable and self.observation_label != SNAPSHOT_OBSERVATION_LABEL:
            raise PitError("only an immutable snapshot observation cutoff is promotable")
        if (
            not self.promotable
            and self.observation_label == SNAPSHOT_OBSERVATION_LABEL
        ):
            raise PitError("immutable snapshot observation cutoff cannot be draft")


def _manifest_observed_through(conn: sqlite3.Connection) -> str | None:
    listing = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = 'personal_history_manifest'"
    ).fetchone()
    if listing is None or str(listing[0]) != "table":
        return None
    columns = {
        str(info[1])
        for info in conn.execute("PRAGMA table_info(personal_history_manifest)")
    }
    if "observed_through" not in columns:
        return None
    row = conn.execute(
        "SELECT observed_through FROM personal_history_manifest WHERE singleton = 1"
    ).fetchone()
    if row is None or row[0] is None or not str(row[0]).strip():
        return None
    return str(row[0])


def read_snapshot_observed_through(conn: sqlite3.Connection) -> str | None:
    """Return the immutable snapshot observation cutoff, if the file has one."""

    try:
        return _manifest_observed_through(conn)
    except sqlite3.Error:
        return None


def draft_observation_clock(*, captured_at: str | None = None) -> tuple[str, str]:
    """Label a non-promotable draft bind observation cutoff."""

    stamp = captured_at or now_iso()
    return normalize_as_of(stamp), DRAFT_OBSERVATION_LABEL


def clock_for_decision(
    decision_at: Any,
    *,
    observed_through: str,
    observation_label: str,
    promotable: bool,
) -> PitReadClock:
    return PitReadClock(
        decision_at=normalize_as_of(decision_at),
        observed_through=observed_through,
        observation_label=observation_label,
        promotable=promotable,
    )


def bound_read_clock() -> PitReadClock | None:
    return getattr(_STATE, "clock", None)


@contextmanager
def install_read_clock(clock: PitReadClock) -> Iterator[PitReadClock]:
    previous = getattr(_STATE, "clock", None)
    _STATE.clock = clock
    try:
        yield clock
    finally:
        if previous is None:
            try:
                del _STATE.clock
            except AttributeError:
                pass
        else:
            _STATE.clock = previous


def resolve_read_clock(
    decision_at: Any,
    *,
    observed_through: str | None = None,
    observation_label: str | None = None,
    promotable: bool | None = None,
    conn: sqlite3.Connection | None = None,
) -> PitReadClock:
    """Build a decision clock. Observation cutoff is adapter- or snapshot-owned.

    An explicit ``observed_through`` is only legal from the bound snapshot
    adapter. A caller-supplied cutoff without an adapter label is rejected.
    """

    decision = normalize_as_of(decision_at)
    bound = bound_read_clock()
    if observed_through is not None:
        if observation_label is None:
            raise InvalidAsOf(
                "observed_through is snapshot-owned and cannot be supplied alone"
            )
        return PitReadClock(
            decision_at=decision,
            observed_through=observed_through,
            observation_label=observation_label,
            promotable=bool(promotable),
        )
    if bound is not None:
        return PitReadClock(
            decision_at=decision,
            observed_through=bound.observed_through,
            observation_label=bound.observation_label,
            promotable=bound.promotable,
        )
    if conn is not None:
        stamped = read_snapshot_observed_through(conn)
        if stamped is not None:
            return PitReadClock(
                decision_at=decision,
                observed_through=stamped,
                observation_label=SNAPSHOT_OBSERVATION_LABEL,
                promotable=True,
            )
    raise PitError(
        "PIT observation cutoff is missing; bind a snapshot or draft view"
    )


def visibility_predicates(clock: PitReadClock) -> tuple[list[str], list[str]]:
    """SQL fragments and bound parameters for the two PIT gates."""

    return (
        [
            "event_time IS NOT NULL",
            "event_time <= ?",
            "available_at IS NOT NULL",
            "available_at <= ?",
            "ingested_at IS NOT NULL",
            "ingested_at <= ?",
        ],
        [clock.decision_at, clock.decision_at, clock.observed_through],
    )


__all__ = [
    "DRAFT_OBSERVATION_LABEL",
    "SNAPSHOT_OBSERVATION_LABEL",
    "PitReadClock",
    "bound_read_clock",
    "clock_for_decision",
    "draft_observation_clock",
    "install_read_clock",
    "read_snapshot_observed_through",
    "resolve_read_clock",
    "visibility_predicates",
]
