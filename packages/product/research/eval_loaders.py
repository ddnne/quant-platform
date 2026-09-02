"""Typed bar / index / options loaders. Skip missing and never invent.

Fixture NDJSON compatibility lives only under :mod:`research.offline`.
Bars versus nky/opt/margin/repo/fins are split across the sibling loaders.
"""
from __future__ import annotations

import json
from typing import Any, Mapping


def _payload_map(raw: Any) -> Mapping[str, Any] | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw if isinstance(raw, Mapping) else None


def _fnum(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _code_of(pl: Mapping[str, Any]) -> str:
    return str(pl.get("Code") or pl.get("code") or "").strip()


def _date_of(pl: Mapping[str, Any], event_time: Any = None) -> str:
    return str(pl.get("Date") or pl.get("date") or str(event_time or "")[:10])[:10]


from research.eval_loaders_bars import (  # noqa: E402
    bars_rich_to_close_panel,
    collect_liquidity_bar_rows,
    load_bars_from_sqlite_rich,
    momentum_series,
)
from research.eval_loaders_sidecars import (  # noqa: E402
    build_nky_vol_series,
    build_repo_curve_series,
    fins_asof,
    fins_summary_ta_eqar_stats,
    load_fins_earnings_date_from_sqlite,
    load_fins_events_from_sqlite,
    load_fins_latest_asof_map,
    load_margin_from_sqlite,
    load_nky_vol_series_from_sqlite,
    load_opt225_regime_bundle_for_eval,
    load_repo_rows_all_tenors_from_sqlite,
    load_repo_rows_from_sqlite,
    load_short_ratio_series_from_sqlite,
    load_topix_close_series_from_sqlite,
    merge_event_calendars,
    repo_history_plane_status,
)


__all__ = [
    "bars_rich_to_close_panel",
    "build_nky_vol_series",
    "build_repo_curve_series",
    "collect_liquidity_bar_rows",
    "fins_asof",
    "fins_summary_ta_eqar_stats",
    "load_bars_from_sqlite_rich",
    "load_fins_earnings_date_from_sqlite",
    "load_fins_events_from_sqlite",
    "load_fins_latest_asof_map",
    "load_margin_from_sqlite",
    "load_nky_vol_series_from_sqlite",
    "load_opt225_regime_bundle_for_eval",
    "load_repo_rows_all_tenors_from_sqlite",
    "load_repo_rows_from_sqlite",
    "load_short_ratio_series_from_sqlite",
    "load_topix_close_series_from_sqlite",
    "merge_event_calendars",
    "momentum_series",
    "repo_history_plane_status",
]
