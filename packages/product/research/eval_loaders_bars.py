"""Typed PIT bar loaders and momentum_series. Skip missing. Never invent.

Public import remains ``research.eval_loaders``. Empty / missing → empty or None.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from pit.history_reads import HISTORY_READ_PAGE_SIZE
from pit.personal_research_view import PersonalResearchDataView
from research.eval_loaders import _payload_map


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


def bars_rich_to_close_panel(
    rich: Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]],
) -> dict[str, list[tuple[str, float]]]:
    """Strip rich bars to (date, close) panel."""
    return {
        str(c): [(d, float(r["close"])) for d, r in pairs]
        for c, pairs in rich.items()
    }


def load_bars_from_sqlite_rich(
    view: PersonalResearchDataView,
    *,
    codes: Sequence[str],
    period_start: str,
    period_end: str,
    max_days: int | None = None,
    decision_date: str | None = None,
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Load bars at one decision vintage from a typed research view.

    The view emits one latest visible vintage per natural key. Pages are bounded.
    """
    if not isinstance(view, PersonalResearchDataView):
        raise TypeError("bar sqlite loader requires PersonalResearchDataView")
    want = [str(c).strip() for c in codes if str(c).strip()]
    if not want:
        return {}
    p0 = str(period_start)[:10]
    p1 = str(period_end)[:10]
    decision = str(decision_date or p1)[:10]
    if decision < p0:
        return {}
    if p1 > decision:
        p1 = decision
    want_set = set(want)
    by_code: dict[str, dict[str, dict[str, Any]]] = {}
    for page in view.iter_decision_pages(
        decision_date=decision,
        dataset="equities_bars_daily",
        codes=want,
        start=p0,
        end=p1,
        page_size=HISTORY_READ_PAGE_SIZE,
    ):
        if len(page) > HISTORY_READ_PAGE_SIZE:
            raise ValueError("history catalog page exceeded the fixed bound")
        for row in page:
            pl = _payload_map(row.get("payload"))
            if pl is None:
                continue
            code = str(pl.get("Code") or pl.get("code") or "").strip()
            if code not in want_set:
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
            by_code.setdefault(code, {})[date] = _bar_rec(code, date, c, pl)
    return {
        code: _trim_dated(dmap, max_days) for code, dmap in by_code.items()
    }


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
