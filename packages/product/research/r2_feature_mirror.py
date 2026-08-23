"""Disposable SQLite mirror of R2 history rows. Never SoT.

Public import remains ``research.r2_feature_context``. Local sqlite is not
history SoT. Permanent DEFER hard-reject.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from data_contracts.permanent_defer import reject_permanent_defer_for_history
from research.r2_feature_parse import _decode_json_obj


def _row_event_day(row: Mapping[str, Any]) -> str | None:
    for key in ("date", "Date", "as_of_date"):
        v = row.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()[:10]
    et = row.get("event_time")
    if et is not None and str(et).strip():
        return str(et).strip()[:10]
    return None


def _row_code(row: Mapping[str, Any]) -> str | None:
    for key in ("code", "Code"):
        v = row.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    for key in ("Code", "code"):
        v = payload.get(key) if isinstance(payload, dict) else None
        if v is not None and str(v).strip():
            return str(v).strip()
    nk = _decode_json_obj(row.get("natural_key"))
    for key in ("Code", "code"):
        v = nk.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def materialize_disposable_sqlite_mirror(
    rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    db_path: str | Path | None = None,
) -> Path:
    """Write normalized R2 rows into a disposable SQLite table. Never SoT."""
    reject_permanent_defer_for_history(
        list(rows_by_dataset.keys()),
        context="disposable sqlite mirror",
    )
    if db_path is None:
        tmp = tempfile.NamedTemporaryFile(
            prefix="r2fc_mirror_", suffix=".sqlite", delete=False
        )
        path = Path(tmp.name)
        tmp.close()
    else:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()

    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE jquants_records ("
            "source TEXT NOT NULL, dataset TEXT NOT NULL, natural_key TEXT NOT NULL, "
            "event_time TEXT NOT NULL, available_at TEXT NOT NULL, ingested_at TEXT NOT NULL, "
            "payload TEXT, raw_payload TEXT, "
            "PRIMARY KEY (source, dataset, natural_key))"
        )
        conn.execute(
            "CREATE TABLE jquants_daily_bars ("
            "source TEXT NOT NULL, code TEXT NOT NULL, date TEXT NOT NULL, "
            "event_time TEXT NOT NULL, available_at TEXT NOT NULL, ingested_at TEXT NOT NULL, "
            "open REAL, high REAL, low REAL, close REAL, volume REAL, payload TEXT, "
            "PRIMARY KEY (source, code, date))"
        )
        conn.execute(
            "CREATE TABLE jquants_market_calendar ("
            "source TEXT NOT NULL, date TEXT NOT NULL, event_time TEXT NOT NULL, "
            "available_at TEXT NOT NULL, ingested_at TEXT NOT NULL, "
            "holiday_division TEXT, payload TEXT, PRIMARY KEY (source, date))"
        )
        for ds, rows in rows_by_dataset.items():
            for row in rows:
                aa = row.get("available_at")
                if aa is None or aa == "":
                    continue
                et = row.get("event_time") or aa
                ingested = row.get("ingested_at") or aa
                source = str(row.get("source") or "jquants")
                payload = row.get("payload")
                if isinstance(payload, dict):
                    payload_s = json.dumps(payload, ensure_ascii=True)
                elif payload is None:
                    payload_s = None
                else:
                    payload_s = str(payload)
                raw = row.get("raw_payload")
                if isinstance(raw, dict):
                    raw_s = json.dumps(raw, ensure_ascii=True)
                elif raw is None:
                    raw_s = payload_s
                else:
                    raw_s = str(raw)

                if ds == "equities_bars_daily":
                    code = str(row.get("code") or "")
                    d = str(row.get("date") or "")[:10]
                    if not code or not d:
                        continue
                    nk = json.dumps(
                        {"Code": code, "Date": d}, ensure_ascii=True, sort_keys=True
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO jquants_records "
                        "(source, dataset, natural_key, event_time, available_at, "
                        "ingested_at, payload, raw_payload) VALUES (?,?,?,?,?,?,?,?)",
                        (source, ds, nk, str(et), str(aa), str(ingested), payload_s, raw_s),
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO jquants_daily_bars "
                        "(source, code, date, event_time, available_at, ingested_at, "
                        "open, high, low, close, volume, payload) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            source,
                            code,
                            d,
                            str(et),
                            str(aa),
                            str(ingested),
                            row.get("open"),
                            row.get("high"),
                            row.get("low"),
                            row.get("close"),
                            row.get("volume"),
                            payload_s,
                        ),
                    )
                elif ds == "markets_calendar":
                    d = str(row.get("date") or "")[:10]
                    if not d:
                        continue
                    nk = json.dumps({"Date": d}, ensure_ascii=True, sort_keys=True)
                    conn.execute(
                        "INSERT OR REPLACE INTO jquants_records "
                        "(source, dataset, natural_key, event_time, available_at, "
                        "ingested_at, payload, raw_payload) VALUES (?,?,?,?,?,?,?,?)",
                        (source, ds, nk, str(et), str(aa), str(ingested), payload_s, raw_s),
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO jquants_market_calendar "
                        "(source, date, event_time, available_at, ingested_at, "
                        "holiday_division, payload) VALUES (?,?,?,?,?,?,?)",
                        (
                            source,
                            d,
                            str(et),
                            str(aa),
                            str(ingested),
                            row.get("holiday_division"),
                            payload_s,
                        ),
                    )
                else:
                    nk = row.get("natural_key")
                    if isinstance(nk, dict):
                        nk_s = json.dumps(nk, ensure_ascii=True, sort_keys=True)
                    elif nk is None or nk == "":
                        d = _row_event_day(row) or "0000-01-01"
                        c = _row_code(row)
                        nk_obj = {"Date": d}
                        if c:
                            nk_obj["Code"] = c
                        nk_s = json.dumps(nk_obj, ensure_ascii=True, sort_keys=True)
                    else:
                        nk_s = str(nk)
                    conn.execute(
                        "INSERT OR REPLACE INTO jquants_records "
                        "(source, dataset, natural_key, event_time, available_at, "
                        "ingested_at, payload, raw_payload) VALUES (?,?,?,?,?,?,?,?)",
                        (source, ds, nk_s, str(et), str(aa), str(ingested), payload_s, raw_s),
                    )
        conn.commit()
    finally:
        conn.close()
    return path


__all__ = [
    "materialize_disposable_sqlite_mirror",
]
