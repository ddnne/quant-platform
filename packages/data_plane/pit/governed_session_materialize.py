"""Freeze-time canonical AM/PM fields from generic J-Quants records.

Does not reconstruct from full-day OHLC, estimate splits, or act as Draft
hydrator authority. Raw payload values are preserved and bound to source
natural keys plus sealed product evidence.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from data_contracts.personal_history_compact import (
    PERSONAL_HISTORY_COMPACT_BARS_CREATE_SQL,
    PERSONAL_HISTORY_COMPACT_BARS_TABLE,
    PERSONAL_HISTORY_COMPACT_MASTER_CREATE_SQL,
    PERSONAL_HISTORY_COMPACT_MASTER_TABLE,
)
from ops.receipt_product import PRODUCT_ARTIFACT_FIELDS, product_artifact_digest

from .errors import SnapshotObservationClockError
from .governed_am_view import (
    GOVERNED_AM_DATASET_ID,
    GOVERNED_DAILY_DATASET_ID,
    _am_payload_price,
    _canonical_payload_text,
    _decode_payload,
    _pm_payload_price,
    official_afternoon_close_as_of,
)


class GovernedSessionMaterializeError(SnapshotObservationClockError):
    """Raised when canonical AM/PM fields cannot be frozen from generic records."""


def _payload_of(row: Mapping[str, Any]) -> dict[str, Any]:
    return _decode_payload(row["payload"] if "payload" in row.keys() else row[6])


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _positive(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price == price and price not in (float("inf"), float("-inf")) and price > 0.0:
        return price
    return None


def materialize_canonical_session_fields(connection: sqlite3.Connection) -> dict[str, int]:
    """Materialize official MAdjC/AAdjC into the immutable snapshot.

    Source of truth is generic ``jquants_records`` plus sealed product
    evidence. Compact columns are filled from those raw payload fields when
    present. Missing canonical session fields fail closed.
    """

    tables = _table_names(connection)
    if "jquants_records" not in tables:
        raise GovernedSessionMaterializeError(
            "generic jquants_records are required to materialize session fields"
        )
    connection.row_factory = sqlite3.Row
    daily = connection.execute(
        "SELECT source, dataset, natural_key, event_time, available_at, "
        "ingested_at, payload, COALESCE(raw_payload, '') AS raw_payload "
        "FROM jquants_records WHERE source='jquants' AND dataset=? "
        "ORDER BY natural_key",
        (GOVERNED_DAILY_DATASET_ID,),
    ).fetchall()
    am_rows = connection.execute(
        "SELECT source, dataset, natural_key, event_time, available_at, "
        "ingested_at, payload, COALESCE(raw_payload, '') AS raw_payload "
        "FROM jquants_records WHERE source='jquants' AND dataset=? "
        "ORDER BY natural_key",
        (GOVERNED_AM_DATASET_ID,),
    ).fetchall()

    compact_am = 0
    compact_pm = 0
    if daily:
        connection.execute(PERSONAL_HISTORY_COMPACT_MASTER_CREATE_SQL)
        connection.execute(PERSONAL_HISTORY_COMPACT_BARS_CREATE_SQL)
        for row in daily:
            payload = _decode_payload(row["payload"])
            code = str(payload.get("Code") or payload.get("code") or "")
            day = str(payload.get("Date") or payload.get("date") or "")[:10]
            if not code or len(day) != 10:
                continue
            morning = _am_payload_price(payload)
            afternoon = _pm_payload_price(payload)
            close = _positive(payload.get("Close") or payload.get("C"))
            if close is None:
                close = morning or afternoon
            if close is None:
                raise GovernedSessionMaterializeError(
                    "canonical daily bar is missing a raw close"
                )
            if morning is None and afternoon is None:
                raise GovernedSessionMaterializeError(
                    "canonical daily bar is missing MAdjC/AAdjC; "
                    "OHLC reconstruction is forbidden"
                )
            if afternoon is None:
                raise GovernedSessionMaterializeError(
                    "canonical afternoon close AAdjC is missing"
                )
            expected_pm_event = official_afternoon_close_as_of(day)
            event_time = str(row["event_time"] or "")
            if event_time and event_time != expected_pm_event:
                # Keep the source event clock; do not rewrite PM to next close.
                pass
            connection.execute(
                f"""
                INSERT INTO {PERSONAL_HISTORY_COMPACT_BARS_TABLE} (
                    code,date,event_time,available_at,ingested_at,
                    close,volume,turnover_value,adjustment_close,adjustment_volume,
                    morning_adjustment_close,afternoon_adjustment_close,
                    morning_turnover_value,afternoon_turnover_value,
                    morning_adjustment_volume,afternoon_adjustment_volume,
                    market_cap
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(code, date) DO UPDATE SET
                    morning_adjustment_close=excluded.morning_adjustment_close,
                    afternoon_adjustment_close=excluded.afternoon_adjustment_close,
                    close=excluded.close,
                    event_time=excluded.event_time,
                    available_at=excluded.available_at,
                    ingested_at=excluded.ingested_at
                """,
                (
                    code,
                    day,
                    event_time,
                    str(row["available_at"] or ""),
                    str(row["ingested_at"] or ""),
                    close,
                    payload.get("Volume") or payload.get("Vo"),
                    payload.get("TurnoverValue") or payload.get("Va"),
                    payload.get("AdjustmentClose")
                    or payload.get("AdjClose")
                    or payload.get("AdjC"),
                    payload.get("AdjustmentVolume")
                    or payload.get("AdjVolume")
                    or payload.get("AdjVo"),
                    morning,
                    afternoon,
                    payload.get("MorningTurnoverValue") or payload.get("MVa"),
                    payload.get("AfternoonTurnoverValue") or payload.get("AVa"),
                    payload.get("MorningAdjustmentVolume") or payload.get("MAdjVo"),
                    payload.get("AfternoonAdjustmentVolume") or payload.get("AAdjVo"),
                    payload.get("MarketCapitalization")
                    or payload.get("MarketCap")
                    or payload.get("MktCap"),
                ),
            )
            if morning is not None:
                compact_am += 1
            if afternoon is not None:
                compact_pm += 1

    if not am_rows:
        raise GovernedSessionMaterializeError(
            "canonical equities_bars_daily_am rows are missing"
        )
    product_rows: list[dict[str, str]] = []
    for row in am_rows:
        payload = _decode_payload(row["payload"])
        if _am_payload_price(payload) is None:
            raise GovernedSessionMaterializeError(
                "canonical AM product row is missing MAdjC"
            )
        payload_text = _canonical_payload_text(row["payload"])
        product_rows.append(
            {
                "source": str(row["source"]),
                "dataset": str(row["dataset"]),
                "natural_key": str(row["natural_key"]),
                "event_time": str(row["event_time"]),
                "available_at": str(row["available_at"]),
                "ingested_at": str(row["ingested_at"]),
                "payload": payload_text,
                "raw_payload": str(row["raw_payload"] or ""),
            }
        )
        for field in PRODUCT_ARTIFACT_FIELDS:
            if type(product_rows[-1][field]) is not str:
                raise GovernedSessionMaterializeError(
                    "AM product evidence fields must preserve raw text"
                )

    if "receipt_product_materializations" in tables and product_rows:
        live_digest = product_artifact_digest(product_rows)
        sealed = connection.execute(
            "SELECT artifact_digest FROM receipt_product_materializations "
            "WHERE source='jquants' AND dataset=?",
            (GOVERNED_AM_DATASET_ID,),
        ).fetchall()
        if not sealed:
            raise GovernedSessionMaterializeError(
                "sealed AM product evidence is missing"
            )
        if live_digest not in {str(row["artifact_digest"]) for row in sealed}:
            raise GovernedSessionMaterializeError(
                "AM product evidence does not bind the generic source rows"
            )

    if compact_pm < 1 and daily:
        raise GovernedSessionMaterializeError(
            "frozen snapshot does not expose canonical AAdjC"
        )
    return {
        "am_source_rows": len(am_rows),
        "daily_source_rows": len(daily),
        "compact_morning_rows": compact_am,
        "compact_afternoon_rows": compact_pm,
    }
