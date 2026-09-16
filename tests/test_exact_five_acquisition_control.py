"""Compiler fill -> exact-five Cron control, including a real pre-period month."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ops.exact_five_acquisition_control import (
    ExactFiveAcquisitionControlError,
    build_exact_five_compiled_acquisition_control,
    catalog_collection_window,
    compiled_fill_selectors,
)
from storage.coverage_ledger import declared_coverage_segments

_CONTAINER = (
    Path(__file__).resolve().parents[1]
    / "platform"
    / "workers"
    / "research-mass-eval"
    / "container"
)
if str(_CONTAINER) not in sys.path:
    sys.path.insert(0, str(_CONTAINER))


def test_compiler_control_tick_window_includes_preperiod_and_rejects_unbounded() -> None:
    from receipt_candidate_job import exact_five_acquisition_control_from_selectors

    planned = declared_coverage_segments(
        ("equities_bars_daily",),
        lookback_start="2022-12-24",
        period_start="2023-01-04",
        period_end="2023-01-06",
        selected_event_dates={},
        bar_split_interval_start="2022-10-20",
    )
    fill = compiled_fill_selectors(
        datasets=("equities_bars_daily",),
        lookback_start="2022-12-24",
        period_start="2023-01-04",
        period_end="2023-01-06",
        selected_event_dates={},
        bar_split_interval_start="2022-10-20",
    )
    assert [item.segment_id for item in planned] == [
        "2022-10",
        "2022-11",
        "2022-12",
        "2023-01",
    ]
    assert fill == tuple(
        {"dataset": item.dataset, "segment_id": item.segment_id} for item in planned
    )
    preperiod = next(item for item in fill if item["segment_id"] == "2022-12")
    control = exact_five_acquisition_control_from_selectors((preperiod,))
    assert control["schema"] == "exact-five-compiled-acquisition/v1"
    assert control["jobs"] == [preperiod]
    assert control["profile_id"] == "controlled-pilot/exact-four"
    assert catalog_collection_window("equities_bars_daily", "2022-12") == (
        "2022-12-01",
        "2022-12-31",
    )

    with pytest.raises(ExactFiveAcquisitionControlError, match="catalog bounds"):
        build_exact_five_compiled_acquisition_control(
            ({"dataset": "markets_calendar", "segment_id": "2024-06"},)
        )
    with pytest.raises(ExactFiveAcquisitionControlError, match="catalog month"):
        build_exact_five_compiled_acquisition_control(
            ({"dataset": "markets_calendar", "segment_id": "2022-13"},)
        )
    with pytest.raises(ExactFiveAcquisitionControlError, match="catalog month"):
        build_exact_five_compiled_acquisition_control(
            ({"dataset": "equities_valuation", "segment_id": "2023-01"},)
        )
