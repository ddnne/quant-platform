"""COMPLETE-21 min feature row parsers.

Payload / bar / catalog row extraction only. No PIT reads, no registry.
Permanent DEFER is enforced by compute before these parsers run.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


def _parse_volume_rows(rows: list[dict[str, Any]]) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for r in rows:
        v = r.get("volume")
        d = r.get("date")
        if v is None or d is None:
            continue
        try:
            out.append((str(d), float(v)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def _parse_close_rows(rows: list[dict[str, Any]]) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for r in rows:
        c = r.get("close")
        d = r.get("date")
        if c is None or d is None:
            # jquants_records payload shape
            payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
            if c is None:
                c = payload.get("Close") or payload.get("close")
            if d is None:
                d = (
                    payload.get("Date")
                    or payload.get("date")
                    or r.get("event_time")
                )
                if d is not None:
                    d = str(d)[:10]
        if c is None or d is None:
            continue
        try:
            out.append((str(d)[:10], float(c)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def _row_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Best-effort payload dict from a jquants_records (or flattened) row."""
    p = row.get("payload")
    if isinstance(p, dict):
        return p
    if isinstance(p, str) and p:
        try:
            loaded = json.loads(p)
            if isinstance(loaded, dict):
                return loaded
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    raw = row.get("raw_payload")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                return loaded
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return {}


def _parse_margin_interest_rows(
    rows: list[dict[str, Any]],
) -> list[tuple[str, float]]:
    """Extract ``(date, LongVol + ShrtVol)`` from margin-interest catalog rows."""
    out: list[tuple[str, float]] = []
    for r in rows:
        payload = _row_payload(r)
        d = (
            payload.get("Date")
            or payload.get("date")
            or r.get("date")
            or (str(r.get("event_time"))[:10] if r.get("event_time") else None)
        )
        long_v = payload.get("LongVol")
        short_v = payload.get("ShrtVol")
        if long_v is None and short_v is None:
            long_v = r.get("LongVol")
            short_v = r.get("ShrtVol")
        if d is None or (long_v is None and short_v is None):
            continue
        try:
            total = float(long_v or 0.0) + float(short_v or 0.0)
            out.append((str(d)[:10], total))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def _latest_short_ratio_row(
    rows: list[dict[str, Any]],
    *,
    section: str,
) -> dict[str, Any] | None:
    """Pick the latest short-ratio row for ``section`` (S33)."""
    section_s = str(section).strip()
    candidates: list[tuple[str, dict[str, Any]]] = []
    for r in rows:
        payload = _row_payload(r)
        s33 = payload.get("S33") or payload.get("section") or r.get("S33")
        if s33 is None or str(s33).strip() != section_s:
            continue
        d = (
            payload.get("Date")
            or payload.get("date")
            or (str(r.get("event_time"))[:10] if r.get("event_time") else None)
        )
        if d is None:
            continue
        candidates.append((str(d)[:10], {**payload, **{k: v for k, v in r.items() if k not in ("payload", "raw_payload")}}))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[-1][1]


