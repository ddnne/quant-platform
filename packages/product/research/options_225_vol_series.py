"""Daily BaseVol + ATM IV series from ``derivatives_bars_daily_options_225``.

W92 / w0818b track A — research-only helpers. Mass / GO stay frozen.

Dataset
-------
J-Quants Nikkei 225 option daily bars
(``/v2/derivatives/bars/daily/options/225``). COMPLETE in local coverage
(164/164 segments, observed ``2013-01-04``→``2026-08-14``). Fields used:

* ``Date``, ``Strike``, ``PCDiv`` (1=put, 2=call), ``CM``, ``LTD``, ``SQD``
* ``BaseVol``, ``IV``, ``UnderPx``, ``Vo``, ``OI``, ``EmMrgnTrgDiv``

J-Quants definition (post ``2016-07-19``): ``BaseVol`` is the average of the
implied volatility of the at-the-money put and call. ``IV`` / ``UnderPx`` /
``LTD`` / ``SQD`` are blank before that date — those days are **gaps**, not
filled.

Written rules
-------------
**Settlement filter.** Prefer rows with ``EmMrgnTrgDiv == "002"`` (settlement
price calculation). If a day has only ``001`` (emergency margin) rows, use
those; never invent.

**Daily BaseVol.** For each ``Date``, collect finite ``BaseVol`` among
settlement-preferring rows. Exchange publishes one BaseVol per day (constant
across the chain). Take the unique value; if multiple distinct values appear,
take the median and flag ``base_vol_conflict``. Omit the day when no finite
BaseVol exists (**no ffill**).

**Daily ATM IV (independent reconstruction).**

1. ``under_px`` = median finite ``UnderPx`` that day (usually unique).
2. Front contract month ``cm`` = earliest ``CM`` among rows with
   ``LTD > Date`` (fallback: ``SQD > Date``; last resort: earliest ``CM``
   whose ``YYYY-MM >= Date[:7]``).
3. ATM ``strike`` = strike minimizing ``|Strike - under_px|`` within that
   ``cm`` (ties → lower strike).
4. At ``(cm, strike)``, take finite put (``PCDiv=1``) and call (``PCDiv=2``)
   ``IV``:

   * both → ``atm_iv = (put+call)/2``, ``pc_used="avg"``
   * call only → ``pc_used="2"``
   * put only → ``pc_used="1"``
   * neither → omit day (**no ffill**)

**Spread.** Inner-join BaseVol and ATM series on ``date``:
``spread = atm_iv - base_vol``. Dates missing either leg are omitted.

**Gap policy.** ``gap_policy = disclose_only_no_ffill_no_invent``. Calendar
holes between observed dates are listed in stats; never forward-filled.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

OPTIONS_225_VOL_SERIES_VERSION: str = "research-options-225-vol-series/v1"
OPTIONS_225_VOL_SERIES_WAVE: str = "W92 / w0818b"

DATASET_ID: str = "derivatives_bars_daily_options_225"
GAP_POLICY: str = "disclose_only_no_ffill_no_invent"

MASS_RESEARCH: str = "NO-GO"
PHASE7: str = "OFF"
READY_DECLARED: bool = False
OPERATIONAL_GO: bool = False

# J-Quants: theoretical / IV fields populated from this date inclusive.
IV_FIELDS_AVAILABLE_FROM: str = "2016-07-19"

PC_PUT: str = "1"
PC_CALL: str = "2"
EM_SETTLE: str = "002"
EM_EMERGENCY: str = "001"


def _as_date(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:10]


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s or s.lower() in {"nan", "null", "none"}:
            return None
        value = s
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def _as_pc(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if s in {PC_PUT, PC_CALL}:
        return s
    # tolerate int 1/2
    if s.endswith(".0") and s[:-2] in {PC_PUT, PC_CALL}:
        return s[:-2]
    try:
        i = int(float(s))
    except (TypeError, ValueError):
        return None
    if i in (1, 2):
        return str(i)
    return None


def _row_get(row: Mapping[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    # case-insensitive fallback
    lower = {str(k).lower(): v for k, v in row.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v not in (None, ""):
            return v
    return None


def normalize_options_225_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Extract the fields needed for BaseVol / ATM IV series builders."""
    if not isinstance(row, Mapping):
        return None
    # unwrap nested payload if present (structured mirrors / D1 dumps)
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = None
    if isinstance(payload, Mapping):
        src = payload
    else:
        src = row

    date = _as_date(_row_get(src, "Date", "date"))
    if not date:
        return None
    strike = _as_float(_row_get(src, "Strike", "strike"))
    under = _as_float(_row_get(src, "UnderPx", "under_px", "UnderPrice"))
    base_vol = _as_float(_row_get(src, "BaseVol", "base_vol", "BaseVolatility"))
    iv = _as_float(_row_get(src, "IV", "iv", "ImpliedVolatility"))
    pc = _as_pc(_row_get(src, "PCDiv", "pc_div", "PutCall", "PC"))
    cm = _row_get(src, "CM", "cm", "ContractMonth")
    cm_s = str(cm).strip()[:7] if cm not in (None, "") else None
    ltd = _as_date(_row_get(src, "LTD", "ltd", "LastTradingDay"))
    sqd = _as_date(_row_get(src, "SQD", "sqd", "SpecialQuotationDay"))
    vo = _as_float(_row_get(src, "Vo", "vo", "Volume"))
    oi = _as_float(_row_get(src, "OI", "oi", "OpenInterest"))
    em = _row_get(src, "EmMrgnTrgDiv", "em_mrgn_trg_div", "EmergencyMarginTriggerDivision")
    em_s = str(em).strip() if em not in (None, "") else None
    code = _row_get(src, "Code", "code")
    return {
        "date": date,
        "code": str(code) if code not in (None, "") else None,
        "strike": strike,
        "under_px": under,
        "base_vol": base_vol,
        "iv": iv,
        "pc_div": pc,
        "cm": cm_s,
        "ltd": ltd,
        "sqd": sqd,
        "vo": vo,
        "oi": oi,
        "em_mrgn_trg_div": em_s,
    }


