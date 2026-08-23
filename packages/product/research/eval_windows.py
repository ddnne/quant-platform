"""Shared honest multi-year eval windows.

Shards match COMPLETE-backed bar mirrors. Occupancy is the stitch of shards.
Do not fork a new window list.
"""
from __future__ import annotations

from typing import Any

HONEST_3Y_WINDOWS: tuple[dict[str, Any], ...] = (
    {
        "window_id": "w2017_2019",
        "label": "2017–2019",
        "data_note": "2018 mirror absent; y2017_q4 + y2019_full",
        "shards": (
            {
                "period_id": "y2017_q4",
                "year": 2017,
                "period_start": "2017-09-01",
                "period_end": "2017-12-29",
                "window_kind": "q4",
            },
            {
                "period_id": "y2019_full",
                "year": 2019,
                "period_start": "2019-01-04",
                "period_end": "2019-10-18",
                "window_kind": "full_prefer",
            },
        ),
    },
    {
        "window_id": "w2020_2022",
        "label": "2020–2022",
        "data_note": "2020/2022 mirrors absent; y2021_full only",
        "shards": (
            {
                "period_id": "y2021_full",
                "year": 2021,
                "period_start": "2021-01-04",
                "period_end": "2021-10-15",
                "window_kind": "full_prefer",
            },
        ),
    },
    {
        "window_id": "w2023_2025",
        "label": "2023–2025",
        "data_note": "2024 mirror absent; y2023_full + y2025_q4",
        "shards": (
            {
                "period_id": "y2023_full",
                "year": 2023,
                "period_start": "2023-01-04",
                "period_end": "2023-10-13",
                "window_kind": "full_prefer",
            },
            {
                "period_id": "y2025_q4",
                "year": 2025,
                "period_start": "2025-09-01",
                "period_end": "2025-12-29",
                "window_kind": "q4",
            },
        ),
    },
)

# Full-prefer 2015/19/21/23; Q4 2017/2025.
DEFAULT_REAL_MULTIYEAR_PERIODS: tuple[dict[str, Any], ...] = (
    {
        "period_id": "y2015_full",
        "year": 2015,
        "period_start": "2015-01-05",
        "period_end": "2015-10-21",
        "window_kind": "full_prefer",
    },
    {
        "period_id": "y2017_q4",
        "year": 2017,
        "period_start": "2017-09-01",
        "period_end": "2017-12-29",
        "window_kind": "q4",
    },
    {
        "period_id": "y2019_full",
        "year": 2019,
        "period_start": "2019-01-04",
        "period_end": "2019-10-18",
        "window_kind": "full_prefer",
    },
    {
        "period_id": "y2021_full",
        "year": 2021,
        "period_start": "2021-01-04",
        "period_end": "2021-10-15",
        "window_kind": "full_prefer",
    },
    {
        "period_id": "y2023_full",
        "year": 2023,
        "period_start": "2023-01-04",
        "period_end": "2023-10-13",
        "window_kind": "full_prefer",
    },
    {
        "period_id": "y2025_q4",
        "year": 2025,
        "period_start": "2025-09-01",
        "period_end": "2025-12-29",
        "window_kind": "q4",
    },
)

DEFAULT_PERIODS = DEFAULT_REAL_MULTIYEAR_PERIODS


def honest_window_ids() -> frozenset[str]:
    """HONEST 3y window_ids plus their shard period_ids. Do not fork."""
    out: set[str] = set()
    for w in HONEST_3Y_WINDOWS:
        out.add(str(w["window_id"]))
        for shard in w.get("shards") or ():
            pid = shard.get("period_id") if isinstance(shard, dict) else None
            if pid:
                out.add(str(pid))
    return frozenset(out)

# Legacy Q4-only periods for regression compare.
DEFAULT_PERIODS_Q4: tuple[dict[str, Any], ...] = (
    {"period_id": "y2015_q4", "year": 2015, "period_start": "2015-09-01", "period_end": "2015-12-29"},
    {"period_id": "y2017_q4", "year": 2017, "period_start": "2017-09-01", "period_end": "2017-12-29"},
    {"period_id": "y2019_q4", "year": 2019, "period_start": "2019-09-01", "period_end": "2019-12-29"},
    {"period_id": "y2021_q4", "year": 2021, "period_start": "2021-09-01", "period_end": "2021-12-29"},
    {"period_id": "y2023_q4", "year": 2023, "period_start": "2023-09-01", "period_end": "2023-12-29"},
    {"period_id": "y2025_q4", "year": 2025, "period_start": "2025-09-01", "period_end": "2025-12-29"},
)

