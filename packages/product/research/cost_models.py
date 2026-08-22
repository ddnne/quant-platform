"""Research cost models: transaction + short borrow + leverage financing.

Research-only (仮定に依存). Does not mint READY / arm Mass / open Phase7.
Repo gaps and missing liquidity are disclosed, never invented or ffilled.

JSDA ``jsda_repo_rates.rate`` is percent: annual = pct/100, annual bp = pct*100.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from research.cost_repo import (
    DEFAULT_REPO_RATE_TYPE,
    DEFAULT_REPO_TENOR,
    REPO_DATASET_ID,
    REPO_TABLE,
    _date_key,
    load_repo_rate_series,
    load_repo_rate_series_from_mapping,
    load_repo_rate_series_from_pit,
    load_repo_rate_series_from_rows,
    lookup_repo_rate,
    mean_repo_rate_pct,
    repo_rate_pct_to_annual_bp,
    repo_rate_pct_to_annual_fraction,
)
from research.freezes import (
    CONNECTED_TO_MASS,
    CONNECTED_TO_READY,
    EDGE_CLAIMED,
    MASS_RESEARCH,
    OPERATIONAL_GO,
    PHASE7,
    READY_DECLARED,
    SIGNIFICANCE_CLAIMED,
)

COST_MODELS_VERSION: str = "research-cost-models/v2"
COST_MODELS_VERSION_V1: str = "research-cost-models/v1"
COST_MODELS_WAVE: str = "W86 / w0816u"
COST_MODELS_LABEL: str = (
    "研究用コストモデル v2・未宣言 "
    "(取引 + 空売り借入 + レバ調達・repo連動優先 + 流動性連動 + "
    "short=repo+spread 感度 L/M/H + paper 日次repo配線 / "
    "READY未接続 / Mass NO-GO)"
)
COST_MODELS_PROOF: str = (
    "docs/proof/w0816u_w86_paper_repo_financing_20260817.md"
)
COST_MODELS_PROOF_SHORT_COST_W85: str = (
    "docs/proof/w0816t_w85_short_cost_repo_spread_20260817.md"
)

# Base transaction (matches robustness_gate / holding_metrics).
DEFAULT_ONE_WAY_COST_BP: float = 10.0
DEFAULT_ONE_WAY_COST: float = DEFAULT_ONE_WAY_COST_BP / 10_000.0  # 0.001
DEFAULT_ROUND_TRIP_COST: float = DEFAULT_ONE_WAY_COST * 2.0

# Fixed-bp placeholders when no repo series is supplied (仮定に依存).
DEFAULT_SHORT_BORROW_ANNUAL_BP: float = 50.0
DEFAULT_SHORT_BORROW_ANNUAL: float = DEFAULT_SHORT_BORROW_ANNUAL_BP / 10_000.0
DEFAULT_TRADING_DAYS_PER_YEAR: int = 245
DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP: float = 25.0
DEFAULT_LEVERAGE_FINANCING_ANNUAL: float = (
    DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP / 10_000.0
)

RATE_SOURCE_FIXED_BP: str = "fixed_bp_placeholder"
RATE_SOURCE_REPO_SERIES: str = "jsda_tokyo_repo_rates"
RATE_SOURCE_REPO_PLUS_SPREAD: str = "repo_plus_borrow_spread"
RATE_SOURCE_BORROW_PROXY: str = "borrow_proxy"
RATE_SOURCE_NOT_APPLICABLE: str = "not_applicable"

# short_annual ≈ repo_annual + spread; mid matches the historical 50bp fallback.
SHORT_BORROW_SPREAD_LOW_BP: float = 25.0
SHORT_BORROW_SPREAD_MID_BP: float = 50.0
SHORT_BORROW_SPREAD_HIGH_BP: float = 150.0
DEFAULT_SHORT_BORROW_SPREAD_BP: float = SHORT_BORROW_SPREAD_MID_BP
SHORT_BORROW_SPREAD_SENSITIVITY: dict[str, float] = {
    "low": SHORT_BORROW_SPREAD_LOW_BP,
    "mid": SHORT_BORROW_SPREAD_MID_BP,
    "high": SHORT_BORROW_SPREAD_HIGH_BP,
}

LIQUIDITY_DATASET_ID: str = "equities_bars_daily"
LIQUIDITY_PROXY_UNIT: str = "jpy_adv"
LIQUIDITY_BUCKET_HIGH: str = "high"
LIQUIDITY_BUCKET_MID: str = "mid"
LIQUIDITY_BUCKET_LOW: str = "low"
LIQUIDITY_BUCKET_MISSING: str = "missing"
KNOWN_LIQUIDITY_BUCKETS: tuple[str, ...] = (
    LIQUIDITY_BUCKET_HIGH,
    LIQUIDITY_BUCKET_MID,
    LIQUIDITY_BUCKET_LOW,
)
LIQUIDITY_ADV_HIGH_JPY: float = 1_000_000_000.0  # 1e9
LIQUIDITY_ADV_MID_JPY: float = 100_000_000.0  # 1e8
LIQUIDITY_TX_MULT: dict[str, float] = {
    LIQUIDITY_BUCKET_HIGH: 1.0,
    LIQUIDITY_BUCKET_MID: 1.5,
    LIQUIDITY_BUCKET_LOW: 2.5,
}
LIQUIDITY_SHORT_SPREAD_MULT: dict[str, float] = {
    LIQUIDITY_BUCKET_HIGH: 1.0,
    LIQUIDITY_BUCKET_MID: 1.5,
    LIQUIDITY_BUCKET_LOW: 2.0,
}
LIQUIDITY_TOPIX_SOFT_UPGRADE: bool = True

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


def _pick_num_field(row: Mapping[str, Any], *keys: str) -> float | None:
    for k in keys:
        if k not in row:
            continue
        v = row.get(k)
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def yen_turnover_from_bar(row: Mapping[str, Any]) -> dict[str, Any]:
    """Extract one bar's yen turnover. Gap → value None (no invent).

    Priority:
    1. ``turnover_value`` / TurnoverValue / Va (売買代金)
    2. ``close * volume``
    3. ``adjustment_close * adjustment_volume``
    """
    d = _date_key(row.get("date") or row.get("Date") or row.get("as_of_date"))
    code = row.get("code") or row.get("Code")
    tv = _pick_num_field(
        row, "turnover_value", "TurnoverValue", "turnoverValue", "Va"
    )
    if tv is not None and tv >= 0:
        return {
            "date": d,
            "code": str(code) if code is not None else None,
            "yen_turnover": float(tv),
            "source_field": "turnover_value",
            "is_gap": False,
        }
    close = _pick_num_field(row, "close", "Close", "C")
    vol = _pick_num_field(row, "volume", "Volume", "Vo")
    if close is not None and vol is not None and close >= 0 and vol >= 0:
        return {
            "date": d,
            "code": str(code) if code is not None else None,
            "yen_turnover": float(close) * float(vol),
            "source_field": "close_x_volume",
            "is_gap": False,
        }
    adj_c = _pick_num_field(
        row, "adjustment_close", "AdjustmentClose", "AdjClose", "AdjC"
    )
    adj_v = _pick_num_field(
        row, "adjustment_volume", "AdjustmentVolume", "AdjVolume", "AdjVo"
    )
    if adj_c is not None and adj_v is not None and adj_c >= 0 and adj_v >= 0:
        return {
            "date": d,
            "code": str(code) if code is not None else None,
            "yen_turnover": float(adj_c) * float(adj_v),
            "source_field": "adjustment_close_x_adjustment_volume",
            "is_gap": False,
        }
    return {
        "date": d,
        "code": str(code) if code is not None else None,
        "yen_turnover": None,
        "source_field": None,
        "is_gap": True,
        "reason": "missing_turnover_and_price_volume",
    }


def compute_liquidity_proxy_from_bars(
    bars: Sequence[Mapping[str, Any]] | None,
    *,
    required_dates: Sequence[Any] | None = None,
    is_topix: bool | None = None,
    scale_category: str | None = None,
    source_label: str = "equities_bars",
) -> dict[str, Any]:
    """Compute ADV (JPY) liquidity proxy from equities bar rows.

    **No invent fill** on missing bars/fields — gaps disclosed.
    """
    bars = list(bars or [])
    by_date: dict[str, float] = {}
    gap_bar_dates: list[str] = []
    source_fields: dict[str, int] = {}
    for raw in bars:
        hit = yen_turnover_from_bar(raw)
        d = hit.get("date")
        if hit.get("is_gap") or hit.get("yen_turnover") is None:
            if d is not None:
                gap_bar_dates.append(str(d))
            continue
        d_s = str(d) if d is not None else f"_nodate_{len(by_date)}"
        # If multiple rows share a date (cross-section), accumulate then
        # we'll mean later; for single-name bars last-write is fine, for
        # multi-name sum per date then mean over dates of daily totals.
        by_date[d_s] = by_date.get(d_s, 0.0) + float(hit["yen_turnover"])
        sf = str(hit.get("source_field") or "unknown")
        source_fields[sf] = int(source_fields.get(sf, 0)) + 1

    req: list[str] = []
    if required_dates is not None:
        seen: set[str] = set()
        for raw in required_dates:
            d = _date_key(raw)
            if d is not None and d not in seen:
                seen.add(d)
                req.append(d)
    req_gaps = [d for d in req if d not in by_date]

    vals = list(by_date.values())
    n_obs = len(vals)
    adv: float | None = (sum(vals) / float(n_obs)) if n_obs > 0 else None

    return {
        "kind": "liquidity_proxy",
        "version": COST_MODELS_VERSION,
        "dataset": LIQUIDITY_DATASET_ID,
        "proxy_unit": LIQUIDITY_PROXY_UNIT,
        "formula": (
            "ADV = mean_t(turnover_value[t] "
            "or close[t]*volume[t] "
            "or adjustment_close[t]*adjustment_volume[t]); "
            "missing fields → gap (no invent)"
        ),
        "adv_jpy": adv,
        "n_obs": n_obs,
        "n_input_bars": len(bars),
        "by_date_yen_turnover": dict(sorted(by_date.items())),
        "source_field_counts": source_fields,
        "required_dates": list(req),
        "gap_dates": list(req_gaps),
        "gap_bar_dates": gap_bar_dates,
        "n_gaps": len(req_gaps),
        "coverage_complete": (len(req_gaps) == 0 if req else n_obs > 0),
        "is_gap": adv is None,
        "ffill_applied": False,
        "invent_fill": False,
        "gap_policy": "disclose_only_no_ffill_no_invent",
        "is_topix": is_topix,
        "scale_category": scale_category,
        "source_label": source_label,
        "note": (
            "Liquidity proxy from equities_bars yen turnover. "
            "Missing bars/fields are gap-flagged; never invented."
        ),
        **_freeze_fields(),
    }


def compute_liquidity_proxy_from_adv(
    adv_jpy: float | None,
    *,
    n_obs: int | None = None,
    is_topix: bool | None = None,
    scale_category: str | None = None,
    source_label: str = "adv_scalar",
    gap_dates: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Build a liquidity proxy envelope from a precomputed ADV (JPY/day).

    ``adv_jpy is None`` → gap (no invent).
    """
    gaps = []
    if gap_dates is not None:
        for raw in gap_dates:
            d = _date_key(raw)
            if d is not None:
                gaps.append(d)
    is_gap = adv_jpy is None
    try:
        adv_f = float(adv_jpy) if adv_jpy is not None else None
    except (TypeError, ValueError):
        adv_f = None
        is_gap = True
    if adv_f is not None and adv_f < 0:
        adv_f = None
        is_gap = True
    return {
        "kind": "liquidity_proxy",
        "version": COST_MODELS_VERSION,
        "dataset": LIQUIDITY_DATASET_ID,
        "proxy_unit": LIQUIDITY_PROXY_UNIT,
        "formula": "ADV supplied as scalar (precomputed); None → gap",
        "adv_jpy": adv_f,
        "n_obs": int(n_obs) if n_obs is not None else (0 if is_gap else 1),
        "n_input_bars": None,
        "by_date_yen_turnover": {},
        "source_field_counts": {},
        "required_dates": [],
        "gap_dates": list(gaps),
        "gap_bar_dates": [],
        "n_gaps": len(gaps),
        "coverage_complete": not is_gap and len(gaps) == 0,
        "is_gap": is_gap,
        "ffill_applied": False,
        "invent_fill": False,
        "gap_policy": "disclose_only_no_ffill_no_invent",
        "is_topix": is_topix,
        "scale_category": scale_category,
        "source_label": source_label,
        "note": (
            "Precomputed ADV. None/invalid → gap disclose; never invent."
        ),
        **_freeze_fields(),
    }


