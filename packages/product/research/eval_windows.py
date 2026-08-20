"""Shared honest multi-year eval windows (not per-wave copies).

These shards match the local COMPLETE-backed bar mirrors used since W98/W99.
Contiguous 3y files are absent; occupancy of a window is the stitch of shards.

Do not fork a new window list in ``scripts/run_wNN_*.py``.
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

# Backward alias used by W99–W107 scripts.
W99_WINDOWS = HONEST_3Y_WINDOWS

FROZEN_PIN_SNAPSHOT: tuple[tuple[str, int, int | None, str], ...] = (
    ("cross_section_hold_10", 10, 5, "KEEP"),
    ("cross_section_hold_10_mom3", 10, 3, "PROMOTE"),
    ("fundamentals_hold_10", 10, 10, "KEEP"),
)
