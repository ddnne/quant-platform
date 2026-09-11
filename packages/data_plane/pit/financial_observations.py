"""Pure catalog payload extraction and latest per-share financial observation.

PIT owns input order and revision selection. This module does not query
storage, sort rows, or apply a newer selection contract. Payload values are
accepted only as ``dict`` (not a general Mapping). An empty payload dict
stops raw-payload fallback. Numeric conversion matches the historical helper:
non-finite floats are not rejected here.
"""

from __future__ import annotations

import json
from typing import Any


def catalog_row_payload(row: dict[str, Any]) -> dict[str, Any]:
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


def _as_float_or_none(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def latest_fins_per_share_observation(
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Select the exact BPS/EPS observation and its own split-safety anchor.

    Prefers BPS as the established value-feature contract does. Statement
    period end is preferred; disclosure date is the explicit fallback.
    ``fins_rows`` counts every nonempty parsed payload, including rows that
    are not per-share observations.
    """
    latest_bps: dict[str, Any] | None = None
    latest_eps: dict[str, Any] | None = None
    parsed_rows = 0
    for row in rows or []:
        payload = catalog_row_payload(row)
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


__all__ = [
    "catalog_row_payload",
    "latest_fins_per_share_observation",
]