def _scale_category_is_large(scale_category: str | None) -> bool:
    if scale_category is None:
        return False
    s = str(scale_category).strip().lower()
    if not s:
        return False
    # JQuants ScaleCategory examples: TOPIX Large70, TOPIX Mid400, etc.
    large_tokens = ("large", "core30", "large70", "topix100")
    return any(t in s for t in large_tokens)


def liquidity_bucket_from_proxy(
    proxy: Mapping[str, Any] | float | None,
    *,
    high_jpy: float = LIQUIDITY_ADV_HIGH_JPY,
    mid_jpy: float = LIQUIDITY_ADV_MID_JPY,
    apply_topix_soft_upgrade: bool = LIQUIDITY_TOPIX_SOFT_UPGRADE,
) -> dict[str, Any]:
    """Map ADV proxy → high/mid/low bucket. Missing → ``missing`` (no invent)."""
    adv: float | None
    is_topix: bool | None = None
    scale_category: str | None = None
    proxy_doc: dict[str, Any] | None = None

    if proxy is None:
        adv = None
    elif isinstance(proxy, (int, float)) and not isinstance(proxy, bool):
        try:
            adv = float(proxy)
        except (TypeError, ValueError):
            adv = None
    elif isinstance(proxy, Mapping):
        proxy_doc = dict(proxy)
        raw_adv = proxy.get("adv_jpy")
        if raw_adv is None and proxy.get("is_gap"):
            adv = None
        else:
            try:
                adv = float(raw_adv) if raw_adv is not None else None
            except (TypeError, ValueError):
                adv = None
        is_topix = proxy.get("is_topix")
        if is_topix is not None:
            is_topix = bool(is_topix)
        scale_category = (
            str(proxy.get("scale_category"))
            if proxy.get("scale_category") is not None
            else None
        )
    else:
        adv = None

    if adv is None:
        return {
            "kind": "liquidity_bucket",
            "version": COST_MODELS_VERSION,
            "bucket": LIQUIDITY_BUCKET_MISSING,
            "adv_jpy": None,
            "is_gap": True,
            "thresholds_jpy": {
                "high": float(high_jpy),
                "mid": float(mid_jpy),
            },
            "soft_upgrade_applied": False,
            "is_topix": is_topix,
            "scale_category": scale_category,
            "formula": (
                f"high if ADV>={high_jpy:g}; mid if ADV>={mid_jpy:g}; "
                "low if ADV observed else missing"
            ),
            "proxy": proxy_doc,
            "ffill_applied": False,
            "invent_fill": False,
            "gap_policy": "disclose_only_no_ffill_no_invent",
            "note": "No ADV observed — liquidity bucket missing (no invent).",
            **_freeze_fields(),
        }

    raw_bucket: str
    if float(adv) >= float(high_jpy):
        raw_bucket = LIQUIDITY_BUCKET_HIGH
    elif float(adv) >= float(mid_jpy):
        raw_bucket = LIQUIDITY_BUCKET_MID
    else:
        raw_bucket = LIQUIDITY_BUCKET_LOW

    soft = False
    bucket = raw_bucket
    membership_large = bool(is_topix) or _scale_category_is_large(scale_category)
    if apply_topix_soft_upgrade and membership_large:
        if raw_bucket == LIQUIDITY_BUCKET_LOW:
            bucket = LIQUIDITY_BUCKET_MID
            soft = True
        elif raw_bucket == LIQUIDITY_BUCKET_MID:
            bucket = LIQUIDITY_BUCKET_HIGH
            soft = True

    return {
        "kind": "liquidity_bucket",
        "version": COST_MODELS_VERSION,
        "bucket": bucket,
        "raw_bucket": raw_bucket,
        "adv_jpy": float(adv),
        "is_gap": False,
        "thresholds_jpy": {
            "high": float(high_jpy),
            "mid": float(mid_jpy),
        },
        "soft_upgrade_applied": soft,
        "is_topix": is_topix,
        "scale_category": scale_category,
        "formula": (
            f"high if ADV>={high_jpy:g}; mid if ADV>={mid_jpy:g}; "
            "low if ADV observed else missing; "
            "optional TOPIX/large soft upgrade one step"
        ),
        "proxy": proxy_doc,
        "ffill_applied": False,
        "invent_fill": False,
        "gap_policy": "disclose_only_no_ffill_no_invent",
        "note": (
            "Research ADV bucket. Soft TOPIX/large upgrade only when ADV "
            "is observed — membership alone never invents a bucket."
        ),
        **_freeze_fields(),
    }


