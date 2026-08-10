"""Normalize parsed JSDA bond-trade records into PIT-annotated structured rows.

Maps the clean records from :mod:`parse` to the ``jsda_bond_trades`` schema.
This is the 引値-equivalent (corporate-bond quote/yield) series — column map
in ``docs/data_sources.md``.
"""

from __future__ import annotations

import json
from typing import Iterable, List, Optional

from ..common.timeutil import parse_dt, to_iso


def normalize_bond_trades(
    records: Iterable[dict], *, ingested_at: str, available_at: Optional[str] = None
) -> List[dict]:
    av = available_at or ingested_at
    out: List[dict] = []
    for rec in records:
        d = rec.get("trade_date")
        if not d:
            continue
        try:
            et = to_iso(parse_dt(f"{d[:10]}T15:00:00"))  # JST trade close
        except ValueError:
            et = to_iso(parse_dt(d[:10]))
        out.append(
            {
                "source": "jsda",
                "trade_date": d[:10],
                "isin": rec.get("isin") or "",
                "issuer_name": rec.get("issuer_name") or "",
                "event_time": et,
                "available_at": av,
                "ingested_at": ingested_at,
                "coupon_rate": rec.get("coupon_rate"),
                "maturity_date": rec.get("maturity_date"),
                "high_yield": rec.get("high_yield"),
                "low_yield": rec.get("low_yield"),
                "close_yield": rec.get("close_yield"),
                "trade_amount_mil_jpy": rec.get("trade_amount"),
                "raw_payload": json.dumps(rec, ensure_ascii=False),
            }
        )
    return out


def normalize_repo_rates(
    records: Iterable[dict],
    *,
    ingested_at: str,
    available_at: Optional[str] = None,
    rate_type: str = "東京レポ・レート",
) -> List[dict]:
    """Normalize parsed repo-rate records into PIT-annotated ``jsda_repo_rates``
    rows.

    Each input record is ``{as_of_date, tenor, rate}`` (from
    :func:`ingestion.jsda.parse.parse_repo_csv`). ``event_time`` is the rate's
    reference day at 15:00 JST (market close, matching the bond-trade
    convention); ``available_at`` defaults to ``ingested_at`` and is therefore
    **仮** until the real TRR publication lag is confirmed (the JSDA typically
    publishes the next business day). ``rate_type`` names the series — the TRR
    time-series file is the 東京レポ・レート; override for other series.
    """
    av = available_at or ingested_at
    out: List[dict] = []
    for rec in records:
        d = rec.get("as_of_date")
        if not d:
            continue
        try:
            et = to_iso(parse_dt(f"{d[:10]}T15:00:00"))  # JST close
        except ValueError:
            et = to_iso(parse_dt(d[:10]))
        tenor = (rec.get("tenor") or "").strip()
        out.append(
            {
                "source": "jsda",
                "as_of_date": d[:10],
                "tenor": tenor,
                "rate_type": rate_type,
                "event_time": et,
                "available_at": av,
                "ingested_at": ingested_at,
                "rate": rec.get("rate"),
                "raw_payload": json.dumps(rec, ensure_ascii=False),
            }
        )
    return out
