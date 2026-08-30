"""Execution-mode definitions for the core engine.

An execution mode fixes two things per decision trading day *D*:

1. The **decision ``as_of``** — the PIT instant whose information set the
   strategy may consult to generate signals on *D*.
2. The **fill** — which session's close the resulting orders transact at, and
   therefore whether a fill can ever coincide with the signal day.

The two implemented modes are deliberately conservative about look-ahead:

* :data:`NEXT_CLOSE` — decide at *D*'s session close, fill at the **next**
  trading day's close. A signal on *D* can never fill on *D*, so even if the
  strategy sees *D*'s close (when the source published it by the close), it
  cannot trade on it same-session.
* :data:`SAME_DAY_CLOSE` — decide at *D*'s session **open** (09:00 JST, before
  the close is known) and fill at *D*'s close. The decision information set
  excludes *D*'s close by construction, so filling at *D*'s close is not
  look-ahead. Use this only when you accept intraday decision timing.
* :data:`AM_SIGNAL_PM_CLOSE` — decide at *D*'s morning close (11:30 JST) and
  fill at *D*'s afternoon adjusted close. Personal-retrospective DRAFT only.
  The decision clock is explicit; it is not inferred from ``fill_offset``.

The close time follows the Tokyo Stock Exchange's 2024-11-05 change
(15:00 -> 15:30 JST), matching ``ingestion.jquants.normalize``.
"""

from __future__ import annotations

from dataclasses import dataclass

# TSE shortened its lunch break on this date; the close moved 15:00 -> 15:30.
# Kept in sync with ingestion.jquants.normalize.CLOSE_CHANGE_DATE.
_CLOSE_CHANGE_DATE = "2024-11-05"


def close_time(date: str) -> str:
    """Session-close ``HH:MM`` for a ``YYYY-MM-DD`` date (JST)."""
    return "15:30" if date >= _CLOSE_CHANGE_DATE else "15:00"


def close_as_of(date: str) -> str:
    """PIT ``as_of`` for *D*'s session close (canonical JST ISO)."""
    return f"{date}T{close_time(date)}:00+09:00"


def open_as_of(date: str) -> str:
    """PIT ``as_of`` for *D*'s session open (09:00 JST) — before the close."""
    return f"{date}T09:00:00+09:00"


def morning_close_as_of(date: str) -> str:
    """Non-price decision cutoff for *D*'s morning close (11:30 JST)."""
    return f"{date}T11:30:00+09:00"


def operational_usable_by_as_of(date: str) -> str:
    """Operational acquisition deadline for *D* (12:30 JST).

    This is not a PIT information cutoff. Non-price facts remain gated at
    :func:`morning_close_as_of` (11:30 JST).
    """
    return f"{date}T12:30:00+09:00"


_DECISION_CLOCKS = {
    "session_close": close_as_of,
    "session_open": open_as_of,
    "morning_close": morning_close_as_of,
}


@dataclass(frozen=True)
class ExecutionMode:
    """One execution mode: how decisions map to a decision ``as_of`` and fill.

    ``decision_clock`` is the explicit decision instant (session close, session
    open, or morning close). ``fill_offset`` is how many trading days after
    the decision the fill happens (1 = next session, 0 = same session). The
    engine uses ``fill_offset`` to decide whether to apply an order
    immediately (same-day) or defer it to the next iteration (next-close).
    The decision clock is never inferred from ``fill_offset``.
    """

    name: str
    fill_offset: int
    as_of_rule: str
    decision_clock: str

    def decision_as_of(self, date: str) -> str:
        try:
            clock = _DECISION_CLOCKS[self.decision_clock]
        except KeyError as exc:  # pragma: no cover - modes are closed
            raise ValueError(
                f"unknown decision_clock {self.decision_clock!r}"
            ) from exc
        return clock(date)


NEXT_CLOSE = ExecutionMode(
    name="next_close",
    fill_offset=1,
    decision_clock="session_close",
    as_of_rule=(
        "decision at session close JST (15:30 from 2024-11-05, else 15:00); "
        "orders fill at the NEXT trading day's session close"
    ),
)

SAME_DAY_CLOSE = ExecutionMode(
    name="same_day_close",
    fill_offset=0,
    decision_clock="session_open",
    as_of_rule=(
        "decision at session open 09:00 JST (excludes the session close); "
        "orders fill at the SAME session's close"
    ),
)

AM_SIGNAL_PM_CLOSE = ExecutionMode(
    name="am_signal_pm_close",
    fill_offset=0,
    decision_clock="morning_close",
    as_of_rule=(
        "information_cutoff D 11:30 JST (non-price PIT); "
        "operational_usable_by D 12:30 JST does not extend the non-price cutoff; "
        "D signal sees prior PIT-visible full daily rows plus a D synthetic "
        "morning-only row (adjustment_close=MAdjC); orders fill the same "
        "session at D afternoon adjustment close (AAdjC); DRAFT personal "
        "retrospective field-time reconstruction, not an 11:30 publication claim; "
        "target shares are sized from D morning prices and realized weights "
        "may drift by the PM close"
    ),
)

MODES: dict[str, ExecutionMode] = {
    NEXT_CLOSE.name: NEXT_CLOSE,
    SAME_DAY_CLOSE.name: SAME_DAY_CLOSE,
    AM_SIGNAL_PM_CLOSE.name: AM_SIGNAL_PM_CLOSE,
}


def get_mode(name: str) -> ExecutionMode:
    """Resolve an execution mode by name (raises ``ValueError`` if unknown)."""
    try:
        return MODES[name]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(
            f"unknown execution_mode {name!r}; choose one of {sorted(MODES)}"
        ) from exc
