"""PIT behavior for closed personal DRAFT TOPIX selectors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.universe import ResolvedDailyUniverse
from data_contracts.identity import natural_key
from research.personal_universe import (
    PERSONAL_UNIVERSE_IDS,
    PersonalUniverseError,
    personal_universe_selector,
    resolve_personal_universe,
)
from storage.sqlite_store import SqliteStore


def _row(
    dataset: str,
    payload: dict,
    *,
    event_time: str,
    available_at: str,
) -> dict:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {
        "source": "jquants",
        "dataset": dataset,
        "natural_key": natural_key(payload, dataset),
        "event_time": event_time,
        "available_at": available_at,
        "ingested_at": available_at,
        "payload": encoded,
        "raw_payload": None,
    }


@pytest.fixture
def reform_snapshot(tmp_path: Path) -> Path:
    path = tmp_path / "topix-reform.sqlite"
    store = SqliteStore(path)
    rows: list[dict] = []
    for day, holiday in (
        ("2022-04-01", "1"),
        ("2022-04-02", "0"),
        ("2022-04-03", "0"),
        ("2022-04-04", "1"),
    ):
        rows.append(
            _row(
                "markets_calendar",
                {"Date": day, "HolidayDivision": holiday},
                event_time=f"{day}T00:00:00+09:00",
                available_at=f"{day}T00:00:00+09:00",
            )
        )

    for code, market, scale in (
        ("1001", "0101", "TOPIX Core30"),
        ("1002", "0101", "TOPIX Small 1"),
        ("9001", "0102", "-"),
    ):
        payload = {
            "Code": code,
            "Date": "2022-04-01",
            "MarketCode": market,
            "ScaleCategory": scale,
        }
        rows.append(
            _row(
                "equities_master",
                payload,
                event_time="2022-04-01T08:00:00+09:00",
                available_at="2022-04-01T08:00:00+09:00",
            )
        )

    for code, market, scale in (
        ("1001", "0111", "TOPIX Core30"),
        ("1002", "0112", "TOPIX Small 1"),
        ("1003", "0113", "TOPIX Small 2"),
        ("9001", "0112", "-"),
    ):
        payload = {
            "Code": code,
            "Date": "2022-04-04",
            "MarketCode": market,
            "ScaleCategory": scale,
        }
        rows.append(
            _row(
                "equities_master",
                payload,
                event_time="2022-04-04T08:00:00+09:00",
                available_at="2022-04-04T08:00:00+09:00",
            )
        )

    for ordinal, code in enumerate(("1001", "1002", "1003"), start=1):
        payload = {
            "Code": code,
            "DiscDate": "2022-03-31",
            "DiscNo": str(ordinal),
        }
        rows.append(
            _row(
                "fins_summary",
                payload,
                event_time="2022-03-31T15:00:00+09:00",
                available_at="2022-03-31T15:00:00+09:00",
            )
        )
    store.upsert("jquants_records", rows)
    store.close()
    return path


def test_default_topix_all_keeps_pre_and_post_reform_non_prime_members(
    reform_snapshot: Path,
) -> None:
    membership = resolve_personal_universe(
        reform_snapshot,
        period_start="2022-04-01",
        period_end="2022-04-04",
    )

    assert membership.rule_id == "topix_all_with_fins"
    assert membership.codes_for("2022-04-01") == ("1001", "1002")
    assert membership.codes_for("2022-04-04") == ("1001", "1002", "1003")
    assert ResolvedDailyUniverse(membership).codes_for("2022-04-04") == (
        "1001",
        "1002",
        "1003",
    )


@pytest.mark.parametrize(
    ("universe_id", "expected"),
    (
        ("topix_core30", ("1001",)),
        ("topix100", ("1001",)),
        ("topix500", ("1001",)),
        ("topix_small1", ("1002",)),
        ("topix_small", ("1002", "1003")),
    ),
)
def test_closed_scale_selectors(
    reform_snapshot: Path,
    universe_id: str,
    expected: tuple[str, ...],
) -> None:
    membership = resolve_personal_universe(
        reform_snapshot,
        period_start="2022-04-04",
        period_end="2022-04-04",
        universe_id=universe_id,
    )

    assert membership.codes_for("2022-04-04") == expected


def test_selector_surface_is_closed() -> None:
    assert PERSONAL_UNIVERSE_IDS == (
        "topix_all",
        "topix_core30",
        "topix_large70",
        "topix_mid400",
        "topix_small1",
        "topix_small2",
        "topix_small",
        "topix100",
        "topix500",
    )
    with pytest.raises(PersonalUniverseError, match="must be one of"):
        personal_universe_selector("all_listed")
