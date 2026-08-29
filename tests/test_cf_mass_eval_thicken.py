from __future__ import annotations

from typing import Any

import research.cf_mass_eval_thicken as thicken
from research.options_225_vol_series import (
    DATASET_ID,
    OPTIONS_225_VOL_SERIES_VERSION,
)


def _bundle(
    *,
    dataset: str = DATASET_ID,
    version: str = OPTIONS_225_VOL_SERIES_VERSION,
) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "version": version,
        "basevol": {
            "rv_abs_by_date": {"2023-01-04": 20.0},
            "rv_short_by_date": {"2023-01-04": 20.0},
            "rv_long_by_date": {"2023-01-04": 19.0},
            "rv_ratio_by_date": {"2023-01-04": 20.0 / 19.0},
        },
    }


def test_attach_opt225_regime_preserves_canonical_source_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        thicken,
        "load_opt225_regime_bundle_for_eval",
        lambda: _bundle(),
    )

    attached = thicken.attach_opt225_regime()

    assert attached["opt225_regime"]["source"] == {
        "dataset": DATASET_ID,
        "version": OPTIONS_225_VOL_SERIES_VERSION,
    }


def test_attach_opt225_regime_rejects_noncanonical_source(monkeypatch) -> None:
    monkeypatch.setattr(
        thicken,
        "load_opt225_regime_bundle_for_eval",
        lambda: _bundle(dataset="derivatives_bars_daily_single_stock_options"),
    )

    attached = thicken.attach_opt225_regime()

    assert "opt225_regime" not in attached
    assert attached == {"opt225_error": "options_225 source identity mismatch"}
