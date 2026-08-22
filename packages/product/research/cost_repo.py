"""Repo rate series construction for research cost models.

Date-keyed JSDA Tokyo repo rates. Gaps disclosed, never ffilled or invented.
ADV/liquidity modulation, short-borrow, and leverage financing stay in
``research.cost_models``.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

REPO_DATASET_ID: str = "jsda_tokyo_repo_rates"
REPO_TABLE: str = "jsda_repo_rates"
DEFAULT_REPO_TENOR: str = "隔日物"
DEFAULT_REPO_RATE_TYPE: str = "東京レポ・レート"


def _date_key(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:10]


def repo_rate_pct_to_annual_fraction(rate_pct: float) -> float:
    """Convert JSDA percent rate to annual fraction (``rate_pct / 100``)."""
    return float(rate_pct) / 100.0


def repo_rate_pct_to_annual_bp(rate_pct: float) -> float:
    """Convert JSDA percent rate to annual bp (``rate_pct * 100``)."""
    return float(rate_pct) * 100.0


def load_repo_rate_series_from_mapping(
    rates_by_date: Mapping[str, Any],
    *,
    required_dates: Sequence[Any] | None = None,
    tenor: str | None = None,
    rate_type: str | None = None,
    source_label: str = "mapping",
) -> dict[str, Any]:
    """Build a date-keyed repo series from ``{YYYY-MM-DD: rate_pct}``.

    Missing ``required_dates`` are listed in ``gap_dates`` — **no ffill invent**.
    """
    from research.cost_models import COST_MODELS_VERSION, _freeze_fields

    series: dict[str, float] = {}
    bad: list[str] = []
    for k, v in dict(rates_by_date or {}).items():
        d = _date_key(k)
        if d is None:
            continue
        if v is None or v == "":
            bad.append(d)
            continue
        try:
            series[d] = float(v)
        except (TypeError, ValueError):
            bad.append(d)

    req: list[str] = []
    if required_dates is not None:
        for raw in required_dates:
            d = _date_key(raw)
            if d is not None:
                req.append(d)
    # De-dupe preserve order
    seen: set[str] = set()
    req_u: list[str] = []
    for d in req:
        if d not in seen:
            seen.add(d)
            req_u.append(d)

    gap_dates = [d for d in req_u if d not in series]
    present_required = [d for d in req_u if d in series]
    # Also treat explicitly bad required keys as gaps
    for d in bad:
        if d in seen and d not in gap_dates and d not in series:
            gap_dates.append(d)

    return {
        "kind": "repo_rate_series",
        "version": COST_MODELS_VERSION,
        "dataset": REPO_DATASET_ID,
        "table": REPO_TABLE,
        "rates_by_date": dict(sorted(series.items())),
        "rate_unit": "percent",
        "tenor": tenor,
        "rate_type": rate_type or DEFAULT_REPO_RATE_TYPE,
        "source_label": source_label,
        "n_obs": len(series),
        "required_dates": list(req_u),
        "present_required_dates": present_required,
        "gap_dates": list(gap_dates),
        "n_gaps": len(gap_dates),
        "coverage_complete": (
            len(gap_dates) == 0 if req_u else len(series) > 0
        ),
        "ffill_applied": False,
        "invent_fill": False,
        "gap_policy": "disclose_only_no_ffill_no_invent",
        "note": (
            "Date-keyed JSDA Tokyo repo rates (%). Missing required dates are "
            "gap-flagged; never forward-filled or invented."
        ),
        **_freeze_fields(),
    }


def load_repo_rate_series_from_rows(
    rows: Sequence[Mapping[str, Any]] | None,
    *,
    required_dates: Sequence[Any] | None = None,
    tenor: str | None = None,
    rate_type: str | None = None,
    prefer_tenor: str | None = DEFAULT_REPO_TENOR,
    source_label: str = "rows",
) -> dict[str, Any]:
    """Load repo series from JSDA / PIT-shaped rows (``as_of_date``, ``rate``).

    When multiple tenors exist for one date, prefer ``prefer_tenor`` (default
    隔日物); else first non-null rate. Filter by ``tenor`` / ``rate_type`` when
    provided. **No invent fill** on gaps.
    """
    rows = list(rows or [])
    # Group candidates per date.
    by_date: dict[str, list[tuple[str, float, Mapping[str, Any]]]] = {}
    for raw in rows:
        d = _date_key(raw.get("as_of_date") or raw.get("date") or raw.get("Date"))
        if d is None:
            continue
        t = str(raw.get("tenor") or "")
        rt = str(raw.get("rate_type") or "")
        if tenor is not None and t != str(tenor):
            continue
        if rate_type is not None and rt != str(rate_type):
            continue
        rate = raw.get("rate")
        if rate is None or rate == "":
            continue
        try:
            rate_f = float(rate)
        except (TypeError, ValueError):
            continue
        by_date.setdefault(d, []).append((t, rate_f, raw))

    rates: dict[str, float] = {}
    chosen_tenor: str | None = tenor
    chosen_rt: str | None = rate_type
    for d, cands in by_date.items():
        picked: tuple[str, float, Mapping[str, Any]] | None = None
        if prefer_tenor is not None:
            for c in cands:
                if c[0] == prefer_tenor:
                    picked = c
                    break
        if picked is None:
            picked = cands[0]
        rates[d] = picked[1]
        if chosen_tenor is None:
            chosen_tenor = picked[0] or None
        if chosen_rt is None:
            chosen_rt = str(picked[2].get("rate_type") or "") or None

    out = load_repo_rate_series_from_mapping(
        rates,
        required_dates=required_dates,
        tenor=chosen_tenor,
        rate_type=chosen_rt or DEFAULT_REPO_RATE_TYPE,
        source_label=source_label,
    )
    out["n_input_rows"] = len(rows)
    out["n_dates_from_rows"] = len(by_date)
    return out


def load_repo_rate_series(
    source: Any = None,
    *,
    required_dates: Sequence[Any] | None = None,
    tenor: str | None = None,
    rate_type: str | None = None,
    prefer_tenor: str | None = DEFAULT_REPO_TENOR,
    source_label: str | None = None,
) -> dict[str, Any]:
    """Unified loader: mapping, row sequence, or prebuilt series dict.

    Parameters
    ----------
    source:
        * ``None`` → empty series (all required_dates = gaps)
        * ``Mapping`` with ``rates_by_date`` key → treated as prebuilt series
          (re-checked against ``required_dates``)
        * ``Mapping[str, rate]`` date→rate
        * ``Sequence[Mapping]`` JSDA/PIT rows
    """
    if source is None:
        return load_repo_rate_series_from_mapping(
            {},
            required_dates=required_dates,
            tenor=tenor,
            rate_type=rate_type,
            source_label=source_label or "empty",
        )

    if isinstance(source, Mapping):
        # Prebuilt series envelope?
        if "rates_by_date" in source and "kind" in source:
            base = dict(source["rates_by_date"] or {})
            return load_repo_rate_series_from_mapping(
                base,
                required_dates=required_dates
                if required_dates is not None
                else source.get("required_dates"),
                tenor=tenor if tenor is not None else source.get("tenor"),
                rate_type=rate_type
                if rate_type is not None
                else source.get("rate_type"),
                source_label=source_label
                or str(source.get("source_label") or "series"),
            )
        # Heuristic: values look like rates (scalar) not nested rows
        values = list(source.values())
        if values and not isinstance(values[0], Mapping):
            return load_repo_rate_series_from_mapping(
                source,  # type: ignore[arg-type]
                required_dates=required_dates,
                tenor=tenor,
                rate_type=rate_type,
                source_label=source_label or "mapping",
            )

    if isinstance(source, Sequence) and not isinstance(source, (str, bytes)):
        return load_repo_rate_series_from_rows(
            source,  # type: ignore[arg-type]
            required_dates=required_dates,
            tenor=tenor,
            rate_type=rate_type,
            prefer_tenor=prefer_tenor,
            source_label=source_label or "rows",
        )

    raise TypeError(
        "load_repo_rate_series source must be None, Mapping, or Sequence of rows; "
        f"got {type(source)!r}"
    )


def load_repo_rate_series_from_pit(
    *,
    as_of: Any,
    required_dates: Sequence[Any] | None = None,
    tenor: str | None = None,
    rate_type: str | None = None,
    from_event: Any = None,
    to_event: Any = None,
    db_path: Any = None,
    prefer_tenor: str | None = DEFAULT_REPO_TENOR,
    get_jsda_repo_rates_fn: Any = None,
) -> dict[str, Any]:
    """Load repo series via PIT ``get_jsda_repo_rates`` (D1 / local SQLite).

    Inject ``get_jsda_repo_rates_fn`` in tests to avoid live D1. Default imports
    ``pit.get_jsda_repo_rates``. History SoT remains R2; this is a **read path**
    only. Gaps are disclosed, never filled.
    """
    if get_jsda_repo_rates_fn is None:
        from pit import get_jsda_repo_rates as get_jsda_repo_rates_fn  # type: ignore

    result = get_jsda_repo_rates_fn(
        as_of,
        tenor=tenor,
        rate_type=rate_type,
        from_event=from_event,
        to_event=to_event,
        db_path=db_path,
    )
    rows: Sequence[Mapping[str, Any]]
    if hasattr(result, "rows"):
        rows = list(result.rows or [])
    elif isinstance(result, Mapping) and "rows" in result:
        rows = list(result["rows"] or [])
    elif isinstance(result, Sequence):
        rows = list(result)  # type: ignore[arg-type]
    else:
        rows = []

    out = load_repo_rate_series_from_rows(
        rows,
        required_dates=required_dates,
        tenor=tenor,
        rate_type=rate_type,
        prefer_tenor=prefer_tenor if tenor is None else tenor,
        source_label="pit_d1_or_local",
    )
    out["as_of"] = str(as_of) if as_of is not None else None
    out["load_path"] = "pit.get_jsda_repo_rates"
    return out


def lookup_repo_rate(
    series: Mapping[str, Any] | None,
    date: Any,
) -> dict[str, Any]:
    """Lookup ``rate_pct`` for a date. Gap → ``rate=None``, ``is_gap=True``.

    Never forward-fills.
    """
    d = _date_key(date)
    rates = {}
    if series is not None:
        if "rates_by_date" in series:
            rates = dict(series.get("rates_by_date") or {})
        else:
            # bare mapping date→rate
            rates = {str(k)[:10]: v for k, v in dict(series).items()}
    if d is None:
        return {
            "date": None,
            "rate_pct": None,
            "rate_annual": None,
            "rate_annual_bp": None,
            "is_gap": True,
            "ffill_applied": False,
            "reason": "invalid_date",
        }
    if d not in rates or rates[d] is None:
        return {
            "date": d,
            "rate_pct": None,
            "rate_annual": None,
            "rate_annual_bp": None,
            "is_gap": True,
            "ffill_applied": False,
            "reason": "missing_repo_rate",
        }
    try:
        rate_pct = float(rates[d])
    except (TypeError, ValueError):
        return {
            "date": d,
            "rate_pct": None,
            "rate_annual": None,
            "rate_annual_bp": None,
            "is_gap": True,
            "ffill_applied": False,
            "reason": "non_numeric_repo_rate",
        }
    return {
        "date": d,
        "rate_pct": rate_pct,
        "rate_annual": repo_rate_pct_to_annual_fraction(rate_pct),
        "rate_annual_bp": repo_rate_pct_to_annual_bp(rate_pct),
        "is_gap": False,
        "ffill_applied": False,
        "reason": None,
    }


def mean_repo_rate_pct(
    series: Mapping[str, Any] | None,
    *,
    dates: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Mean of **observed** repo rates only (gaps excluded, never invented)."""
    if series is None:
        return {
            "mean_rate_pct": None,
            "mean_annual_bp": None,
            "n_obs": 0,
            "gap_dates": list(dates or []),
            "n_gaps": len(list(dates or [])),
        }
    rates = dict(series.get("rates_by_date") or {})
    if dates is None:
        vals = list(rates.values())
        gap_dates: list[str] = []
        used_dates = list(rates.keys())
    else:
        vals = []
        gap_dates = []
        used_dates = []
        for raw in dates:
            d = _date_key(raw)
            if d is None:
                continue
            if d in rates and rates[d] is not None:
                try:
                    vals.append(float(rates[d]))
                    used_dates.append(d)
                except (TypeError, ValueError):
                    gap_dates.append(d)
            else:
                gap_dates.append(d)
    if not vals:
        return {
            "mean_rate_pct": None,
            "mean_annual_bp": None,
            "n_obs": 0,
            "used_dates": used_dates,
            "gap_dates": gap_dates,
            "n_gaps": len(gap_dates),
        }
    mean_pct = sum(vals) / float(len(vals))
    return {
        "mean_rate_pct": mean_pct,
        "mean_annual_bp": repo_rate_pct_to_annual_bp(mean_pct),
        "n_obs": len(vals),
        "used_dates": used_dates,
        "gap_dates": gap_dates,
        "n_gaps": len(gap_dates),
        "note": "Mean over observed rates only; gaps excluded (no invent).",
    }


__all__ = [
    "DEFAULT_REPO_RATE_TYPE",
    "DEFAULT_REPO_TENOR",
    "REPO_DATASET_ID",
    "REPO_TABLE",
    "load_repo_rate_series",
    "load_repo_rate_series_from_mapping",
    "load_repo_rate_series_from_pit",
    "load_repo_rate_series_from_rows",
    "lookup_repo_rate",
    "mean_repo_rate_pct",
    "repo_rate_pct_to_annual_bp",
    "repo_rate_pct_to_annual_fraction",
]
