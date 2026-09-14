"""Personal catalog aggregates on one owned readonly connection.

Draft-policy / quick-check helpers stay in ``pit._draft_storage``. Holiday,
range, mix, and manifest policy stay in paper_runtime.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from data_contracts.personal_history_compact import (
    PERSONAL_HISTORY_COMPACT_BARS_TABLE,
    PERSONAL_HISTORY_COMPACT_MASTER_TABLE,
    CompactHistoryState,
    compact_history_state,
)
from pit._draft_storage import (
    _quick_check,
    _readonly_connection,
    _reject_unstable_policy,
    _table_columns,
    _verify_personal_draft_policy,
)


_GENERIC_REQUIRED = {"source", "dataset", "event_time", "payload"}
_TYPED_DAILY_BARS_COLUMNS = {
    "source",
    "code",
    "date",
    "event_time",
    "available_at",
}
_COMPACT_FAIL_STATES = frozenset({"invalid", "mixed"})


def _detached_row(row: Any) -> Mapping[str, Any]:
    return MappingProxyType(dict(row))


def _aggregate_observation(
    connection: sqlite3.Connection,
    *,
    dataset_id: str,
    table: str,
    date_column: str,
    where: str = "",
) -> Mapping[str, Any] | None:
    row = connection.execute(
        f"SELECT '{dataset_id}' AS dataset,COUNT(*) AS row_count,"
        f"MIN({date_column}) AS min_event_date,MAX({date_column}) AS max_event_date "
        f"FROM {table}{where}"
    ).fetchone()
    if row is None or int(row["row_count"] or 0) < 1:
        return None
    return _detached_row(row)


def _typed_daily_bars_observation(
    connection: sqlite3.Connection,
) -> Mapping[str, Any] | None:
    typed_columns = _table_columns(connection, "jquants_daily_bars")
    if not _TYPED_DAILY_BARS_COLUMNS <= typed_columns:
        return None
    return _aggregate_observation(
        connection,
        dataset_id="equities_bars_daily",
        table="jquants_daily_bars",
        date_column="date",
        where=" WHERE source='jquants'",
    )


@dataclass(frozen=True, slots=True)
class PersonalCatalogObservations:
    compact_state: CompactHistoryState
    generic_by_dataset: Mapping[str, Mapping[str, Any]]
    compact_master: Mapping[str, Any] | None
    compact_bars: Mapping[str, Any] | None
    typed_daily_bars: Mapping[str, Any] | None
    calendar_period_rows: tuple[Mapping[str, Any], ...]


def _read_personal_catalog_observations(
    connection: sqlite3.Connection,
    required_datasets: Sequence[str],
    *,
    period_start: str,
    period_end: str,
) -> PersonalCatalogObservations:
    generic_columns = _table_columns(connection, "jquants_records")
    generic: dict[str, Mapping[str, Any]] = {}
    if _GENERIC_REQUIRED <= generic_columns:
        placeholders = ",".join("?" for _ in required_datasets)
        rows = connection.execute(
            "SELECT dataset,COUNT(*) AS row_count,"
            "MIN(substr(event_time,1,10)) AS min_event_date,"
            "MAX(substr(event_time,1,10)) AS max_event_date "
            "FROM jquants_records WHERE source='jquants' "
            f"AND dataset IN ({placeholders}) GROUP BY dataset ORDER BY dataset",
            tuple(required_datasets),
        ).fetchall()
        generic = {
            str(row["dataset"]): _detached_row(row) for row in rows
        }

    compact_state = compact_history_state(connection)
    compact_master = None
    compact_bars = None
    typed_daily_bars = None
    calendar_period_rows: tuple[Mapping[str, Any], ...] = ()
    if compact_state not in _COMPACT_FAIL_STATES:
        if compact_state == "compact":
            if "equities_master" in required_datasets:
                compact_master = _aggregate_observation(
                    connection,
                    dataset_id="equities_master",
                    table=PERSONAL_HISTORY_COMPACT_MASTER_TABLE,
                    date_column="snapshot_date",
                )
            if "equities_bars_daily" in required_datasets:
                compact_bars = _aggregate_observation(
                    connection,
                    dataset_id="equities_bars_daily",
                    table=PERSONAL_HISTORY_COMPACT_BARS_TABLE,
                    date_column="date",
                )
        elif "equities_bars_daily" in required_datasets:
            typed_daily_bars = _typed_daily_bars_observation(connection)
        if (
            _GENERIC_REQUIRED <= generic_columns
            and "equities_bars_daily" in required_datasets
            and "markets_calendar" in required_datasets
        ):
            calendar_period_rows = tuple(
                _detached_row(row)
                for row in connection.execute(
                    "SELECT substr(event_time,1,10) AS event_date,payload "
                    "FROM jquants_records WHERE source='jquants' "
                    "AND dataset='markets_calendar' "
                    "AND substr(event_time,1,10) BETWEEN ? AND ? "
                    "ORDER BY event_time",
                    (period_start, period_end),
                )
            )
    return PersonalCatalogObservations(
        compact_state=compact_state,
        generic_by_dataset=MappingProxyType(generic),
        compact_master=compact_master,
        compact_bars=compact_bars,
        typed_daily_bars=typed_daily_bars,
        calendar_period_rows=calendar_period_rows,
    )


def observe_personal_draft_copy(
    database_path: str | Path,
    required_datasets: Sequence[str],
    *,
    period_start: str,
    period_end: str,
    personal_policy: Any,
    source_provenance: Any,
) -> PersonalCatalogObservations:
    connection = _readonly_connection(Path(database_path))
    try:
        observations = _read_personal_catalog_observations(
            connection,
            required_datasets,
            period_start=period_start,
            period_end=period_end,
        )
        if observations.compact_state not in _COMPACT_FAIL_STATES:
            _verify_personal_draft_policy(
                connection,
                personal_policy=personal_policy,
                source_provenance=source_provenance,
            )
        return observations
    finally:
        connection.close()


def observe_personal_published_snapshot(
    database_path: str | Path,
    required_datasets: Sequence[str],
    *,
    period_start: str,
    period_end: str,
    personal_policy: Any,
    source_provenance: Any,
) -> PersonalCatalogObservations:
    connection = _readonly_connection(Path(database_path))
    try:
        _verify_personal_draft_policy(
            connection,
            personal_policy=personal_policy,
            source_provenance=source_provenance,
        )
        observations = _read_personal_catalog_observations(
            connection,
            required_datasets,
            period_start=period_start,
            period_end=period_end,
        )
        if observations.compact_state not in _COMPACT_FAIL_STATES:
            _reject_unstable_policy(connection, where="personal snapshot")
            _quick_check(connection)
        return observations
    finally:
        connection.close()
