"""Research cost models: transaction + short borrow + leverage financing.

Wave
----
* W77 / w0816k — explicit leverage/short assumptions (checklist v2)
* W78 / w0816m — **prefer date-matched ``jsda_tokyo_repo_rates``** over fixed bp

Purpose
-------
Document **explicit research cost assumptions** beyond the base 10bp one-way
transaction cost. Used by checklist v2 so leverage/short costs are never
implicit.

Hard constraints
----------------
* Research-only · 仮定に依存 · 運用GOではない
* Does **not** mint READY / arm Mass / open Phase7 / authorize orders
* Does **not** claim edge / significance
* Pure helpers preferred (unit-testable without R2 / D1)
* **No invent fill** on repo gaps — missing dates are gap-flagged, never ffilled

Models
------
1. **Transaction (base)** — one-way default 10bp (matches robustness_gate).
2. **Short borrow** — preferred: ``f(repo[t] + borrow_spread, short_frac)`` with
   documented low/mid/high spread sensitivity; fallback: fixed annual bp
   placeholder or pure ``borrow_proxy``.
3. **Leverage / financing** — preferred: ``f(repo_rate[t], leverage excess)``;
   fallback: fixed annual bp placeholder when no repo series is supplied.
4. **Long-only unlevered** — tx cost only; leverage/short **N/A** with explicit
   assumptions (required even when unused).

Rate units
----------
JSDA ``jsda_repo_rates.rate`` is stored as **percent** (schema /
``docs/data_sources.md``). Conversion:

* annual fraction = ``rate_pct / 100``
* annual bp      = ``rate_pct * 100``   (1.0% → 100bp)
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# ---------------------------------------------------------------------------
# Identity / freeze (must never arm)
# ---------------------------------------------------------------------------

COST_MODELS_VERSION: str = "research-cost-models/v2"
COST_MODELS_VERSION_V1: str = "research-cost-models/v1"
COST_MODELS_WAVE: str = "W78 / w0816m"
COST_MODELS_LABEL: str = (
    "研究用コストモデル v2・未宣言 "
    "(取引 + 空売り借入 + レバ調達・repo連動優先 / READY未接続 / Mass NO-GO)"
)
COST_MODELS_PROOF: str = (
    "docs/proof/w0816m_w78_repo_linked_cost_model_20260816.md"
)

MASS_RESEARCH: str = "NO-GO"
PHASE7: str = "OFF"
READY_DECLARED: bool = False
OPERATIONAL_GO: bool = False
SIGNIFICANCE_CLAIMED: bool = False
EDGE_CLAIMED: bool = False
CONNECTED_TO_READY: bool = False
CONNECTED_TO_MASS: bool = False

# Base transaction (matches robustness_gate / holding_metrics).
DEFAULT_ONE_WAY_COST_BP: float = 10.0
DEFAULT_ONE_WAY_COST: float = DEFAULT_ONE_WAY_COST_BP / 10_000.0  # 0.001
DEFAULT_ROUND_TRIP_COST: float = DEFAULT_ONE_WAY_COST * 2.0

# Short borrow / stock-lending (research defaults; 仮定に依存).
# Fixed-bp placeholder when no repo series is supplied.
# ~50bp annualized is a conservative liquid-name research placeholder;
# TSE large-cap hard-to-borrow is higher; document when overriding.
DEFAULT_SHORT_BORROW_ANNUAL_BP: float = 50.0
DEFAULT_SHORT_BORROW_ANNUAL: float = DEFAULT_SHORT_BORROW_ANNUAL_BP / 10_000.0
# Trading days per year for daily amortization illustration.
DEFAULT_TRADING_DAYS_PER_YEAR: int = 245

# Leverage / financing fixed-bp placeholder (used only when no repo series).
# Prefer date-matched jsda_tokyo_repo_rates over this constant.
DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP: float = 25.0
DEFAULT_LEVERAGE_FINANCING_ANNUAL: float = (
    DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP / 10_000.0
)

# ---------------------------------------------------------------------------
# Repo-linked model identity / rate sources
# ---------------------------------------------------------------------------

REPO_DATASET_ID: str = "jsda_tokyo_repo_rates"
REPO_TABLE: str = "jsda_repo_rates"
# Preferred tenor for overnight-ish financing (source string kept as-is).
DEFAULT_REPO_TENOR: str = "隔日物"
DEFAULT_REPO_RATE_TYPE: str = "東京レポ・レート"

RATE_SOURCE_FIXED_BP: str = "fixed_bp_placeholder"
RATE_SOURCE_REPO_SERIES: str = "jsda_tokyo_repo_rates"
RATE_SOURCE_REPO_PLUS_SPREAD: str = "repo_plus_borrow_spread"
RATE_SOURCE_BORROW_PROXY: str = "borrow_proxy"
RATE_SOURCE_NOT_APPLICABLE: str = "not_applicable"

# Short-borrow spread over repo (research sensitivity bands).
# short_annual ≈ repo_annual + spread; mid matches the historical fixed 50bp
# placeholder when repo ≈ 0.
SHORT_BORROW_SPREAD_LOW_BP: float = 25.0
SHORT_BORROW_SPREAD_MID_BP: float = 50.0
SHORT_BORROW_SPREAD_HIGH_BP: float = 150.0
DEFAULT_SHORT_BORROW_SPREAD_BP: float = SHORT_BORROW_SPREAD_MID_BP
SHORT_BORROW_SPREAD_SENSITIVITY: dict[str, float] = {
    "low": SHORT_BORROW_SPREAD_LOW_BP,
    "mid": SHORT_BORROW_SPREAD_MID_BP,
    "high": SHORT_BORROW_SPREAD_HIGH_BP,
}

# Position style tags accepted by checklist v2.
POSITION_STYLE_LONG_ONLY_UNLEVERED: str = "long_only_unlevered"
POSITION_STYLE_LONG_SHORT: str = "long_short"
POSITION_STYLE_LEVERED_LONG: str = "levered_long"
POSITION_STYLE_LEVERED_LONG_SHORT: str = "levered_long_short"
KNOWN_POSITION_STYLES: tuple[str, ...] = (
    POSITION_STYLE_LONG_ONLY_UNLEVERED,
    POSITION_STYLE_LONG_SHORT,
    POSITION_STYLE_LEVERED_LONG,
    POSITION_STYLE_LEVERED_LONG_SHORT,
)


def _freeze_fields() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "edge_claimed": EDGE_CLAIMED,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
        "label": COST_MODELS_LABEL,
    }


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


def annual_bp_to_fraction(annual_bp: float) -> float:
    """``bp / 10_000`` → annual fraction."""
    return float(annual_bp) / 10_000.0


# ---------------------------------------------------------------------------
# Repo series load API (keyed by date; gaps disclosed, never ffilled)
# ---------------------------------------------------------------------------


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
    out["history_sot_note"] = (
        "PIT/D1 is tip-capable local/hot read; full history SoT is R2 "
        "quant-structured (jsda_tokyo_repo_rates). No invent fill."
    )
    return out


def load_repo_rate_series_from_r2_rows(
    rows: Sequence[Mapping[str, Any]] | None,
    *,
    required_dates: Sequence[Any] | None = None,
    tenor: str | None = None,
    rate_type: str | None = None,
    prefer_tenor: str | None = DEFAULT_REPO_TENOR,
) -> dict[str, Any]:
    """Normalize R2-extracted ``jsda_tokyo_repo_rates`` rows into a series.

    Caller supplies already-extracted rows (from
    ``r2_feature_context`` / structured JSONL). This helper does not fetch R2.
    """
    out = load_repo_rate_series_from_rows(
        rows,
        required_dates=required_dates,
        tenor=tenor,
        rate_type=rate_type,
        prefer_tenor=prefer_tenor,
        source_label="r2_rows",
    )
    out["load_path"] = "r2_rows"
    out["history_sot_note"] = (
        "Rows presumed from R2 quant-structured history (SoT). No invent fill."
    )
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


# ---------------------------------------------------------------------------
# Daily cost pure helpers
# ---------------------------------------------------------------------------


def short_borrow_daily_cost(
    *,
    short_borrow_annual: float = DEFAULT_SHORT_BORROW_ANNUAL,
    short_borrow_annual_bp: float | None = None,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
    short_fraction: float = 1.0,
) -> float:
    """Daily short-borrow cost fraction of short notional (research).

    Parameters
    ----------
    short_borrow_annual:
        Annualized borrow rate as fraction (default 50bp = 0.005).
    short_borrow_annual_bp:
        If set, overrides annual rate via bp / 10_000.
    trading_days_per_year:
        Days used to amortize annual rate (default 245).
    short_fraction:
        Fraction of gross that is short (0..1+); multiplies daily cost.
    """
    if short_borrow_annual_bp is not None:
        annual = float(short_borrow_annual_bp) / 10_000.0
    else:
        annual = float(short_borrow_annual)
    days = int(trading_days_per_year)
    if days <= 0:
        raise ValueError(f"trading_days_per_year must be positive, got {days}")
    frac = max(0.0, float(short_fraction))
    return (annual / float(days)) * frac


def leverage_financing_daily_cost(
    *,
    gross_leverage: float = 1.0,
    financing_annual: float = DEFAULT_LEVERAGE_FINANCING_ANNUAL,
    financing_annual_bp: float | None = None,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
) -> float:
    """Daily financing cost on excess leverage above 1× (research).

    ``gross_leverage <= 1`` → 0 (unlevered long or dollar-neutral L/S with
    no borrowed cash illustration).
    """
    if financing_annual_bp is not None:
        annual = float(financing_annual_bp) / 10_000.0
    else:
        annual = float(financing_annual)
    days = int(trading_days_per_year)
    if days <= 0:
        raise ValueError(f"trading_days_per_year must be positive, got {days}")
    lev = float(gross_leverage)
    excess = max(lev - 1.0, 0.0)
    return (annual * excess) / float(days)


def leverage_financing_daily_cost_from_repo(
    repo_rate_pct: float,
    *,
    gross_leverage: float = 1.0,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
) -> float:
    """Daily financing = f(repo_rate[t], leverage excess).

    ``financing_daily = (repo_pct/100) * max(gross_leverage - 1, 0) / days``
    """
    annual = repo_rate_pct_to_annual_fraction(repo_rate_pct)
    return leverage_financing_daily_cost(
        gross_leverage=gross_leverage,
        financing_annual=annual,
        trading_days_per_year=trading_days_per_year,
    )


def short_borrow_daily_cost_from_repo(
    repo_rate_pct: float,
    *,
    short_fraction: float = 1.0,
    spread_bp: float = DEFAULT_SHORT_BORROW_SPREAD_BP,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
    sensitivity: str | None = None,
) -> float:
    """Daily short cost = f(repo[t] + spread, short_frac).

    Preferred research model: ``short_annual = repo_annual + spread``.
    ``sensitivity`` in {low, mid, high} overrides ``spread_bp`` via documented
    bands (25 / 50 / 150 bp).
    """
    if sensitivity is not None:
        key = str(sensitivity).strip().lower()
        if key not in SHORT_BORROW_SPREAD_SENSITIVITY:
            raise ValueError(
                f"sensitivity must be one of "
                f"{list(SHORT_BORROW_SPREAD_SENSITIVITY)}, got {sensitivity!r}"
            )
        spread_bp = float(SHORT_BORROW_SPREAD_SENSITIVITY[key])
    repo_bp = repo_rate_pct_to_annual_bp(repo_rate_pct)
    annual_bp = repo_bp + float(spread_bp)
    return short_borrow_daily_cost(
        short_borrow_annual_bp=annual_bp,
        trading_days_per_year=trading_days_per_year,
        short_fraction=short_fraction,
    )


def short_borrow_daily_cost_from_proxy(
    borrow_proxy_annual_bp: float,
    *,
    short_fraction: float = 1.0,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
) -> float:
    """Daily short cost from an explicit borrow-proxy annual bp (no repo)."""
    return short_borrow_daily_cost(
        short_borrow_annual_bp=float(borrow_proxy_annual_bp),
        trading_days_per_year=trading_days_per_year,
        short_fraction=short_fraction,
    )


def date_matched_leverage_financing_costs(
    series: Mapping[str, Any] | None,
    dates: Sequence[Any],
    *,
    gross_leverage: float = 1.0,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
) -> dict[str, Any]:
    """Per-date financing costs from repo series. Gaps → cost None + flag.

    **No ffill invent.**
    """
    by_date: dict[str, Any] = {}
    gap_dates: list[str] = []
    costs: list[float] = []
    for raw in dates:
        d = _date_key(raw)
        if d is None:
            continue
        hit = lookup_repo_rate(series, d)
        if hit["is_gap"]:
            gap_dates.append(d)
            by_date[d] = {
                "date": d,
                "is_gap": True,
                "repo_rate_pct": None,
                "financing_daily": None,
                "financing_daily_bp": None,
                "gross_leverage": float(gross_leverage),
                "ffill_applied": False,
            }
            continue
        daily = leverage_financing_daily_cost_from_repo(
            float(hit["rate_pct"]),
            gross_leverage=gross_leverage,
            trading_days_per_year=trading_days_per_year,
        )
        costs.append(daily)
        by_date[d] = {
            "date": d,
            "is_gap": False,
            "repo_rate_pct": hit["rate_pct"],
            "repo_annual_bp": hit["rate_annual_bp"],
            "financing_daily": daily,
            "financing_daily_bp": daily * 10_000.0,
            "gross_leverage": float(gross_leverage),
            "excess_leverage": max(float(gross_leverage) - 1.0, 0.0),
            "ffill_applied": False,
        }
    return {
        "kind": "date_matched_leverage_financing",
        "version": COST_MODELS_VERSION,
        "rate_source": RATE_SOURCE_REPO_SERIES,
        "formula": (
            "financing_daily[t] = (repo_pct[t]/100) "
            "* max(gross_leverage-1,0) / trading_days"
        ),
        "gross_leverage": float(gross_leverage),
        "trading_days_per_year": int(trading_days_per_year),
        "by_date": by_date,
        "gap_dates": gap_dates,
        "n_gaps": len(gap_dates),
        "n_obs": len(costs),
        "mean_financing_daily": (
            (sum(costs) / float(len(costs))) if costs else None
        ),
        "ffill_applied": False,
        "invent_fill": False,
        "note": "Gaps disclosed with financing_daily=None; never ffilled.",
        **_freeze_fields(),
    }


def date_matched_short_borrow_costs(
    series: Mapping[str, Any] | None,
    dates: Sequence[Any],
    *,
    short_fraction: float = 0.5,
    spread_bp: float = DEFAULT_SHORT_BORROW_SPREAD_BP,
    sensitivity: str | None = None,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
) -> dict[str, Any]:
    """Per-date short costs = f(repo[t] + spread, short_frac). Gaps flagged.

    **No ffill invent.** ``sensitivity`` low/mid/high overrides ``spread_bp``.
    """
    if sensitivity is not None:
        key = str(sensitivity).strip().lower()
        if key not in SHORT_BORROW_SPREAD_SENSITIVITY:
            raise ValueError(
                f"sensitivity must be one of "
                f"{list(SHORT_BORROW_SPREAD_SENSITIVITY)}, got {sensitivity!r}"
            )
        spread_bp = float(SHORT_BORROW_SPREAD_SENSITIVITY[key])
        sens_label = key
    else:
        sens_label = None
        # Infer band label when exact match
        for k, v in SHORT_BORROW_SPREAD_SENSITIVITY.items():
            if abs(float(spread_bp) - float(v)) < 1e-12:
                sens_label = k
                break

    by_date: dict[str, Any] = {}
    gap_dates: list[str] = []
    costs: list[float] = []
    for raw in dates:
        d = _date_key(raw)
        if d is None:
            continue
        hit = lookup_repo_rate(series, d)
        if hit["is_gap"]:
            gap_dates.append(d)
            by_date[d] = {
                "date": d,
                "is_gap": True,
                "repo_rate_pct": None,
                "short_borrow_daily": None,
                "short_borrow_daily_bp": None,
                "ffill_applied": False,
            }
            continue
        daily = short_borrow_daily_cost_from_repo(
            float(hit["rate_pct"]),
            short_fraction=short_fraction,
            spread_bp=float(spread_bp),
            trading_days_per_year=trading_days_per_year,
        )
        costs.append(daily)
        by_date[d] = {
            "date": d,
            "is_gap": False,
            "repo_rate_pct": hit["rate_pct"],
            "repo_annual_bp": hit["rate_annual_bp"],
            "spread_bp": float(spread_bp),
            "short_annual_bp": float(hit["rate_annual_bp"]) + float(spread_bp),
            "short_borrow_daily": daily,
            "short_borrow_daily_bp": daily * 10_000.0,
            "short_fraction": float(short_fraction),
            "ffill_applied": False,
        }
    return {
        "kind": "date_matched_short_borrow",
        "version": COST_MODELS_VERSION,
        "rate_source": RATE_SOURCE_REPO_PLUS_SPREAD,
        "formula": (
            "short_borrow_daily[t] = "
            "((repo_pct[t]*100 + spread_bp)/10000) / trading_days * short_fraction"
        ),
        "spread_bp": float(spread_bp),
        "sensitivity": sens_label,
        "sensitivity_bands_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
        "short_fraction": float(short_fraction),
        "trading_days_per_year": int(trading_days_per_year),
        "by_date": by_date,
        "gap_dates": gap_dates,
        "n_gaps": len(gap_dates),
        "n_obs": len(costs),
        "mean_short_borrow_daily": (
            (sum(costs) / float(len(costs))) if costs else None
        ),
        "ffill_applied": False,
        "invent_fill": False,
        "note": "Gaps disclosed with short_borrow_daily=None; never ffilled.",
        **_freeze_fields(),
    }


def research_net_with_extended_costs(
    gross_signed_mean: float | None,
    *,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    short_borrow_daily: float = 0.0,
    financing_daily: float = 0.0,
) -> float | None:
    """Research net = gross − one_way − short_borrow_daily − financing_daily.

    All costs are fractional per active unit (same units as gross_signed_mean).
    """
    if gross_signed_mean is None:
        return None
    try:
        g = float(gross_signed_mean)
    except (TypeError, ValueError):
        return None
    return (
        g
        - float(one_way_cost)
        - float(short_borrow_daily)
        - float(financing_daily)
    )


# ---------------------------------------------------------------------------
# Public document + assumption builders
# ---------------------------------------------------------------------------


def cost_models_document() -> dict[str, Any]:
    """Public document for research cost-model surface (checklist v2)."""
    doc: dict[str, Any] = {
        "version": COST_MODELS_VERSION,
        "prior_version": COST_MODELS_VERSION_V1,
        "wave": COST_MODELS_WAVE,
        "label": COST_MODELS_LABEL,
        "proof": COST_MODELS_PROOF,
        "preferred_rate_source": RATE_SOURCE_REPO_SERIES,
        "transaction": {
            "one_way_cost_bp": DEFAULT_ONE_WAY_COST_BP,
            "one_way_cost": DEFAULT_ONE_WAY_COST,
            "round_trip_cost_bp": DEFAULT_ONE_WAY_COST_BP * 2.0,
            "round_trip_cost": DEFAULT_ROUND_TRIP_COST,
            "formula_one_way": "net_one_way = gross_signed_mean_active - one_way_cost",
            "change_requires": "cost_change_reason",
            "label": "仮定に依存・研究用・運用GOではない",
        },
        "short_borrow": {
            "preferred_model": RATE_SOURCE_REPO_PLUS_SPREAD,
            "formula_preferred": (
                "short_borrow_daily[t] ≈ "
                "(repo_pct[t]/100 + spread) / trading_days * short_fraction"
            ),
            "spread_sensitivity_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
            "default_spread_bp": DEFAULT_SHORT_BORROW_SPREAD_BP,
            "fallback_fixed_annual_bp": DEFAULT_SHORT_BORROW_ANNUAL_BP,
            "fallback_model": RATE_SOURCE_FIXED_BP,
            "alt_model": RATE_SOURCE_BORROW_PROXY,
            "default_annual_bp": DEFAULT_SHORT_BORROW_ANNUAL_BP,
            "default_annual": DEFAULT_SHORT_BORROW_ANNUAL,
            "trading_days_per_year": DEFAULT_TRADING_DAYS_PER_YEAR,
            "formula_daily_fixed": (
                "short_borrow_daily ≈ short_borrow_annual / trading_days_per_year"
            ),
            "applies_when": "position_style uses short side (long_short / levered_long_short)",
            "note": (
                "Prefer repo[t] + explicit borrow spread (low/mid/high). "
                "Fixed 50bp annual is a fallback placeholder when no repo series. "
                "Not a broker borrow quote. Hard-to-borrow names need higher spreads."
            ),
        },
        "leverage_financing": {
            "preferred_model": RATE_SOURCE_REPO_SERIES,
            "formula_preferred": (
                "financing_daily[t] ≈ (repo_pct[t]/100) "
                "* max(gross_leverage-1, 0) / trading_days"
            ),
            "fallback_fixed_annual_bp": DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP,
            "fallback_model": RATE_SOURCE_FIXED_BP,
            "default_annual_bp": DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP,
            "default_annual": DEFAULT_LEVERAGE_FINANCING_ANNUAL,
            "trading_days_per_year": DEFAULT_TRADING_DAYS_PER_YEAR,
            "formula_daily_fixed": (
                "financing_daily ≈ leverage_financing_annual "
                "* max(gross_leverage - 1, 0) / trading_days_per_year"
            ),
            "applies_when": "gross_leverage > 1 (levered styles)",
            "repo_dataset": REPO_DATASET_ID,
            "repo_table": REPO_TABLE,
            "default_tenor": DEFAULT_REPO_TENOR,
            "gap_policy": "disclose_only_no_ffill_no_invent",
            "long_only_unlevered_rule": (
                "Must state position_style=long_only_unlevered and "
                "financing_not_applicable=True (or gross_leverage<=1)"
            ),
            "note": (
                "Prefer date-matched jsda_tokyo_repo_rates over fixed bp. "
                "Fixed 25bp is a research placeholder only when no series. "
                "Not operational GO."
            ),
        },
        "repo_series_api": {
            "load_repo_rate_series": "unified loader (mapping / rows / series)",
            "load_repo_rate_series_from_mapping": "date→rate_pct mapping",
            "load_repo_rate_series_from_rows": "JSDA/PIT rows",
            "load_repo_rate_series_from_pit": "pit.get_jsda_repo_rates (D1/local)",
            "load_repo_rate_series_from_r2_rows": "R2-extracted rows (no fetch)",
            "lookup_repo_rate": "single-date lookup with gap flag",
            "date_matched_leverage_financing_costs": "per-date financing",
            "date_matched_short_borrow_costs": "per-date short cost",
        },
        "known_position_styles": list(KNOWN_POSITION_STYLES),
        "defaults_policy": {
            "prefer_repo_linked": True,
            "require_repo_linked": False,
            "fixed_bp_fallback_when": "no repo_rate_series supplied",
            "long_only_unlevered": "tx only; short/financing N/A explicit",
            "note": (
                "Checklist v2 prefers repo-linked financing/short when series "
                "is available; fixed bp remains valid disclosed fallback. "
                "Gaps never invent-filled."
            ),
        },
        "note": (
            "Research cost models for checklist v2 (v2 surface). Explicit "
            "short/leverage assumptions required. Prefer date-matched "
            "jsda_tokyo_repo_rates. Pass does not mint READY, arm Mass, or "
            "claim edge."
        ),
    }
    doc.update(_freeze_fields())
    return doc


def build_leverage_short_cost_assumption(
    *,
    position_style: str = POSITION_STYLE_LONG_ONLY_UNLEVERED,
    gross_leverage: float = 1.0,
    short_fraction: float = 0.0,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    one_way_cost_bp: float | None = None,
    short_borrow_annual_bp: float | None = None,
    financing_annual_bp: float | None = None,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
    cost_change_reason: str | None = None,
    short_borrow_change_reason: str | None = None,
    financing_change_reason: str | None = None,
    uses_short: bool | None = None,
    uses_leverage: bool | None = None,
    # --- W78 repo-linked ---
    repo_rate_series: Mapping[str, Any] | None = None,
    prefer_repo_linked: bool = True,
    short_borrow_spread_bp: float | None = None,
    short_borrow_sensitivity: str | None = None,
    borrow_proxy_annual_bp: float | None = None,
    required_dates: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Build explicit leverage/short cost assumption block for checklist v2.

    Long-only unlevered hyps **must** still produce this block with
    ``financing_not_applicable=True`` and ``short_borrow_not_applicable=True``.

    When ``repo_rate_series`` is supplied and ``prefer_repo_linked=True``
    (default), financing uses mean observed repo rates and short uses
    repo + spread (low/mid/high). **Gaps are disclosed, never ffilled.**

    Returns a freeze-wrapped dict. Does not mint READY/Mass.
    """
    style = str(position_style or "").strip().lower() or POSITION_STYLE_LONG_ONLY_UNLEVERED
    if style not in KNOWN_POSITION_STYLES:
        style_known = False
    else:
        style_known = True

    if one_way_cost_bp is not None:
        tx = float(one_way_cost_bp) / 10_000.0
        tx_bp = float(one_way_cost_bp)
    else:
        tx = float(one_way_cost)
        tx_bp = tx * 10_000.0

    # Infer uses_short / uses_leverage from style when not provided.
    if uses_short is None:
        uses_short = style in (
            POSITION_STYLE_LONG_SHORT,
            POSITION_STYLE_LEVERED_LONG_SHORT,
        ) or float(short_fraction) > 0.0
    else:
        uses_short = bool(uses_short)
    if uses_leverage is None:
        uses_leverage = style in (
            POSITION_STYLE_LEVERED_LONG,
            POSITION_STYLE_LEVERED_LONG_SHORT,
        ) or float(gross_leverage) > 1.0 + 1e-12
    else:
        uses_leverage = bool(uses_leverage)

    # Resolve short spread sensitivity.
    spread_bp = (
        float(short_borrow_spread_bp)
        if short_borrow_spread_bp is not None
        else DEFAULT_SHORT_BORROW_SPREAD_BP
    )
    sens_label: str | None = None
    if short_borrow_sensitivity is not None:
        key = str(short_borrow_sensitivity).strip().lower()
        if key not in SHORT_BORROW_SPREAD_SENSITIVITY:
            raise ValueError(
                f"short_borrow_sensitivity must be one of "
                f"{list(SHORT_BORROW_SPREAD_SENSITIVITY)}, got "
                f"{short_borrow_sensitivity!r}"
            )
        spread_bp = float(SHORT_BORROW_SPREAD_SENSITIVITY[key])
        sens_label = key
    else:
        for k, v in SHORT_BORROW_SPREAD_SENSITIVITY.items():
            if abs(spread_bp - float(v)) < 1e-12:
                sens_label = k
                break

    # Normalize / re-check series against required_dates if given.
    series_doc: dict[str, Any] | None = None
    repo_mean: dict[str, Any] | None = None
    repo_available = False
    if repo_rate_series is not None:
        series_doc = load_repo_rate_series(
            repo_rate_series,
            required_dates=required_dates,
        )
        repo_mean = mean_repo_rate_pct(
            series_doc,
            dates=required_dates if required_dates is not None else None,
        )
        repo_available = int(repo_mean.get("n_obs") or 0) > 0

    use_repo = bool(prefer_repo_linked and repo_available)

    # ---- Short borrow rate resolution ----
    short_rate_source = RATE_SOURCE_NOT_APPLICABLE
    if uses_short:
        if borrow_proxy_annual_bp is not None and not use_repo:
            borrow_bp = float(borrow_proxy_annual_bp)
            short_rate_source = RATE_SOURCE_BORROW_PROXY
        elif use_repo and repo_mean is not None and repo_mean.get("mean_annual_bp") is not None:
            borrow_bp = float(repo_mean["mean_annual_bp"]) + float(spread_bp)
            short_rate_source = RATE_SOURCE_REPO_PLUS_SPREAD
        elif short_borrow_annual_bp is not None:
            borrow_bp = float(short_borrow_annual_bp)
            short_rate_source = RATE_SOURCE_FIXED_BP
        else:
            borrow_bp = DEFAULT_SHORT_BORROW_ANNUAL_BP
            short_rate_source = RATE_SOURCE_FIXED_BP
    else:
        borrow_bp = (
            float(short_borrow_annual_bp)
            if short_borrow_annual_bp is not None
            else DEFAULT_SHORT_BORROW_ANNUAL_BP
        )

    # ---- Financing rate resolution ----
    fin_rate_source = RATE_SOURCE_NOT_APPLICABLE
    if uses_leverage:
        if use_repo and repo_mean is not None and repo_mean.get("mean_annual_bp") is not None:
            fin_bp = float(repo_mean["mean_annual_bp"])
            fin_rate_source = RATE_SOURCE_REPO_SERIES
        elif financing_annual_bp is not None:
            fin_bp = float(financing_annual_bp)
            fin_rate_source = RATE_SOURCE_FIXED_BP
        else:
            fin_bp = DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP
            fin_rate_source = RATE_SOURCE_FIXED_BP
    else:
        fin_bp = (
            float(financing_annual_bp)
            if financing_annual_bp is not None
            else DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP
        )

    short_daily = 0.0
    short_not_applicable = not uses_short
    sf = 0.0
    if uses_short:
        sf = float(short_fraction) if float(short_fraction) > 0 else 0.5
        short_daily = short_borrow_daily_cost(
            short_borrow_annual_bp=borrow_bp,
            trading_days_per_year=trading_days_per_year,
            short_fraction=sf,
        )

    fin_daily = 0.0
    financing_not_applicable = not uses_leverage
    lev = float(gross_leverage)
    if uses_leverage:
        if lev <= 1.0:
            lev = 1.0
            financing_not_applicable = True
            fin_daily = 0.0
            fin_rate_source = RATE_SOURCE_NOT_APPLICABLE
        else:
            fin_daily = leverage_financing_daily_cost(
                gross_leverage=lev,
                financing_annual_bp=fin_bp,
                trading_days_per_year=trading_days_per_year,
            )

    # Long-only unlevered: force N/A disclosure.
    if style == POSITION_STYLE_LONG_ONLY_UNLEVERED and not uses_short and not uses_leverage:
        short_not_applicable = True
        financing_not_applicable = True
        short_daily = 0.0
        fin_daily = 0.0
        lev = min(lev, 1.0)
        short_rate_source = RATE_SOURCE_NOT_APPLICABLE
        fin_rate_source = RATE_SOURCE_NOT_APPLICABLE

    default_tx = float(DEFAULT_ONE_WAY_COST)
    tx_changed = abs(tx - default_tx) > 1e-15
    # For disclosure: fixed-bp override detection vs historical defaults
    # (repo-linked rates are not "changed from fixed default" in the same sense)
    if short_rate_source == RATE_SOURCE_FIXED_BP:
        borrow_changed = abs(borrow_bp - DEFAULT_SHORT_BORROW_ANNUAL_BP) > 1e-12
    elif short_rate_source == RATE_SOURCE_BORROW_PROXY:
        borrow_changed = True  # explicit proxy always disclosed as non-default
    else:
        borrow_changed = False  # repo-linked is preferred path
    if fin_rate_source == RATE_SOURCE_FIXED_BP:
        fin_changed = abs(fin_bp - DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP) > 1e-12
    else:
        fin_changed = False

    disclosed = True
    missing: list[str] = []
    if not style:
        disclosed = False
        missing.append("position_style")
    if tx_changed and not (cost_change_reason and str(cost_change_reason).strip()):
        disclosed = False
        missing.append("cost_change_reason")
    if (
        uses_short
        and short_rate_source == RATE_SOURCE_FIXED_BP
        and borrow_changed
        and not (short_borrow_change_reason and str(short_borrow_change_reason).strip())
    ):
        disclosed = False
        missing.append("short_borrow_change_reason")
    if (
        uses_leverage
        and fin_rate_source == RATE_SOURCE_FIXED_BP
        and fin_changed
        and not (financing_change_reason and str(financing_change_reason).strip())
    ):
        disclosed = False
        missing.append("financing_change_reason")

    assumptions_complete = disclosed and (
        short_not_applicable or uses_short
    ) and (
        financing_not_applicable or uses_leverage or lev <= 1.0
    )

    gap_dates: list[str] = []
    n_gaps = 0
    coverage_complete: bool | None = None
    if series_doc is not None:
        gap_dates = list(series_doc.get("gap_dates") or [])
        n_gaps = int(series_doc.get("n_gaps") or 0)
        coverage_complete = bool(series_doc.get("coverage_complete"))

    repo_block: dict[str, Any] = {
        "preferred": bool(prefer_repo_linked),
        "series_supplied": repo_rate_series is not None,
        "series_usable": repo_available,
        "used_for_financing": fin_rate_source == RATE_SOURCE_REPO_SERIES,
        "used_for_short": short_rate_source == RATE_SOURCE_REPO_PLUS_SPREAD,
        "dataset": REPO_DATASET_ID,
        "table": REPO_TABLE,
        "rate_unit": "percent",
        "mean_rate_pct": (
            repo_mean.get("mean_rate_pct") if repo_mean is not None else None
        ),
        "mean_annual_bp": (
            repo_mean.get("mean_annual_bp") if repo_mean is not None else None
        ),
        "n_obs": int(repo_mean.get("n_obs") or 0) if repo_mean else 0,
        "gap_dates": gap_dates,
        "n_gaps": n_gaps,
        "coverage_complete": coverage_complete,
        "ffill_applied": False,
        "invent_fill": False,
        "gap_policy": "disclose_only_no_ffill_no_invent",
        "series": series_doc,
        "note": (
            "Prefer date-matched jsda_tokyo_repo_rates. "
            "Mean over observed rates only when summarizing; "
            "gaps never invent-filled."
            if prefer_repo_linked
            else "prefer_repo_linked=False; fixed/proxy path used."
        ),
    }

    out: dict[str, Any] = {
        "version": COST_MODELS_VERSION,
        "prior_version": COST_MODELS_VERSION_V1,
        "wave": COST_MODELS_WAVE,
        "kind": "leverage_short_cost_assumption",
        "position_style": style,
        "position_style_known": style_known,
        "gross_leverage": lev,
        "short_fraction": (sf if uses_short else 0.0),
        "uses_short": uses_short,
        "uses_leverage": uses_leverage,
        "prefer_repo_linked": bool(prefer_repo_linked),
        "repo_linked": bool(
            fin_rate_source == RATE_SOURCE_REPO_SERIES
            or short_rate_source == RATE_SOURCE_REPO_PLUS_SPREAD
        ),
        "transaction": {
            "one_way_cost": tx,
            "one_way_cost_bp": tx_bp,
            "round_trip_cost": tx * 2.0,
            "round_trip_cost_bp": tx_bp * 2.0,
            "default_one_way_cost": default_tx,
            "changed_from_default": tx_changed,
            "change_reason": (
                str(cost_change_reason).strip() if cost_change_reason else None
            ),
            "formula": "net_one_way = gross_signed_mean_active - one_way_cost",
        },
        "short_borrow": {
            "not_applicable": short_not_applicable,
            "rate_source": short_rate_source,
            "annual_bp": borrow_bp if uses_short else None,
            "annual": (borrow_bp / 10_000.0) if uses_short else None,
            "daily_cost": short_daily,
            "daily_cost_bp": short_daily * 10_000.0,
            "trading_days_per_year": int(trading_days_per_year),
            "default_annual_bp": DEFAULT_SHORT_BORROW_ANNUAL_BP,
            "spread_bp": (
                float(spread_bp)
                if uses_short and short_rate_source == RATE_SOURCE_REPO_PLUS_SPREAD
                else None
            ),
            "sensitivity": (
                sens_label
                if uses_short and short_rate_source == RATE_SOURCE_REPO_PLUS_SPREAD
                else None
            ),
            "sensitivity_bands_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
            "borrow_proxy_annual_bp": (
                float(borrow_proxy_annual_bp)
                if borrow_proxy_annual_bp is not None
                and short_rate_source == RATE_SOURCE_BORROW_PROXY
                else None
            ),
            "changed_from_default": borrow_changed if uses_short else False,
            "change_reason": (
                str(short_borrow_change_reason).strip()
                if short_borrow_change_reason
                else None
            ),
            "formula": (
                "short_borrow_daily ≈ (repo_annual + spread) / trading_days "
                "* short_fraction"
                if short_rate_source == RATE_SOURCE_REPO_PLUS_SPREAD
                else (
                    "short_borrow_daily ≈ (annual_bp/10000) / trading_days "
                    "* short_fraction"
                )
            ),
            "note": (
                "Research stock-lending fee model (repo + spread preferred). "
                if uses_short
                else "Short side not used; borrow fee N/A (explicit)."
            ),
        },
        "leverage_financing": {
            "not_applicable": financing_not_applicable,
            "rate_source": fin_rate_source,
            "annual_bp": (
                fin_bp if uses_leverage and not financing_not_applicable else None
            ),
            "annual": (
                (fin_bp / 10_000.0)
                if uses_leverage and not financing_not_applicable
                else None
            ),
            "daily_cost": fin_daily,
            "daily_cost_bp": fin_daily * 10_000.0,
            "gross_leverage": lev,
            "trading_days_per_year": int(trading_days_per_year),
            "default_annual_bp": DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP,
            "changed_from_default": fin_changed if uses_leverage else False,
            "change_reason": (
                str(financing_change_reason).strip()
                if financing_change_reason
                else None
            ),
            "formula": (
                "financing_daily ≈ (repo_pct/100) * max(gross_leverage-1,0) "
                "/ trading_days"
                if fin_rate_source == RATE_SOURCE_REPO_SERIES
                else (
                    "financing_daily ≈ (annual_bp/10000) * max(gross_leverage-1,0) "
                    "/ trading_days"
                )
            ),
            "note": (
                "Research financing from date-matched Tokyo repo rates "
                "(mean of observed; gaps disclosed). "
                if fin_rate_source == RATE_SOURCE_REPO_SERIES
                else (
                    "Research financing/repo illustration (fixed-bp fallback). "
                    if uses_leverage and not financing_not_applicable
                    else "Unlevered or financing N/A (explicit)."
                )
            ),
        },
        "repo_rate": repo_block,
        "combined_daily_extra_cost": short_daily + fin_daily,
        "combined_daily_extra_cost_bp": (short_daily + fin_daily) * 10_000.0,
        "net_formula_extended": (
            "net = gross - one_way_cost - short_borrow_daily - financing_daily"
        ),
        "assumptions_disclosed": disclosed,
        "assumptions_complete": bool(assumptions_complete),
        "missing_disclosure": missing,
        "label": "仮定に依存・研究用・運用GOではない",
        "note": (
            "Explicit leverage/short cost assumptions for checklist v2. "
            "Prefer date-matched jsda_tokyo_repo_rates over fixed bp. "
            "Long-only unlevered must still state N/A. Not READY / not Mass."
        ),
    }
    out.update(_freeze_fields())
    return out


