"""Bar ndjson/sqlite loaders and momentum_series. Skip missing. Never invent.

Public import remains ``research.eval_loaders``. Empty / missing → empty or None.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from research.eval_loaders import (
    DEFAULT_BARS_FULL_MIRROR_DIR,
    DEFAULT_BARS_MIRROR_DIR,
    _code_of,
    _date_of,
    _iter_ndjson,
    _open_ro,
    _payload_map,
    _period_year,
)
from research.eval_universe import DEFAULT_SQLITE


def _bar_rec(
    code: str, date: str, close: float, pl: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "close": close,
        "C": close,
        "Close": close,
        "Code": code,
        "Date": date,
        "date": date,
        "Va": pl.get("Va") or pl.get("AVa") or pl.get("MVa"),
        "Vo": pl.get("Vo") or pl.get("AVo") or pl.get("MVo"),
        "AdjC": pl.get("AdjC") or pl.get("AAdjC"),
        "AdjVo": pl.get("AdjVo") or pl.get("AAdjVo"),
    }


def _trim_dated(dmap: Mapping[str, Any], max_days: int | None) -> list:
    pairs = sorted(dmap.items(), key=lambda x: x[0])
    if max_days is not None and len(pairs) > int(max_days):
        pairs = pairs[-int(max_days) :]
    return pairs


def load_bars_ndjson_rich(
    path: str | Path,
    *,
    codes: Sequence[str] | None = None,
    max_days: int | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Load bars with close + liquidity fields. Skip missing. Never invent."""
    code_filter = {str(c).strip() for c in codes} if codes else None
    p_start = str(period_start)[:10] if period_start else None
    p_end = str(period_end)[:10] if period_end else None
    by_code: dict[str, dict[str, dict[str, Any]]] = {}
    for payload in _iter_ndjson(path):
        code = _code_of(payload)
        date = _date_of(payload)
        if not code or not date:
            continue
        if code_filter is not None and code not in code_filter:
            continue
        if p_start and date < p_start:
            continue
        if p_end and date > p_end:
            continue
        close = payload.get("C")
        if close is None:
            close = payload.get("Close") or payload.get("AdjC")
        try:
            c = float(close)
        except (TypeError, ValueError):
            continue
        by_code.setdefault(code, {})[date] = _bar_rec(code, date, c, payload)
    return {code: _trim_dated(dmap, max_days) for code, dmap in by_code.items()}


def bars_rich_to_close_panel(
    rich: Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]],
) -> dict[str, list[tuple[str, float]]]:
    """Strip rich bars to (date, close) panel."""
    return {
        str(c): [(d, float(r["close"])) for d, r in pairs]
        for c, pairs in rich.items()
    }


def load_bars_from_sqlite_rich(
    *,
    codes: Sequence[str],
    period_start: str,
    period_end: str,
    db_path: str | Path = DEFAULT_SQLITE,
    max_days: int | None = None,
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Load extra names from sqlite ``jquants_records`` via PK range per code.

    Missing requested codes are omitted (no invent). Empty code → omitted.
    """
    want = [str(c).strip() for c in codes if str(c).strip()]
    con = _open_ro(db_path)
    if con is None or not want:
        return {}
    p0 = str(period_start)[:10]
    p1 = str(period_end)[:10]
    out: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    sql = (
        "SELECT payload FROM jquants_records "
        "WHERE source = 'jquants' AND dataset = 'equities_bars_daily' "
        "AND natural_key >= ? AND natural_key <= ?"
    )
    try:
        for code in want:
            lo = json.dumps({"Code": code, "Date": p0}, separators=(",", ":"))
            hi = json.dumps({"Code": code, "Date": p1 + "~"}, separators=(",", ":"))
            dmap: dict[str, dict[str, Any]] = {}
            for (payload,) in con.execute(sql, (lo, hi)):
                pl = _payload_map(payload)
                if pl is None:
                    continue
                date = str(pl.get("Date") or pl.get("date") or "")[:10]
                if not date or date < p0 or date > p1:
                    continue
                close = pl.get("C")
                if close is None:
                    close = pl.get("Close") or pl.get("AdjC") or pl.get("AAdjC")
                try:
                    c = float(close)
                except (TypeError, ValueError):
                    continue
                dmap[date] = _bar_rec(code, date, c, pl)
            if not dmap:
                continue
            out[code] = _trim_dated(dmap, max_days)
    finally:
        con.close()
    return out


def resolve_bars_path(
    period_id: str,
    *,
    mirror_dir: str | Path = DEFAULT_BARS_MIRROR_DIR,
    prefer_full: bool = True,
) -> Path | None:
    """Map period_id like y2015_q4 / y2015_full → local ndjson mirror path."""
    d = Path(mirror_dir)
    year = _period_year(period_id)
    if year is None:
        return None
    pid = str(period_id).lower()
    want_full = prefer_full and ("full" in pid or not pid.endswith("q4"))
    full_path = (
        DEFAULT_BARS_FULL_MIRROR_DIR / f"equities_bars_daily_y{year}_full.ndjson"
    )
    q4_path = d / f"equities_bars_daily_y{year}_q4.ndjson"
    candidates = (
        [full_path, d / f"equities_bars_daily_y{year}_full.ndjson", q4_path]
        if want_full
        else [q4_path, full_path, d / f"equities_bars_daily_y{year}_full.ndjson"]
    )
    for c in candidates:
        if c.exists():
            return c
    return None


def collect_liquidity_bar_rows(
    rich: Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]],
) -> list[dict[str, Any]]:
    """Flatten rich bars to rows for ``compute_liquidity_proxy_from_bars``."""
    rows: list[dict[str, Any]] = []
    for code, pairs in rich.items():
        for d, r in pairs:
            row = dict(r)
            row.setdefault("Code", code)
            row.setdefault("Date", d)
            rows.append(row)
    return rows


def momentum_series(
    closes: Sequence[tuple[str, float]],
    *,
    n: int,
) -> list[tuple[str, float | None]]:
    """Per-date momentum_n from sorted (date, close) pairs."""
    n_i = int(n)
    out: list[tuple[str, float | None]] = []
    for i, (d, _) in enumerate(closes):
        if i < n_i:
            out.append((d, None))
            continue
        base = closes[i - n_i][1]
        last = closes[i][1]
        if base == 0:
            out.append((d, None))
        else:
            out.append((d, (last - base) / base))
    return out