def _parse_futures_volume_rows(
    rows: list[dict[str, Any]],
) -> list[tuple[str, float]]:
    """Extract ``(date, volume)`` from derivatives futures catalog rows."""
    out: list[tuple[str, float]] = []
    for r in rows:
        payload = _row_payload(r)
        d = (
            payload.get("Date")
            or payload.get("date")
            or r.get("date")
            or (str(r.get("event_time"))[:10] if r.get("event_time") else None)
        )
        vol = (
            payload.get("Volume")
            or payload.get("volume")
            or r.get("volume")
            or r.get("Volume")
        )
        if d is None or vol is None:
            continue
        try:
            out.append((str(d)[:10], float(vol)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def _as_float_or_none(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _latest_fins_eps_bps(
    rows: list[dict[str, Any]],
) -> tuple[float | None, float | None, dict[str, Any]]:
    """Walk PIT-visible fins_summary rows; take latest non-empty EPS/BPS."""
    eps: float | None = None
    bps: float | None = None
    disc_date: str | None = None
    n = 0
    for row in rows or []:
        payload = row.get("payload") if isinstance(row, Mapping) else None
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        if not isinstance(payload, Mapping):
            continue
        n += 1
        e = _as_float_or_none(
            payload.get("EPS") if payload.get("EPS") is not None else payload.get("eps")
        )
        b = _as_float_or_none(
            payload.get("BPS") if payload.get("BPS") is not None else payload.get("bps")
        )
        if e is not None:
            eps = e
        if b is not None:
            bps = b
        if e is not None or b is not None:
            disc_date = (
                str(payload.get("DiscDate") or payload.get("disc_date") or "")[:10]
                or disc_date
            )
    return eps, bps, {"fins_rows": n, "disc_date": disc_date}


def _latest_fins_per_share_observation(
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Select the exact BPS/EPS observation and its own split-safety anchor.

    The legacy parser intentionally remains untouched.  This stricter helper
    binds the chosen per-share value to the row that supplied it, preferring
    BPS as the established value-feature contract does.  Statement period
    end is preferred; disclosure date is the explicit fallback.
    """
    latest_bps: dict[str, Any] | None = None
    latest_eps: dict[str, Any] | None = None
    parsed_rows = 0
    for row in rows or []:
        payload = _row_payload(row)
        if not payload:
            continue
        parsed_rows += 1
        bps = _as_float_or_none(
            payload.get("BPS")
            if payload.get("BPS") is not None
            else payload.get("bps")
        )
        eps = _as_float_or_none(
            payload.get("EPS")
            if payload.get("EPS") is not None
            else payload.get("eps")
        )
        period_end = next(
            (
                str(payload.get(key))[:10]
                for key in (
                    "CurrentPeriodEndDate",
                    "CurPerEn",
                    "CurrentFiscalYearEndDate",
                    "CurFYEn",
                    "FiscalYearEndDate",
                    "PeriodEndDate",
                    "period_end",
                )
                if payload.get(key)
            ),
            None,
        )
        disclosure_date = next(
            (
                str(payload.get(key))[:10]
                for key in (
                    "DisclosedDate",
                    "DiscDate",
                    "disclosed_date",
                    "disc_date",
                )
                if payload.get(key)
            ),
            None,
        )
        anchor = period_end or disclosure_date
        common = {
            "statement_period_end": period_end,
            "disclosure_date": disclosure_date,
            "split_safety_anchor": anchor,
            "split_safety_anchor_source": (
                "statement_period_end" if period_end else "disclosure_date"
            ),
            "fins_rows": parsed_rows,
        }
        if bps is not None:
            latest_bps = {**common, "mode": "bps_over_price", "bps": bps}
        if eps is not None:
            latest_eps = {**common, "mode": "eps_over_price", "eps": eps}
    selected = latest_bps or latest_eps
    if selected is None:
        return None
    return {**selected, "fins_rows": parsed_rows}


def _retrospective_split_safety(
    rows: list[dict[str, Any]],
    *,
    anchor: str,
    factor_threshold: float = 0.01,
) -> tuple[bool, dict[str, Any]]:
    """Check per-share comparability from statement anchor through decision.

    ``AdjustmentVolume / Volume`` is invariant to a later adjustment that is
    applied uniformly to the whole inspected interval, so comparing its
    within-window ratios does not depend on a future adjustment constant.
    Missing adjusted-close evidence fails closed. AdjustmentVolume is only
    corroborating evidence: when absent, the AdjustmentClose / raw Close
    ratio remains the factor detector. Zero-volume sessions carry no volume
    ratio and are skipped for that corroborating leg.
    """
    observations: list[tuple[str, float, float | None, float]] = []
    for row in rows:
        day = str(row.get("date") or "")[:10]
        if not day:
            continue
        raw_close = _as_float_or_none(row.get("close"))
        adjusted_close = _as_float_or_none(row.get("adjustment_close"))
        volume = _as_float_or_none(row.get("volume"))
        adjusted_volume = _as_float_or_none(row.get("adjustment_volume"))
        if raw_close is None or adjusted_close is None or adjusted_close <= 0.0:
            return False, {
                "reason": "missing_adjusted_price_evidence",
                "event_date": day,
            }
        ratio: float | None = None
        if volume is not None and volume != 0.0:
            if adjusted_volume is not None:
                ratio = adjusted_volume / volume
                if ratio <= 0.0:
                    ratio = None
        if raw_close == 0.0:
            return False, {
                "reason": "invalid_raw_close_for_adjustment_ratio",
                "event_date": day,
            }
        price_ratio = adjusted_close / raw_close
        observations.append((day, adjusted_close, ratio, price_ratio))

    baseline_candidates = [item for item in observations if item[0] <= anchor]
    if not baseline_candidates:
        return False, {
            "reason": "missing_pre_anchor_factor_baseline",
            "anchor": anchor,
            "rows_seen": len(observations),
        }
    baseline = baseline_candidates[-1]
    volume_baseline = next(
        (item for item in reversed(baseline_candidates) if item[2] is not None),
        None,
    )
    base_volume_ratio = volume_baseline[2] if volume_baseline is not None else None
    base_price_ratio = baseline[3]
    volume_factor_change_dates: list[str] = []
    if base_volume_ratio is not None:
        for day, _close, ratio, _price_ratio in observations:
            if day <= anchor:
                continue
            if ratio is None:
                continue
            if abs(ratio / base_volume_ratio - 1.0) > factor_threshold:
                volume_factor_change_dates.append(day)
    price_factor_change_dates: list[str] = []
    if base_price_ratio is not None:
        for day, _close, _volume_ratio, price_ratio in observations:
            if day <= anchor:
                continue
            if abs(price_ratio / base_price_ratio - 1.0) > factor_threshold:
                price_factor_change_dates.append(day)
    factor_change_dates = sorted(
        set(volume_factor_change_dates) | set(price_factor_change_dates)
    )
    safe = not factor_change_dates
    return safe, {
        "reason": "split_safe" if safe else "per_share_split_blackout",
        "anchor": anchor,
        "rows_seen": len(observations),
        "factor_change_dates": sorted(set(factor_change_dates)),
        "price_factor_change_dates": sorted(set(price_factor_change_dates)),
        "volume_factor_change_dates": sorted(
            set(volume_factor_change_dates)
        ),
        "factor_threshold": factor_threshold,
    }