def default_long_only_unlevered_cost_assumption(
    *,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    cost_change_reason: str | None = None,
    repo_rate_series: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience: long-only unlevered with base 10bp + explicit N/A shorts/lev.

    Repo series may be attached for disclosure/inventory but financing/short
    remain N/A for this style.
    """
    return build_leverage_short_cost_assumption(
        position_style=POSITION_STYLE_LONG_ONLY_UNLEVERED,
        gross_leverage=1.0,
        short_fraction=0.0,
        one_way_cost=one_way_cost,
        cost_change_reason=cost_change_reason,
        uses_short=False,
        uses_leverage=False,
        repo_rate_series=repo_rate_series,
        prefer_repo_linked=True,
    )


def annotate_period_rows_with_extended_costs(
    period_rows: Sequence[Mapping[str, Any]],
    *,
    cost_assumption: Mapping[str, Any] | None = None,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    repo_rate_series: Mapping[str, Any] | None = None,
    date_field: str = "period_end",
    gross_leverage: float | None = None,
    short_fraction: float | None = None,
    short_borrow_spread_bp: float = DEFAULT_SHORT_BORROW_SPREAD_BP,
    short_borrow_sensitivity: str | None = None,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
) -> list[dict[str, Any]]:
    """Copy period rows adding extended net fields (research illustration).

    When ``repo_rate_series`` is provided and a row has ``date_field``, uses
    **date-matched** repo costs. Gap days get ``financing_daily`` /
    ``short_borrow_daily`` = None and ``repo_rate_gap=True`` (no invent).
    """
    ca = dict(cost_assumption) if cost_assumption is not None else {}
    tx = float(ca.get("transaction", {}).get("one_way_cost", one_way_cost))
    uses_short = bool(ca.get("uses_short", False))
    uses_leverage = bool(ca.get("uses_leverage", False))
    lev = float(
        gross_leverage
        if gross_leverage is not None
        else ca.get("gross_leverage", 1.0)
    )
    sf = float(
        short_fraction
        if short_fraction is not None
        else ca.get("short_fraction", 0.0)
    )
    static_short = float(ca.get("short_borrow", {}).get("daily_cost") or 0.0)
    static_fin = float(ca.get("leverage_financing", {}).get("daily_cost") or 0.0)

    series = repo_rate_series
    if series is None and isinstance(ca.get("repo_rate"), Mapping):
        series = (ca.get("repo_rate") or {}).get("series")

    out: list[dict[str, Any]] = []
    for raw in period_rows:
        row = dict(raw)
        gross = row.get("gross_signed_mean_active")
        if gross is None:
            gross = row.get("gross_signed_mean")
        try:
            g = float(gross) if gross is not None else None
        except (TypeError, ValueError):
            g = None

        d = _date_key(row.get(date_field) or row.get("date") or row.get("as_of_date"))
        short_d: float | None = static_short if uses_short else 0.0
        fin_d: float | None = static_fin if uses_leverage else 0.0
        repo_gap = False
        repo_pct: float | None = None
        rate_source_short = (ca.get("short_borrow") or {}).get("rate_source")
        rate_source_fin = (ca.get("leverage_financing") or {}).get("rate_source")

        if series is not None and d is not None and (uses_short or uses_leverage):
            hit = lookup_repo_rate(series, d)
            if hit["is_gap"]:
                repo_gap = True
                if uses_short:
                    short_d = None
                if uses_leverage:
                    fin_d = None
            else:
                repo_pct = float(hit["rate_pct"])
                if uses_short:
                    short_d = short_borrow_daily_cost_from_repo(
                        repo_pct,
                        short_fraction=sf if sf > 0 else 0.5,
                        spread_bp=short_borrow_spread_bp,
                        sensitivity=short_borrow_sensitivity,
                        trading_days_per_year=trading_days_per_year,
                    )
                    rate_source_short = RATE_SOURCE_REPO_PLUS_SPREAD
                if uses_leverage:
                    fin_d = leverage_financing_daily_cost_from_repo(
                        repo_pct,
                        gross_leverage=lev,
                        trading_days_per_year=trading_days_per_year,
                    )
                    rate_source_fin = RATE_SOURCE_REPO_SERIES

        if short_d is None or fin_d is None:
            net_ext = None
        else:
            net_ext = research_net_with_extended_costs(
                g,
                one_way_cost=tx,
                short_borrow_daily=float(short_d),
                financing_daily=float(fin_d),
            )

        row["gross_signed_mean_active"] = g
        row["net_one_way_mean_active"] = (
            (g - tx) if g is not None else None
        )
        row["net_extended_mean_active"] = net_ext
        row["one_way_cost"] = tx
        row["short_borrow_daily"] = short_d
        row["financing_daily"] = fin_d
        row["repo_rate_pct"] = repo_pct
        row["repo_rate_gap"] = repo_gap
        row["repo_rate_date"] = d
        row["short_rate_source"] = rate_source_short
        row["financing_rate_source"] = rate_source_fin
        row["extended_cost_formula"] = (
            "net_extended = gross - one_way - short_borrow_daily - financing_daily"
        )
        row["gap_policy"] = "disclose_only_no_ffill_no_invent"
        out.append(row)
    return out


__all__ = [
    "CONNECTED_TO_MASS",
    "CONNECTED_TO_READY",
    "COST_MODELS_LABEL",
    "COST_MODELS_PROOF",
    "COST_MODELS_VERSION",
    "COST_MODELS_VERSION_V1",
    "COST_MODELS_WAVE",
    "DEFAULT_LEVERAGE_FINANCING_ANNUAL",
    "DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP",
    "DEFAULT_ONE_WAY_COST",
    "DEFAULT_ONE_WAY_COST_BP",
    "DEFAULT_REPO_RATE_TYPE",
    "DEFAULT_REPO_TENOR",
    "DEFAULT_ROUND_TRIP_COST",
    "DEFAULT_SHORT_BORROW_ANNUAL",
    "DEFAULT_SHORT_BORROW_ANNUAL_BP",
    "DEFAULT_SHORT_BORROW_SPREAD_BP",
    "DEFAULT_TRADING_DAYS_PER_YEAR",
    "EDGE_CLAIMED",
    "KNOWN_POSITION_STYLES",
    "MASS_RESEARCH",
    "OPERATIONAL_GO",
    "PHASE7",
    "POSITION_STYLE_LEVERED_LONG",
    "POSITION_STYLE_LEVERED_LONG_SHORT",
    "POSITION_STYLE_LONG_ONLY_UNLEVERED",
    "POSITION_STYLE_LONG_SHORT",
    "RATE_SOURCE_BORROW_PROXY",
    "RATE_SOURCE_FIXED_BP",
    "RATE_SOURCE_NOT_APPLICABLE",
    "RATE_SOURCE_REPO_PLUS_SPREAD",
    "RATE_SOURCE_REPO_SERIES",
    "READY_DECLARED",
    "REPO_DATASET_ID",
    "REPO_TABLE",
    "SHORT_BORROW_SPREAD_HIGH_BP",
    "SHORT_BORROW_SPREAD_LOW_BP",
    "SHORT_BORROW_SPREAD_MID_BP",
    "SHORT_BORROW_SPREAD_SENSITIVITY",
    "SIGNIFICANCE_CLAIMED",
    "annual_bp_to_fraction",
    "annotate_period_rows_with_extended_costs",
    "build_leverage_short_cost_assumption",
    "cost_models_document",
    "date_matched_leverage_financing_costs",
    "date_matched_short_borrow_costs",
    "default_long_only_unlevered_cost_assumption",
    "leverage_financing_daily_cost",
    "leverage_financing_daily_cost_from_repo",
    "load_repo_rate_series",
    "load_repo_rate_series_from_mapping",
    "load_repo_rate_series_from_pit",
    "load_repo_rate_series_from_r2_rows",
    "load_repo_rate_series_from_rows",
    "lookup_repo_rate",
    "mean_repo_rate_pct",
    "repo_rate_pct_to_annual_bp",
    "repo_rate_pct_to_annual_fraction",
    "research_net_with_extended_costs",
    "short_borrow_daily_cost",
    "short_borrow_daily_cost_from_proxy",
    "short_borrow_daily_cost_from_repo",
]
