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


@dataclass(frozen=True)
class ExecutionMode:
    """One execution mode: how decisions map to a decision ``as_of`` and fill.

    ``decision_as_of(date)`` is the PIT instant for the signal; ``fill_offset``
    is how many trading days after the decision the fill happens (1 = next
    session, 0 = same session). The engine uses ``fill_offset`` to decide
    whether to apply an order immediately (same-day) or defer it to the next
    iteration (next-close).
    """

    name: str
    fill_offset: int
    as_of_rule: str

    def decision_as_of(self, date: str) -> str:
        if self.fill_offset == 0:
            return open_as_of(date)
        return close_as_of(date)


NEXT_CLOSE = ExecutionMode(
    name="next_close",
    fill_offset=1,
    as_of_rule=(
        "decision at session close JST (15:30 from 2024-11-05, else 15:00); "
        "orders fill at the NEXT trading day's session close"
    ),
)

SAME_DAY_CLOSE = ExecutionMode(
    name="same_day_close",
    fill_offset=0,
    as_of_rule=(
        "decision at session open 09:00 JST (excludes the session close); "
        "orders fill at the SAME session's close"
    ),
)

MODES: dict[str, ExecutionMode] = {
    NEXT_CLOSE.name: NEXT_CLOSE,
    SAME_DAY_CLOSE.name: SAME_DAY_CLOSE,
}


def get_mode(name: str) -> ExecutionMode:
    """Resolve an execution mode by name (raises ``ValueError`` if unknown)."""
    try:
        return MODES[name]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(
            f"unknown execution_mode {name!r}; choose one of {sorted(MODES)}"
        ) from exc
