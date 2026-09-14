"""Closed two-clock PIT read context owned by the snapshot adapter.

Decision visibility is ``event_time`` / ``available_at`` versus ``decision_at``.
Observation visibility is ``ingested_at`` versus the snapshot's immutable
``observed_through``. This module also owns canonical ``as_of`` and the default
structured DB path used by those reads. Callers never supply an arbitrary
observation cutoff.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from contextlib import contextmanager

from ingestion.common.timeutil import ensure_jst, now_iso, now_jst, parse_dt, to_iso

from .errors import AsOfRequired, InvalidAsOf, PitError

_NOT_GIVEN: Any = object()
DEFAULT_DB_PATH = Path("data/structured/ingestion.sqlite")
MAX_SNAPSHOT_CLOCK_FUTURE_SKEW = timedelta(minutes=5)

_STATE = threading.local()
DRAFT_OBSERVATION_LABEL = "draft_bind_observation_cutoff"
SNAPSHOT_OBSERVATION_LABEL = "immutable_snapshot_observed_through"


def normalize_as_of(as_of: Any = _NOT_GIVEN) -> str:
    """Return a canonical JST ISO string for ``as_of``, or raise.

    * missing (sentinel) / ``None`` / empty string -> :class:`AsOfRequired`
      (PIT has **no** "latest" default).
    * unparseable -> :class:`InvalidAsOf`.

    Accepts ISO-8601 strings, aware or naive :class:`~datetime.datetime`
    (naive assumed JST), and :class:`~datetime.date` (JST midnight). The
    result is seconds-precision ``+09:00`` — the same canonical form
    ``available_at`` is stored in (see
    :func:`ingestion.common.available_at.validate_available_at`) — so the two
    compare correctly as ISO strings in SQL.
    """
    if as_of is None or as_of is _NOT_GIVEN:
        raise AsOfRequired(
            "as_of is required (PIT has no 'latest' default); pass an explicit "
            "Asia/Tokyo instant, e.g. as_of='2025-04-01T00:00:00+09:00'."
        )
    if isinstance(as_of, datetime):
        return to_iso(ensure_jst(as_of))
    if isinstance(as_of, date):  # datetime is a subclass of date — checked above
        return to_iso(ensure_jst(datetime(as_of.year, as_of.month, as_of.day)))
    if isinstance(as_of, str):
        s = as_of.strip()
        if not s:
            raise AsOfRequired("as_of is required (an empty string is not allowed).")
        try:
            return to_iso(parse_dt(s))
        except ValueError as exc:
            raise InvalidAsOf(
                f"as_of {as_of!r} is not a valid ISO-8601 instant: {exc}"
            ) from exc
    raise InvalidAsOf(
        f"as_of unsupported type {type(as_of).__name__!r}; "
        "expected str / datetime / date."
    )


def resolve_db_path(db_path: Any) -> Path:
    """Resolved DB path: explicit override or :data:`DEFAULT_DB_PATH`."""
    return Path(db_path) if db_path is not None else DEFAULT_DB_PATH


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
        listing = conn.execute(
            "SELECT type FROM sqlite_master "
            "WHERE name = 'snapshot_observation_clock'"
        ).fetchone()
        if listing is not None:
            if str(listing[0]) != "table":
                raise PitError("snapshot observation clock is not a table")
            rows = conn.execute(
                "SELECT observed_through FROM snapshot_observation_clock"
            ).fetchall()
            if len(rows) != 1 or rows[0][0] is None or not str(rows[0][0]).strip():
                raise PitError("snapshot observation clock is not a valid singleton")
            return str(rows[0][0])
        return _manifest_observed_through(conn)
    except sqlite3.Error as exc:
        raise PitError("snapshot observation clock is unreadable") from exc


SNAPSHOT_OBSERVATION_CLOCK_DDL = """
CREATE TABLE snapshot_observation_clock (
    singleton INTEGER NOT NULL PRIMARY KEY CHECK (singleton = 1),
    observed_through TEXT NOT NULL CHECK (length(observed_through) >= 25)
)
"""


def write_publisher_owned_snapshot_observation_clock(
    conn: sqlite3.Connection, observed_through: str
) -> str:
    """Write exactly one publisher-owned snapshot observation clock row."""

    if type(conn) is not sqlite3.Connection:
        raise PitError("snapshot observation clock requires sqlite3.Connection")
    canonical = normalize_as_of(observed_through)
    if type(observed_through) is not str or observed_through != canonical:
        raise PitError("snapshot observation clock is noncanonical")
    if parse_dt(canonical) - now_jst() > MAX_SNAPSHOT_CLOCK_FUTURE_SKEW:
        raise PitError("snapshot observation clock is in the future")
    conn.execute("DROP TABLE IF EXISTS snapshot_observation_clock")
    conn.execute(SNAPSHOT_OBSERVATION_CLOCK_DDL)
    conn.execute(
        "INSERT INTO snapshot_observation_clock(singleton, observed_through) "
        "VALUES (1, ?)",
        (canonical,),
    )
    rows = conn.execute(
        "SELECT observed_through FROM snapshot_observation_clock"
    ).fetchall()
    if len(rows) != 1 or str(rows[0][0]) != canonical:
        raise PitError("publisher observation clock is not a singleton")
    return canonical


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
    "DEFAULT_DB_PATH",
    "DRAFT_OBSERVATION_LABEL",
    "MAX_SNAPSHOT_CLOCK_FUTURE_SKEW",
    "SNAPSHOT_OBSERVATION_LABEL",
    "PitReadClock",
    "normalize_as_of",
    "resolve_db_path",
    "bound_read_clock",
    "clock_for_decision",
    "draft_observation_clock",
    "install_read_clock",
    "read_snapshot_observed_through",
    "resolve_read_clock",
    "visibility_predicates",
    "write_publisher_owned_snapshot_observation_clock",
]
