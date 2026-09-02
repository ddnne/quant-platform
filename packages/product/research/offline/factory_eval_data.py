"""Cached factory batch panels (not GO / READY).

``BatchDataContext`` / loaders for fail-fast eval. Eval stays in
``research.offline.factory_eval``; screen policy in
``research.offline.factory_eval_screen``. Unique/combo generation_enabled stays False.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass
class BatchDataContext:
    """Cached offline panels for fail-fast batch eval."""

    periods: list[dict[str, Any]]
    panels: list[dict[str, Any]]
    one_way_cost: float
    load_notes: dict[str, Any] = field(default_factory=dict)


def load_batch_data_context(
    config: MassFactoryConfig,
    *,
    periods: Sequence[Mapping[str, Any]] | None = None,
    codes: Sequence[str] | None = None,
    view: Any | None = None,
    synthetic: bool = False,
    mirror_dir: str | Path | None = None,
    sqlite_path: str | Path | None = None,
) -> BatchDataContext:
    """Synthetic panels only. Non-synthetic Mass factory is disabled."""
    del periods, codes, view, mirror_dir, sqlite_path
    if synthetic:
        return _synthetic_batch_context(config)
    from research.mass_disabled import refuse_mass_host_entrypoint

    refuse_mass_host_entrypoint("load_batch_data_context")
    raise AssertionError("mass factory data path remains disabled")


def _synthetic_batch_context(config: MassFactoryConfig) -> BatchDataContext:
    """Deterministic synthetic panels for unit tests (no disk)."""
    panels: list[dict[str, Any]] = []
    for yi, year in enumerate((2019, 2021, 2023)):
        dates = [f"{year}-10-{d:02d}" for d in range(1, 29)]
        bars: dict[str, list[tuple[str, float]]] = {}
        margin: dict[str, list[tuple[str, float]]] = {}
        for ci, code in enumerate(("13010", "72030", "67580", "99840")):
            base = 100.0 + 10 * ci + yi
            series = [
                (d, base + 0.4 * i + (0.2 if (i + ci) % 5 == 0 else 0.0))
                for i, d in enumerate(dates)
            ]
            bars[code] = series
            margin[code] = [
                (dates[i], 1000.0 + 20 * i + 5 * ci)
                for i in range(0, len(dates), 3)
            ]
        rates = {d: 0.05 + 0.001 * i for i, d in enumerate(dates)}
        short_r = {d: 0.04 + 0.001 * i for i, d in enumerate(dates)}
        long_r = {
            d: (0.06 + 0.001 * i if i % 7 != 0 else 0.02 + 0.0005 * i)
            for i, d in enumerate(dates)
        }
        spread = {d: long_r[d] - short_r[d] for d in dates}
        repo_series = {"rates_by_date": rates}
        curve_series = {
            "short_rates_by_date": short_r,
            "long_rates_by_date": long_r,
            "spread_by_date": spread,
            "rates_by_date": short_r,
        }
        from research.eval_loaders import build_nky_vol_series
        from research.options_225_vol_series import build_opt225_regime_bundle

        nky_closes = []
        px = 38000.0 + 500 * yi
        for i, d in enumerate(dates):
            shock = 0.02 if (i % 11 == 0) else (0.005 if i % 3 == 0 else 0.001)
            sign = 1.0 if i % 2 == 0 else -1.0
            px = max(1000.0, px * (1.0 + sign * shock * (1.0 + 0.1 * (i % 5))))
            nky_closes.append((d, px))
        nky_vol_series = build_nky_vol_series(
            nky_closes,
            short_n=5,
            long_n=15,
            source="synthetic_nk225f",
            dataset="synthetic",
        )
        base_rows = []
        atm_rows = []
        skew_rows = []
        term_rows = []
        for i, d in enumerate(dates):
            bv = 14.0 + 6.0 * ((i % 17) / 16.0) + (8.0 if i % 13 == 0 else 0.0)
            atm = bv + (0.8 if i % 5 == 0 else (-0.3 if i % 7 == 0 else 0.0))
            base_rows.append({"date": d, "base_vol": bv})
            atm_rows.append({"date": d, "atm_iv": atm})
            skew_rows.append(
                {
                    "date": d,
                    "skew": 1.0 + 2.5 * ((i % 11) / 10.0) + (2.0 if i % 9 == 0 else 0.0),
                }
            )
            term_rows.append(
                {
                    "date": d,
                    "cm_term": -0.5
                    + 2.0 * ((i % 13) / 12.0)
                    + (1.5 if i % 8 == 0 else 0.0),
                }
            )
        opt225_regime = build_opt225_regime_bundle(
            base_rows,
            atm_rows,
            skew_rows=skew_rows,
            term_rows=term_rows,
            short_n=5,
            long_n=15,
        )
        fins_events = {
            "13010": [
                {
                    "disc_date": dates[5],
                    "disc_time": "15:00:00",
                    "eps": 10.0 + yi,
                    "feps": 9.0,
                    "bps": 50.0,
                    "prior_eps": 8.0,
                }
            ],
            "72030": [
                {
                    "disc_date": dates[10],
                    "disc_time": "16:00:00",
                    "eps": 5.0,
                    "feps": 6.0,
                    "bps": 20.0,
                    "prior_eps": 5.5,
                }
            ],
        }
        panels.append(
            {
                "period_id": f"y{year}_syn",
                "year": year,
                "period_start": dates[0],
                "period_end": dates[-1],
                "status": "ok",
                "bars": bars,
                "margin": margin,
                "repo_series": repo_series,
                "curve_series": curve_series,
                "nky_vol_series": nky_vol_series,
                "opt225_regime": opt225_regime,
                "fins_events": fins_events,
                "short_series": [
                    (d, 0.01 + 0.0001 * i) for i, d in enumerate(dates)
                ],
            }
        )
    return BatchDataContext(
        periods=[{"period_id": p["period_id"], "year": p["year"]} for p in panels],
        panels=panels,
        one_way_cost=float(config.one_way_cost),
        load_notes={
            "synthetic": True,
            "n_periods": len(panels),
        },
    )


from research.offline.factory import MassFactoryConfig  # noqa: E402

__all__ = [
    "BatchDataContext",
    "load_batch_data_context",
]
