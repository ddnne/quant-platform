"""Full TSE cash-equity sessions, distinct from scheduled business dates.

Keep the provider calendar and its provenance unchanged. Only an explicitly
documented whole-market halt can remove a scheduled session; absent price rows
alone must never classify a day as closed. This does not describe derivatives,
settlement/master publication dates, or half-day AM-only sessions.
"""

# TSE halted all securities for the whole day (announced before the AM cutoff).
# https://www.jpx.co.jp/news/1030/20201001-04.html
_TSE_FULL_DAY_HALTS = frozenset({"2020-10-01"})


def is_tse_full_session(day: str, holiday_division: str | None) -> bool:
    return holiday_division == "1" and day not in _TSE_FULL_DAY_HALTS
