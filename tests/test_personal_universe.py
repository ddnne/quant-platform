"""PIT behavior for closed personal DRAFT TOPIX selectors."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from core.execution import close_as_of, morning_close_as_of
from core.universe import ResolvedDailyUniverse
from data_contracts.identity import natural_key
from personal_history_compact_support import (
    insert_compact_master,
    install_compact_schema,
    stamp_compact_manifest,
)
from pit.personal_research_view import OfflineFixtureDataView
from pit.universe_pit import resolve_universe_day_slices
from research.personal_universe import (
    PERSONAL_UNIVERSE_DECISION_CUTOFFS,
    PERSONAL_UNIVERSE_IDS,
    PersonalUniverseError,
    personal_research_universe_decision_cutoff,
    personal_research_universe_rule_digest,
    personal_universe_selector,
    resolve_personal_universe,
    resolve_personal_universe_with_evidence,
)
from research.universe_contract import resolve_tse_prime_with_fins
from storage.sqlite_store import SqliteStore


def _view(path: Path, *, cutoff: str = "morning_close") -> OfflineFixtureDataView:
    return OfflineFixtureDataView.bind(
        path, artifact_root=path.parent / "personal-art", decision_cutoff=cutoff
    )


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
        _view(reform_snapshot),
        period_start="2022-04-01",
        period_end="2022-04-04",
    )

    assert membership.rule_id == "topix_all_with_fins"
    assert membership.membership_proof.startswith("personal-draft-resolved-universe:")
    assert not membership.membership_proof.startswith(
        "controlled-resolved-universe:"
    )
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
        _view(reform_snapshot),
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
    assert PERSONAL_UNIVERSE_DECISION_CUTOFFS == ("session_close", "morning_close")
    default = personal_universe_selector("topix_all")
    am = personal_universe_selector("topix_all", decision_cutoff="morning_close")
    assert default.to_canonical_dict()["decision_clock"] == "tse_morning_close_jst"
    assert am.to_canonical_dict()["decision_clock"] == "tse_morning_close_jst"
    assert default.rule_digest == am.rule_digest
    session = personal_universe_selector("topix_all", decision_cutoff="session_close")
    assert session.to_canonical_dict()["decision_clock"] == "tse_session_close_jst"
    assert personal_research_universe_decision_cutoff(am_pm=True) == "morning_close"
    assert personal_research_universe_decision_cutoff(am_pm=False) == "session_close"
    assert personal_research_universe_rule_digest("topix_all", am_pm=True) == (
        am.rule_digest
    )
    assert personal_research_universe_rule_digest("topix_all", am_pm=False) == (
        session.rule_digest
    )
    with pytest.raises(PersonalUniverseError, match="decision_cutoff"):
        personal_universe_selector("topix_all", decision_cutoff="session_open")


def _write_generic_calendar_and_fins(
    path: Path,
    *,
    days: tuple[tuple[str, str], ...],
    fins_codes: tuple[str, ...],
    master_rows: list[dict] | None = None,
) -> None:
    rows: list[dict] = []
    for day, holiday in days:
        rows.append(
            _row(
                "markets_calendar",
                {"Date": day, "HolidayDivision": holiday},
                event_time=f"{day}T00:00:00+09:00",
                available_at=f"{day}T00:00:00+09:00",
            )
        )
    for ordinal, code in enumerate(fins_codes, start=1):
        rows.append(
            _row(
                "fins_summary",
                {
                    "Code": code,
                    "DiscDate": "2025-03-31",
                    "DiscNo": str(ordinal),
                },
                event_time="2025-03-31T15:00:00+09:00",
                available_at="2025-03-31T15:00:00+09:00",
            )
        )
    if master_rows:
        rows.extend(master_rows)
    store = SqliteStore(path)
    store.upsert("jquants_records", rows)
    store.close()
    connection = sqlite3.connect(path)
    stamp_compact_manifest(connection, format_name="unmanaged-catalog")
    connection.commit()
    connection.close()


def _install_compact_master(
    path: Path,
    members: tuple[tuple[str, str, str, str, str], ...],
) -> None:
    conn = sqlite3.connect(path)
    install_compact_schema(conn)
    for snapshot_date, code, available_at, scale, source_scale in members:
        insert_compact_master(
            conn,
            snapshot_date=snapshot_date,
            code=code,
            available_at=available_at,
            ingested_at=available_at,
            scale_category=scale,
            source_scale_category=source_scale,
        )
    conn.commit()
    conn.close()


def test_compact_v7_classification_change_updates_latest_snapshot(
    tmp_path: Path,
) -> None:
    path = tmp_path / "compact-class.sqlite"
    _write_generic_calendar_and_fins(
        path,
        days=(("2025-04-01", "1"), ("2025-04-02", "1")),
        fins_codes=("1001", "1002"),
    )
    _install_compact_master(
        path,
        (
            ("2025-04-01", "1001", "2025-04-01T08:00:00+09:00", "TOPIX Core30", "Core30"),
            ("2025-04-01", "1002", "2025-04-01T08:00:00+09:00", "TOPIX Small 1", "Small1"),
            ("2025-04-02", "1001", "2025-04-02T08:00:00+09:00", "TOPIX Small 1", "Small1"),
            ("2025-04-02", "1002", "2025-04-02T08:00:00+09:00", "TOPIX Small 1", "Small1"),
        ),
    )

    membership = resolve_personal_universe(
        _view(path),
        period_start="2025-04-01",
        period_end="2025-04-02",
        universe_id="topix_small",
    )
    core = resolve_personal_universe(
        _view(path),
        period_start="2025-04-01",
        period_end="2025-04-01",
        universe_id="topix_core30",
    )

    assert membership.codes_for("2025-04-01") == ("1002",)
    assert membership.codes_for("2025-04-02") == ("1001", "1002")
    assert core.codes_for("2025-04-01") == ("1001",)


def test_compact_v7_daily_pit_and_delisting(tmp_path: Path) -> None:
    path = tmp_path / "compact-pit.sqlite"
    _write_generic_calendar_and_fins(
        path,
        days=(("2025-04-01", "1"), ("2025-04-02", "1")),
        fins_codes=("1001", "1002", "1003"),
    )
    _install_compact_master(
        path,
        (
            ("2025-04-01", "1001", "2025-04-01T08:00:00+09:00", "TOPIX Core30", "Core30"),
            ("2025-04-01", "1002", "2025-04-01T08:00:00+09:00", "TOPIX Small 1", "Small1"),
            ("2025-04-02", "1001", "2025-04-02T08:00:00+09:00", "TOPIX Core30", "Core30"),
            (
                "2025-04-02",
                "1003",
                "2025-04-02T16:00:00+09:00",
                "TOPIX Core30",
                "Core30",
            ),
        ),
    )

    membership = resolve_personal_universe(
        _view(path),
        period_start="2025-04-01",
        period_end="2025-04-02",
    )

    assert membership.codes_for("2025-04-01") == ("1001", "1002")
    assert membership.codes_for("2025-04-02") == ("1001",)


def test_compact_v7_fail_closed_state_mapping(tmp_path: Path) -> None:
    invalid = tmp_path / "compact-invalid.sqlite"
    _write_generic_calendar_and_fins(
        invalid,
        days=(("2025-04-01", "1"),),
        fins_codes=("1001",),
    )
    conn = sqlite3.connect(invalid)
    stamp_compact_manifest(conn)
    conn.commit()
    conn.close()
    with pytest.raises(PersonalUniverseError, match="rebuild as personal-draft-history/v8"):
        resolve_personal_universe(
            _view(invalid),
            period_start="2025-04-01",
            period_end="2025-04-01",
        )

    mixed = tmp_path / "compact-mixed.sqlite"
    _write_generic_calendar_and_fins(
        mixed,
        days=(("2025-04-01", "1"),),
        fins_codes=("1001",),
        master_rows=[
            _row(
                "equities_master",
                {
                    "Code": "1001",
                    "Date": "2025-04-01",
                    "MarketCode": "0111",
                    "ScaleCategory": "TOPIX Core30",
                },
                event_time="2025-04-01T08:00:00+09:00",
                available_at="2025-04-01T08:00:00+09:00",
            )
        ],
    )
    _install_compact_master(
        mixed,
        (("2025-04-01", "1001", "2025-04-01T08:00:00+09:00", "TOPIX Core30", "Core30"),),
    )
    with pytest.raises(PersonalUniverseError, match="cannot mix compact master"):
        resolve_personal_universe(
            _view(mixed),
            period_start="2025-04-01",
            period_end="2025-04-01",
        )


def test_v6_manifest_without_compact_master_keeps_legacy_generic_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-v6.sqlite"
    _write_generic_calendar_and_fins(
        path,
        days=(("2025-04-01", "1"),),
        fins_codes=("1001",),
        master_rows=[
            _row(
                "equities_master",
                {
                    "Code": "1001",
                    "Date": "2025-04-01",
                    "MarketCode": "0111",
                    "ScaleCategory": "TOPIX Core30",
                },
                event_time="2025-04-01T08:00:00+09:00",
                available_at="2025-04-01T08:00:00+09:00",
            )
        ],
    )
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE IF EXISTS personal_history_manifest")
    conn.execute(
        "CREATE TABLE personal_history_manifest ("
        "singleton INTEGER PRIMARY KEY, format TEXT, observed_through TEXT)"
    )
    conn.execute(
        "INSERT INTO personal_history_manifest(singleton, format, observed_through) "
        "VALUES (1, ?, '2099-01-01T00:00:00+09:00')",
        ("personal-draft-history/v6",),
    )
    conn.commit()
    conn.close()

    membership = resolve_personal_universe(
        _view(path),
        period_start="2025-04-01",
        period_end="2025-04-01",
    )

    assert membership.codes_for("2025-04-01") == ("1001",)


def test_am_cutoff_excludes_afternoon_fins_until_next_trading_day(
    tmp_path: Path,
) -> None:
    path = tmp_path / "am-lookahead.sqlite"
    day = "2024-04-01"
    nxt = "2024-04-02"
    rows = [
        _row(
            "markets_calendar",
            {"Date": value, "HolidayDivision": "1"},
            event_time=f"{value}T00:00:00+09:00",
            available_at=f"{value}T00:00:00+09:00",
        )
        for value in (day, nxt)
    ]
    for code, scale in (("1001", "TOPIX Core30"), ("1002", "TOPIX Large70")):
        payload = {
            "Code": code,
            "Date": day,
            "MarketCode": "0111",
            "ScaleCategory": scale,
        }
        rows.append(
            _row(
                "equities_master",
                payload,
                event_time=f"{day}T08:00:00+09:00",
                available_at=f"{day}T08:00:00+09:00",
            )
        )
    rows.append(
        _row(
            "fins_summary",
            {"Code": "1001", "DiscDate": "2024-03-29", "DiscNo": "1"},
            event_time="2024-03-29T15:00:00+09:00",
            available_at="2024-03-29T15:00:00+09:00",
        )
    )
    rows.append(
        _row(
            "fins_summary",
            {"Code": "1002", "DiscDate": day, "DiscNo": "2"},
            event_time=f"{day}T14:00:00+09:00",
            available_at=f"{day}T14:00:00+09:00",
        )
    )
    store = SqliteStore(path)
    store.upsert("jquants_records", rows)
    store.close()
    connection = sqlite3.connect(path)
    stamp_compact_manifest(connection, format_name="unmanaged-catalog")
    connection.commit()
    connection.close()

    am, am_evidence = resolve_personal_universe_with_evidence(
        _view(path, cutoff="morning_close"),
        period_start=day,
        period_end=nxt,
        decision_cutoff="morning_close",
    )
    close_path = resolve_personal_universe(
        _view(path, cutoff="session_close"),
        period_start=day,
        period_end=nxt,
        decision_cutoff="session_close",
    )

    assert morning_close_as_of(day) == f"{day}T11:30:00+09:00"
    assert close_as_of(day) == f"{day}T15:00:00+09:00"
    assert am_evidence["decision_cutoff"] == "morning_close"
    assert am_evidence["selector"]["decision_clock"] == "tse_morning_close_jst"
    assert am.codes_for(day) == ("1001",)
    assert am.codes_for(nxt) == ("1001", "1002")
    assert close_path.codes_for(day) == ("1001", "1002")
    assert close_path.codes_for(nxt) == ("1001", "1002")
    assert close_path.rule_digest != am.rule_digest


def test_master_scale_correction_obeys_decision_cutoff(tmp_path: Path) -> None:
    path = tmp_path / "master-correction.sqlite"
    day = "2025-04-01"
    store = SqliteStore(path)
    rows = [
        _row(
            "markets_calendar",
            {"Date": day, "HolidayDivision": "1"},
            event_time=f"{day}T00:00:00+09:00",
            available_at=f"{day}T00:00:00+09:00",
        ),
        _row(
            "fins_summary",
            {"Code": "1001", "DiscDate": "2025-03-31", "DiscNo": "1"},
            event_time="2025-03-31T15:00:00+09:00",
            available_at="2025-03-31T15:00:00+09:00",
        ),
        _row(
            "equities_master",
            {
                "Code": "1001",
                "Date": day,
                "MarketCode": "0111",
                "ScaleCategory": "TOPIX Core30",
            },
            event_time=f"{day}T08:00:00+09:00",
            available_at=f"{day}T08:00:00+09:00",
        ),
    ]
    store.upsert("jquants_records", rows)
    store.upsert(
        "jquants_records",
        [
            _row(
                "equities_master",
                {
                    "Code": "1001",
                    "Date": day,
                    "MarketCode": "0111",
                    "ScaleCategory": "TOPIX Small 1",
                },
                event_time=f"{day}T08:00:00+09:00",
                available_at=f"{day}T14:00:00+09:00",
            )
        ],
    )
    store.close()

    morning = resolve_personal_universe(
        _view(path, cutoff="morning_close"),
        period_start=day,
        period_end=day,
        universe_id="topix_core30",
        decision_cutoff="morning_close",
    )
    close_small = resolve_personal_universe(
        _view(path, cutoff="session_close"),
        period_start=day,
        period_end=day,
        universe_id="topix_small",
        decision_cutoff="session_close",
    )

    assert morning.codes_for(day) == ("1001",)
    assert close_small.codes_for(day) == ("1001",)
    with pytest.raises(PersonalUniverseError, match="resolves no master members"):
        resolve_personal_universe(
            _view(path, cutoff="session_close"),
            period_start=day,
            period_end=day,
            universe_id="topix_core30",
            decision_cutoff="session_close",
        )
    with pytest.raises(PersonalUniverseError, match="resolves no master members"):
        resolve_personal_universe(
            _view(path, cutoff="morning_close"),
            period_start=day,
            period_end=day,
            universe_id="topix_small",
            decision_cutoff="morning_close",
        )


def test_future_effective_master_snapshot_is_not_visible_before_event(
    tmp_path: Path,
) -> None:
    """Apr-2 snapshot published early must not win Apr-1 decisions."""

    path = tmp_path / "future-effective-master.sqlite"
    day = "2025-04-01"
    nxt = "2025-04-02"
    rows = [
        _row(
            "markets_calendar",
            {"Date": value, "HolidayDivision": "1"},
            event_time=f"{value}T00:00:00+09:00",
            available_at=f"{value}T00:00:00+09:00",
        )
        for value in (day, nxt)
    ]
    rows.append(
        _row(
            "equities_master",
            {
                "Code": "1001",
                "Date": day,
                "MarketCode": "0111",
                "ScaleCategory": "TOPIX Core30",
            },
            event_time=f"{day}T08:00:00+09:00",
            available_at=f"{day}T08:00:00+09:00",
        )
    )
    rows.append(
        _row(
            "equities_master",
            {
                "Code": "1002",
                "Date": nxt,
                "MarketCode": "0111",
                "ScaleCategory": "TOPIX Core30",
            },
            event_time=f"{nxt}T08:00:00+09:00",
            available_at=f"{day}T14:00:00+09:00",
        )
    )
    for ordinal, code in enumerate(("1001", "1002"), start=1):
        rows.append(
            _row(
                "fins_summary",
                {"Code": code, "DiscDate": "2025-03-31", "DiscNo": str(ordinal)},
                event_time="2025-03-31T15:00:00+09:00",
                available_at="2025-03-31T15:00:00+09:00",
            )
        )
    store = SqliteStore(path)
    store.upsert("jquants_records", rows)
    store.close()
    connection = sqlite3.connect(path)
    stamp_compact_manifest(connection, format_name="unmanaged-catalog")
    connection.commit()
    connection.close()

    personal_close = resolve_personal_universe(
        _view(path, cutoff="session_close"),
        period_start=day,
        period_end=nxt,
        universe_id="topix_core30",
        decision_cutoff="session_close",
    )
    personal_am = resolve_personal_universe(
        _view(path, cutoff="morning_close"),
        period_start=day,
        period_end=nxt,
        universe_id="topix_core30",
        decision_cutoff="morning_close",
    )
    as_of_for_day = {day: close_as_of(day), nxt: close_as_of(nxt)}
    controlled = resolve_tse_prime_with_fins(
        resolve_universe_day_slices(
            path, period_start=day, period_end=nxt, as_of_for_day=as_of_for_day
        ),
        period_start=day,
        period_end=nxt,
    )

    assert close_as_of(day).endswith("T15:30:00+09:00")
    assert morning_close_as_of(day) == f"{day}T11:30:00+09:00"
    assert personal_close.codes_for(day) == ("1001",)
    assert personal_am.codes_for(day) == ("1001",)
    assert personal_close.codes_for(nxt) == ("1002",)
    assert personal_am.codes_for(nxt) == ("1002",)
    assert controlled.codes_for(day) == ("1001",)
    assert controlled.codes_for(nxt) == ("1002",)


def test_pre_window_master_and_fins_history_are_not_materialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pit.universe_pit as universe_pit

    path = tmp_path / "pre-window-history.sqlite"
    day = "2025-04-01"
    rows = [
        _row(
            "markets_calendar",
            {"Date": day, "HolidayDivision": "1"},
            event_time=f"{day}T00:00:00+09:00",
            available_at=f"{day}T00:00:00+09:00",
        ),
        _row(
            "equities_master",
            {
                "Code": "1001",
                "Date": day,
                "MarketCode": "0111",
                "ScaleCategory": "TOPIX Core30",
            },
            event_time=f"{day}T08:00:00+09:00",
            available_at=f"{day}T08:00:00+09:00",
        ),
        _row(
            "fins_summary",
            {"Code": "1001", "DiscDate": "2025-03-31", "DiscNo": "1"},
            event_time="2025-03-31T15:00:00+09:00",
            available_at="2025-03-31T15:00:00+09:00",
        ),
    ]
    for offset in range(180):
        old = date(2010, 1, 1) + timedelta(days=offset)
        stamp = f"{old.isoformat()}T08:00:00+09:00"
        rows.append(
            _row(
                "equities_master",
                {
                    "Code": "9999",
                    "Date": old.isoformat(),
                    "MarketCode": "0111",
                    "ScaleCategory": "TOPIX Core30",
                },
                event_time=stamp,
                available_at=stamp,
            )
        )
        rows.append(
            _row(
                "fins_summary",
                {
                    "Code": "8888",
                    "DiscDate": old.isoformat(),
                    "DiscNo": "1",
                },
                event_time=f"{old.isoformat()}T15:00:00+09:00",
                available_at=f"{old.isoformat()}T15:00:00+09:00",
            )
        )
    store = SqliteStore(path)
    store.upsert("jquants_records", rows)
    store.close()
    connection = sqlite3.connect(path)
    stamp_compact_manifest(connection, format_name="unmanaged-catalog")
    connection.commit()
    connection.close()

    captured: dict[str, object] = {}
    real_master = universe_pit._iter_master_events

    def spy_master(*args, **kwargs):
        codes: set[str] = set()
        count = 0
        for event in real_master(*args, **kwargs):
            count += 1
            codes.add(event.code)
            yield event
        captured["master_codes"] = codes
        captured["master_count"] = count

    monkeypatch.setattr(universe_pit, "_iter_master_events", spy_master)
    membership = resolve_personal_universe(
        _view(path),
        period_start=day,
        period_end=day,
        universe_id="topix_core30",
    )

    assert membership.codes_for(day) == ("1001",)
    assert captured["master_codes"] == {"1001"}
    assert captured["master_count"] == 1
