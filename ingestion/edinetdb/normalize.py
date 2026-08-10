"""Normalize EDINET DB payloads into PIT-annotated structured rows.

Field names are matched against several likely JSON keys (EDINET DB shape is
**仮**); see ``docs/data_sources.md``.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, List, Optional

from ..common.timeutil import parse_dt, to_iso


def _num(x: Any) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _s(x: Any) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()
    return s or None


def _pick(d: dict, *keys: str) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def normalize_companies(
    rows: Iterable[dict], *, ingested_at: str, available_at: Optional[str] = None
) -> List[dict]:
    av = available_at or ingested_at
    out: List[dict] = []
    for r in rows:
        code = _pick(r, "code", "edinet_code", "Code", "EdinetCode", "stock_code")
        if not code:
            continue
        out.append(
            {
                "source": "edinetdb",
                "code": code,
                "event_time": av,  # as-of snapshot moment
                "available_at": av,
                "ingested_at": ingested_at,
                "company_name": _pick(r, "name", "company_name", "CompanyName", "firm_name"),
                "edinet_code": _pick(r, "edinet_code", "EdinetCode"),
                "sector": _pick(r, "sector", "industry", "Industry"),
                "english_name": _pick(r, "english_name", "name_en", "EnglishName"),
                "raw_payload": json.dumps(r, ensure_ascii=False),
            }
        )
    return out


def normalize_financials(
    rows: Iterable[dict],
    *,
    code: str,
    ingested_at: str,
    available_at: Optional[str] = None,
) -> List[dict]:
    av = available_at or ingested_at
    out: List[dict] = []
    for r in rows:
        period = _pick(r, "period", "fiscal_year", "Period", "fiscal_period") or "unknown"
        stype = _pick(r, "statement_type", "type", "StatementType") or ""
        period_end = _pick(r, "period_end", "end_date", "EndDate", "fiscal_year_end")
        if period_end:
            try:
                et = to_iso(parse_dt(f"{period_end[:10]}T00:00:00"))
            except ValueError:
                et = av
        else:
            et = av
        out.append(
            {
                "source": "edinetdb",
                "code": code,
                "period": str(period),
                "statement_type": stype,
                "event_time": et,
                "available_at": av,
                "ingested_at": ingested_at,
                "revenue": _num(r.get("revenue") or r.get("net_sales") or r.get("NetSales")),
                "operating_income": _num(
                    r.get("operating_income") or r.get("operating_profit")
                ),
                "net_income": _num(
                    r.get("net_income") or r.get("profit") or r.get("net_profit")
                ),
                "total_assets": _num(r.get("total_assets") or r.get("TotalAssets")),
                "equity": _num(r.get("equity") or r.get("net_assets")),
                "raw_payload": json.dumps(r, ensure_ascii=False),
            }
        )
    return out
