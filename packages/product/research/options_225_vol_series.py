"""Daily BaseVol + ATM IV + skew / CM-term / ΔBaseVol from options_225.

Research-only. Missing days → omit (no ffill / no invent). BaseVol is the
canonical level; reconstructed ATM IV is compare-only.

Dataset: J-Quants Nikkei 225 option daily bars
(``derivatives_bars_daily_options_225``). IV / UnderPx / LTD / SQD blank
before ``2016-07-19`` are gaps. Prefer settlement rows
(``EmMrgnTrgDiv==002``); emergency-only days use those rows.

Eval/CF consume cached ndjson via :func:`load_opt225_series_cache` →
:func:`build_opt225_regime_bundle`. Never invent missing series.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import date as _date
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

OPTIONS_225_VOL_SERIES_VERSION: str = "research-options-225-vol-series/v1.2"
OPTIONS_225_VOL_SERIES_WAVE: str = "W95 / w0818e"

DATASET_ID: str = "derivatives_bars_daily_options_225"
GAP_POLICY: str = "disclose_only_no_ffill_no_invent"

from research.freezes import (
    MASS_RESEARCH,
    OPERATIONAL_GO,
    PHASE7,
    READY_DECLARED,
)

IV_FIELDS_AVAILABLE_FROM: str = "2016-07-19"
# Front-CM LTD DTE floor; fall back to near-expiry only if none eligible.
DEFAULT_ATM_MIN_DTE_DAYS: int = 6
DEFAULT_SKEW_PUT_MONEYNESS: float = 0.95
BASEVOL_ROLE: str = "canonical_level"
ATM_IV_ROLE: str = "compare_only"

PC_PUT: str = "1"
PC_CALL: str = "2"
EM_SETTLE: str = "002"

SKEW_CONVENTION: str = "put_iv(~0.95*UnderPx) - atm_mid_iv"
CM_TERM_CONVENTION: str = "near_cm_atm_iv - next_cm_atm_iv"
BASEVOL_DELTA_CONVENTION: str = "BaseVol[t] - BaseVol[t-1]"


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


def _cm_dte_days(date: str, expiry: str | None) -> int | None:
    """Calendar days from ``date`` to expiry (LTD/SQD); None if unparseable."""
    if not expiry:
        return None
    try:
        d0 = _date.fromisoformat(str(date)[:10])
        d1 = _date.fromisoformat(str(expiry)[:10])
    except ValueError:
        return None
    return (d1 - d0).days


def _cm_dtes(
    date: str,
    day_rows: Sequence[Mapping[str, Any]],
    *,
    field: str,
    min_dte: int | None = None,
    after_cm: str | None = None,
) -> dict[str, int]:
    """Map CM → min DTE for rows whose ``field`` expiry is strictly after date."""
    out: dict[str, int] = {}
    floor = 0 if min_dte is None else max(0, int(min_dte))
    for r in day_rows:
        cm = r.get("cm")
        exp = r.get(field)
        if not cm or not exp or str(exp) <= date:
            continue
        if after_cm is not None and str(cm) <= after_cm:
            continue
        dte = _cm_dte_days(date, str(exp))
        if dte is None or (min_dte is not None and dte < floor):
            continue
        cm_s = str(cm)
        out[cm_s] = dte if cm_s not in out else min(out[cm_s], dte)
    return out


def _pick_cm(
    buckets: Sequence[tuple[dict[str, int], str, bool]],
    meta: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    for mapping, rule, near in buckets:
        if mapping:
            cm = min(mapping)
            meta["cm_pick_rule"] = rule
            meta["dte"] = mapping[cm]
            meta["near_expiry_fallback"] = near
            return cm, meta
    return None, meta


def _pick_front_cm(
    date: str,
    day_rows: Sequence[Mapping[str, Any]],
    *,
    min_dte_days: int = DEFAULT_ATM_MIN_DTE_DAYS,
) -> tuple[str | None, dict[str, Any]]:
    """Pick front CM with optional near-expiry roll (W93)."""
    min_dte = max(0, int(min_dte_days))
    meta: dict[str, Any] = {
        "min_dte_days": min_dte,
        "near_expiry_fallback": False,
        "cm_pick_rule": None,
        "dte": None,
    }
    cm, meta = _pick_cm(
        (
            (_cm_dtes(date, day_rows, field="ltd", min_dte=min_dte), "ltd_min_dte", False),
            (_cm_dtes(date, day_rows, field="sqd", min_dte=min_dte), "sqd_min_dte", False),
            (_cm_dtes(date, day_rows, field="ltd"), "ltd_any_near_expiry_fallback", True),
            (_cm_dtes(date, day_rows, field="sqd"), "sqd_any_near_expiry_fallback", True),
        ),
        meta,
    )
    if cm:
        return cm, meta
    month = date[:7]
    cms_ge = {str(r["cm"]) for r in day_rows if r.get("cm") and str(r["cm"]) >= month}
    if cms_ge:
        meta["cm_pick_rule"] = "cm_ge_month"
        return min(cms_ge), meta
    cms_all = {str(r["cm"]) for r in day_rows if r.get("cm")}
    if cms_all:
        meta["cm_pick_rule"] = "any_cm"
        return min(cms_all), meta
    return None, meta


def _median(xs: Sequence[float]) -> float:
    return float(statistics.median(xs))


def _nearest_strike(
    day_rows: Sequence[Mapping[str, Any]],
    *,
    cm: str,
    target: float,
    pc_div: str | None = None,
    require_finite_iv: bool = False,
) -> float | None:
    """Pick listed strike nearest to ``target`` within ``cm`` (ties → lower).

    Never invents strikes. When ``pc_div`` is set, only that put/call side is
    considered. When ``require_finite_iv``, rows without finite IV are skipped.
    """
    best_dist: float | None = None
    best_strike: float | None = None
    for r in day_rows:
        if r.get("cm") != cm or r.get("strike") is None:
            continue
        if pc_div is not None and r.get("pc_div") != pc_div:
            continue
        if require_finite_iv and r.get("iv") is None:
            continue
        strike = float(r["strike"])  # type: ignore[arg-type]
        dist = abs(strike - target)
        if best_dist is None or dist < best_dist or (
            dist == best_dist and best_strike is not None and strike < best_strike
        ):
            best_dist = dist
            best_strike = strike
    return best_strike


def _atm_iv_at_cm(
    day_rows: Sequence[Mapping[str, Any]],
    *,
    cm: str,
    under_px: float,
) -> dict[str, Any] | None:
    """ATM-ish put/call mid IV within a fixed CM. None if no finite IV.

    Strike = listed strike minimizing |Strike − under_px| (ties → lower).
    Never invents strikes beyond the available chain.
    """
    best_strike = _nearest_strike(day_rows, cm=cm, target=under_px)
    if best_strike is None:
        return None
    atm_rows = [
        r
        for r in day_rows
        if r.get("cm") == cm
        and r.get("strike") is not None
        and float(r["strike"]) == best_strike  # type: ignore[arg-type]
    ]
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
        return None
    vo_sum = sum(float(r["vo"]) for r in atm_rows if r.get("vo") is not None)
    oi_sum = sum(float(r["oi"]) for r in atm_rows if r.get("oi") is not None)
    ltds = sorted({r["ltd"] for r in atm_rows if r.get("ltd")})
    sqds = sorted({r["sqd"] for r in atm_rows if r.get("sqd")})
    return {
        "atm_iv": float(atm_iv),
        "strike": float(best_strike),
        "pc_used": pc_used,
        "put_iv": put_iv,
        "call_iv": call_iv,
        "abs_moneyness": abs(best_strike - under_px),
        "rel_moneyness": (
            abs(best_strike - under_px) / under_px if under_px else None
        ),
        "ltd": ltds[0] if ltds else None,
        "sqd": sqds[0] if sqds else None,
        "vo_atm": vo_sum if vo_sum else None,
        "oi_atm": oi_sum if oi_sum else None,
    }


def _pick_next_cm(
    date: str,
    day_rows: Sequence[Mapping[str, Any]],
    *,
    near_cm: str,
    min_dte_days: int = DEFAULT_ATM_MIN_DTE_DAYS,
) -> tuple[str | None, dict[str, Any]]:
    """Earliest CM strictly after ``near_cm`` with min_dte eligibility."""
    meta: dict[str, Any] = {
        "min_dte_days": max(0, int(min_dte_days)),
        "cm_pick_rule": None,
        "dte": None,
        "near_expiry_fallback": False,
    }
    return _pick_cm(
        (
            (
                _cm_dtes(
                    date, day_rows, field="ltd", min_dte=min_dte_days, after_cm=near_cm
                ),
                "ltd_min_dte_after_near",
                False,
            ),
            (
                _cm_dtes(date, day_rows, field="ltd", after_cm=near_cm),
                "ltd_any_after_near_fallback",
                True,
            ),
        ),
        meta,
    )


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


def _settled_under(
    date: str,
    by_date: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    min_dte_days: int,
) -> tuple[list[Mapping[str, Any]], float, str, dict[str, Any]] | None:
    day = _prefer_settlement(by_date[date])
    unders = [float(r["under_px"]) for r in day if r.get("under_px") is not None]
    if not unders:
        return None
    under_px = _median(unders)
    cm, cm_meta = _pick_front_cm(date, day, min_dte_days=min_dte_days)
    if not cm:
        return None
    return list(day), under_px, cm, cm_meta


def build_daily_atm_iv_series(
    rows: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    *,
    min_dte_days: int = DEFAULT_ATM_MIN_DTE_DAYS,
) -> list[dict[str, Any]]:
    """Compare-only ATM IV vs BaseVol. Missing day → omit. Never invent strikes."""
    by_date = _group_by_date(rows)
    out: list[dict[str, Any]] = []
    for date in sorted(by_date):
        sess = _settled_under(date, by_date, min_dte_days=min_dte_days)
        if sess is None:
            continue
        day, under_px, cm, cm_meta = sess
        atm = _atm_iv_at_cm(day, cm=cm, under_px=under_px)
        if atm is None:
            continue
        ltd = atm.get("ltd")
        dte = cm_meta.get("dte")
        if dte is None and ltd is not None:
            dte = _cm_dte_days(date, str(ltd))
        out.append(
            {
                "date": date,
                "atm_iv": float(atm["atm_iv"]),
                "strike": float(atm["strike"]),
                "under_px": float(under_px),
                "cm": cm,
                "pc_used": atm["pc_used"],
                "put_iv": atm["put_iv"],
                "call_iv": atm["call_iv"],
                "abs_moneyness": atm["abs_moneyness"],
                "rel_moneyness": atm["rel_moneyness"],
                "ltd": ltd,
                "sqd": atm.get("sqd"),
                "dte": dte,
                "cm_pick_rule": cm_meta.get("cm_pick_rule"),
                "near_expiry_fallback": bool(cm_meta.get("near_expiry_fallback")),
                "min_dte_days": int(cm_meta.get("min_dte_days") or min_dte_days),
                "vo_atm": atm.get("vo_atm"),
                "oi_atm": atm.get("oi_atm"),
                "n_contracts_day": len(day),
                "role": ATM_IV_ROLE,
                "compare_only": True,
                "canonical_level": BASEVOL_ROLE,
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


def build_daily_skew_series(
    rows: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    *,
    min_dte_days: int = DEFAULT_ATM_MIN_DTE_DAYS,
    put_moneyness: float = DEFAULT_SKEW_PUT_MONEYNESS,
) -> list[dict[str, Any]]:
    """95% put IV minus ATM mid. Missing put/ATM → omit. Never invent strikes."""
    target_m = float(put_moneyness)
    if not math.isfinite(target_m) or target_m <= 0.0:
        raise ValueError(f"put_moneyness must be finite > 0, got {put_moneyness!r}")
    by_date = _group_by_date(rows)
    out: list[dict[str, Any]] = []
    for date in sorted(by_date):
        sess = _settled_under(date, by_date, min_dte_days=min_dte_days)
        if sess is None:
            continue
        day, under_px, cm, cm_meta = sess
        atm = _atm_iv_at_cm(day, cm=cm, under_px=under_px)
        if atm is None:
            continue
        target_strike = target_m * under_px
        skew_strike = _nearest_strike(
            day,
            cm=cm,
            target=target_strike,
            pc_div=PC_PUT,
            require_finite_iv=True,
        )
        if skew_strike is None:
            continue
        put_ivs = [
            float(r["iv"])
            for r in day
            if r.get("cm") == cm
            and r.get("pc_div") == PC_PUT
            and r.get("strike") is not None
            and float(r["strike"]) == skew_strike  # type: ignore[arg-type]
            and r.get("iv") is not None
        ]
        if not put_ivs:
            continue
        put_iv = _median(put_ivs)
        atm_iv = float(atm["atm_iv"])
        skew = put_iv - atm_iv
        out.append(
            {
                "date": date,
                "skew": float(skew),
                "put_iv": float(put_iv),
                "atm_iv": atm_iv,
                "strike": float(skew_strike),
                "atm_strike": float(atm["strike"]),
                "target_strike": float(target_strike),
                "put_moneyness_target": target_m,
                "realized_moneyness": (
                    float(skew_strike) / under_px if under_px else None
                ),
                "under_px": float(under_px),
                "cm": cm,
                "dte": cm_meta.get("dte"),
                "cm_pick_rule": cm_meta.get("cm_pick_rule"),
                "near_expiry_fallback": bool(cm_meta.get("near_expiry_fallback")),
                "min_dte_days": int(cm_meta.get("min_dte_days") or min_dte_days),
                "convention": SKEW_CONVENTION,
                "invent_strike": False,
                "gap_policy": GAP_POLICY,
                "ffill_applied": False,
            }
        )
    return out


def build_daily_term_series(
    rows: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    *,
    min_dte_days: int = DEFAULT_ATM_MIN_DTE_DAYS,
) -> list[dict[str, Any]]:
    """Near CM ATM IV minus next CM. Missing leg → omit. Never invent strikes."""
    by_date = _group_by_date(rows)
    out: list[dict[str, Any]] = []
    for date in sorted(by_date):
        sess = _settled_under(date, by_date, min_dte_days=min_dte_days)
        if sess is None:
            continue
        day, under_px, near_cm, near_meta = sess
        next_cm, next_meta = _pick_next_cm(
            date, day, near_cm=near_cm, min_dte_days=min_dte_days
        )
        if not next_cm:
            continue
        near_atm = _atm_iv_at_cm(day, cm=near_cm, under_px=under_px)
        next_atm = _atm_iv_at_cm(day, cm=next_cm, under_px=under_px)
        if near_atm is None or next_atm is None:
            continue
        near_iv = float(near_atm["atm_iv"])
        next_iv = float(next_atm["atm_iv"])
        out.append(
            {
                "date": date,
                "cm_term": near_iv - next_iv,
                "near_atm_iv": near_iv,
                "next_atm_iv": next_iv,
                "near_cm": near_cm,
                "next_cm": next_cm,
                "near_strike": float(near_atm["strike"]),
                "next_strike": float(next_atm["strike"]),
                "near_dte": near_meta.get("dte"),
                "next_dte": next_meta.get("dte"),
                "near_cm_pick_rule": near_meta.get("cm_pick_rule"),
                "next_cm_pick_rule": next_meta.get("cm_pick_rule"),
                "near_expiry_fallback": bool(
                    near_meta.get("near_expiry_fallback")
                    or next_meta.get("near_expiry_fallback")
                ),
                "min_dte_days": int(min_dte_days),
                "under_px": float(under_px),
                "convention": CM_TERM_CONVENTION,
                "invent_strike": False,
                "gap_policy": GAP_POLICY,
                "ffill_applied": False,
            }
        )
    return out


def build_daily_basevol_delta_series(
    base: Sequence[Mapping[str, Any]] | None = None,
    rows: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Observed BaseVol[t] − BaseVol[t-1]. First day omitted. No ffill."""
    if base is None:
        if rows is None:
            raise ValueError("build_daily_basevol_delta_series requires base or rows")
        base = build_daily_basevol_series(rows)
    ordered = sorted(
        (
            r
            for r in base
            if r.get("date") is not None and r.get("base_vol") is not None
        ),
        key=lambda r: str(r["date"])[:10],
    )
    out: list[dict[str, Any]] = []
    for i in range(1, len(ordered)):
        prev = ordered[i - 1]
        cur = ordered[i]
        bv0 = float(prev["base_vol"])  # type: ignore[arg-type]
        bv1 = float(cur["base_vol"])  # type: ignore[arg-type]
        d0 = str(prev["date"])[:10]
        d1 = str(cur["date"])[:10]
        log_delta: float | None
        if bv0 > 0.0 and bv1 > 0.0:
            log_delta = math.log(bv1 / bv0)
        else:
            log_delta = None
        out.append(
            {
                "date": d1,
                "basevol_delta": bv1 - bv0,
                "log_delta": log_delta,
                "base_vol": bv1,
                "base_vol_prev": bv0,
                "prev_date": d0,
                "convention": BASEVOL_DELTA_CONVENTION,
                "gap_policy": GAP_POLICY,
                "ffill_applied": False,
                "first_day_omitted": False,
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
    base_gaps = calendar_gap_dates(base_dates)
    atm_gaps = calendar_gap_dates(atm_dates)
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
        "calendar_gaps_in_base_span": base_gaps,
        "calendar_gaps_in_atm_span": atm_gaps,
        "n_calendar_gaps_base": len(base_gaps),
        "n_calendar_gaps_atm": len(atm_gaps),
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
    }


def build_series_bundle_from_rows(
    rows: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Convenience: BaseVol + ATM + spread + skew + CM-term + ΔBaseVol + stats."""
    materialised = list(rows)
    base = build_daily_basevol_series(materialised)
    atm = build_daily_atm_iv_series(materialised)
    spread = build_spread_series(base, atm)
    skew = build_daily_skew_series(materialised)
    term = build_daily_term_series(materialised)
    delta = build_daily_basevol_delta_series(base=base)
    stats = summarize_vol_series(base, atm, spread)
    stats["n_skew_days"] = len(skew)
    stats["n_cm_term_days"] = len(term)
    stats["n_basevol_delta_days"] = len(delta)
    if skew:
        stats["skew_mean"] = statistics.mean(float(r["skew"]) for r in skew)
    if term:
        stats["cm_term_mean"] = statistics.mean(float(r["cm_term"]) for r in term)
    if delta:
        stats["basevol_delta_mean"] = statistics.mean(
            float(r["basevol_delta"]) for r in delta
        )
    return {
        "base_vol_series": base,
        "atm_iv_series": atm,
        "spread_series": spread,
        "skew_series": skew,
        "cm_term_series": term,
        "basevol_delta_series": delta,
        "stats": stats,
        "version": OPTIONS_225_VOL_SERIES_VERSION,
        "wave": OPTIONS_225_VOL_SERIES_WAVE,
        "dataset": DATASET_ID,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "ffill_applied": False,
        "canonical_level": "base_vol",
        "atm_iv_role": ATM_IV_ROLE,
    }


# Regime maps for factory / CF (rolling short/long on observed dates only).
# Units: percent vol points (J-Quants BaseVol / IV). Not annualized decimal RV.
DEFAULT_OPT225_SHORT_N: int = 10
DEFAULT_OPT225_LONG_N: int = 60
SPREAD_CONVENTION: str = "atm_iv - base_vol"

_DEFAULT_LOG_DIR = (
    Path(__file__).resolve().parents[3] / ".glm-logs" / "w0818b_w92_options_vol"
)
_W94_LOG_DIR = (
    Path(__file__).resolve().parents[3] / ".glm-logs" / "w0818d_w94_opt_skew_thick"
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
    skew_rows: Sequence[Mapping[str, Any]] | None = None,
    term_rows: Sequence[Mapping[str, Any]] | None = None,
    basevol_delta_rows: Sequence[Mapping[str, Any]] | None = None,
    short_n: int = DEFAULT_OPT225_SHORT_N,
    long_n: int = DEFAULT_OPT225_LONG_N,
) -> dict[str, Any]:
    """Build BaseVol / ATM / spread / skew / CM-term / ΔBaseVol regime maps.

    BaseVol = canonical level. ATM IV maps are included as **compare-only**.
    """
    if spread_rows is None:
        spread_rows = build_spread_series(base_rows, atm_rows)
    if basevol_delta_rows is None:
        basevol_delta_rows = build_daily_basevol_delta_series(base=base_rows)
    base_lvl = series_rows_to_level_map(base_rows, "base_vol")
    atm_lvl = series_rows_to_level_map(atm_rows, "atm_iv")
    spread_lvl = series_rows_to_level_map(spread_rows, "spread")
    skew_lvl = (
        series_rows_to_level_map(skew_rows, "skew") if skew_rows is not None else {}
    )
    term_lvl = (
        series_rows_to_level_map(term_rows, "cm_term") if term_rows is not None else {}
    )
    delta_lvl = series_rows_to_level_map(basevol_delta_rows, "basevol_delta")
    # day-over-day change of spread (skip first obs / gaps → no invent)
    spread_chg: dict[str, float] = {}
    sp_dates = sorted(spread_lvl)
    for i in range(1, len(sp_dates)):
        d0, d1 = sp_dates[i - 1], sp_dates[i]
        spread_chg[d1] = spread_lvl[d1] - spread_lvl[d0]
    bundle: dict[str, Any] = {
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
            source="options_225_atm_iv_compare_only",
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
        "skew_convention": SKEW_CONVENTION,
        "cm_term_convention": CM_TERM_CONVENTION,
        "basevol_delta_convention": BASEVOL_DELTA_CONVENTION,
        "units": "percent_vol_points",
        "dataset": DATASET_ID,
        "version": OPTIONS_225_VOL_SERIES_VERSION,
        "wave": OPTIONS_225_VOL_SERIES_WAVE,
        "canonical_level": "basevol",
        "atm_iv_role": ATM_IV_ROLE,
        "ffill_applied": False,
        "invent_fill": False,
    }
    # Mark ATM series compare-only on the regime map itself.
    bundle["atm_iv"]["compare_only"] = True
    bundle["atm_iv"]["role"] = ATM_IV_ROLE
    bundle["basevol"]["role"] = BASEVOL_ROLE
    if skew_lvl:
        bundle["skew"] = level_series_to_regime_maps(
            skew_lvl,
            short_n=short_n,
            long_n=long_n,
            source="options_225_skew_95put",
            series_kind="skew",
        )
    if term_lvl:
        bundle["cm_term"] = level_series_to_regime_maps(
            term_lvl,
            short_n=short_n,
            long_n=long_n,
            source="options_225_cm_term_near_minus_next",
            series_kind="cm_term",
        )
    if delta_lvl:
        bundle["basevol_delta"] = level_series_to_regime_maps(
            delta_lvl,
            short_n=short_n,
            long_n=long_n,
            source="options_225_basevol_delta",
            series_kind="basevol_delta",
        )
    return bundle


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
    """Load pre-built series ndjson from W92/W94 log dirs.

    Prefers explicit ``log_dir``. Otherwise tries W94 then W92. Missing
    skew / CM-term stay empty/None; ΔBaseVol derives from BaseVol when absent.
    """
    candidates: list[Path] = []
    if log_dir is not None:
        candidates.append(Path(log_dir))
    else:
        candidates.extend([_W94_LOG_DIR, _DEFAULT_LOG_DIR])
    d: Path | None = None
    for c in candidates:
        if (c / "base_vol_series.ndjson").is_file() and (
            c / "atm_iv_series.ndjson"
        ).is_file():
            d = c
            break
    if d is None:
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
    delta_p = d / "basevol_delta_series.ndjson"
    skew = load_ndjson_series(skew_p) if skew_p.is_file() else None
    term = load_ndjson_series(term_p) if term_p.is_file() else None
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
        "basevol_delta_series": delta,
        "meta": meta,
        "log_dir": str(d),
        "dataset": DATASET_ID,
        "source": "opt225_log_cache",
        "canonical_level": "base_vol",
        "atm_iv_role": ATM_IV_ROLE,
    }


__all__ = [
    "OPTIONS_225_VOL_SERIES_VERSION",
    "OPTIONS_225_VOL_SERIES_WAVE",
    "DATASET_ID",
    "GAP_POLICY",
    "IV_FIELDS_AVAILABLE_FROM",
    "BASEVOL_ROLE",
    "ATM_IV_ROLE",
    "normalize_options_225_row",
    "build_daily_basevol_series",
    "build_daily_atm_iv_series",
    "build_spread_series",
    "build_daily_skew_series",
    "build_daily_term_series",
    "build_daily_basevol_delta_series",
    "calendar_gap_dates",
    "pearson_corr",
    "summarize_vol_series",
    "build_series_bundle_from_rows",
    "DEFAULT_OPT225_SHORT_N",
    "DEFAULT_OPT225_LONG_N",
    "DEFAULT_SKEW_PUT_MONEYNESS",
    "SPREAD_CONVENTION",
    "SKEW_CONVENTION",
    "CM_TERM_CONVENTION",
    "BASEVOL_DELTA_CONVENTION",
    "DEFAULT_ATM_MIN_DTE_DAYS",
    "level_series_to_regime_maps",
    "series_rows_to_level_map",
    "build_opt225_regime_bundle",
    "load_ndjson_series",
    "load_opt225_series_cache",
]