def _group_by_date(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in rows:
        norm = normalize_options_225_row(raw)
        if norm is None:
            continue
        by_date[norm["date"]].append(norm)
    return dict(by_date)


def _prefer_settlement(day_rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    settle = [r for r in day_rows if r.get("em_mrgn_trg_div") == EM_SETTLE]
    if settle:
        return list(settle)
    # blank EmMrgnTrgDiv (pre-field era) — keep all
    blank = [r for r in day_rows if not r.get("em_mrgn_trg_div")]
    if blank:
        return list(blank)
    # emergency-only day
    return list(day_rows)


def _pick_front_cm(date: str, day_rows: Sequence[Mapping[str, Any]]) -> str | None:
    cms_ltd: set[str] = set()
    cms_sqd: set[str] = set()
    cms_ge: set[str] = set()
    month = date[:7]
    for r in day_rows:
        cm = r.get("cm")
        if not cm:
            continue
        ltd = r.get("ltd")
        sqd = r.get("sqd")
        if ltd and str(ltd) > date:
            cms_ltd.add(str(cm))
        if sqd and str(sqd) > date:
            cms_sqd.add(str(cm))
        if str(cm) >= month:
            cms_ge.add(str(cm))
    if cms_ltd:
        return min(cms_ltd)
    if cms_sqd:
        return min(cms_sqd)
    if cms_ge:
        return min(cms_ge)
    cms_all = {str(r["cm"]) for r in day_rows if r.get("cm")}
    return min(cms_all) if cms_all else None


def _median(xs: Sequence[float]) -> float:
    return float(statistics.median(xs))


def build_daily_basevol_series(
    rows: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build ``[{date, base_vol, n_contracts, ...}]`` — no ffill."""
    by_date = _group_by_date(rows)
    out: list[dict[str, Any]] = []
    for date in sorted(by_date):
        day = _prefer_settlement(by_date[date])
        bvs = [float(r["base_vol"]) for r in day if r.get("base_vol") is not None]
        if not bvs:
            continue
        unique = sorted({round(v, 10) for v in bvs})
        conflict = len(unique) > 1
        base_vol = _median(bvs) if conflict else float(unique[0])
        unders = [float(r["under_px"]) for r in day if r.get("under_px") is not None]
        out.append(
            {
                "date": date,
                "base_vol": base_vol,
                "n_contracts": len(day),
                "n_base_vol_obs": len(bvs),
                "base_vol_conflict": conflict,
                "under_px": _median(unders) if unders else None,
                "em_filter": (
                    EM_SETTLE
                    if any(r.get("em_mrgn_trg_div") == EM_SETTLE for r in day)
                    else (day[0].get("em_mrgn_trg_div") if day else None)
                ),
                "gap_policy": GAP_POLICY,
                "ffill_applied": False,
            }
        )
    return out


def build_daily_atm_iv_series(
    rows: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build ``[{date, atm_iv, strike, under_px, cm, pc_used, ...}]`` — no ffill."""
    by_date = _group_by_date(rows)
    out: list[dict[str, Any]] = []
    for date in sorted(by_date):
        day = _prefer_settlement(by_date[date])
        unders = [float(r["under_px"]) for r in day if r.get("under_px") is not None]
        if not unders:
            continue
        under_px = _median(unders)
        cm = _pick_front_cm(date, day)
        if not cm:
            continue
        cm_rows = [
            r
            for r in day
            if r.get("cm") == cm and r.get("strike") is not None
        ]
        if not cm_rows:
            continue
        # nearest strike to under
        best_dist: float | None = None
        best_strike: float | None = None
        for r in cm_rows:
            strike = float(r["strike"])  # type: ignore[arg-type]
            dist = abs(strike - under_px)
            if best_dist is None or dist < best_dist or (
                dist == best_dist and best_strike is not None and strike < best_strike
            ):
                best_dist = dist
                best_strike = strike
        assert best_strike is not None and best_dist is not None
        atm_rows = [r for r in cm_rows if float(r["strike"]) == best_strike]  # type: ignore[arg-type]
        put_ivs = [
            float(r["iv"])
            for r in atm_rows
            if r.get("pc_div") == PC_PUT and r.get("iv") is not None
        ]
        call_ivs = [
            float(r["iv"])
            for r in atm_rows
            if r.get("pc_div") == PC_CALL and r.get("iv") is not None
        ]
        put_iv = _median(put_ivs) if put_ivs else None
        call_iv = _median(call_ivs) if call_ivs else None
        if put_iv is not None and call_iv is not None:
            atm_iv = (put_iv + call_iv) / 2.0
            pc_used = "avg"
        elif call_iv is not None:
            atm_iv = call_iv
            pc_used = PC_CALL
        elif put_iv is not None:
            atm_iv = put_iv
            pc_used = PC_PUT
        else:
            continue
        vo_sum = sum(float(r["vo"]) for r in atm_rows if r.get("vo") is not None)
        oi_sum = sum(float(r["oi"]) for r in atm_rows if r.get("oi") is not None)
        ltds = sorted({r["ltd"] for r in atm_rows if r.get("ltd")})
        sqds = sorted({r["sqd"] for r in atm_rows if r.get("sqd")})
        out.append(
            {
                "date": date,
                "atm_iv": float(atm_iv),
                "strike": float(best_strike),
                "under_px": float(under_px),
                "cm": cm,
                "pc_used": pc_used,
                "put_iv": put_iv,
                "call_iv": call_iv,
                "abs_moneyness": float(best_dist),
                "rel_moneyness": float(best_dist / under_px) if under_px else None,
                "ltd": ltds[0] if ltds else None,
                "sqd": sqds[0] if sqds else None,
                "vo_atm": vo_sum if vo_sum else None,
                "oi_atm": oi_sum if oi_sum else None,
                "n_contracts_day": len(day),
                "gap_policy": GAP_POLICY,
                "ffill_applied": False,
            }
        )
    return out


def build_spread_series(
    base: Sequence[Mapping[str, Any]],
    atm: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Inner-join BaseVol and ATM IV: ``spread = atm_iv - base_vol`` (no ffill)."""
    base_by = {
        str(r["date"])[:10]: r
        for r in base
        if r.get("date") is not None and r.get("base_vol") is not None
    }
    atm_by = {
        str(r["date"])[:10]: r
        for r in atm
        if r.get("date") is not None and r.get("atm_iv") is not None
    }
    out: list[dict[str, Any]] = []
    for date in sorted(set(base_by) & set(atm_by)):
        b = base_by[date]
        a = atm_by[date]
        bv = float(b["base_vol"])  # type: ignore[arg-type]
        av = float(a["atm_iv"])  # type: ignore[arg-type]
        out.append(
            {
                "date": date,
                "spread": av - bv,
                "base_vol": bv,
                "atm_iv": av,
                "strike": a.get("strike"),
                "under_px": a.get("under_px") if a.get("under_px") is not None else b.get("under_px"),
                "cm": a.get("cm"),
                "pc_used": a.get("pc_used"),
                "gap_policy": GAP_POLICY,
                "ffill_applied": False,
            }
        )
    return out


def calendar_gap_dates(dates: Sequence[str]) -> list[str]:
    """Return YYYY-MM-DD strings strictly between min..max that are absent.

    Note: this is a **calendar** hole list (includes weekends/holidays). Callers
    that need trading-day gaps should intersect with a calendar externally.
    """
    if len(dates) < 2:
        return []
    from datetime import date as _date
    from datetime import timedelta

    ordered = sorted({str(d)[:10] for d in dates})
    start = _date.fromisoformat(ordered[0])
    end = _date.fromisoformat(ordered[-1])
    have = set(ordered)
    gaps: list[str] = []
    cur = start + timedelta(days=1)
    while cur < end:
        s = cur.isoformat()
        if s not in have:
            gaps.append(s)
        cur += timedelta(days=1)
    return gaps


def pearson_corr(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson correlation; None if undefined."""
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    x = [float(xs[i]) for i in range(n)]
    y = [float(ys[i]) for i in range(n)]
    mx = statistics.mean(x)
    my = statistics.mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den_x = math.sqrt(sum((a - mx) ** 2 for a in x))
    den_y = math.sqrt(sum((b - my) ** 2 for b in y))
    if den_x <= 0.0 or den_y <= 0.0:
        return None
    return num / (den_x * den_y)


def summarize_vol_series(
    base: Sequence[Mapping[str, Any]],
    atm: Sequence[Mapping[str, Any]],
    spread: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Coverage / corr(BaseVol, ATM IV) / missing-day disclosure."""
    if spread is None:
        spread = build_spread_series(base, atm)
    base_dates = [str(r["date"])[:10] for r in base]
    atm_dates = [str(r["date"])[:10] for r in atm]
    spread_dates = [str(r["date"])[:10] for r in spread]
    paired = [
        (float(r["base_vol"]), float(r["atm_iv"]))  # type: ignore[arg-type]
        for r in spread
    ]
    corr = pearson_corr([p[0] for p in paired], [p[1] for p in paired]) if paired else None
    abs_spreads = [abs(float(r["spread"])) for r in spread]  # type: ignore[arg-type]
    return {
        "dataset": DATASET_ID,
        "version": OPTIONS_225_VOL_SERIES_VERSION,
        "wave": OPTIONS_225_VOL_SERIES_WAVE,
        "gap_policy": GAP_POLICY,
        "ffill_applied": False,
        "invent_fill": False,
        "iv_fields_available_from": IV_FIELDS_AVAILABLE_FROM,
        "n_base_vol_days": len(base),
        "n_atm_iv_days": len(atm),
        "n_spread_days": len(spread),
        "base_vol_date_start": base_dates[0] if base_dates else None,
        "base_vol_date_end": base_dates[-1] if base_dates else None,
        "atm_iv_date_start": atm_dates[0] if atm_dates else None,
        "atm_iv_date_end": atm_dates[-1] if atm_dates else None,
        "corr_basevol_atm_iv": corr,
        "spread_mean": statistics.mean([float(r["spread"]) for r in spread]) if spread else None,  # type: ignore[arg-type]
        "spread_abs_mean": statistics.mean(abs_spreads) if abs_spreads else None,
        "spread_abs_max": max(abs_spreads) if abs_spreads else None,
        "calendar_gaps_in_base_span": calendar_gap_dates(base_dates),
        "calendar_gaps_in_atm_span": calendar_gap_dates(atm_dates),
        "n_calendar_gaps_base": len(calendar_gap_dates(base_dates)),
        "n_calendar_gaps_atm": len(calendar_gap_dates(atm_dates)),
        "dates_base_only": sorted(set(base_dates) - set(atm_dates)),
        "dates_atm_only": sorted(set(atm_dates) - set(base_dates)),
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
    }


# --------------------------------------------------------------------------- loaders


def iter_options_225_rows_from_raw_json(
    path: str | Path,
) -> Iterator[dict[str, Any]]:
    """Yield option contract rows from a local raw monthly JSON mirror."""
    p = Path(path)
    obj = json.loads(p.read_text())
    if isinstance(obj, Mapping):
        data = obj.get("data")
        if isinstance(data, list):
            for row in data:
                if isinstance(row, Mapping):
                    yield dict(row)
            return
        # single wrapped row
        if "Date" in obj or "date" in obj:
            yield dict(obj)
            return
    if isinstance(obj, list):
        for row in obj:
            if isinstance(row, Mapping):
                yield dict(row)


def iter_options_225_rows_from_ndjson(
    path: str | Path,
) -> Iterator[dict[str, Any]]:
    """Yield rows from structured JSONL / ndjson mirrors."""
    p = Path(path)
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
                yield dict(row)


def _options_225_window_key(path: Path) -> str:
    """Extract ``from=YYYY-MM-DD_to=YYYY-MM-DD`` window key from filename."""
    name = path.name
    i = name.find("from=")
    if i < 0:
        return name
    # window ends before optional _from_r2_ / _sealpage_ / .json suffix noise
    rest = name[i:]
    # keep from=..._to=YYYY-MM-DD
    j = rest.find("_to=")
    if j < 0:
        return rest.split("_from_r2")[0].split("_sealpage")[0].split(".json")[0]
    # to=YYYY-MM-DD is 14 chars (_to= + 10 date)
    end = j + 4 + 10
    return rest[:end]


def discover_options_225_raw_files(
    raw_root: str | Path | None = None,
) -> list[Path]:
    """Locate COMPLETE local raw monthly JSON mirrors for options_225.

    Same calendar window may appear under multiple ingest dates / seal vs R2
    copies. Prefer the **largest** file per ``from=…_to=…`` window (more
    complete page aggregate), not the first rglob hit.
    """
    root = Path(raw_root) if raw_root else Path(__file__).resolve().parents[3] / "data" / "raw"
    files = list(root.rglob("derivatives_bars_daily_options_225_from=*.json"))
    by_window: dict[str, Path] = {}
    for f in files:
        key = _options_225_window_key(f)
        prev = by_window.get(key)
        if prev is None:
            by_window[key] = f
            continue
        try:
            if f.stat().st_size > prev.stat().st_size:
                by_window[key] = f
        except OSError:
            continue
    return sorted(by_window.values(), key=lambda p: _options_225_window_key(p))


def load_options_225_rows(
    *,
    raw_files: Sequence[str | Path] | None = None,
    ndjson_path: str | Path | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    """Load option rows from raw JSON and/or ndjson, optional date filter."""
    p_start = str(start)[:10] if start else None
    p_end = str(end)[:10] if end else None
    out: list[dict[str, Any]] = []

    def _accept(row: Mapping[str, Any]) -> bool:
        d = _as_date(_row_get(row, "Date", "date"))
        if d is None:
            # try payload
            norm = normalize_options_225_row(row)
            d = norm["date"] if norm else None
        if d is None:
            return False
        if p_start and d < p_start:
            return False
        if p_end and d > p_end:
            return False
        return True

    if raw_files:
        for fp in raw_files:
            for row in iter_options_225_rows_from_raw_json(fp):
                if _accept(row):
                    out.append(row)
    if ndjson_path:
        for row in iter_options_225_rows_from_ndjson(ndjson_path):
            if _accept(row):
                out.append(row)
    return out


def build_series_bundle_from_rows(
    rows: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Convenience: BaseVol + ATM IV + spread + stats from row iterable."""
    materialised = list(rows)
    base = build_daily_basevol_series(materialised)
    atm = build_daily_atm_iv_series(materialised)
    spread = build_spread_series(base, atm)
    stats = summarize_vol_series(base, atm, spread)
    return {
        "base_vol_series": base,
        "atm_iv_series": atm,
        "spread_series": spread,
        "stats": stats,
        "rules": {
            "base_vol": (
                "Per-date median/unique finite BaseVol among settlement-preferring "
                "rows; omit day if none (no ffill)."
            ),
            "atm_iv": (
                "Front CM (min CM with LTD>Date) nearest strike to UnderPx; "
                "avg put/call IV when both finite else available side."
            ),
            "spread": "atm_iv - base_vol on inner-joined dates.",
            "gap_policy": GAP_POLICY,
            "iv_fields_available_from": IV_FIELDS_AVAILABLE_FROM,
        },
        "version": OPTIONS_225_VOL_SERIES_VERSION,
        "wave": OPTIONS_225_VOL_SERIES_WAVE,
        "dataset": DATASET_ID,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "ffill_applied": False,
    }


# ---------------------------------------------------------------------------
# Regime maps for factory / CF (rolling short/long on daily level series)
# ---------------------------------------------------------------------------

# Units: percent vol points (J-Quants BaseVol / IV). Not annualized decimal RV.
DEFAULT_OPT225_SHORT_N: int = 10
DEFAULT_OPT225_LONG_N: int = 60
# BaseVol / ATM IV abs thresholds (percent points; ~p10/p90 of observed series).
DEFAULT_OPT225_BASEVOL_HIGH: float = 24.0
DEFAULT_OPT225_BASEVOL_LOW: float = 12.0
DEFAULT_OPT225_ATM_IV_HIGH: float = 25.0
DEFAULT_OPT225_ATM_IV_LOW: float = 12.0
# Spread = atm_iv - base_vol (percent vol points). Median≈0; use mild bands.
DEFAULT_OPT225_SPREAD_HIGH: float = 1.0
DEFAULT_OPT225_SPREAD_LOW: float = -0.5
DEFAULT_OPT225_EXPAND_RATIO: float = 1.20
DEFAULT_OPT225_COMPRESS_RATIO: float = 0.80
SPREAD_CONVENTION: str = "atm_iv - base_vol"

_DEFAULT_LOG_DIR = (
    Path(__file__).resolve().parents[3] / ".glm-logs" / "w0818b_w92_options_vol"
)


def _rolling_mean(values: Sequence[float], end_idx: int, win: int) -> float | None:
    if win < 1 or end_idx + 1 < win:
        return None
    sl = values[end_idx + 1 - win : end_idx + 1]
    if len(sl) < win:
        return None
    return float(statistics.mean(sl))


def level_series_to_regime_maps(
    level_by_date: Mapping[str, float],
    *,
    short_n: int = DEFAULT_OPT225_SHORT_N,
    long_n: int = DEFAULT_OPT225_LONG_N,
    source: str = "options_225_level",
    dataset: str = DATASET_ID,
    units: str = "percent_vol_points",
    series_kind: str = "level",
) -> dict[str, Any]:
    """Convert a daily level series into abs / short / long / ratio maps.

    Missing days are omitted (no invent / no ffill). Rolling windows only use
    observed points in chronological order (not calendar-day pads).
    """
    sn = max(2, int(short_n))
    ln = max(sn + 1, int(long_n))
    dates = sorted(str(d)[:10] for d in level_by_date.keys())
    vals = [float(level_by_date[d]) for d in dates]
    abs_by: dict[str, float] = {}
    short_by: dict[str, float] = {}
    long_by: dict[str, float] = {}
    ratio_by: dict[str, float] = {}
    for i, d in enumerate(dates):
        abs_by[d] = vals[i]
        s = _rolling_mean(vals, i, sn)
        lo = _rolling_mean(vals, i, ln)
        if s is not None:
            short_by[d] = s
        if lo is not None:
            long_by[d] = lo
        if s is not None and lo is not None and abs(lo) > 1e-12:
            ratio_by[d] = s / lo
    return {
        "kind": "opt225_vol_regime_series",
        "series_kind": series_kind,
        "dataset": dataset,
        "source": source,
        "units": units,
        "short_n": sn,
        "long_n": ln,
        "level_by_date": dict(sorted((d, float(level_by_date[d])) for d in dates)),
        # Align key names with nky_vol_series / CF worker (reuse eval path).
        "rv_abs_by_date": dict(sorted(abs_by.items())),
        "rv_short_by_date": dict(sorted(short_by.items())),
        "rv_long_by_date": dict(sorted(long_by.items())),
        "rv_ratio_by_date": dict(sorted(ratio_by.items())),
        "n_obs_level": len(abs_by),
        "n_obs_short": len(short_by),
        "n_obs_long": len(long_by),
        "n_obs_ratio": len(ratio_by),
        "ffill_applied": False,
        "invent_fill": False,
        "gap_policy": GAP_POLICY,
    }


def series_rows_to_level_map(
    rows: Sequence[Mapping[str, Any]],
    value_key: str,
) -> dict[str, float]:
    """``[{date, <value_key>}, ...]`` → ``{date: float}``."""
    out: dict[str, float] = {}
    for r in rows:
        d = _as_date(r.get("date"))
        v = _as_float(r.get(value_key))
        if d is None or v is None:
            continue
        out[d] = v
    return out


def build_opt225_regime_bundle(
    base_rows: Sequence[Mapping[str, Any]],
    atm_rows: Sequence[Mapping[str, Any]],
    spread_rows: Sequence[Mapping[str, Any]] | None = None,
    *,
    short_n: int = DEFAULT_OPT225_SHORT_N,
    long_n: int = DEFAULT_OPT225_LONG_N,
) -> dict[str, Any]:
    """Build BaseVol / ATM IV / spread regime maps for factory + CF panels."""
    if spread_rows is None:
        spread_rows = build_spread_series(base_rows, atm_rows)
    base_lvl = series_rows_to_level_map(base_rows, "base_vol")
    atm_lvl = series_rows_to_level_map(atm_rows, "atm_iv")
    spread_lvl = series_rows_to_level_map(spread_rows, "spread")
    # day-over-day change of spread (skip first obs / gaps → no invent)
    spread_chg: dict[str, float] = {}
    sp_dates = sorted(spread_lvl)
    for i in range(1, len(sp_dates)):
        d0, d1 = sp_dates[i - 1], sp_dates[i]
        spread_chg[d1] = spread_lvl[d1] - spread_lvl[d0]
    return {
        "basevol": level_series_to_regime_maps(
            base_lvl,
            short_n=short_n,
            long_n=long_n,
            source="options_225_basevol",
            series_kind="basevol",
        ),
        "atm_iv": level_series_to_regime_maps(
            atm_lvl,
            short_n=short_n,
            long_n=long_n,
            source="options_225_atm_iv",
            series_kind="atm_iv",
        ),
        "spread": level_series_to_regime_maps(
            spread_lvl,
            short_n=short_n,
            long_n=long_n,
            source="options_225_iv_base_spread",
            series_kind="spread",
        ),
        "spread_change": level_series_to_regime_maps(
            spread_chg,
            short_n=short_n,
            long_n=long_n,
            source="options_225_iv_base_spread_change",
            series_kind="spread_change",
        ),
        "spread_convention": SPREAD_CONVENTION,
        "units": "percent_vol_points",
        "dataset": DATASET_ID,
        "version": OPTIONS_225_VOL_SERIES_VERSION,
        "wave": OPTIONS_225_VOL_SERIES_WAVE,
        "ffill_applied": False,
        "invent_fill": False,
    }


def load_ndjson_series(path: str | Path) -> list[dict[str, Any]]:
    """Load a daily series ndjson artifact."""
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


def load_opt225_series_cache(
    log_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    """Load pre-built BaseVol / ATM / spread ndjson from W92 log dir."""
    d = Path(log_dir) if log_dir else _DEFAULT_LOG_DIR
    base_p = d / "base_vol_series.ndjson"
    atm_p = d / "atm_iv_series.ndjson"
    spread_p = d / "spread_series.ndjson"
    if not (base_p.is_file() and atm_p.is_file()):
        return None
    base = load_ndjson_series(base_p)
    atm = load_ndjson_series(atm_p)
    spread = load_ndjson_series(spread_p) if spread_p.is_file() else build_spread_series(base, atm)
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
        "meta": meta,
        "log_dir": str(d),
        "dataset": DATASET_ID,
        "source": "w92_log_cache",
    }


def write_definition_rules(
    out_dir: str | Path,
    *,
    stats: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    """Write ``basevol_rule.json`` / ``atm_iv_rule.json`` / ``series_meta.json``."""
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    basevol_rule = {
        "rule_id": "opt225_daily_basevol",
        "wave": OPTIONS_225_VOL_SERIES_WAVE,
        "version": OPTIONS_225_VOL_SERIES_VERSION,
        "dataset": DATASET_ID,
        "units": "percent_vol_points",
        "aggregation": (
            "Per Date: prefer EmMrgnTrgDiv==002 settlement rows; collect finite "
            "BaseVol; unique value if constant across chain else median; flag "
            "base_vol_conflict when distinct values appear. CM/expiry not filtered "
            "— BaseVol is day-level exchange base (same across contracts)."
        ),
        "cm_expiry_handling": (
            "Not applied for BaseVol (day-level). Exchange BaseVol already "
            "represents ATM put/call mid IV (J-Quants post 2016-07-19)."
        ),
        "missing_days": GAP_POLICY,
        "ffill_applied": False,
        "invent_fill": False,
        "iv_fields_available_from": IV_FIELDS_AVAILABLE_FROM,
    }
    atm_iv_rule = {
        "rule_id": "opt225_daily_atm_iv",
        "wave": OPTIONS_225_VOL_SERIES_WAVE,
        "version": OPTIONS_225_VOL_SERIES_VERSION,
        "dataset": DATASET_ID,
        "units": "percent_vol_points",
        "front_cm": (
            "Earliest CM among rows with LTD > Date; fallback SQD > Date; "
            "last resort CM >= Date[:7]."
        ),
        "atm_strike": "argmin |Strike - median(UnderPx)| within front CM (ties → lower strike).",
        "atm_iv": (
            "At (cm, strike): avg(put IV, call IV) when both finite; else available "
            "side. Optional Vo/OI recorded but not required filters."
        ),
        "missing_days": GAP_POLICY,
        "ffill_applied": False,
        "invent_fill": False,
        "iv_fields_available_from": IV_FIELDS_AVAILABLE_FROM,
        "note_vs_basevol": (
            "J-Quants BaseVol ≈ ATM put/call mid by definition; reconstructed ATM IV "
            "corr≈0.9 with small residual spread (microstructure / CM selection)."
        ),
    }
    series_meta = {
        "wave": OPTIONS_225_VOL_SERIES_WAVE,
        "version": OPTIONS_225_VOL_SERIES_VERSION,
        "dataset": DATASET_ID,
        "spread_convention": SPREAD_CONVENTION,
        "spread_units": "percent_vol_points",
        "gap_policy": GAP_POLICY,
        "regime_windows": {
            "short_n": DEFAULT_OPT225_SHORT_N,
            "long_n": DEFAULT_OPT225_LONG_N,
        },
        "thresholds": {
            "basevol_high": DEFAULT_OPT225_BASEVOL_HIGH,
            "basevol_low": DEFAULT_OPT225_BASEVOL_LOW,
            "atm_iv_high": DEFAULT_OPT225_ATM_IV_HIGH,
            "atm_iv_low": DEFAULT_OPT225_ATM_IV_LOW,
            "spread_high": DEFAULT_OPT225_SPREAD_HIGH,
            "spread_low": DEFAULT_OPT225_SPREAD_LOW,
            "expand_ratio": DEFAULT_OPT225_EXPAND_RATIO,
            "compress_ratio": DEFAULT_OPT225_COMPRESS_RATIO,
        },
        "proxy_compare_only": {
            "nky_vol_*": (
                "W91 TOPIX/NK225F realized-vol proxy — keep parallel; "
                "options_225 BaseVol/ATM IV is canonical Nikkei vol SoT."
            )
        },
        "stats": dict(stats) if stats else None,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
    }
    paths = {
        "basevol_rule": d / "basevol_rule.json",
        "atm_iv_rule": d / "atm_iv_rule.json",
        "series_meta": d / "series_meta.json",
    }
    paths["basevol_rule"].write_text(json.dumps(basevol_rule, indent=2) + "\n")
    paths["atm_iv_rule"].write_text(json.dumps(atm_iv_rule, indent=2) + "\n")
    paths["series_meta"].write_text(json.dumps(series_meta, indent=2, default=str) + "\n")
    return paths


__all__ = [
    "OPTIONS_225_VOL_SERIES_VERSION",
    "OPTIONS_225_VOL_SERIES_WAVE",
    "DATASET_ID",
    "GAP_POLICY",
    "IV_FIELDS_AVAILABLE_FROM",
    "MASS_RESEARCH",
    "PHASE7",
    "READY_DECLARED",
    "OPERATIONAL_GO",
    "normalize_options_225_row",
    "build_daily_basevol_series",
    "build_daily_atm_iv_series",
    "build_spread_series",
    "calendar_gap_dates",
    "pearson_corr",
    "summarize_vol_series",
    "iter_options_225_rows_from_raw_json",
    "iter_options_225_rows_from_ndjson",
    "discover_options_225_raw_files",
    "load_options_225_rows",
    "build_series_bundle_from_rows",
    "DEFAULT_OPT225_SHORT_N",
    "DEFAULT_OPT225_LONG_N",
    "DEFAULT_OPT225_BASEVOL_HIGH",
    "DEFAULT_OPT225_BASEVOL_LOW",
    "DEFAULT_OPT225_ATM_IV_HIGH",
    "DEFAULT_OPT225_ATM_IV_LOW",
    "DEFAULT_OPT225_SPREAD_HIGH",
    "DEFAULT_OPT225_SPREAD_LOW",
    "DEFAULT_OPT225_EXPAND_RATIO",
    "DEFAULT_OPT225_COMPRESS_RATIO",
    "SPREAD_CONVENTION",
    "level_series_to_regime_maps",
    "series_rows_to_level_map",
    "build_opt225_regime_bundle",
    "load_ndjson_series",
    "load_opt225_series_cache",
    "write_definition_rules",
]
