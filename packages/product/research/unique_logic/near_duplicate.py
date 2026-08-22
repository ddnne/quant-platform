"""Near-duplicate / gate-soup audit. Park permutations. Not GO."""
from __future__ import annotations

NEAR_DUPLICATE_GROUPS: tuple[dict[str, object], ...] = (
    {
        "group_id": "event_weekday_skip",
        "keep": "event_skip_monday",
        "park": ("event_skip_tuesday", "event_skip_wednesday"),
        "reason": "weekday-skip permutation of Monday-gap PEAD",
    },
    {
        "group_id": "event_calendar_window",
        "keep": "event_first_half_month",
        "park": ("event_not_last_week", "event_month_start7", "event_not_first_week"),
        "reason": "month-window permutation of first-half PEAD",
    },
    {
        "group_id": "event_afterclose_calendar",
        "keep": "event_afterclose_skip_monday",
        "park": ("event_afterclose_skip_friday", "event_afterclose_not_last_week"),
        "reason": "afterclose × weekday permutation",
    },
    {
        "group_id": "event_easing_weekday",
        "keep": "event_skip_monday_easing",
        "park": ("event_easing_skip_tuesday", "event_easy_skip_tuesday"),
        "reason": "easing × weekday permutation",
    },
    {
        "group_id": "event_uncrowded_weekday",
        "keep": "event_skip_monday_uncrowded",
        "park": ("event_uncrowded_skip_friday",),
        "reason": "uncrowded × weekday permutation",
    },
    {
        "group_id": "surprise_calendar",
        "keep": "surprise_xs_skip_monday",
        "park": (
            "surprise_xs_skip_tuesday",
            "surprise_xs_not_last_week",
            "surprise_xs_month_start7",
            "surprise_xs_not_first_week",
        ),
        "reason": "surprise calendar permutation of skip_monday",
    },
    {
        "group_id": "surprise_easing_weekday",
        "keep": "surprise_xs_easing_change",
        "park": ("surprise_xs_easing_skip_friday",),
        "reason": "surprise easing × weekday permutation",
    },
    {
        "group_id": "surprise_afterclose_weekday",
        "keep": "surprise_xs_afterclose",
        "park": ("surprise_xs_afterclose_skip_friday",),
        "reason": "surprise afterclose × weekday permutation",
    },
    {
        "group_id": "cs_weekday_skip",
        "keep": "cs_skip_monday",
        "park": (
            "cs_skip_tuesday",
            "cs_skip_wednesday",
            "cs_not_last_week",
            "cs_month_start7",
            "cs_not_first_week",
        ),
        "reason": "CS weekday/calendar permutation of skip_monday",
    },
    {
        "group_id": "cs_easy_weekday",
        "keep": "cs_easy_skip_monday",
        "park": ("cs_easy_skip_friday",),
        "reason": "easy-overnight × weekday permutation",
    },
    {
        "group_id": "cs_overnight_down_weekday",
        "keep": "overnight_down_skip_monday_cs",
        "park": ("overnight_down_skip_tuesday_cs",),
        "reason": "overnight-down × weekday permutation",
    },
)

NEAR_DUPLICATE_PARK: frozenset[str] = frozenset(
    lid
    for g in NEAR_DUPLICATE_GROUPS
    for lid in tuple(g.get("park") or ())  # type: ignore[union-attr]
)


def is_near_duplicate(logic_id: str) -> bool:
    return str(logic_id) in NEAR_DUPLICATE_PARK