def liquidity_cost_multipliers(
    bucket: str | Mapping[str, Any] | None,
    *,
    tx_mult_map: Mapping[str, float] | None = None,
    short_spread_mult_map: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Return tx / short-spread multipliers for a liquidity bucket.

    Missing / unknown bucket → multipliers 1.0 (unmodulated) + gap flag.
    """
    tx_map = dict(tx_mult_map or LIQUIDITY_TX_MULT)
    sp_map = dict(short_spread_mult_map or LIQUIDITY_SHORT_SPREAD_MULT)

    b: str | None
    is_gap = False
    if bucket is None:
        b = LIQUIDITY_BUCKET_MISSING
        is_gap = True
    elif isinstance(bucket, Mapping):
        b = str(bucket.get("bucket") or LIQUIDITY_BUCKET_MISSING)
        is_gap = bool(bucket.get("is_gap")) or b == LIQUIDITY_BUCKET_MISSING
    else:
        b = str(bucket).strip().lower()
        if b not in KNOWN_LIQUIDITY_BUCKETS:
            if b in ("missing", "none", "gap", ""):
                b = LIQUIDITY_BUCKET_MISSING
                is_gap = True
            else:
                raise ValueError(
                    f"liquidity bucket must be one of "
                    f"{list(KNOWN_LIQUIDITY_BUCKETS)} or missing; got {bucket!r}"
                )

    if is_gap or b == LIQUIDITY_BUCKET_MISSING:
        return {
            "kind": "liquidity_cost_multipliers",
            "version": COST_MODELS_VERSION,
            "bucket": LIQUIDITY_BUCKET_MISSING,
            "is_gap": True,
            "tx_mult": 1.0,
            "short_spread_mult": 1.0,
            "tx_mult_map": dict(tx_map),
            "short_spread_mult_map": dict(sp_map),
            "modulated": False,
            "formula": (
                "one_way_eff = one_way_base * tx_mult; "
                "spread_eff = spread_base * short_spread_mult; "
                "missing → mult=1.0 unmodulated (no invent)"
            ),
            "note": (
                "Liquidity missing — costs unmodulated (mult=1.0); gap disclosed."
            ),
            **_freeze_fields(),
        }

    return {
        "kind": "liquidity_cost_multipliers",
        "version": COST_MODELS_VERSION,
        "bucket": b,
        "is_gap": False,
        "tx_mult": float(tx_map[b]),
        "short_spread_mult": float(sp_map[b]),
        "tx_mult_map": dict(tx_map),
        "short_spread_mult_map": dict(sp_map),
        "modulated": True,
        "formula": (
            "one_way_eff = one_way_base * tx_mult[bucket]; "
            "spread_eff_bp = spread_base_bp * short_spread_mult[bucket]"
        ),
        "note": (
            "Research liquidity multipliers. high→base; low→higher costs."
        ),
        **_freeze_fields(),
    }


def resolve_liquidity_modulation(
    *,
    liquidity_proxy: Mapping[str, Any] | float | None = None,
    liquidity_bars: Sequence[Mapping[str, Any]] | None = None,
    liquidity_bucket: str | None = None,
    liquidity_adv_jpy: float | None = None,
    is_topix: bool | None = None,
    scale_category: str | None = None,
    required_dates: Sequence[Any] | None = None,
    high_jpy: float = LIQUIDITY_ADV_HIGH_JPY,
    mid_jpy: float = LIQUIDITY_ADV_MID_JPY,
    prefer_liquidity_linked: bool = True,
    apply_topix_soft_upgrade: bool = LIQUIDITY_TOPIX_SOFT_UPGRADE,
) -> dict[str, Any]:
    """Resolve liquidity proxy → bucket → multipliers (gap-safe).

    Priority for inputs:
    1. explicit ``liquidity_bucket`` (if known high/mid/low)
    2. ``liquidity_proxy`` envelope or ADV scalar
    3. ``liquidity_adv_jpy`` scalar
    4. ``liquidity_bars`` → compute proxy
    5. none → missing gap

    When ``prefer_liquidity_linked=False``, still computes disclosure but
    forces ``modulated=False`` and mult=1.0.
    """
    proxy_doc: dict[str, Any] | None = None
    bucket_doc: dict[str, Any]

    explicit_bucket = None
    if liquidity_bucket is not None:
        key = str(liquidity_bucket).strip().lower()
        if key in KNOWN_LIQUIDITY_BUCKETS:
            explicit_bucket = key
        elif key in ("missing", "none", "gap", ""):
            explicit_bucket = LIQUIDITY_BUCKET_MISSING
        else:
            raise ValueError(
                f"liquidity_bucket must be one of "
                f"{list(KNOWN_LIQUIDITY_BUCKETS)} or missing; "
                f"got {liquidity_bucket!r}"
            )

    if explicit_bucket is not None and explicit_bucket != LIQUIDITY_BUCKET_MISSING:
        bucket_doc = {
            "kind": "liquidity_bucket",
            "version": COST_MODELS_VERSION,
            "bucket": explicit_bucket,
            "raw_bucket": explicit_bucket,
            "adv_jpy": None,
            "is_gap": False,
            "thresholds_jpy": {"high": float(high_jpy), "mid": float(mid_jpy)},
            "soft_upgrade_applied": False,
            "is_topix": is_topix,
            "scale_category": scale_category,
            "formula": "explicit bucket override",
            "proxy": None,
            "ffill_applied": False,
            "invent_fill": False,
            "gap_policy": "disclose_only_no_ffill_no_invent",
            "note": "Explicit liquidity_bucket supplied by caller.",
            **_freeze_fields(),
        }
    else:
        if liquidity_proxy is not None:
            if isinstance(liquidity_proxy, Mapping):
                proxy_doc = dict(liquidity_proxy)
                # Allow injecting membership if not already on proxy.
                if is_topix is not None and proxy_doc.get("is_topix") is None:
                    proxy_doc["is_topix"] = is_topix
                if (
                    scale_category is not None
                    and proxy_doc.get("scale_category") is None
                ):
                    proxy_doc["scale_category"] = scale_category
            else:
                proxy_doc = compute_liquidity_proxy_from_adv(
                    float(liquidity_proxy)
                    if liquidity_proxy is not None
                    else None,
                    is_topix=is_topix,
                    scale_category=scale_category,
                )
        elif liquidity_adv_jpy is not None:
            proxy_doc = compute_liquidity_proxy_from_adv(
                liquidity_adv_jpy,
                is_topix=is_topix,
                scale_category=scale_category,
            )
        elif liquidity_bars is not None:
            proxy_doc = compute_liquidity_proxy_from_bars(
                liquidity_bars,
                required_dates=required_dates,
                is_topix=is_topix,
                scale_category=scale_category,
            )
        elif explicit_bucket == LIQUIDITY_BUCKET_MISSING:
            proxy_doc = compute_liquidity_proxy_from_adv(
                None,
                is_topix=is_topix,
                scale_category=scale_category,
                source_label="explicit_missing",
            )
        else:
            proxy_doc = compute_liquidity_proxy_from_adv(
                None,
                is_topix=is_topix,
                scale_category=scale_category,
                source_label="empty",
            )
        bucket_doc = liquidity_bucket_from_proxy(
            proxy_doc,
            high_jpy=high_jpy,
            mid_jpy=mid_jpy,
            apply_topix_soft_upgrade=apply_topix_soft_upgrade,
        )

    mults = liquidity_cost_multipliers(bucket_doc)
    prefer = bool(prefer_liquidity_linked)
    applied = bool(prefer and mults.get("modulated"))
    if not prefer:
        # Still disclose bucket, but force unmodulated costs.
        mults = dict(mults)
        mults["tx_mult"] = 1.0
        mults["short_spread_mult"] = 1.0
        mults["modulated"] = False
        mults["prefer_liquidity_linked"] = False
        mults["note"] = (
            "prefer_liquidity_linked=False; multipliers forced to 1.0 "
            "(bucket still disclosed)."
        )
    else:
        mults = dict(mults)
        mults["prefer_liquidity_linked"] = True

    return {
        "kind": "liquidity_modulation",
        "version": COST_MODELS_VERSION,
        "wave": COST_MODELS_WAVE,
        "prefer_liquidity_linked": prefer,
        "applied": applied,
        "is_gap": bool(bucket_doc.get("is_gap") or mults.get("is_gap")),
        "bucket": bucket_doc.get("bucket"),
        "adv_jpy": bucket_doc.get("adv_jpy"),
        "tx_mult": float(mults["tx_mult"]),
        "short_spread_mult": float(mults["short_spread_mult"]),
        "proxy": proxy_doc,
        "bucket_detail": bucket_doc,
        "multipliers": mults,
        "dataset": LIQUIDITY_DATASET_ID,
        "ffill_applied": False,
        "invent_fill": False,
        "gap_policy": "disclose_only_no_ffill_no_invent",
        "formula": (
            "one_way_eff = one_way_base * tx_mult[bucket]; "
            "spread_eff = short_sensitivity_spread * short_spread_mult[bucket]; "
            "missing liquidity → mult=1.0, gap disclosed (no invent)"
        ),
        "note": (
            "Liquidity-linked cost modulation (W79). Combines with short "
            "low/mid/high sensitivity. Missing liquidity never invented."
        ),
        **_freeze_fields(),
    }


def apply_liquidity_to_one_way_cost(
    one_way_cost: float,
    *,
    tx_mult: float = 1.0,
) -> float:
    """``one_way_eff = one_way_base * tx_mult``."""
    return float(one_way_cost) * float(tx_mult)


def apply_liquidity_to_short_spread_bp(
    spread_bp: float,
    *,
    short_spread_mult: float = 1.0,
) -> float:
    """``spread_eff_bp = spread_base_bp * short_spread_mult``."""
    return float(spread_bp) * float(short_spread_mult)


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



def resolve_short_borrow_spread_bp(
    *,
    sensitivity: str | None = None,
    spread_bp: float | None = None,
) -> tuple[float, str | None]:
    """Resolve short-borrow spread bp and band label (low/mid/high).

    ``sensitivity`` overrides ``spread_bp`` via documented bands
    (25 / 50 / 150). When only ``spread_bp`` is given, label is inferred on
    exact band match (else ``None``). Default = mid 50bp.
    """
    if sensitivity is not None:
        key = str(sensitivity).strip().lower()
        if key not in SHORT_BORROW_SPREAD_SENSITIVITY:
            raise ValueError(
                f"sensitivity must be one of "
                f"{list(SHORT_BORROW_SPREAD_SENSITIVITY)}, got {sensitivity!r}"
            )
        return float(SHORT_BORROW_SPREAD_SENSITIVITY[key]), key
    bp = (
        float(spread_bp)
        if spread_bp is not None
        else float(DEFAULT_SHORT_BORROW_SPREAD_BP)
    )
    label: str | None = None
    for k, v in SHORT_BORROW_SPREAD_SENSITIVITY.items():
        if abs(bp - float(v)) < 1e-12:
            label = k
            break
    return bp, label


def short_borrow_hold_cost_from_repo(
    repo_rate_pct: float,
    *,
    hold_days: int = 1,
    short_fraction: float = 0.5,
    spread_bp: float = DEFAULT_SHORT_BORROW_SPREAD_BP,
    sensitivity: str | None = None,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
) -> float:
    """Hold-period short cost = daily(repo[t] + spread) * hold_days.

    Approved multi-day L-S approximation (W85): continuous borrow over the
    sticky hold horizon. ``short_fraction`` scales book short exposure
    (0.5 for equal L-S books).
    """
    h = max(int(hold_days), 1)
    daily = short_borrow_daily_cost_from_repo(
        float(repo_rate_pct),
        short_fraction=short_fraction,
        spread_bp=spread_bp,
        sensitivity=sensitivity,
        trading_days_per_year=trading_days_per_year,
    )
    return float(daily) * float(h)


def short_cost_sensitivity_bands(
    repo_rate_pct: float | None,
    *,
    hold_days: int = 1,
    short_fraction: float = 0.5,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
    liquidity_short_spread_mult: float = 1.0,
) -> dict[str, Any]:
    """Low/mid/high short-cost table for a single repo observation (or gap).

    On repo gap (``repo_rate_pct is None``) costs are ``None`` — never invent.
    """
    h = max(int(hold_days), 1)
    mult = float(liquidity_short_spread_mult)
    bands: dict[str, Any] = {}
    for label, base_bp in SHORT_BORROW_SPREAD_SENSITIVITY.items():
        spread_eff = float(base_bp) * mult
        if repo_rate_pct is None:
            bands[label] = {
                "sensitivity": label,
                "spread_base_bp": float(base_bp),
                "spread_eff_bp": spread_eff,
                "is_gap": True,
                "repo_rate_pct": None,
                "short_annual_bp": None,
                "short_borrow_daily": None,
                "short_borrow_hold": None,
                "short_borrow_daily_bp": None,
                "short_borrow_hold_bp": None,
            }
            continue
        repo_bp = repo_rate_pct_to_annual_bp(float(repo_rate_pct))
        annual_bp = repo_bp + spread_eff
        daily = short_borrow_daily_cost(
            short_borrow_annual_bp=annual_bp,
            trading_days_per_year=trading_days_per_year,
            short_fraction=short_fraction,
        )
        hold = float(daily) * float(h)
        bands[label] = {
            "sensitivity": label,
            "spread_base_bp": float(base_bp),
            "spread_eff_bp": spread_eff,
            "is_gap": False,
            "repo_rate_pct": float(repo_rate_pct),
            "repo_annual_bp": repo_bp,
            "short_annual_bp": annual_bp,
            "short_borrow_daily": daily,
            "short_borrow_hold": hold,
            "short_borrow_daily_bp": daily * 10_000.0,
            "short_borrow_hold_bp": hold * 10_000.0,
        }
    return {
        "kind": "short_cost_sensitivity_bands",
        "version": COST_MODELS_VERSION,
        "wave": COST_MODELS_WAVE,
        "formula": (
            "short_annual_bp = repo_pct*100 + spread_base*liq_mult; "
            "daily = (annual_bp/10000)/trading_days * short_fraction; "
            "hold = daily * hold_days"
        ),
        "hold_days": h,
        "short_fraction": float(short_fraction),
        "trading_days_per_year": int(trading_days_per_year),
        "liquidity_short_spread_mult": mult,
        "sensitivity_bands_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
        "bands": bands,
        "gap_policy": "disclose_only_no_ffill_no_invent",
        "default_sensitivity": "mid",
        **_freeze_fields(),
    }


def research_net_with_short_hold_cost(
    gross_signed_mean: float | None,
    *,
    amortized_one_way_cost: float = 0.0,
    short_borrow_hold: float | None = 0.0,
) -> float | None:
    """Multi-day research net = gross − am_tx − short_hold.

    ``short_borrow_hold`` may be ``None`` on repo gap (no invent → net None).
    """
    if gross_signed_mean is None:
        return None
    if short_borrow_hold is None:
        return None
    try:
        g = float(gross_signed_mean)
    except (TypeError, ValueError):
        return None
    return g - float(amortized_one_way_cost) - float(short_borrow_hold)


def remeasure_period_rows_with_short_cost(
    period_rows: Sequence[Mapping[str, Any]],
    *,
    repo_rate_series: Mapping[str, Any] | None = None,
    short_fraction: float = 0.5,
    hold_days: int | None = None,
    hold_days_field: str = "hold_days",
    date_field: str = "period_end",
    default_sensitivity: str = "mid",
    sensitivities: Sequence[str] = ("low", "mid", "high"),
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
    liquidity_short_spread_mult: float = 1.0,
    apply_primary_net: bool = True,
    fallback_mean_repo_when_date_gap: bool = False,
) -> dict[str, Any]:
    """Remeasure L-S period rows with short = f(repo[t] + spread) · hold.

    Primary net (``default_sensitivity``, mid) is written to
    ``net_one_way_mean_active`` when ``apply_primary_net`` (CS L-S remeasure
    path). Full low/mid/high nets kept under ``short_cost_sensitivity``.

    **Gap policy:** date-matched repo lookup; missing date → short cost None
    for that row (never ffill). Optional ``fallback_mean_repo_when_date_gap``
    is **off by default** (no invent). When True, uses observed-only mean
    with explicit ``rate_source=mean_repo_fallback`` disclosure — still not
    a per-date invent fill.
    """
    sens_list = [str(s).strip().lower() for s in sensitivities]
    for s in sens_list:
        if s not in SHORT_BORROW_SPREAD_SENSITIVITY:
            raise ValueError(
                f"unknown sensitivity {s!r}; "
                f"expected one of {list(SHORT_BORROW_SPREAD_SENSITIVITY)}"
            )
    primary = str(default_sensitivity).strip().lower()
    if primary not in SHORT_BORROW_SPREAD_SENSITIVITY:
        raise ValueError(f"default_sensitivity must be a known band, got {primary!r}")

    mean_repo: dict[str, Any] | None = None
    mean_pct: float | None = None
    if repo_rate_series is not None:
        mean_repo = mean_repo_rate_pct(repo_rate_series)
        mean_pct = mean_repo.get("mean_rate_pct")
        if mean_pct is not None:
            mean_pct = float(mean_pct)

    out_rows: list[dict[str, Any]] = []
    n_gaps = 0
    n_obs = 0
    primary_nets: list[float] = []

    for raw in period_rows:
        row = dict(raw)
        status = str(row.get("status") or "ok")
        gross = row.get("gross_signed_mean_active")
        if gross is None:
            gross = row.get("gross_signed_mean")
        try:
            g = float(gross) if gross is not None else None
        except (TypeError, ValueError):
            g = None

        am_tx = row.get("amortized_one_way_cost")
        if am_tx is None:
            am_tx = row.get("one_way_cost_eff")
        if am_tx is None:
            am_tx = row.get("one_way_cost", 0.0)
        try:
            am = float(am_tx) if am_tx is not None else 0.0
        except (TypeError, ValueError):
            am = 0.0

        h = hold_days
        if h is None:
            try:
                h = int(row.get(hold_days_field) or 1)
            except (TypeError, ValueError):
                h = 1
        h = max(int(h), 1)

        d = _date_key(
            row.get(date_field) or row.get("date") or row.get("as_of_date")
        )
        repo_pct: float | None = None
        repo_gap = False
        rate_source = RATE_SOURCE_FIXED_BP
        if status != "ok" or g is None:
            row["short_cost_sensitivity"] = {}
            row["short_borrow_hold"] = None
            row["short_borrow_sensitivity"] = primary
            row["repo_rate_gap"] = False
            out_rows.append(row)
            continue

        if repo_rate_series is not None and d is not None:
            hit = lookup_repo_rate(repo_rate_series, d)
            if hit["is_gap"]:
                repo_gap = True
                if fallback_mean_repo_when_date_gap and mean_pct is not None:
                    repo_pct = mean_pct
                    rate_source = "mean_repo_fallback"
                    repo_gap = False  # cost computable via disclosed mean
                else:
                    rate_source = RATE_SOURCE_REPO_PLUS_SPREAD
            else:
                repo_pct = float(hit["rate_pct"])
                rate_source = RATE_SOURCE_REPO_PLUS_SPREAD
        elif mean_pct is not None:
            # No per-date key — use observed mean (disclosed)
            repo_pct = mean_pct
            rate_source = "mean_repo_series"
        else:
            # No series at all → fixed-bp placeholder path (disclosed)
            repo_pct = 0.0
            rate_source = RATE_SOURCE_FIXED_BP

        if repo_gap and repo_pct is None:
            n_gaps += 1
            sens_map: dict[str, Any] = {}
            for label in sens_list:
                sens_map[label] = {
                    "sensitivity": label,
                    "is_gap": True,
                    "short_borrow_hold": None,
                    "net_with_short": None,
                }
            row["short_cost_sensitivity"] = sens_map
            row["short_borrow_hold"] = None
            row["short_borrow_sensitivity"] = primary
            row["repo_rate_pct"] = None
            row["repo_rate_gap"] = True
            row["repo_rate_date"] = d
            row["short_rate_source"] = rate_source
            row["net_tx_only_mean_active"] = g - am
            if apply_primary_net:
                # Gap: do not invent short cost; leave tx-only net and flag.
                row["net_one_way_mean_active"] = g - am
                row["short_cost_applied"] = False
            out_rows.append(row)
            continue

        n_obs += 1
        bands = short_cost_sensitivity_bands(
            repo_pct,
            hold_days=h,
            short_fraction=short_fraction,
            trading_days_per_year=trading_days_per_year,
            liquidity_short_spread_mult=liquidity_short_spread_mult,
        )["bands"]
        sens_map = {}
        for label in sens_list:
            b = bands[label]
            hold_cost = b.get("short_borrow_hold")
            net_s = research_net_with_short_hold_cost(
                g, amortized_one_way_cost=am, short_borrow_hold=hold_cost
            )
            sens_map[label] = {
                "sensitivity": label,
                "spread_base_bp": b.get("spread_base_bp"),
                "spread_eff_bp": b.get("spread_eff_bp"),
                "short_annual_bp": b.get("short_annual_bp"),
                "short_borrow_daily": b.get("short_borrow_daily"),
                "short_borrow_hold": hold_cost,
                "short_borrow_hold_bp": (
                    (hold_cost * 10_000.0) if hold_cost is not None else None
                ),
                "net_with_short": net_s,
                "net_with_short_bp": (
                    (net_s * 10_000.0) if net_s is not None else None
                ),
                "is_gap": False,
            }
        primary_hold = sens_map[primary]["short_borrow_hold"]
        primary_net = sens_map[primary]["net_with_short"]
        row["short_cost_sensitivity"] = sens_map
        row["short_borrow_hold"] = primary_hold
        row["short_borrow_hold_bp"] = (
            (primary_hold * 10_000.0) if primary_hold is not None else None
        )
        row["short_borrow_sensitivity"] = primary
        row["repo_rate_pct"] = repo_pct
        row["repo_rate_gap"] = False
        row["repo_rate_date"] = d
        row["short_rate_source"] = rate_source
        row["short_fraction"] = float(short_fraction)
        row["hold_days_for_short_cost"] = h
        row["net_tx_only_mean_active"] = g - am
        row["short_cost_applied"] = True
        row["short_cost_formula"] = (
            "net = gross - amortized_one_way - "
            "short_borrow_daily(repo[t]+spread)*hold_days"
        )
        if apply_primary_net and primary_net is not None:
            row["net_one_way_mean_active"] = primary_net
            primary_nets.append(float(primary_net))
        elif primary_net is not None:
            row["net_with_short_mean_active"] = primary_net
            primary_nets.append(float(primary_net))
        out_rows.append(row)

    # Summary table low/mid/high over ok rows with short applied
    summary_bands: dict[str, Any] = {}
    for label in sens_list:
        nets: list[float] = []
        holds: list[float] = []
        for r in out_rows:
            if r.get("status") not in (None, "ok"):
                continue
            sc = (r.get("short_cost_sensitivity") or {}).get(label) or {}
            n = sc.get("net_with_short")
            if n is not None:
                nets.append(float(n))
            hc = sc.get("short_borrow_hold")
            if hc is not None:
                holds.append(float(hc))
        summary_bands[label] = {
            "sensitivity": label,
            "spread_bp": float(SHORT_BORROW_SPREAD_SENSITIVITY[label]),
            "n_periods": len(nets),
            "mean_net": (sum(nets) / len(nets)) if nets else None,
            "mean_net_bp": (
                (sum(nets) / len(nets)) * 10_000.0 if nets else None
            ),
            "mean_short_hold": (sum(holds) / len(holds)) if holds else None,
            "mean_short_hold_bp": (
                (sum(holds) / len(holds)) * 10_000.0 if holds else None
            ),
        }

    return {
        "kind": "remeasure_period_rows_with_short_cost",
        "version": COST_MODELS_VERSION,
        "wave": COST_MODELS_WAVE,
        "proof": COST_MODELS_PROOF,
        "formula": (
            "short_annual = repo_annual_bp + spread_bp[low|mid|high]; "
            "hold_cost = daily(short_annual, short_frac) * hold_days; "
            "net = gross - amortized_one_way - hold_cost"
        ),
        "default_sensitivity": primary,
        "sensitivities": list(sens_list),
        "sensitivity_bands_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
        "short_fraction": float(short_fraction),
        "trading_days_per_year": int(trading_days_per_year),
        "liquidity_short_spread_mult": float(liquidity_short_spread_mult),
        "apply_primary_net": bool(apply_primary_net),
        "fallback_mean_repo_when_date_gap": bool(fallback_mean_repo_when_date_gap),
        "n_rows": len(out_rows),
        "n_short_cost_obs": n_obs,
        "n_repo_gaps": n_gaps,
        "mean_repo": mean_repo,
        "summary_by_sensitivity": summary_bands,
        "period_rows": out_rows,
        "gap_policy": "disclose_only_no_ffill_no_invent",
        "assumptions": {
            "short_cost": "f(repo_rate[t]) + fixed_spread_bp",
            "spread_sensitivity_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
            "hold_scaling": "daily * hold_days (continuous borrow over sticky hold)",
            "short_fraction_default": 0.5,
            "repo_gaps": "no invent / no ffill; cost None or tx-only net flagged",
            "not_broker_quote": True,
            "research_only": True,
        },
        **_freeze_fields(),
    }


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
    repo_rate_series: Mapping[str, Any] | None = None,
    prefer_repo_linked: bool = True,
    short_borrow_spread_bp: float | None = None,
    short_borrow_sensitivity: str | None = None,
    borrow_proxy_annual_bp: float | None = None,
    required_dates: Sequence[Any] | None = None,
    liquidity_proxy: Mapping[str, Any] | float | None = None,
    liquidity_bars: Sequence[Mapping[str, Any]] | None = None,
    liquidity_bucket: str | None = None,
    liquidity_adv_jpy: float | None = None,
    is_topix: bool | None = None,
    scale_category: str | None = None,
    prefer_liquidity_linked: bool = True,
    require_liquidity_linked: bool = False,
    liquidity_required_dates: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Build explicit leverage/short cost assumption block for checklist v2.

    Long-only unlevered hyps **must** still produce this block with
    ``financing_not_applicable=True`` and ``short_borrow_not_applicable=True``.

    When ``repo_rate_series`` is supplied and ``prefer_repo_linked=True``
    (default), financing uses mean observed repo rates and short uses
    repo + spread (low/mid/high). **Gaps are disclosed, never ffilled.**

    When liquidity inputs are supplied and ``prefer_liquidity_linked=True``
    (default), one-way tx cost and short borrow *spread* are scaled by
    liquidity bucket (high/mid/low). Short low/mid/high sensitivity is
    applied **first**, then liquidity mult. **Missing liquidity is never
    invented** — multipliers stay 1.0 and the gap is disclosed.

    Returns a freeze-wrapped dict. Does not mint READY/Mass.
    """
    style = str(position_style or "").strip().lower() or POSITION_STYLE_LONG_ONLY_UNLEVERED
    if style not in KNOWN_POSITION_STYLES:
        style_known = False
    else:
        style_known = True

    if one_way_cost_bp is not None:
        tx_base = float(one_way_cost_bp) / 10_000.0
        tx_base_bp = float(one_way_cost_bp)
    else:
        tx_base = float(one_way_cost)
        tx_base_bp = tx_base * 10_000.0

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

    spread_base_bp = (
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
        spread_base_bp = float(SHORT_BORROW_SPREAD_SENSITIVITY[key])
        sens_label = key
    else:
        for k, v in SHORT_BORROW_SPREAD_SENSITIVITY.items():
            if abs(spread_base_bp - float(v)) < 1e-12:
                sens_label = k
                break

    liq_req = (
        liquidity_required_dates
        if liquidity_required_dates is not None
        else required_dates
    )
    liq = resolve_liquidity_modulation(
        liquidity_proxy=liquidity_proxy,
        liquidity_bars=liquidity_bars,
        liquidity_bucket=liquidity_bucket,
        liquidity_adv_jpy=liquidity_adv_jpy,
        is_topix=is_topix,
        scale_category=scale_category,
        required_dates=liq_req,
        prefer_liquidity_linked=bool(prefer_liquidity_linked),
    )
    tx_mult = float(liq["tx_mult"])
    short_spread_mult = float(liq["short_spread_mult"])
    liq_applied = bool(liq.get("applied"))
    liq_gap = bool(liq.get("is_gap"))

    tx = apply_liquidity_to_one_way_cost(tx_base, tx_mult=tx_mult)
    tx_bp = tx * 10_000.0
    spread_bp = apply_liquidity_to_short_spread_bp(
        spread_base_bp, short_spread_mult=short_spread_mult
    )

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

    short_rate_source = RATE_SOURCE_NOT_APPLICABLE
    if uses_short:
        if borrow_proxy_annual_bp is not None and not use_repo:
            borrow_bp = float(borrow_proxy_annual_bp) * (
                short_spread_mult if liq_applied else 1.0
            )
            short_rate_source = RATE_SOURCE_BORROW_PROXY
        elif use_repo and repo_mean is not None and repo_mean.get("mean_annual_bp") is not None:
            borrow_bp = float(repo_mean["mean_annual_bp"]) + float(spread_bp)
            short_rate_source = RATE_SOURCE_REPO_PLUS_SPREAD
        elif short_borrow_annual_bp is not None:
            borrow_bp = float(short_borrow_annual_bp) * (
                short_spread_mult if liq_applied else 1.0
            )
            short_rate_source = RATE_SOURCE_FIXED_BP
        else:
            borrow_bp = DEFAULT_SHORT_BORROW_ANNUAL_BP * (
                short_spread_mult if liq_applied else 1.0
            )
            short_rate_source = RATE_SOURCE_FIXED_BP
    else:
        borrow_bp = (
            float(short_borrow_annual_bp)
            if short_borrow_annual_bp is not None
            else DEFAULT_SHORT_BORROW_ANNUAL_BP
        )

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

    if style == POSITION_STYLE_LONG_ONLY_UNLEVERED and not uses_short and not uses_leverage:
        short_not_applicable = True
        financing_not_applicable = True
        short_daily = 0.0
        fin_daily = 0.0
        lev = min(lev, 1.0)
        short_rate_source = RATE_SOURCE_NOT_APPLICABLE
        fin_rate_source = RATE_SOURCE_NOT_APPLICABLE

    default_tx = float(DEFAULT_ONE_WAY_COST)
    # Base (pre-liquidity) change detection — liquidity mult alone is not a
    # "cost_change_reason" requirement (it is an explicit model path).
    tx_changed = abs(tx_base - default_tx) > 1e-15
    # For disclosure: fixed-bp override detection vs historical defaults
    # (repo-linked rates are not "changed from fixed default" in the same sense)
    # Compare pre-liquidity fixed/proxy overrides.
    if short_rate_source == RATE_SOURCE_FIXED_BP:
        if short_borrow_annual_bp is not None:
            borrow_changed = (
                abs(float(short_borrow_annual_bp) - DEFAULT_SHORT_BORROW_ANNUAL_BP)
                > 1e-12
            )
        elif liq_applied:
            borrow_changed = False  # default annual * liq mult is model path
        else:
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

    # Optional hard prefer: require_liquidity_linked blocks completeness when
    # liquidity is missing/unusable.
    if bool(require_liquidity_linked) and liq_gap:
        disclosed = False
        if "liquidity_proxy" not in missing:
            missing.append("liquidity_proxy")

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

    liq_block: dict[str, Any] = {
        "preferred": bool(prefer_liquidity_linked),
        "require_liquidity_linked": bool(require_liquidity_linked),
        "applied": liq_applied,
        "is_gap": liq_gap,
        "bucket": liq.get("bucket"),
        "adv_jpy": liq.get("adv_jpy"),
        "tx_mult": tx_mult,
        "short_spread_mult": short_spread_mult,
        "spread_base_bp": float(spread_base_bp),
        "spread_effective_bp": float(spread_bp),
        "tx_base": float(tx_base),
        "tx_base_bp": float(tx_base_bp),
        "tx_effective": float(tx),
        "tx_effective_bp": float(tx_bp),
        "tx_mult_map": dict(LIQUIDITY_TX_MULT),
        "short_spread_mult_map": dict(LIQUIDITY_SHORT_SPREAD_MULT),
        "dataset": LIQUIDITY_DATASET_ID,
        "proxy_unit": LIQUIDITY_PROXY_UNIT,
        "proxy": liq.get("proxy"),
        "bucket_detail": liq.get("bucket_detail"),
        "multipliers": liq.get("multipliers"),
        "ffill_applied": False,
        "invent_fill": False,
        "gap_policy": "disclose_only_no_ffill_no_invent",
        "formula": liq.get("formula"),
        "note": (
            "Liquidity scales one_way_tx and short spread (after low/mid/high "
            "sensitivity). Missing liquidity → mult=1.0, gap disclosed, no invent."
            if prefer_liquidity_linked
            else "prefer_liquidity_linked=False; mult forced to 1.0."
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
        "prefer_liquidity_linked": bool(prefer_liquidity_linked),
        "require_liquidity_linked": bool(require_liquidity_linked),
        "liquidity_linked": liq_applied,
        "transaction": {
            "one_way_cost": tx,
            "one_way_cost_bp": tx_bp,
            "one_way_cost_base": tx_base,
            "one_way_cost_base_bp": tx_base_bp,
            "round_trip_cost": tx * 2.0,
            "round_trip_cost_bp": tx_bp * 2.0,
            "default_one_way_cost": default_tx,
            "liquidity_tx_mult": tx_mult,
            "changed_from_default": tx_changed,
            "change_reason": (
                str(cost_change_reason).strip() if cost_change_reason else None
            ),
            "formula": (
                "net_one_way = gross_signed_mean_active - one_way_cost; "
                "one_way_cost = one_way_base * liquidity_tx_mult[bucket]"
            ),
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
                else (float(spread_bp) if uses_short and liq_applied else None)
            ),
            "spread_base_bp": (
                float(spread_base_bp)
                if uses_short
                and (
                    short_rate_source == RATE_SOURCE_REPO_PLUS_SPREAD
                    or liq_applied
                )
                else None
            ),
            "liquidity_short_spread_mult": (
                short_spread_mult if uses_short else None
            ),
            "sensitivity": (
                sens_label
                if uses_short
                and (
                    short_rate_source == RATE_SOURCE_REPO_PLUS_SPREAD
                    or sens_label is not None
                )
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
                "short_borrow_daily ≈ (repo_annual + spread_base*liq_mult) "
                "/ trading_days * short_fraction"
                if short_rate_source == RATE_SOURCE_REPO_PLUS_SPREAD
                else (
                    "short_borrow_daily ≈ (annual_bp/10000) / trading_days "
                    "* short_fraction"
                    + (
                        " (annual scaled by liq short_spread_mult when applied)"
                        if liq_applied
                        else ""
                    )
                )
            ),
            "note": (
                "Research stock-lending fee model (repo + spread preferred; "
                "spread = sensitivity_band * liquidity_mult). "
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
        "liquidity": liq_block,
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
            "Liquidity modulates tx cost and short spread (W79); missing "
            "liquidity disclosed, never invented. "
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
    liquidity_proxy: Mapping[str, Any] | float | None = None,
    liquidity_bars: Sequence[Mapping[str, Any]] | None = None,
    liquidity_bucket: str | None = None,
    liquidity_adv_jpy: float | None = None,
    is_topix: bool | None = None,
    scale_category: str | None = None,
    prefer_liquidity_linked: bool = True,
) -> dict[str, Any]:
    """Convenience: long-only unlevered with base 10bp + explicit N/A shorts/lev.

    Repo series may be attached for disclosure/inventory but financing/short
    remain N/A for this style. Liquidity may still scale one-way tx cost.
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
        liquidity_proxy=liquidity_proxy,
        liquidity_bars=liquidity_bars,
        liquidity_bucket=liquidity_bucket,
        liquidity_adv_jpy=liquidity_adv_jpy,
        is_topix=is_topix,
        scale_category=scale_category,
        prefer_liquidity_linked=prefer_liquidity_linked,
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
    "COST_MODELS_LABEL",
    "COST_MODELS_PROOF",
    "COST_MODELS_PROOF_SHORT_COST_W85",
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
    "KNOWN_LIQUIDITY_BUCKETS",
    "KNOWN_POSITION_STYLES",
    "LIQUIDITY_ADV_HIGH_JPY",
    "LIQUIDITY_ADV_MID_JPY",
    "LIQUIDITY_BUCKET_HIGH",
    "LIQUIDITY_BUCKET_LOW",
    "LIQUIDITY_BUCKET_MID",
    "LIQUIDITY_BUCKET_MISSING",
    "LIQUIDITY_DATASET_ID",
    "LIQUIDITY_PROXY_UNIT",
    "LIQUIDITY_SHORT_SPREAD_MULT",
    "LIQUIDITY_TOPIX_SOFT_UPGRADE",
    "LIQUIDITY_TX_MULT",
    "POSITION_STYLE_LEVERED_LONG",
    "POSITION_STYLE_LEVERED_LONG_SHORT",
    "POSITION_STYLE_LONG_ONLY_UNLEVERED",
    "POSITION_STYLE_LONG_SHORT",
    "RATE_SOURCE_BORROW_PROXY",
    "RATE_SOURCE_FIXED_BP",
    "RATE_SOURCE_NOT_APPLICABLE",
    "RATE_SOURCE_REPO_PLUS_SPREAD",
    "RATE_SOURCE_REPO_SERIES",
    "REPO_DATASET_ID",
    "REPO_TABLE",
    "SHORT_BORROW_SPREAD_HIGH_BP",
    "SHORT_BORROW_SPREAD_LOW_BP",
    "SHORT_BORROW_SPREAD_MID_BP",
    "SHORT_BORROW_SPREAD_SENSITIVITY",
    "annotate_period_rows_with_extended_costs",
    "apply_liquidity_to_one_way_cost",
    "apply_liquidity_to_short_spread_bp",
    "build_leverage_short_cost_assumption",
    "compute_liquidity_proxy_from_adv",
    "compute_liquidity_proxy_from_bars",
    "date_matched_leverage_financing_costs",
    "date_matched_short_borrow_costs",
    "default_long_only_unlevered_cost_assumption",
    "leverage_financing_daily_cost",
    "leverage_financing_daily_cost_from_repo",
    "liquidity_bucket_from_proxy",
    "liquidity_cost_multipliers",
    "load_repo_rate_series",
    "load_repo_rate_series_from_mapping",
    "load_repo_rate_series_from_pit",
    "load_repo_rate_series_from_rows",
    "lookup_repo_rate",
    "mean_repo_rate_pct",
    "remeasure_period_rows_with_short_cost",
    "repo_rate_pct_to_annual_bp",
    "repo_rate_pct_to_annual_fraction",
    "research_net_with_extended_costs",
    "research_net_with_short_hold_cost",
    "resolve_liquidity_modulation",
    "resolve_short_borrow_spread_bp",
    "short_borrow_daily_cost",
    "short_borrow_daily_cost_from_repo",
    "short_borrow_hold_cost_from_repo",
    "short_cost_sensitivity_bands",
    "yen_turnover_from_bar",
]
