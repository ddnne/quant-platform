"""Bar / index / options loaders for research eval. Skip missing. Never invent.

CF staging imports this module. Offline bar eval is ``research.offline.bar_eval``.
No ffill. Empty / missing inputs return empty or None.

Shared sqlite/ndjson helpers live here. Bars vs nky/opt/margin/repo/fins
live in eval_loaders_bars / eval_loaders_sidecars.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from qp_paths import repo_root

DEFAULT_BARS_MIRROR_DIR: Path = (
    repo_root() / ".glm-logs" / "w0815bd_w63_multiyear" / "r2_mirror"
)
DEFAULT_BARS_FULL_MIRROR_DIR: Path = (
    repo_root() / ".glm-logs" / "w0815be_w64_cost_full" / "r2_mirror"
)


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


def _open_ro(db_path: str | Path) -> sqlite3.Connection | None:
    db = Path(db_path)
    if not db.exists():
        return None
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def _iter_ndjson(
    path: str | Path, *, payload_or_row: bool = False
) -> Iterator[Mapping[str, Any]]:
    with Path(path).open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            pl = _payload_map(row.get("payload") if isinstance(row, Mapping) else None)
            if pl is None and payload_or_row and isinstance(row, Mapping):
                pl = row
            if pl is not None:
                yield pl


def _code_like(codes: Sequence[str]) -> tuple[str, list[str]]:
    if not codes:
        return "", []
    clauses = " OR ".join(["natural_key LIKE ?" for _ in codes])
    return f" AND ({clauses})", [f'%"{c}"%' for c in codes]


def _event_time_filters(
    start: str | None, end: str | None
) -> tuple[str, list[Any]]:
    sql = ""
    params: list[Any] = []
    if start:
        sql += " AND event_time >= ?"
        params.append(str(start)[:10])
    if end:
        sql += " AND event_time <= ?"
        params.append(str(end)[:10] + "T23:59:59")
    return sql, params


def _period_year(period_id: str) -> int | None:
    for token in str(period_id).split("_"):
        if token.startswith("y") and token[1:].isdigit():
            return int(token[1:])
    if str(period_id).isdigit():
        return int(period_id)
    return None


from research.eval_loaders_bars import (  # noqa: E402
    bars_rich_to_close_panel,
    collect_liquidity_bar_rows,
    load_bars_from_sqlite_rich,
    load_bars_ndjson_rich,
    momentum_series,
    resolve_bars_path,
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
    load_margin_ndjson,
    load_nky_vol_series_from_sqlite,
    load_opt225_regime_bundle_for_eval,
    load_repo_rows_all_tenors_from_sqlite,
    load_repo_rows_from_sqlite,
    load_short_ratio_series_from_sqlite,
    load_topix_close_series_from_ndjson,
    load_topix_close_series_from_sqlite,
    merge_event_calendars,
    repo_history_plane_status,
    resolve_margin_path,
)


__all__ = [
    "DEFAULT_BARS_FULL_MIRROR_DIR",
    "DEFAULT_BARS_MIRROR_DIR",
    "bars_rich_to_close_panel",
    "build_nky_vol_series",
    "build_repo_curve_series",
    "collect_liquidity_bar_rows",
    "fins_asof",
    "fins_summary_ta_eqar_stats",
    "load_bars_from_sqlite_rich",
    "load_bars_ndjson_rich",
    "load_fins_earnings_date_from_sqlite",
    "load_fins_events_from_sqlite",
    "load_fins_latest_asof_map",
    "load_margin_from_sqlite",
    "load_margin_ndjson",
    "load_nky_vol_series_from_sqlite",
    "load_opt225_regime_bundle_for_eval",
    "load_repo_rows_all_tenors_from_sqlite",
    "load_repo_rows_from_sqlite",
    "load_short_ratio_series_from_sqlite",
    "load_topix_close_series_from_ndjson",
    "load_topix_close_series_from_sqlite",
    "merge_event_calendars",
    "momentum_series",
    "repo_history_plane_status",
    "resolve_bars_path",
    "resolve_margin_path",
]
