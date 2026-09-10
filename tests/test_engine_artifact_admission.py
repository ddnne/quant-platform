"""Historic AM+gross-cap PM-resize artifacts fail closed at selection."""

from __future__ import annotations

import pytest

from selection.engine_artifact_admission import (
    AM_PM_GROSS_CAP_PM_RESIZE_REASON,
    admit_engine_artifact_for_selection,
    is_am_gross_cap_pm_resize_artifact,
)


@pytest.mark.parametrize(
    ("payload", "affected"),
    [
        (
            {
                "execution_mode": "am_signal_pm_close",
                "core_engine_version": "0.8.0",
                "max_gross_weight_limit": 0.5,
            },
            True,
        ),
        (
            {
                "execution_mode": "am_signal_pm_close",
                "weight_sizing_rule": "realized_pm_gross_capped_at_max_gross_weight",
            },
            True,
        ),
        (
            {
                "execution_mode": "am_signal_pm_close",
                "max_gross_weight_limit": 0.5,
            },
            True,
        ),
        (
            {
                "execution_mode": "am_signal_pm_close",
                "core_engine_version": "0.9.0",
                "am_order_batch_policy": "am_frozen_order_batch/v1",
                "max_gross_weight_limit": 0.5,
            },
            False,
        ),
        (
            {
                "execution_mode": "am_signal_pm_close",
                "core_engine_version": "0.8.0",
            },
            False,
        ),
        (
            {
                "execution_mode": "next_close",
                "core_engine_version": "0.8.0",
                "max_gross_weight_limit": 0.5,
            },
            False,
        ),
    ],
)
def test_am_gross_cap_pm_resize_invalidation(payload: dict, affected: bool) -> None:
    assert is_am_gross_cap_pm_resize_artifact(payload) is affected
    admitted, reasons = admit_engine_artifact_for_selection(payload)
    assert admitted is (not affected)
    if affected:
        assert reasons == (AM_PM_GROSS_CAP_PM_RESIZE_REASON,)
    else:
        assert reasons == ()
