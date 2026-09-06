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
        lambda _view: _bundle(),
    )
    monkeypatch.setattr(thicken, "_require_view", lambda value: value)

    attached = thicken.attach_opt225_regime(object())

    assert attached["opt225_regime"]["source"] == {
        "dataset": DATASET_ID,
        "version": OPTIONS_225_VOL_SERIES_VERSION,
    }


def test_attach_opt225_regime_rejects_noncanonical_source(monkeypatch) -> None:
    monkeypatch.setattr(
        thicken,
        "load_opt225_regime_bundle_for_eval",
        lambda _view: _bundle(dataset="derivatives_bars_daily_single_stock_options"),
    )
    monkeypatch.setattr(thicken, "_require_view", lambda value: value)

    attached = thicken.attach_opt225_regime(object())

    assert "opt225_regime" not in attached
    assert attached == {"opt225_error": "options_225 source identity mismatch"}


def test_attach_nky_proxy_binds_topix_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        thicken,
        "load_nky_vol_series_from_sqlite",
        lambda *_args, **_kwargs: {
            "closes_by_date": {
                "2022-12-30": 1_890.0,
                "2023-01-04": 1_900.0,
            },
            "rv_short_by_date": {"2023-01-04": 0.15},
            "rv_long_by_date": {"2023-01-04": 0.12},
            "rv_abs_by_date": {"2023-01-04": 0.15},
            "rv_ratio_by_date": {"2023-01-04": 1.25},
        },
    )
    bars: dict[str, list[list[Any]]] = {}

    view = object()
    monkeypatch.setattr(thicken, "_require_view", lambda value: value)
    attached = thicken.attach_nky_proxy(
        bars,
        {"period_start": "2023-01-04", "period_end": "2023-01-31"},
        view,
    )

    assert bars["__NKY_PROXY__"] == [
        ["2022-12-30", 1_890.0],
        ["2023-01-04", 1_900.0],
    ]
    assert attached["index_proxy"] == {
        "dataset": "indices_bars_daily_topix",
        "label": "TOPIX",
        "role": "nky_vol_proxy_compare_only",
        "note": (
            "TOPIX closes staged as __NKY_PROXY__ for beta and realized-vol "
            "comparisons only. Nikkei 225 option volatility remains the "
            "canonical volatility signal."
        ),
    }
