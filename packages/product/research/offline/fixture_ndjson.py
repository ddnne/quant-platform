"""DRAFT/nonpromotable fixture NDJSON adapters. Not a product market path.

These helpers parse local NDJSON for unit tests and offline fixture recovery.
They are not a Pilot, Mass, READY, or cloud-first market input.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from qp_paths import repo_root

from research.eval_loaders import (
    _code_of,
    _date_of,
)
from research.eval_loaders_bars import _bar_rec, _trim_dated
from research.eval_loaders_sidecars import _margin_total
from research.options_225_vol_series import (
    ATM_IV_ROLE,
    DATASET_ID,
    build_daily_basevol_delta_series,
    build_daily_term_ratio_series,
    build_spread_series,
)

DEFAULT_BARS_MIRROR_DIR: Path = (
    repo_root() / ".glm-logs" / "w0815bd_w63_multiyear" / "r2_mirror"
)
DEFAULT_BARS_FULL_MIRROR_DIR: Path = (
    repo_root() / ".glm-logs" / "w0815be_w64_cost_full" / "r2_mirror"
)


def _iter_ndjson(
    path: str | Path, *, payload_or_row: bool = False
) -> Iterator[Mapping[str, Any]]:
    from cf_platform.eval_ndjson import iter_ndjson_payloads

    yield from iter_ndjson_payloads(path, payload_or_row=payload_or_row)


def _period_year(period_id: str) -> int | None:
    for token in str(period_id).split("_"):
        if token.startswith("y") and token[1:].isdigit():
            return int(token[1:])
    if str(period_id).isdigit():
        return int(period_id)
    return None

def load_bars_ndjson_rich(
    path: str | Path,
    *,
    codes: Sequence[str] | None = None,
    max_days: int | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Load bars with close + liquidity fields."""
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


def resolve_margin_path(
    period_id: str,
    *,
    mirror_dir: str | Path = DEFAULT_BARS_MIRROR_DIR,
) -> Path | None:
    """Map period_id → markets_margin_interest local ndjson if present."""
    d = Path(mirror_dir)
    year = _period_year(period_id)
    if year is None:
        return None
    for c in (
        d / f"markets_margin_interest_y{year}_q4.ndjson",
        d / f"markets_margin_interest_y{year}_full.ndjson",
    ):
        if c.exists():
            return c
    return None


def load_margin_ndjson(
    path: str | Path,
    *,
    codes: Sequence[str] | None = None,
) -> dict[str, list[tuple[str, float]]]:
    """Load markets_margin_interest ndjson → ``{code: [(date, total_vol), ...]}``."""
    code_filter = {str(c).strip() for c in codes} if codes else None
    by_code: dict[str, dict[str, float]] = {}
    for payload in _iter_ndjson(path):
        code = _code_of(payload)
        date = _date_of(payload)
        if not code or not date:
            continue
        if code_filter is not None and code not in code_filter:
            continue
        total = _margin_total(payload)
        if total is None:
            continue
        by_code.setdefault(code, {})[date] = total
    return {code: sorted(dmap.items(), key=lambda x: x[0]) for code, dmap in by_code.items()}


def load_ndjson_series(path: str | Path) -> list[dict[str, Any]]:
    """Fixture-only daily series ndjson reader."""
    p = Path(path)
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    with p.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, Mapping):
                out.append(dict(row))
    return out


def load_opt225_series_cache(log_dir: str | Path) -> dict[str, Any] | None:
    """Private OfflineFixture cache reader. Not a product or Mass path."""
    d = Path(log_dir)
    if not (d / "base_vol_series.ndjson").is_file() or not (
        d / "atm_iv_series.ndjson"
    ).is_file():
        return None
    base = load_ndjson_series(d / "base_vol_series.ndjson")
    atm = load_ndjson_series(d / "atm_iv_series.ndjson")
    spread_p = d / "spread_series.ndjson"
    spread = (
        load_ndjson_series(spread_p)
        if spread_p.is_file()
        else build_spread_series(base, atm)
    )
    skew_p = d / "skew_series.ndjson"
    term_p = d / "cm_term_series.ndjson"
    term_ratio_p = d / "cm_term_ratio_series.ndjson"
    delta_p = d / "basevol_delta_series.ndjson"
    skew = load_ndjson_series(skew_p) if skew_p.is_file() else None
    term = load_ndjson_series(term_p) if term_p.is_file() else None
    term_ratio = (
        build_daily_term_ratio_series(load_ndjson_series(term_ratio_p))
        if term_ratio_p.is_file()
        else (build_daily_term_ratio_series(term) if term is not None else None)
    )
    delta = (
        load_ndjson_series(delta_p)
        if delta_p.is_file()
        else build_daily_basevol_delta_series(base=base)
    )
    meta: dict[str, Any] = {}
    meta_p = d / "meta.json"
    if meta_p.is_file():
        try:
            meta = json.loads(meta_p.read_text())
        except json.JSONDecodeError:
            meta = {}
    return {
        "base_vol_series": base,
        "atm_iv_series": atm,
        "spread_series": spread,
        "skew_series": skew,
        "cm_term_series": term,
        "cm_term_ratio_series": term_ratio,
        "basevol_delta_series": delta,
        "meta": meta,
        "dataset": DATASET_ID,
        "source": "opt225_offline_fixture_cache",
        "canonical_level": "base_vol",
        "atm_iv_role": ATM_IV_ROLE,
    }


__all__ = [
    "load_bars_ndjson_rich",
    "load_margin_ndjson",
    "load_ndjson_series",
    "load_opt225_series_cache",
    "resolve_bars_path",
    "resolve_margin_path",
]
