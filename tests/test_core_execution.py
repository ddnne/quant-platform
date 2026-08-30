"""Execution-mode clocks stay explicit and fill_offset does not imply them."""

from __future__ import annotations

from core.execution import (
    AM_SIGNAL_PM_CLOSE,
    NEXT_CLOSE,
    SAME_DAY_CLOSE,
    get_mode,
    morning_close_as_of,
    operational_usable_by_as_of,
)


def test_am_signal_pm_close_decides_at_1130_and_fills_same_session():
    mode = get_mode("am_signal_pm_close")
    assert mode is AM_SIGNAL_PM_CLOSE
    assert mode.fill_offset == 0
    assert mode.decision_clock == "morning_close"
    assert mode.decision_as_of("2025-04-01") == morning_close_as_of("2025-04-01")
    assert mode.decision_as_of("2025-04-01") == "2025-04-01T11:30:00+09:00"
    assert operational_usable_by_as_of("2025-04-01") == "2025-04-01T12:30:00+09:00"
    assert "information_cutoff D 11:30" in mode.as_of_rule
    assert "operational_usable_by D 12:30" in mode.as_of_rule
    assert operational_usable_by_as_of("2025-04-01") != mode.decision_as_of(
        "2025-04-01"
    )


def test_next_close_and_same_day_close_clocks_unchanged():
    assert NEXT_CLOSE.fill_offset == 1
    assert NEXT_CLOSE.decision_clock == "session_close"
    assert NEXT_CLOSE.decision_as_of("2025-04-01") == "2025-04-01T15:30:00+09:00"
    assert NEXT_CLOSE.decision_as_of("2024-10-31") == "2024-10-31T15:00:00+09:00"

    assert SAME_DAY_CLOSE.fill_offset == 0
    assert SAME_DAY_CLOSE.decision_clock == "session_open"
    assert SAME_DAY_CLOSE.decision_as_of("2025-04-01") == "2025-04-01T09:00:00+09:00"

    # Same fill_offset must not collapse AM onto the open clock.
    assert AM_SIGNAL_PM_CLOSE.fill_offset == SAME_DAY_CLOSE.fill_offset
    assert AM_SIGNAL_PM_CLOSE.decision_as_of("2025-04-01") != (
        SAME_DAY_CLOSE.decision_as_of("2025-04-01")
    )
