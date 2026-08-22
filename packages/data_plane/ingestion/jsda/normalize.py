"""Normalize parsed JSDA records into PIT-annotated structured rows."""

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


def normalize_otc_reference_prices(
    records: Iterable[dict],
    *,
    ingested_at: str,
    publication_label_date: Optional[str] = None,
    quote_effective_date: Optional[str] = None,
    available_at: Optional[str] = None,
    source_url: str,
    raw_digest: str,
    segment_id: str,
    source_format: str = "csv",
    correction_publication_label: Optional[str] = None,
    correction_published_at: Optional[str] = None,
    correction_source_url: Optional[str] = None,
    correction_raw_digest: Optional[str] = None,
) -> List[dict]:
    """Normalize OTC-reference rows. Publication label is not the quote date."""
    availability = available_at or ingested_at
    out: list[dict] = []
    for record in records:
        label = record.get("publication_label_date") or publication_label_date
        effective = record.get("quote_effective_date") or quote_effective_date
        if not label:
            raise ValueError("OTC reference row missing publication_label_date")
        if not effective:
            raise ValueError(
                "OTC reference row missing calendar-resolved quote_effective_date"
            )
        label = str(label)[:10]
        effective = str(effective)[:10]
        event_time = to_iso(parse_dt(f"{effective}T15:00:00"))
        out.append({
            "source": "jsda",
            "publication_label_date": label,
            "quote_effective_date": effective,
            "security_code": str(record.get("security_code") or "").strip(),
            "bond_name": str(record.get("bond_name") or "").strip(),
            "quote_effective_time": event_time,
            "event_time": event_time,
            "available_at": availability,
            "ingested_at": ingested_at,
            "coupon_rate": record.get("coupon_rate"),
            "maturity_date": record.get("maturity_date"),
            "average_price": record.get("average_price"),
            "average_yield": record.get("average_yield"),
            "median_price": record.get("median_price"),
            "median_yield": record.get("median_yield"),
            "high_price": record.get("high_price"),
            "high_yield": record.get("high_yield"),
            "low_price": record.get("low_price"),
            "low_yield": record.get("low_yield"),
            "individual_investor_flag": record.get("individual_investor_flag"),
            "source_row_number": record.get("source_row_number"),
            "source_url": source_url,
            "raw_digest": raw_digest,
            "segment_id": segment_id,
            "source_format": source_format,
            "correction_publication_label": correction_publication_label,
            "correction_published_at": correction_published_at,
            "correction_source_url": correction_source_url,
            "correction_raw_digest": correction_raw_digest,
            "raw_payload": json.dumps(record, ensure_ascii=False, sort_keys=True),
        })
    return out


def normalize_corporate_bond_transactions(
    records: Iterable[dict],
    *,
    ingested_at: str,
    publication_label_date: Optional[str] = None,
    available_at: Optional[str] = None,
    source_url: str,
    raw_digest: str,
    segment_id: str,
    source_format: str = "csv",
    correction_publication_label: Optional[str] = None,
    correction_published_at: Optional[str] = None,
    correction_source_url: Optional[str] = None,
    correction_raw_digest: Optional[str] = None,
) -> List[dict]:
    """Normalize 社債の取引情報 rows. NK is publication + source_record_id."""
    availability = available_at or ingested_at
    out: list[dict] = []
    for index, record in enumerate(records):
        label = record.get("publication_label_date") or publication_label_date
        trade_date = record.get("trade_date")
        if not label:
            raise ValueError(
                "corporate bond row missing publication_label_date"
            )
        if not trade_date:
            raise ValueError("corporate bond row missing trade_date")
        label = str(label)[:10]
        trade_date = str(trade_date)[:10]
        source_record_id = str(
            record.get("source_record_id")
            or record.get("source_row_number")
            or (index + 1)
        )
        try:
            event_time = to_iso(parse_dt(f"{trade_date}T15:00:00"))  # JST close
        except ValueError:
            event_time = to_iso(parse_dt(trade_date))
        out.append({
            "source": "jsda",
            "publication_label_date": label,
            "trade_date": trade_date,
            "security_code": str(record.get("security_code") or "").strip(),
            "source_record_id": source_record_id,
            "issuer_name": str(record.get("issuer_name") or "").strip(),
            "isin": str(record.get("isin") or "").strip(),
            "event_time": event_time,
            "available_at": availability,
            "ingested_at": ingested_at,
            "coupon_rate": record.get("coupon_rate"),
            "maturity_date": record.get("maturity_date"),
            "transaction_type": record.get("transaction_type"),
            "buyer_counterparty_type": record.get("buyer_counterparty_type"),
            "seller_counterparty_type": record.get("seller_counterparty_type"),
            "face_value_mil_jpy": record.get("face_value_mil_jpy"),
            "trade_amount_mil_jpy": record.get("trade_amount_mil_jpy"),
            "execution_price": record.get("execution_price"),
            "execution_yield": record.get("execution_yield"),
            "source_url": source_url,
            "raw_digest": raw_digest,
            "segment_id": segment_id,
            "source_format": source_format,
            "correction_publication_label": correction_publication_label,
            "correction_published_at": correction_published_at,
            "correction_source_url": correction_source_url,
            "correction_raw_digest": correction_raw_digest,
            "raw_payload": json.dumps(record, ensure_ascii=False, sort_keys=True),
        })
    return out


def normalize_repo_rates(
    records: Iterable[dict],
    *,
    ingested_at: str,
    available_at: Optional[str] = None,
    rate_type: str = "東京レポ・レート",
) -> List[dict]:
    """Normalize ``{as_of_date, tenor, rate}`` into PIT ``jsda_repo_rates`` rows."""
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
