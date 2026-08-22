"""Shared offline fixtures for COMPLETE-21 min feature tests.

Not collected by pytest (no ``test_`` prefix). Seed helpers write through
:class:`storage.sqlite_store.SqliteStore` so feature compute sees the same
generic catalog layout as local ingest.
"""

from __future__ import annotations

import json
from pathlib import Path

from storage.sqlite_store import SqliteStore

from tests._coreseed import CODES, close_iso, seed_db

# W49–W50 held (7) + W51 expand (+3) = 10 complete21 min features.
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

# W52 + W53 + W54 + W55 + W56 + W57 O2 promotions; version pin remains 1.0.0.
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
        # Prefer Date/Code natural keys when present; else compact payload key.
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
