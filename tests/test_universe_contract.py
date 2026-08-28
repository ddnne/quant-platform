"""Focused behavior tests for observed universe-breadth evidence."""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
from typing import Any

from data_contracts.identity import natural_key
import research.universe_contract as universe_contract_module
from research.universe_contract import (
    UNIVERSE_BREADTH_EVIDENCE_FORMAT,
    resolve_tse_prime_with_fins,
    resolve_tse_prime_with_fins_evidence,
)


def _insert_record(
    connection: sqlite3.Connection,
    *,
    table: str = "jquants_records",
    dataset: str,
    payload: dict[str, Any],
    event_time: str,
    available_at: str,
) -> None:
    serialized = json.dumps(payload, sort_keys=True)
    connection.execute(
        f"INSERT INTO {table} VALUES "
        "('jquants',?,?,?,?,?,?,?)",
        (
            dataset,
            natural_key(payload, dataset),
            event_time,
            available_at,
            available_at,
            serialized,
            serialized,
        ),
    )


def _universe_db(path: Path, *, fins_codes: tuple[str, ...]) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE jquants_records ("
            "source TEXT NOT NULL,dataset TEXT NOT NULL,natural_key TEXT NOT NULL,"
            "event_time TEXT NOT NULL,available_at TEXT NOT NULL,"
            "ingested_at TEXT NOT NULL,payload TEXT NOT NULL,"
            "raw_payload TEXT NOT NULL,"
            "PRIMARY KEY(source,dataset,natural_key))"
        )
        _insert_record(
            connection,
            dataset="markets_calendar",
            payload={"Date": "2024-01-02", "HolidayDivision": "1"},
            event_time="2024-01-02T00:00:00+09:00",
            available_at="2024-01-01T12:00:00+09:00",
        )
        for code in ("1301", "1302"):
            _insert_record(
                connection,
                dataset="equities_master",
                payload={
                    "Code": code,
                    "Date": "2024-01-02",
                    "MarketCode": "0111",
                },
                event_time="2024-01-02T00:00:00+09:00",
                available_at="2024-01-02T09:00:00+09:00",
            )
        for index, code in enumerate(fins_codes, start=1):
            _insert_record(
                connection,
                dataset="fins_summary",
                payload={
                    "Code": code,
                    "DiscDate": "2024-01-01",
                    "DiscNo": str(index),
                },
                event_time="2024-01-01T14:00:00+09:00",
                available_at="2024-01-01T14:00:00+09:00",
            )
        connection.commit()


