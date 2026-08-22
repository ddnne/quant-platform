"""Shared offline fixtures for COMPLETE-21 min feature tests.

Not collected by pytest (no ``test_`` prefix). Seed helpers write through
:class:`storage.sqlite_store.SqliteStore` so feature compute sees the same
generic catalog layout as local ingest.
"""

from __future__ import annotations

import json
from pathlib import Path

from storage.sqlite_store import SqliteStore

from features import compute

from tests._coreseed import CODES, close_iso, seed_db


def _seed_c21(tmp_path, days=None, *, prices=None, price=100.0):
    days = list(days or ("2025-04-01", "2025-04-02"))
    if prices is None:
        prices = {CODES[0]: {d: price for d in days}}
    return days, seed_db(tmp_path, days=days, prices=prices)


COMPLETE21_MIN_IDS = (
    "volume_change_1d",
    "topix_relative_1d",
    "disclosure_flag_fins",
    "margin_interest_change_1d",
    "short_ratio_level",
    "is_trading_day",
    "repo_rate_level",
    "return_1d_c21",
    "margin_alert_flag",
    "futures_activity_proxy",
)

COMPLETE21_MIN_APPROVED_IDS = (
    "is_trading_day",
    "volume_change_1d",
    "topix_relative_1d",
    "disclosure_flag_fins",
    "margin_interest_change_1d",
    "repo_rate_level",
    "short_ratio_level",
    "futures_activity_proxy",
    "margin_alert_flag",
)
COMPLETE21_MIN_CANDIDATE_IDS = tuple(
    fid for fid in COMPLETE21_MIN_IDS if fid not in COMPLETE21_MIN_APPROVED_IDS
)

# Features that require a specific kwargs at the runtime gate.
_REQUIRED_INPUT_CASES = (
    ("volume_change_1d", ("code",)),
    ("topix_relative_1d", ("code",)),
    ("disclosure_flag_fins", ("code",)),
    ("margin_interest_change_1d", ("code",)),
    ("short_ratio_level", ("section",)),
    ("return_1d_c21", ("code",)),
    ("margin_alert_flag", ("code",)),
)


def _upsert_jquants_records(
    db_path: Path,
    *,
    dataset: str,
    payloads: list[dict],
    available_at: str | None = None,
) -> None:
    """Seed generic catalog rows for complete21 feature tests."""
    store = SqliteStore(db_path)
    rows = []
    for p in payloads:
        nk_obj: dict = {}
        if "Code" in p or "code" in p:
            nk_obj["Code"] = str(p.get("Code") or p.get("code"))
        if "Date" in p or "date" in p:
            nk_obj["Date"] = str(p.get("Date") or p.get("date"))[:10]
        if "S33" in p:
            nk_obj["S33"] = str(p["S33"])
        if not nk_obj:
            nk_obj = {"_row": json.dumps(p, sort_keys=True, separators=(",", ":"))}
        d = nk_obj.get("Date") or "2025-04-01"
        avail = available_at or close_iso(d)
        rows.append(
            {
                "source": "jquants",
                "dataset": dataset,
                "natural_key": json.dumps(nk_obj, sort_keys=True, separators=(",", ":")),
                "event_time": f"{d}T00:00:00+09:00",
                "available_at": avail,
                "ingested_at": avail,
                "payload": json.dumps(p, ensure_ascii=False),
                "raw_payload": json.dumps(p, ensure_ascii=False),
            }
        )
    store.upsert("jquants_records", rows)
    store.close()


def _upsert_repo_rates(
    db_path: Path,
    rows: list[dict],
) -> None:
    store = SqliteStore(db_path)
    store.upsert("jsda_repo_rates", rows)
    store.close()


def _feat(fid, db, day, **kw):
    return compute(fid, as_of=close_iso(day), db_path=db, **kw)


def _seed_payloads(
    tmp_path,
    payloads=None,
    *,
    days=None,
    prices=None,
    price=100.0,
    repo=None,
):
    days, db = _seed_c21(tmp_path, days, prices=prices, price=price)
    for ds, rows in (payloads or {}).items():
        _upsert_jquants_records(db, dataset=ds, payloads=rows)
    if repo is not None:
        _upsert_repo_rates(db, repo)
    return days, db


def _seed_feat(
    tmp_path,
    fid,
    *,
    days=None,
    prices=None,
    price=100.0,
    payloads=None,
    repo=None,
    as_of=None,
    **kw,
):
    days, db = _seed_payloads(
        tmp_path, payloads, days=days, prices=prices, price=price, repo=repo
    )
    return _feat(fid, db, as_of or days[-1], **kw), days, db


def _ramp(days, start=100.0, step=1.0):
    return {CODES[0]: {d: start + i * step for i, d in enumerate(days)}}


def _const_px(days, price=100.0):
    return {CODES[0]: {d: price for d in days}}


def _margin_row(day, long_vol, shrt_vol=0.0, code=None):
    return {
        "Date": day,
        "Code": code or CODES[0],
        "LongVol": long_vol,
        "ShrtVol": shrt_vol,
    }


def _short_ratio_payload(day, s33, sell, with_res, no_res):
    return {
        "Date": day,
        "S33": s33,
        "SellExShortVa": sell,
        "ShrtWithResVa": with_res,
        "ShrtNoResVa": no_res,
    }


def _alert_row(day, code=None):
    c = code or CODES[0]
    return {"Code": c, "PubDate": day, "AppDate": day, "Date": day}


def _fut_row(day, code, volume, close):
    return {"Date": day, "Code": code, "Volume": volume, "Close": close}


def _topix_row(day, close):
    return {"Date": day, "Close": close}


def _fins_row(day, **extra):
    return {"Code": CODES[0], "Date": day, **extra}


def _repo_row(day, rate, tenor="overnight"):
    iso = close_iso(day)
    return {
        "source": "jsda",
        "as_of_date": day,
        "tenor": tenor,
        "rate_type": "東京レポ・レート",
        "event_time": f"{day}T15:00:00+09:00",
        "available_at": iso,
        "ingested_at": iso,
        "rate": rate,
    }
