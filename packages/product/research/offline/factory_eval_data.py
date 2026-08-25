"""Cached factory batch panels (not GO / READY).

``BatchDataContext`` / loaders for fail-fast eval. Eval and screen stay in
``research.offline.factory_eval``. Unique/combo generation_enabled stays False.
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
    mirror_dir: str | Path | None = None,
    sqlite_path: str | Path | None = None,
    synthetic: bool = False,
) -> BatchDataContext:
    """Load period panels once for the batch (lite multi-year by default)."""
    from research.eval_loaders import (
        DEFAULT_BARS_MIRROR_DIR,
        bars_rich_to_close_panel,
        build_repo_curve_series,
        load_bars_ndjson_rich,
        load_fins_events_from_sqlite,
        load_margin_ndjson,
        load_nky_vol_series_from_sqlite,
        load_opt225_regime_bundle_for_eval,
        load_repo_rows_all_tenors_from_sqlite,
        load_repo_rows_from_sqlite,
        load_short_ratio_series_from_sqlite,
        resolve_bars_path,
        resolve_margin_path,
    )
    from research.eval_universe import DEFAULT_SQLITE, select_eval_universe
    from research.eval_windows import (
        DEFAULT_PERIODS,
        DEFAULT_PERIODS_Q4,
    )
    from research.cost_models import load_repo_rate_series_from_rows

    if synthetic:
        return _synthetic_batch_context(config)

    period_list = [
        dict(p)
        for p in (
            periods
            or (
                DEFAULT_PERIODS_Q4
                if config.use_q4_periods
                else DEFAULT_PERIODS
            )
        )
    ]
    selected = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes is not None
        else select_eval_universe(max_codes=int(config.max_codes))
    )
    mdir = Path(mirror_dir) if mirror_dir else DEFAULT_BARS_MIRROR_DIR
    db = Path(sqlite_path) if sqlite_path else DEFAULT_SQLITE

    as_of_s = max(
        (
            str(p.get("period_end") or p.get("end") or "")[:10]
            for p in period_list
        ),
        default="",
    )
    if db.exists() and not as_of_s:
        raise ValueError("as_of is required (PIT has no latest default)")
    repo_rows = (
        load_repo_rows_from_sqlite(db, as_of=as_of_s) if db.exists() else []
    )
    repo_series = (
        load_repo_rate_series_from_rows(repo_rows) if repo_rows else None
    )
    repo_all = (
        load_repo_rows_all_tenors_from_sqlite(db, as_of=as_of_s)
        if db.exists()
        else []
    )
    curve_series = build_repo_curve_series(repo_all) if repo_all else None
    nky_vol_series = (
        load_nky_vol_series_from_sqlite(
            db, start="2014-01-01", end="2026-12-31"
        )
        if db.exists()
        else None
    )
    opt225_regime = load_opt225_regime_bundle_for_eval()
    fins_events = (
        load_fins_events_from_sqlite(
            db, codes=selected, start="2014-01-01", end="2026-12-31"
        )
        if db.exists()
        else {}
    )
    short_series = (
        load_short_ratio_series_from_sqlite(
            db, section="0050", start="2014-01-01", end="2026-12-31"
        )
        if db.exists()
        else []
    )
    sidecars = {
        "repo_series": repo_series,
        "curve_series": curve_series,
        "nky_vol_series": nky_vol_series,
        "opt225_regime": opt225_regime,
        "fins_events": fins_events,
        "short_series": short_series,
    }

    panels: list[dict[str, Any]] = []
    for raw in period_list:
        p = dict(raw)
        pid = str(p.get("period_id") or p.get("year") or "period")
        p_start = str(p.get("period_start") or "")[:10] or None
        p_end = str(p.get("period_end") or "")[:10] or None
        head = {
            "period_id": pid,
            "year": p.get("year"),
            "period_start": p_start,
            "period_end": p_end,
            **sidecars,
        }
        bars_path = p.get("bars_path") or resolve_bars_path(pid, mirror_dir=mdir)
        if bars_path is None or not Path(bars_path).exists():
            panels.append({**head, "status": "missing_bars", "bars": {}, "margin": {}})
            continue
        rich = load_bars_ndjson_rich(
            bars_path,
            codes=selected,
            max_days=int(config.max_days_per_period),
            period_start=p_start,
            period_end=p_end,
        )
        bars = bars_rich_to_close_panel(rich)
        margin_path = resolve_margin_path(pid, mirror_dir=mdir)
        margin: dict[str, list[tuple[str, float]]] = {}
        if margin_path is not None and Path(margin_path).exists():
            try:
                margin = load_margin_ndjson(margin_path, codes=selected)
            except Exception:
                margin = {}
        panels.append(
            {
                **head,
                "status": "ok" if bars else "empty_bars",
                "bars": bars,
                "margin": margin,
                "bars_path": str(bars_path),
            }
        )

    return BatchDataContext(
        periods=period_list,
        panels=panels,
        one_way_cost=float(config.one_way_cost),
        load_notes={
            "n_periods": len(panels),
            "n_codes": len(selected),
            "codes": selected,
            "mirror_dir": str(mdir),
            "sqlite": str(db),
            "sqlite_exists": db.exists(),
            "use_q4_periods": bool(config.use_q4_periods),
            "max_days_per_period": int(config.max_days_per_period),
        },
    )


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