def _revisioned_universe_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE jquants_records (
                source TEXT NOT NULL,
                dataset TEXT NOT NULL,
                natural_key TEXT NOT NULL,
                event_time TEXT NOT NULL,
                available_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                PRIMARY KEY(source,dataset,natural_key)
            );
            CREATE TABLE jquants_records_revisions AS
                SELECT * FROM jquants_records WHERE 0;
            """
        )
        for day in ("2024-01-02", "2024-01-03"):
            calendar = {"Date": day, "HolidayDivision": "1"}
            _insert_record(
                connection,
                table="jquants_records_revisions",
                dataset="markets_calendar",
                payload=calendar,
                event_time=f"{day}T00:00:00+09:00",
                available_at="2024-01-01T12:00:00+09:00",
            )
            _insert_record(
                connection,
                dataset="markets_calendar",
                payload=calendar,
                event_time=f"{day}T00:00:00+09:00",
                available_at="2024-01-02T16:00:00+09:00",
            )

        for code in ("1301", "1302"):
            original_master = {
                "Code": code,
                "Date": "2024-01-02",
                "MarketCode": "0111",
            }
            _insert_record(
                connection,
                table="jquants_records_revisions",
                dataset="equities_master",
                payload=original_master,
                event_time="2024-01-02T00:00:00+09:00",
                available_at="2024-01-02T09:00:00+09:00",
            )
            corrected_master = {
                **original_master,
                "MarketCode": "0111" if code == "1301" else "0112",
            }
            _insert_record(
                connection,
                dataset="equities_master",
                payload=corrected_master,
                event_time="2024-01-02T00:00:00+09:00",
                available_at="2024-01-02T16:00:00+09:00",
            )

            fins = {
                "Code": code,
                "DiscDate": "2024-01-01",
                "DiscNo": code,
            }
            _insert_record(
                connection,
                table="jquants_records_revisions",
                dataset="fins_summary",
                payload=fins,
                event_time="2024-01-01T14:00:00+09:00",
                available_at="2024-01-01T14:00:00+09:00",
            )
            _insert_record(
                connection,
                dataset="fins_summary",
                payload={**fins, "Correction": "later-main-version"},
                event_time="2024-01-01T14:00:00+09:00",
                available_at="2024-01-02T16:00:00+09:00",
            )
        connection.commit()


def _scale_universe_db(path: Path, *, day_count: int) -> tuple[str, str]:
    start = date(2024, 1, 2)
    end = start + timedelta(days=day_count - 1)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE jquants_records ("
            "source TEXT NOT NULL,dataset TEXT NOT NULL,natural_key TEXT NOT NULL,"
            "event_time TEXT NOT NULL,available_at TEXT NOT NULL,"
            "ingested_at TEXT NOT NULL,payload TEXT NOT NULL,"
            "raw_payload TEXT NOT NULL,"
            "PRIMARY KEY(source,dataset,natural_key))"
        )
        for offset in range(day_count):
            day = (start + timedelta(days=offset)).isoformat()
            _insert_record(
                connection,
                dataset="markets_calendar",
                payload={"Date": day, "HolidayDivision": "1"},
                event_time=f"{day}T00:00:00+09:00",
                available_at="2023-12-01T12:00:00+09:00",
            )
        _insert_record(
            connection,
            dataset="equities_master",
            payload={
                "Code": "1301",
                "Date": start.isoformat(),
                "MarketCode": "0111",
            },
            event_time=f"{start.isoformat()}T00:00:00+09:00",
            available_at=f"{start.isoformat()}T09:00:00+09:00",
        )
        _insert_record(
            connection,
            dataset="fins_summary",
            payload={"Code": "1301", "DiscDate": "2024-01-01", "DiscNo": "1"},
            event_time="2024-01-01T14:00:00+09:00",
            available_at="2024-01-01T14:00:00+09:00",
        )
        connection.commit()
    return start.isoformat(), end.isoformat()


def test_observed_universe_breadth_reports_partial_fins_without_a_threshold(
    tmp_path: Path,
) -> None:
    partial_db = tmp_path / "partial.sqlite"
    complete_db = tmp_path / "complete.sqlite"
    _universe_db(partial_db, fins_codes=("1301",))
    _universe_db(complete_db, fins_codes=("1301", "1302"))

    partial_membership, partial = resolve_tse_prime_with_fins_evidence(
        partial_db,
        period_start="2024-01-02",
        period_end="2024-01-02",
    )
    complete_membership, complete = resolve_tse_prime_with_fins_evidence(
        complete_db,
        period_start="2024-01-02",
        period_end="2024-01-02",
    )

    assert partial == {
        "format": UNIVERSE_BREADTH_EVIDENCE_FORMAT,
        "evidence_kind": "OBSERVED",
        "rule_id": "tse_prime_with_fins",
        "rule_version": "tse-prime-with-fins/v1",
        "period_start": "2024-01-02",
        "period_end": "2024-01-02",
        "daily_observations": [
            {
                "decision_date": "2024-01-02",
                "prime_master_count": 2,
                "resolved_fins_intersection_count": 1,
                "resolved_fins_intersection_ratio": 0.5,
            }
        ],
        "total_prime_master_observations": 2,
        "total_resolved_fins_intersection_observations": 1,
        "overall_ratio": 0.5,
        "minimum_daily_ratio": 0.5,
        "worst_days": ["2024-01-02"],
        "source_complete_claim": False,
    }
    assert complete["overall_ratio"] == 1.0
    assert partial["overall_ratio"] < complete["overall_ratio"]
    assert partial_membership.codes_for("2024-01-02") == ("1301",)
    assert complete_membership.codes_for("2024-01-02") == ("1301", "1302")

    delegated = resolve_tse_prime_with_fins(
        partial_db,
        period_start="2024-01-02",
        period_end="2024-01-02",
    )
    assert delegated == partial_membership
    assert (
        delegated.resolved_membership_digest
        == partial_membership.resolved_membership_digest
    )


def test_revision_history_is_resolved_per_decision_as_of(tmp_path: Path) -> None:
    database = tmp_path / "revisioned.sqlite"
    _revisioned_universe_db(database)

    membership, evidence = resolve_tse_prime_with_fins_evidence(
        database,
        period_start="2024-01-02",
        period_end="2024-01-03",
    )

    assert membership.decision_memberships == (
        ("2024-01-02", ("1301", "1302")),
        ("2024-01-03", ("1301",)),
    )
    assert evidence["daily_observations"] == [
        {
            "decision_date": "2024-01-02",
            "prime_master_count": 2,
            "resolved_fins_intersection_count": 2,
            "resolved_fins_intersection_ratio": 1.0,
        },
        {
            "decision_date": "2024-01-03",
            "prime_master_count": 1,
            "resolved_fins_intersection_count": 1,
            "resolved_fins_intersection_ratio": 1.0,
        },
    ]
    assert resolve_tse_prime_with_fins(
        database,
        period_start="2024-01-02",
        period_end="2024-01-03",
    ) == membership


def test_resolution_iterates_each_history_only_once_for_many_decisions(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database = tmp_path / "scale.sqlite"
    start, end = _scale_universe_db(database, day_count=60)
    original_loader = universe_contract_module._load_governed_rows
    loaded = original_loader(
        database, ("markets_calendar", "equities_master", "fins_summary")
    )

    class IterationGuard:
        def __init__(self, values: tuple[dict[str, Any], ...]) -> None:
            self.values = values
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            if self.iterations > 1:
                raise AssertionError("governed history was rescanned")
            return iter(self.values)

    guarded = {key: IterationGuard(value) for key, value in loaded.items()}

    def guarded_loader(*_args: Any, **_kwargs: Any):
        return guarded

    monkeypatch.setattr(
        universe_contract_module, "_load_governed_rows", guarded_loader
    )
    membership = resolve_tse_prime_with_fins(
        database,
        period_start=start,
        period_end=end,
    )

    assert len(membership.decision_memberships) == 60
    assert {key: value.iterations for key, value in guarded.items()} == {
        "markets_calendar": 1,
        "equities_master": 1,
        "fins_summary": 1,
    }
