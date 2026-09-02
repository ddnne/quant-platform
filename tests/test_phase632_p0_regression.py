"""P0 regression probes: two-clock leak, coverage parity, READY, ephemeral, digest."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import tracemalloc
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.execution import close_as_of
from data_contracts.membership_runs import MembershipRun, stream_membership_digest
from personal_history_compact_support import (
    create_compact_tables,
    insert_compact_bar,
    install_compact_schema,
    stamp_compact_manifest,
)
from pit import PitError, SnapshotNotReady, get_equity_bars_daily
from pit.cooperative_deadline import CooperativeDeadline, DeadlineExceeded, install_deadline
from pit.history_reads import iter_unmanaged_draft_catalog_pages
from pit.personal_research_view import (
    OfflineFixtureDataView,
    PersonalResearchViewError,
    require_ephemeral_path,
)
from pit.query import connect_readonly
from pit.universe_pit import resolve_universe_day_slices
from research.cf_mass_eval_thicken import attach_nky_proxy, _build_thicken_sidecars
from research.universe_contract import resolve_tse_prime_with_fins


def _slices(path: Path, start: str, end: str):
    cursor = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    as_of_for_day = {}
    while cursor <= stop:
        day = cursor.isoformat()
        as_of_for_day[day] = close_as_of(day)
        cursor += timedelta(days=1)
    return resolve_universe_day_slices(
        path,
        period_start=start,
        period_end=end,
        as_of_for_day=as_of_for_day,
    )


def test_catalog_pagination_ranks_all_vintages_before_keyset(tmp_path: Path) -> None:
    path = tmp_path / "rank-before-keyset.sqlite"
    connection = sqlite3.connect(path)
    for table in ("jquants_records", "jquants_records_revisions"):
        connection.execute(
            f"CREATE TABLE {table} ("
            "source TEXT, dataset TEXT, natural_key TEXT, event_time TEXT, "
            "available_at TEXT, ingested_at TEXT, payload TEXT, raw_payload TEXT)"
        )
    payload = json.dumps(
        {"Code": "1301", "Date": "2024-01-01", "C": 100.0},
        sort_keys=True,
        separators=(",", ":"),
    )
    # The newer vintage corrects event_time backwards. Ranking must happen
    # before page-2 keyset filtering or the displaced row reappears there.
    connection.execute(
        "INSERT INTO jquants_records VALUES (?,?,?,?,?,?,?,?)",
        (
            "jquants",
            "equities_bars_daily",
            "same-key",
            "2024-01-01T10:00:00+09:00",
            "2024-01-03T10:00:00+09:00",
            "2024-01-03T10:00:00+09:00",
            payload,
            payload,
        ),
    )
    connection.execute(
        "INSERT INTO jquants_records_revisions VALUES (?,?,?,?,?,?,?,?)",
        (
            "jquants",
            "equities_bars_daily",
            "same-key",
            "2024-01-02T10:00:00+09:00",
            "2024-01-02T10:00:00+09:00",
            "2024-01-02T10:00:00+09:00",
            payload,
            payload,
        ),
    )
    stamp_compact_manifest(
        connection,
        format_name="unmanaged-catalog",
        observed_through="2024-01-04T23:00:00+09:00",
    )
    connection.commit()
    connection.close()

    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "rank-art", decision_cutoff="session_close"
    )
    pages = list(
        view.iter_decision_pages(
            decision_date="2024-01-04",
            dataset="equities_bars_daily",
            codes=("1301",),
            start="2024-01-01",
            end="2024-01-04",
            page_size=1,
        )
    )
    rows = [row for page in pages for row in page]
    assert [(row["natural_key"], row["event_time"]) for row in rows] == [
        ("same-key", "2024-01-01T10:00:00+09:00")
    ]

    version_pages = list(
        iter_unmanaged_draft_catalog_pages(
            path,
            as_of="2024-01-04T15:00:00+09:00",
            dataset="equities_bars_daily",
            codes=("1301",),
            include_available_at=True,
            versions=True,
            page_size=1,
        )
    )
    versions = [row for page in version_pages for row in page]
    assert [row["event_time"] for row in versions] == [
        "2024-01-01T10:00:00+09:00",
        "2024-01-02T10:00:00+09:00",
    ]


def test_version_pagination_disambiguates_current_revision_clock_collision(
    tmp_path: Path,
) -> None:
    from pit.history_reads import (
        fetch_unmanaged_draft_catalog_rows,
        fetch_unmanaged_draft_revision_rows,
        iter_unmanaged_draft_revision_pages,
    )

    path = tmp_path / "version-origin-cursor.sqlite"
    connection = sqlite3.connect(path)
    for table in ("jquants_records", "jquants_records_revisions"):
        connection.execute(
            f"CREATE TABLE {table} ("
            "source TEXT, dataset TEXT, natural_key TEXT, event_time TEXT, "
            "available_at TEXT, ingested_at TEXT, payload TEXT, raw_payload TEXT)"
        )
    event_time = "2024-01-01T10:00:00+09:00"
    collision_time = "2024-01-03T10:00:00+09:00"

    def _insert(table: str, *, version: int, available_at: str) -> None:
        payload = json.dumps(
            {"Code": "1301", "Date": "2024-01-01", "version": version},
            sort_keys=True,
            separators=(",", ":"),
        )
        connection.execute(
            f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?)",
            (
                "jquants",
                "fins_summary",
                "same-key",
                event_time,
                available_at,
                available_at,
                payload,
                payload,
            ),
        )

    _insert(
        "jquants_records_revisions",
        version=0,
        available_at="2024-01-02T10:00:00+09:00",
    )
    _insert(
        "jquants_records_revisions", version=1, available_at=collision_time
    )
    _insert("jquants_records", version=2, available_at=collision_time)
    stamp_compact_manifest(
        connection,
        format_name="unmanaged-catalog",
        observed_through="2024-01-04T23:00:00+09:00",
    )
    connection.commit()
    connection.close()

    version_pages = list(
        iter_unmanaged_draft_catalog_pages(
            path,
            as_of="2024-01-04T15:00:00+09:00",
            dataset="fins_summary",
            include_available_at=True,
            versions=True,
            page_size=1,
        )
    )
    revision_pages = list(
        iter_unmanaged_draft_revision_pages(
            path,
            as_of="2024-01-04T15:00:00+09:00",
            dataset="fins_summary",
            page_size=1,
        )
    )
    ranked_pages = list(
        iter_unmanaged_draft_catalog_pages(
            path,
            as_of="2024-01-04T15:00:00+09:00",
            dataset="fins_summary",
            include_available_at=True,
            versions=False,
            page_size=1,
        )
    )

    def _versions(pages: list[tuple[dict[str, object], ...]]) -> list[int]:
        rows = [row for page in pages for row in page]
        assert all("_pit_current" not in row for row in rows)
        return [int(json.loads(str(row["payload"]))["version"]) for row in rows]

    # page_size=1 forces two resume operations. The displaced revision and the
    # current row share the former four-field cursor tuple but remain lossless.
    assert _versions(version_pages) == [0, 1, 2]
    assert _versions(revision_pages) == [0, 1, 2]
    # Product PIT semantics remain one latest visible vintage per natural key.
    assert _versions(ranked_pages) == [2]
    direct = fetch_unmanaged_draft_catalog_rows(
        path,
        as_of="2024-01-04T15:00:00+09:00",
        dataset="fins_summary",
        versions=True,
    )
    assert len(direct) == 3
    assert all("_pit_current" not in row for row in direct)
    # Cursor values are private closed types, not caller-fabricated tuples.
    with pytest.raises(PitError, match="catalog cursor is invalid"):
        fetch_unmanaged_draft_catalog_rows(
            path,
            as_of="2024-01-04T15:00:00+09:00",
            dataset="fins_summary",
            versions=True,
            _after_cursor=(
                event_time,
                collision_time,
                collision_time,
                "same-key",
                0,
            ),
        )
    with pytest.raises(PitError, match="revision cursor is invalid"):
        fetch_unmanaged_draft_revision_rows(
            path,
            as_of="2024-01-04T15:00:00+09:00",
            dataset="fins_summary",
            _after_cursor=(
                collision_time,
                collision_time,
                "same-key",
                event_time,
                0,
            ),
        )


def test_unmanifested_future_ingested_row_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "leak.sqlite"
    connection = sqlite3.connect(path)
    create_compact_tables(connection)
    insert_compact_bar(
        connection,
        code="1301",
        day="2025-01-02",
        close=10.0,
        available_at="2025-01-02T15:30:00+09:00",
        ingested_at="2099-01-01T00:00:00+09:00",
        event_time="2025-01-02T15:30:00+09:00",
    )
    connection.commit()
    connection.close()
    with pytest.raises(PitError):
        get_equity_bars_daily(
            as_of="2025-01-02T15:30:00+09:00",
            code="1301",
            from_event="2025-01-02",
            to_event="2025-01-02",
            db_path=path,
        )

    connection = sqlite3.connect(path)
    stamp_compact_manifest(
        connection, observed_through="2025-01-02T16:00:00+09:00"
    )
    connection.commit()
    connection.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "b", decision_cutoff="session_close"
    )
    pages = list(
        view.iter_decision_pages(
            decision_date="2025-01-02",
            dataset="equities_bars_daily",
            codes=["1301"],
            start="2025-01-02",
            end="2025-01-02",
        )
    )
    assert pages == [] or pages == [()]


def test_coverage_and_pages_share_wall_for_future_ingested_row(tmp_path: Path) -> None:
    path = tmp_path / "cover.sqlite"
    connection = sqlite3.connect(path)
    install_compact_schema(connection)
    insert_compact_bar(
        connection,
        code="1301",
        day="2025-01-02",
        close=10.0,
        available_at="2025-01-02T15:30:00+09:00",
        ingested_at="2099-01-01T00:00:00+09:00",
        event_time="2025-01-02T15:30:00+09:00",
    )
    stamp_compact_manifest(
        connection, observed_through="2025-01-02T16:00:00+09:00"
    )
    connection.commit()
    connection.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "c", decision_cutoff="session_close"
    )
    pages = list(
        view.iter_decision_pages(
            decision_date="2025-01-02",
            dataset="equities_bars_daily",
            codes=["1301"],
            start="2025-01-02",
            end="2025-01-02",
        )
    )
    visible = [row for page in pages for row in page]
    assert visible == []
    universe = SimpleNamespace(
        period_start="2025-01-02",
        period_end="2025-01-02",
        decision_memberships=(("2025-01-02", ("1301",)),),
    )
    coverage = view.observed_bar_coverage(universe, minimum_ratio=1.0)
    assert coverage["status"] in {"FAIL", "UNKNOWN"}
    assert int(coverage.get("observed_rows") or 0) == 0
    assert coverage.get("status") != "PASS"


def test_arbitrary_caller_cannot_open_preready_scope(tmp_path: Path) -> None:
    import pit._ready_verifier_reads as ready_reads

    path = tmp_path / "preready.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE local_snapshot_policy ("
        "singleton INTEGER PRIMARY KEY, require_manifest INTEGER, "
        "snapshot_ready INTEGER, publication_state TEXT)"
    )
    connection.execute(
        "INSERT INTO local_snapshot_policy VALUES (1, 1, 0, 'BUILDING')"
    )
    connection.commit()
    connection.close()
    assert not hasattr(ready_reads, "publication_verifier_scope")
    assert not hasattr(ready_reads, "_VERIFIER_OWNER")
    assert not hasattr(ready_reads, "_VerifierSession")
    assert not hasattr(ready_reads, "_open_readonly_sqlite")
    assert not hasattr(ready_reads, "load_ready_receipt_scope")
    assert not hasattr(ready_reads, "iter_ready_catalog_fact_pages")
    assert not hasattr(ready_reads, "iter_ready_catalog_product_rows")
    assert not hasattr(ready_reads, "lookup_ready_catalog_rows")
    assert not hasattr(ready_reads, "_connect_ready_source")
    with pytest.raises(SnapshotNotReady):
        connect_readonly(path)


def _managed_building_secret_db(tmp_path: Path) -> Path:
    path = tmp_path / "managed-building-secret.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE local_snapshot_policy ("
        "singleton INTEGER PRIMARY KEY, require_manifest INTEGER, "
        "snapshot_ready INTEGER, publication_state TEXT)"
    )
    connection.execute(
        "INSERT INTO local_snapshot_policy VALUES (1, 1, 0, 'BUILDING')"
    )
    connection.execute(
        "CREATE TABLE jquants_records ("
        "source TEXT, dataset TEXT, natural_key TEXT, event_time TEXT, "
        "available_at TEXT, ingested_at TEXT, payload TEXT, raw_payload TEXT)"
    )
    connection.execute(
        "INSERT INTO jquants_records VALUES ("
        "'jquants','equities_bars_daily','secret-key',"
        "'2025-01-02T15:30:00+09:00','2025-01-02T15:30:00+09:00',"
        "'2025-01-02T16:00:00+09:00',"
        "'{\"Code\":\"1301\",\"Date\":\"2025-01-02\",\"C\":1}',"
        "'{}')"
    )
    stamp_compact_manifest(
        connection,
        format_name="unmanaged-catalog",
        observed_through="2025-01-02T16:00:00+09:00",
    )
    connection.commit()
    connection.close()
    return path


def _assert_no_secret_rows(rows: object) -> None:
    blob = json.dumps(rows, default=str)
    assert "secret-key" not in blob
    if isinstance(rows, (list, tuple)):
        assert list(rows) == []


def test_forged_clock_cannot_fetch_managed_building_secret_rows(
    tmp_path: Path,
) -> None:
    from pit.history_reads import fetch_unmanaged_draft_catalog_rows
    from pit.read_clock import (
        PitReadClock,
        SNAPSHOT_OBSERVATION_LABEL,
        install_read_clock,
    )

    path = _managed_building_secret_db(tmp_path)
    clock = PitReadClock(
        decision_at="2025-01-02T15:30:00+09:00",
        observed_through="2025-01-02T16:00:00+09:00",
        observation_label=SNAPSHOT_OBSERVATION_LABEL,
        promotable=True,
    )
    with install_read_clock(clock):
        with pytest.raises(SnapshotNotReady):
            rows = fetch_unmanaged_draft_catalog_rows(
                path,
                as_of="2025-01-02T15:30:00+09:00",
                dataset="equities_bars_daily",
            )
            _assert_no_secret_rows(rows)


def test_raw_opener_cannot_return_managed_building_connection_or_secret(
    tmp_path: Path,
) -> None:
    import pit.query as query

    path = _managed_building_secret_db(tmp_path)
    leaked = None
    try:
        with pytest.raises(SnapshotNotReady):
            leaked = query._open_readonly_sqlite(path)
            rows = leaked.execute(
                "SELECT natural_key FROM jquants_records"
            ).fetchall()
            keys = [str(row[0]) for row in rows]
            assert "secret-key" not in keys
            pytest.fail("raw opener returned a managed BUILDING connection")
    finally:
        if leaked is not None:
            leaked.close()


@pytest.mark.parametrize("state", ("BUILDING", "VALIDATING"))
def test_offline_draft_bind_rejects_unstable_managed_source(
    tmp_path: Path, state: str
) -> None:
    from paper_runtime.personal_snapshot import PersonalSnapshotError

    path = tmp_path / f"managed-{state.lower()}.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE local_snapshot_policy ("
        "singleton INTEGER PRIMARY KEY,require_manifest INTEGER NOT NULL,"
        "snapshot_ready INTEGER NOT NULL,publication_state TEXT,last_error TEXT)"
    )
    connection.execute(
        "INSERT INTO local_snapshot_policy VALUES (1,1,0,?,NULL)", (state,)
    )
    connection.commit()
    connection.close()
    with pytest.raises(PersonalSnapshotError, match="retry after sync finishes"):
        OfflineFixtureDataView.bind(path, artifact_root=tmp_path / "art")


def test_container_bind_copies_stable_managed_source_to_personal_draft(
    tmp_path: Path,
) -> None:
    from cf_platform.container_data_view import ContainerEphemeralDataView
    from pit._draft_storage import draft_sqlite_path

    source = tmp_path / "managed-synced.sqlite"
    connection = sqlite3.connect(source)
    connection.execute(
        "CREATE TABLE local_snapshot_policy ("
        "singleton INTEGER PRIMARY KEY,require_manifest INTEGER NOT NULL,"
        "snapshot_ready INTEGER NOT NULL,publication_state TEXT,last_error TEXT)"
    )
    connection.execute(
        "INSERT INTO local_snapshot_policy VALUES (1,1,0,'SYNCED',NULL)"
    )
    connection.commit()
    connection.close()
    view = ContainerEphemeralDataView.bind(
        source,
        artifact_root=tmp_path / "container-artifacts",
    )
    bound = draft_sqlite_path(view)
    assert bound != source.resolve()
    assert view.research_state == "UNMANAGED_DRAFT"
    assert view.controlled_eligible is False
    copied = sqlite3.connect(f"file:{bound}?mode=ro", uri=True)
    copied_policy = copied.execute(
        "SELECT require_manifest,snapshot_ready,publication_state "
        "FROM local_snapshot_policy WHERE singleton=1"
    ).fetchone()
    marker = copied.execute(
        "SELECT target_publication_state FROM personal_snapshot_provenance"
    ).fetchone()
    copied.close()
    assert copied_policy == (0, 0, "SYNCED")
    assert marker == ("PERSONAL_DRAFT",)
    original = sqlite3.connect(source)
    original_policy = original.execute(
        "SELECT require_manifest,snapshot_ready,publication_state "
        "FROM local_snapshot_policy WHERE singleton=1"
    ).fetchone()
    original.close()
    assert original_policy == (1, 0, "SYNCED")


def test_caller_opener_scope_cannot_return_managed_building_connection(
    tmp_path: Path,
) -> None:
    from urllib.parse import quote

    import pit.query as query

    path = _managed_building_secret_db(tmp_path)

    def forged_opener() -> sqlite3.Connection:
        uri = "file:" + quote(str(path.resolve())) + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    try:
        with query._install_readonly_scope(path, forged_opener):
            scoped = query._scoped_read_connection(path)
            if scoped is not None:
                rows = scoped.execute(
                    "SELECT natural_key FROM jquants_records"
                ).fetchall()
                keys = [str(row[0]) for row in rows]
                assert "secret-key" not in keys
                pytest.fail("caller-opener scope returned a BUILDING connection")
    except TypeError:
        pass
    except SnapshotNotReady:
        pass

    with pytest.raises(SnapshotNotReady):
        with query._install_readonly_scope(path):
            scoped = query._scoped_read_connection(path)
            if scoped is not None:
                rows = scoped.execute(
                    "SELECT natural_key FROM jquants_records"
                ).fetchall()
                keys = [str(row[0]) for row in rows]
                assert "secret-key" not in keys
                pytest.fail("readonly scope returned a BUILDING connection")
    assert query._scoped_read_connection(path) is None


def test_thread_registry_injection_cannot_access_managed_building_secret(
    tmp_path: Path,
) -> None:
    from urllib.parse import quote

    import pit.query as query
    from pit import get_jquants_records

    path = _managed_building_secret_db(tmp_path)
    key = str(path.resolve())
    uri = "file:" + quote(key) + "?mode=ro"
    injected = sqlite3.connect(uri, uri=True)
    injected.row_factory = sqlite3.Row
    try:
        if hasattr(query, "_thread_read_scopes"):
            registry = query._thread_read_scopes()
            if isinstance(registry, dict):
                registry[key] = (injected, 1)

        state = getattr(query, "_READ_SCOPE_STATE", None)
        if state is not None:
            for attr in ("connections", "scopes", "registry"):
                setattr(state, attr, {key: (injected, 1)})

        box_cls = getattr(query, "_ReadScopeBox", None)
        if isinstance(box_cls, type) and state is not None:
            box = box_cls()
            leases = getattr(box, "_leases", None)
            if isinstance(leases, dict):
                leases[key] = (injected, 1)
            setattr(state, "_box", box)

        try:
            scoped = query._scoped_read_connection(path)
        except SnapshotNotReady:
            scoped = None
        if scoped is not None:
            rows = scoped.execute(
                "SELECT natural_key FROM jquants_records"
            ).fetchall()
            keys = [str(row[0]) for row in rows]
            assert "secret-key" not in keys
            pytest.fail("thread-registry injection returned a BUILDING connection")

        with pytest.raises(SnapshotNotReady):
            rows = get_jquants_records(
                as_of="2025-01-02T15:30:00+09:00",
                dataset="equities_bars_daily",
                db_path=path,
            )
            _assert_no_secret_rows(rows)
    finally:
        injected.close()
        state = getattr(query, "_READ_SCOPE_STATE", None)
        if state is not None:
            for attr in ("_box", "connections", "scopes", "registry"):
                if hasattr(state, attr):
                    delattr(state, attr)
    assert query._scoped_read_connection(path) is None
    assert not hasattr(query, "_thread_read_scopes")


def test_ready_verifier_and_public_universe_do_not_share_thread_registry(
    tmp_path: Path,
) -> None:
    from data_contracts.identity import natural_key
    from paper_runtime.ready_publication import ReadyPublicationService
    from selection.budget_ledger import MassResearchDisabledError

    import pit.query as query

    def _write_universe(path: Path, *, publication_state: str | None) -> None:
        connection = sqlite3.connect(path)
        stamp_compact_manifest(
            connection,
            format_name="unmanaged-catalog",
            observed_through="2024-01-02T16:00:00+09:00",
        )
        connection.execute(
            "CREATE TABLE jquants_records ("
            "source TEXT NOT NULL, dataset TEXT NOT NULL, natural_key TEXT NOT NULL,"
            "event_time TEXT NOT NULL, available_at TEXT NOT NULL,"
            "ingested_at TEXT NOT NULL, payload TEXT NOT NULL,"
            "raw_payload TEXT NOT NULL,"
            "PRIMARY KEY(source, dataset, natural_key))"
        )
        rows = (
            (
                "markets_calendar",
                {"Date": "2024-01-02", "HolidayDivision": "1"},
                "2024-01-02T00:00:00+09:00",
                "2024-01-01T12:00:00+09:00",
            ),
            (
                "equities_master",
                {
                    "Code": "1301",
                    "Date": "2024-01-02",
                    "MarketCode": "0111",
                },
                "2024-01-02T00:00:00+09:00",
                "2024-01-02T09:00:00+09:00",
            ),
            (
                "fins_summary",
                {"Code": "1301", "DiscDate": "2024-01-01", "DiscNo": "1"},
                "2024-01-01T14:00:00+09:00",
                "2024-01-01T14:00:00+09:00",
            ),
        )
        for dataset, payload, event_time, available_at in rows:
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            connection.execute(
                "INSERT INTO jquants_records VALUES (?,?,?,?,?,?,?,?)",
                (
                    "jquants",
                    dataset,
                    natural_key(payload, dataset),
                    event_time,
                    available_at,
                    available_at,
                    encoded,
                    encoded,
                ),
            )
        if publication_state is not None:
            connection.execute(
                "CREATE TABLE local_snapshot_policy ("
                "singleton INTEGER PRIMARY KEY, require_manifest INTEGER, "
                "snapshot_ready INTEGER, publication_state TEXT)"
            )
            snapshot_ready = 1 if publication_state == "READY" else 0
            connection.execute(
                "INSERT INTO local_snapshot_policy VALUES (1, 1, ?, ?)",
                (snapshot_ready, publication_state),
            )
        connection.commit()
        connection.close()

    unmanaged = tmp_path / "unmanaged-universe.sqlite"
    _write_universe(unmanaged, publication_state=None)
    unmanaged_slices = _slices(unmanaged, "2024-01-02", "2024-01-02")
    assert unmanaged_slices[0].members[0].code == "1301"

    ready = tmp_path / "ready-universe.sqlite"
    _write_universe(ready, publication_state="READY")
    ready_slices = _slices(ready, "2024-01-02", "2024-01-02")
    assert [member.code for member in ready_slices[0].members] == ["1301"]
    with query._readonly_connection_scope(ready):
        scoped = query._scoped_read_connection(ready)
        assert scoped is not None
        assert scoped.execute("SELECT COUNT(*) FROM jquants_records").fetchone()[0] == 3

    building = tmp_path / "building-universe.sqlite"
    _write_universe(building, publication_state="BUILDING")
    with pytest.raises(SnapshotNotReady):
        _slices(building, "2024-01-02", "2024-01-02")

    binding = SimpleNamespace(
        profiles=(
            SimpleNamespace(
                period_start="2024-01-02",
                period_end="2024-01-02",
                dataset_scopes=({"required_lookback_trading_days": 1},) * 5,
            ),
        ),
        required_datasets=(
            "equities_bars_daily",
            "equities_master",
            "fins_summary",
            "indices_bars_daily_topix",
            "markets_calendar",
        ),
        profile_digest="sha256:" + "aa" * 32,
        plan_set_digest="sha256:" + "bb" * 32,
        closure_set_digest="sha256:" + "cc" * 32,
    )
    with pytest.raises(TypeError, match="filesystem path"):
        ReadyPublicationService().request_verified_publication(building, binding)
    assert query._scoped_read_connection(building) is None
    assert not hasattr(query, "_thread_read_scopes")


def test_forged_promotable_clock_has_no_callable_preready_raw_reader(
    tmp_path: Path,
) -> None:
    import importlib
    import inspect

    import paper_runtime.ready_publication as publication
    import pit
    import pit.api as pit_api
    import pit.query as query
    import pit.read_clock as clocks
    import research.ready_manifest as ready_manifest
    from pit.read_clock import PitReadClock, SNAPSHOT_OBSERVATION_LABEL
    from selection.budget_ledger import MassResearchDisabledError

    path = tmp_path / "preready.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE local_snapshot_policy ("
        "singleton INTEGER PRIMARY KEY, require_manifest INTEGER, "
        "snapshot_ready INTEGER, publication_state TEXT)"
    )
    connection.execute(
        "INSERT INTO local_snapshot_policy VALUES (1, 1, 0, 'BUILDING')"
    )
    connection.commit()
    connection.close()

    modules = [
        pit,
        pit_api,
        query,
        clocks,
        publication,
        ready_manifest,
        importlib.import_module("pit._ready_verifier_reads"),
    ]
    imported: dict[str, object] = {}
    for module in modules:
        for name in getattr(module, "__all__", ()):
            imported[f"{module.__name__}.{name}"] = getattr(module, name)
        for name, value in vars(module).items():
            imported[f"{module.__name__}.{name}"] = value

    clock = PitReadClock(
        decision_at="2025-01-02T15:30:00+09:00",
        observed_through="2025-01-02T16:00:00+09:00",
        observation_label=SNAPSHOT_OBSERVATION_LABEL,
        promotable=True,
    )
    raw_names = {
        "iter_ready_catalog_fact_pages",
        "iter_ready_catalog_product_rows",
        "load_ready_receipt_scope",
        "lookup_ready_catalog_rows",
        "_connect_ready_source",
        "publication_verifier_scope",
        "_VERIFIER_OWNER",
        "_VerifierSession",
    }
    for module in modules:
        for name in raw_names:
            assert not hasattr(module, name), f"{module.__name__}.{name}"
        if module.__name__ == "pit._ready_verifier_reads":
            assert not hasattr(module, "_open_readonly_sqlite")
            owned = [
                value
                for value in vars(module).values()
                if callable(value)
                and getattr(value, "__module__", "") == module.__name__
            ]
            assert owned == []

    for key, value in imported.items():
        short = key.rsplit(".", 1)[-1]
        assert short not in raw_names
        if not callable(value):
            continue
        try:
            signature = inspect.signature(value)
        except (TypeError, ValueError):
            continue
        params = signature.parameters
        if "clock" not in params:
            continue
        if not any(
            name in params for name in ("db_path", "path", "source", "dataset")
        ):
            continue
        kwargs: dict[str, object] = {}
        for name, parameter in params.items():
            if name in {"self", "cls"}:
                continue
            if name == "clock":
                kwargs[name] = clock
            elif name in {"db_path", "path", "source"}:
                kwargs[name] = path
            elif name == "dataset":
                kwargs[name] = "equities_bars_daily"
            elif name in {"event_start", "event_end", "from_event", "to_event"}:
                kwargs[name] = "2025-01-02"
            elif name in {"as_of", "decision_at"}:
                kwargs[name] = "2025-01-02T15:30:00+09:00"
            elif parameter.default is not inspect.Parameter.empty:
                continue
            else:
                kwargs = {}
                break
        if "clock" not in kwargs:
            continue
        try:
            result = value(**kwargs)
        except TypeError:
            continue
        except Exception:
            continue
        if result is None:
            continue
        if inspect.isgenerator(result):
            with pytest.raises(Exception):
                list(result)
        else:
            assert not isinstance(result, (list, tuple, dict))

    with pytest.raises(SnapshotNotReady):
        connect_readonly(path)
    with pytest.raises(TypeError):
        publication.verify_controlled_publication_evidence(
            path, object(), clock=clock
        )
    dummy = SimpleNamespace(profiles=())
    with pytest.raises(TypeError, match="filesystem path"):
        publication.ReadyPublicationService().request_verified_publication(
            path, dummy
        )


def test_persistent_tmp_component_is_rejected_for_both_roots(tmp_path: Path) -> None:
    from cf_platform.container_data_view import ContainerEphemeralDataView

    persistent = Path(__file__).resolve().parent / "_persistent_tmp_probe"
    if persistent.exists():
        import shutil
        shutil.rmtree(persistent)
    persistent.mkdir(parents=True)
    source = persistent / "source.sqlite"
    connection = sqlite3.connect(source)
    install_compact_schema(connection)
    stamp_compact_manifest(connection)
    connection.commit()
    connection.close()
    artifacts = persistent / "artifacts"
    artifacts.mkdir()
    with pytest.raises(PersonalResearchViewError, match="ephemeral"):
        require_ephemeral_path(source)
    with pytest.raises(PersonalResearchViewError, match="ephemeral"):
        require_ephemeral_path(artifacts)
    try:
        with pytest.raises(PersonalResearchViewError, match="ephemeral"):
            ContainerEphemeralDataView.bind(source, artifact_root=artifacts)
    finally:
        import shutil
        shutil.rmtree(persistent, ignore_errors=True)


def test_cancellation_inside_write_leaves_no_final_artifact(tmp_path: Path) -> None:
    path = tmp_path / "write.sqlite"
    connection = sqlite3.connect(path)
    install_compact_schema(connection)
    stamp_compact_manifest(connection)
    connection.commit()
    connection.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "art", decision_cutoff="session_close"
    )
    deadline = CooperativeDeadline()
    with install_deadline(deadline):
        deadline.cancel()
        with pytest.raises(DeadlineExceeded):
            view.write_artifact(category="reports", suffix="json", payload=b"{}")
    written = list((tmp_path / "art").rglob("*"))
    finals = [item for item in written if item.is_file() and "partial" not in item.name]
    assert finals == []


def test_alternating_6500x2000_membership_digest_stays_bounded() -> None:
    codes_a = tuple(f"{1000 + i:04d}" for i in range(2000))
    codes_b = tuple(f"{3000 + i:04d}" for i in range(2000))
    start = date(2008, 1, 4)
    runs = []
    intern_a = codes_a
    intern_b = codes_b
    for offset in range(6500):
        day = (start + timedelta(days=offset)).isoformat()
        runs.append(
            MembershipRun(
                start=day,
                end=day,
                codes=intern_a if offset % 2 == 0 else intern_b,
            )
        )
    period_start = start.isoformat()
    period_end = (start + timedelta(days=6499)).isoformat()
    reference_payload = {
        "membership_runs": [
            {"codes": list(run.codes), "end": run.end, "start": run.start}
            for run in runs[:2]
        ],
        "period_end": period_end,
        "period_start": period_start,
        "rule_digest": "sha256:" + "ab" * 32,
        "rule_id": "tse_prime_with_fins",
        "rule_version": "tse-prime-with-fins/v1",
    }
    # Canonical two-run prefix is not the full digest; hash the streamed form.
    tracemalloc.start()
    digest = stream_membership_digest(
        rule_id="tse_prime_with_fins",
        rule_version="tse-prime-with-fins/v1",
        rule_digest="sha256:" + "ab" * 32,
        period_start=period_start,
        period_end=period_end,
        runs=runs,
    )
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert digest.startswith("sha256:")
    assert len(digest) == 71
    assert peak < 32 * 1024 * 1024
    expected = "sha256:" + hashlib.sha256(
        json.dumps(
            {
                "membership_runs": [
                    {"codes": list(run.codes), "end": run.end, "start": run.start}
                    for run in runs
                ],
                "period_end": period_end,
                "period_start": period_start,
                "rule_digest": "sha256:" + "ab" * 32,
                "rule_id": "tse_prime_with_fins",
                "rule_version": "tse-prime-with-fins/v1",
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert digest == expected
    del reference_payload


def test_thicken_sidecar_flow_requires_typed_view_and_does_not_swallow(
    tmp_path: Path,
) -> None:
    path = tmp_path / "side.sqlite"
    connection = sqlite3.connect(path)
    install_compact_schema(connection)
    stamp_compact_manifest(connection)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS jquants_records ("
        "source TEXT, dataset TEXT, natural_key TEXT, event_time TEXT, "
        "available_at TEXT, ingested_at TEXT, payload TEXT, raw_payload TEXT)"
    )
    connection.commit()
    connection.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "s", decision_cutoff="session_close"
    )
    period = {"period_start": "2025-01-02", "period_end": "2025-01-02"}
    with pytest.raises(TypeError, match="PersonalResearchDataView"):
        _build_thicken_sidecars(period, codes=["1301"], view=path)
    out = _build_thicken_sidecars(period, codes=["1301"], view=view)
    assert out["calendar"]["hol_div_by_date"] == {}
    assert out["repo_rate_regime"]["status"] == "empty"
    bars: dict[str, list[list[object]]] = {}
    attached = attach_nky_proxy(bars, period, view)
    assert "nky_proxy_error" not in attached


def test_path_is_not_a_controlled_universe_capability(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="closed PIT slices"):
        resolve_tse_prime_with_fins(
            tmp_path / "missing.sqlite",
            period_start="2024-01-02",
            period_end="2024-01-02",
        )


def test_typed_close_scan_obeys_two_clocks_and_fails_closed(tmp_path: Path) -> None:
    from pit.api import first_invalid_adjusted_close
    from pit.read_clock import install_read_clock, PitReadClock, SNAPSHOT_OBSERVATION_LABEL

    path = tmp_path / "typed.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE jquants_daily_bars ("
        "source TEXT, code TEXT, date TEXT, event_time TEXT, available_at TEXT, "
        "ingested_at TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, "
        "turnover_value REAL, adjustment_open REAL, adjustment_high REAL, "
        "adjustment_low REAL, adjustment_close REAL, adjustment_volume REAL, "
        "raw_payload TEXT, PRIMARY KEY(source, code, date))"
    )
    connection.execute(
        "INSERT INTO jquants_daily_bars VALUES ("
        "'jquants','1301','2025-01-02','2025-01-02T15:30:00+09:00',"
        "'2025-01-02T15:30:00+09:00','2099-01-01T00:00:00+09:00',"
        "10,10,10,10,1,10,10,10,10,-1,1,'{}')"
    )
    connection.execute(
        "CREATE TABLE jquants_records ("
        "source TEXT, dataset TEXT, natural_key TEXT, event_time TEXT, "
        "available_at TEXT, ingested_at TEXT, payload TEXT, raw_payload TEXT)"
    )
    stamp_compact_manifest(connection, format_name="unmanaged-catalog",
                           observed_through="2025-01-02T16:00:00+09:00")
    connection.commit()
    connection.close()
    visible = get_equity_bars_daily(
        as_of="2025-01-02T15:30:00+09:00",
        code="1301",
        from_event="2025-01-02",
        to_event="2025-01-02",
        db_path=path,
    )
    assert list(visible) == []
    invalid = first_invalid_adjusted_close(
        as_of="2025-01-02T15:30:00+09:00",
        codes=("1301",),
        from_event="2025-01-02",
        to_event="2025-01-02",
        db_path=path,
    )
    assert invalid is None
    unstamped = tmp_path / "unbound.sqlite"
    connection = sqlite3.connect(unstamped)
    connection.execute(
        "CREATE TABLE jquants_daily_bars ("
        "source TEXT, code TEXT, date TEXT, event_time TEXT, available_at TEXT, "
        "ingested_at TEXT, adjustment_close REAL, PRIMARY KEY(source, code, date))"
    )
    connection.execute(
        "INSERT INTO jquants_daily_bars VALUES ("
        "'jquants','1301','2025-01-02','2025-01-02T15:30:00+09:00',"
        "'2025-01-02T15:30:00+09:00','2025-01-02T16:00:00+09:00', -1)"
    )
    connection.commit()
    connection.close()
    with pytest.raises(PitError, match="observation cutoff is missing"):
        first_invalid_adjusted_close(
            as_of="2025-01-02T15:30:00+09:00",
            codes=("1301",),
            from_event="2025-01-02",
            to_event="2025-01-02",
            db_path=unstamped,
        )


def test_jsda_history_requires_event_and_ingested_gates(tmp_path: Path) -> None:
    from pit.errors import HistoryReadError
    from pit.history_reads import fetch_jsda_repo_history_rows
    from pit.read_clock import install_read_clock, PitReadClock, DRAFT_OBSERVATION_LABEL

    incomplete = tmp_path / "jsda-incomplete.sqlite"
    connection = sqlite3.connect(incomplete)
    connection.execute(
        "CREATE TABLE jsda_repo_rates ("
        "as_of_date TEXT, tenor TEXT, rate_type TEXT, rate REAL, "
        "available_at TEXT, event_time TEXT)"
    )
    connection.execute(
        "INSERT INTO jsda_repo_rates VALUES ("
        "'2025-01-02','overnight','trr',0.1,"
        "'2025-01-02T15:00:00+09:00','2025-01-02T00:00:00+09:00')"
    )
    connection.commit()
    connection.close()
    with pytest.raises(HistoryReadError, match="cannot prove"):
        fetch_jsda_repo_history_rows(
            incomplete, as_of="2025-01-02T15:30:00+09:00"
        )

    complete = tmp_path / "jsda-complete.sqlite"
    connection = sqlite3.connect(complete)
    connection.execute(
        "CREATE TABLE jsda_repo_rates ("
        "as_of_date TEXT, tenor TEXT, rate_type TEXT, rate REAL, "
        "available_at TEXT, event_time TEXT, ingested_at TEXT)"
    )
    connection.execute(
        "INSERT INTO jsda_repo_rates VALUES ("
        "'2025-01-02','overnight','trr',0.1,"
        "'2025-01-02T15:00:00+09:00','2025-01-02T00:00:00+09:00',"
        "'2099-01-01T00:00:00+09:00')"
    )
    stamp_compact_manifest(
        connection, format_name="unmanaged-catalog",
        observed_through="2025-01-02T16:00:00+09:00",
    )
    connection.commit()
    connection.close()
    rows = fetch_jsda_repo_history_rows(
        complete, as_of="2025-01-02T15:30:00+09:00"
    )
    assert rows == []


def test_morning_close_coverage_does_not_substitute_session_close(
    tmp_path: Path,
) -> None:
    path = tmp_path / "am.sqlite"
    connection = sqlite3.connect(path)
    install_compact_schema(connection)
    insert_compact_bar(
        connection,
        code="1301",
        day="2025-01-02",
        close=10.0,
        available_at="2025-01-02T15:30:00+09:00",
        ingested_at="2025-01-02T16:00:00+09:00",
        event_time="2025-01-02T15:30:00+09:00",
    )
    stamp_compact_manifest(
        connection, observed_through="2025-01-02T16:00:00+09:00"
    )
    connection.commit()
    connection.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "am-art", decision_cutoff="morning_close"
    )
    try:
        pages = list(
            view.iter_decision_pages(
                decision_date="2025-01-02",
                dataset="equities_bars_daily_am",
                codes=["1301"],
                start="2025-01-02",
                end="2025-01-02",
            )
        )
    except Exception:
        pages = []
    visible = [row for page in pages for row in page]
    assert visible == []
    universe = SimpleNamespace(
        period_start="2025-01-02",
        period_end="2025-01-02",
        decision_memberships=(("2025-01-02", ("1301",)),),
    )
    coverage = view.observed_bar_coverage(universe, minimum_ratio=1.0)
    assert coverage["status"] in {"FAIL", "UNKNOWN"}
    assert coverage.get("bar_dataset") == "equities_bars_daily_am"
    assert int(coverage.get("observed_rows") or 0) == 0
    assert coverage.get("status") != "PASS"


def test_ready_proof_ignores_rows_after_observed_through(tmp_path: Path) -> None:
    import inspect
    from types import SimpleNamespace

    import pit._ready_verifier_reads as ready_reads
    from paper_runtime.ready_publication import (
        ReadyPublicationService,
        VerifiedPublicationEvidence,
        verify_controlled_publication_evidence,
    )
    from pit.read_clock import PitReadClock, SNAPSHOT_OBSERVATION_LABEL
    from selection.budget_ledger import MassResearchDisabledError

    path = tmp_path / "ready-facts.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE jquants_records ("
        "source TEXT, dataset TEXT, natural_key TEXT, event_time TEXT, "
        "available_at TEXT, ingested_at TEXT, payload TEXT, raw_payload TEXT)"
    )
    connection.execute(
        "INSERT INTO jquants_records VALUES ("
        "'jquants','equities_bars_daily','{\"Code\":\"1301\",\"Date\":\"2025-01-02\"}',"
        "'2025-01-02T15:30:00+09:00','2025-01-02T15:30:00+09:00',"
        "'2099-01-01T00:00:00+09:00','{\"Code\":\"1301\",\"Date\":\"2025-01-02\",\"C\":1}',"
        "'{}')"
    )
    stamp_compact_manifest(
        connection, format_name="unmanaged-catalog",
        observed_through="2025-01-02T16:00:00+09:00",
    )
    connection.commit()
    connection.close()
    clock = PitReadClock(
        decision_at="2025-01-02T15:30:00+09:00",
        observed_through="2025-01-02T16:00:00+09:00",
        observation_label=SNAPSHOT_OBSERVATION_LABEL,
        promotable=True,
    )
    assert not hasattr(ready_reads, "iter_ready_catalog_product_rows")
    signature = inspect.signature(
        ReadyPublicationService.request_verified_publication
    )
    assert "clock" not in signature.parameters
    scope = {"required_lookback_trading_days": 2}
    profile = SimpleNamespace(
        period_start="2025-01-02",
        period_end="2025-01-02",
        dataset_scopes=tuple(scope for _ in range(5)),
    )
    binding = SimpleNamespace(
        profiles=(profile,),
        required_datasets=(
            "equities_bars_daily",
            "equities_master",
            "fins_summary",
            "indices_bars_daily_topix",
            "markets_calendar",
        ),
        profile_digest="sha256:" + "aa" * 32,
        plan_set_digest="sha256:" + "bb" * 32,
        closure_set_digest="sha256:" + "cc" * 32,
    )
    with pytest.raises(TypeError, match="filesystem path"):
        evidence = ReadyPublicationService().request_verified_publication(
            path, binding
        )
        assert not isinstance(evidence, (list, tuple))
        assert not isinstance(evidence, VerifiedPublicationEvidence) or (
            evidence.as_dict().get("status") != "PASS"
        )
    with pytest.raises(TypeError):
        verify_controlled_publication_evidence(path, binding, clock=clock)  # type: ignore[call-arg]


def test_mass_eval_rejects_arbitrary_ndjson_market_path(tmp_path: Path) -> None:
    from research.cf_mass_eval_stage import build_real_period_panel

    ndjson = tmp_path / "equities_bars_daily_y2025_full.ndjson"
    ndjson.write_text(
        '{"payload":{"Code":"1301","Date":"2025-01-02","C":1,'
        '"available_at":"2099-01-01T00:00:00+09:00"}}\n'
    )
    from selection.budget_ledger import MassResearchDisabledError

    with pytest.raises(MassResearchDisabledError, match="build_real_period_panel"):
        build_real_period_panel(
            {
                "period_id": "y2025_full",
                "period_start": "2025-01-02",
                "period_end": "2025-01-02",
            },
            codes=["1301"],
        )
    with pytest.raises(MassResearchDisabledError, match="build_real_period_panel"):
        build_real_period_panel(
            {
                "period_id": "y2025_full",
                "period_start": "2025-01-02",
                "period_end": "2025-01-02",
            },
            codes=["1301"],
            view=tmp_path,
        )


def test_artifact_category_rejects_traversal_and_symlink(tmp_path: Path) -> None:
    path = tmp_path / "art.sqlite"
    connection = sqlite3.connect(path)
    install_compact_schema(connection)
    stamp_compact_manifest(connection)
    connection.commit()
    connection.close()
    artifacts = tmp_path / "artifacts"
    view = OfflineFixtureDataView.bind(
        path, artifact_root=artifacts, decision_cutoff="session_close"
    )
    with pytest.raises(PersonalResearchViewError, match="category"):
        view.write_artifact(category="../../escaped", suffix="json", payload=b"{}")
    outside = tmp_path / "outside"
    outside.mkdir()
    leaked = artifacts / "reports"
    if leaked.exists():
        leaked.unlink()
    leaked.symlink_to(outside)
    with pytest.raises(PersonalResearchViewError):
        view.write_artifact(category="reports", suffix="json", payload=b"{}")
    assert list(outside.iterdir()) == []


def test_injected_cancellation_after_final_link_removes_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pit.personal_research_view as view_mod

    path = tmp_path / "write2.sqlite"
    connection = sqlite3.connect(path)
    install_compact_schema(connection)
    stamp_compact_manifest(connection)
    connection.commit()
    connection.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "art2", decision_cutoff="session_close"
    )
    real = view_mod.check_deadline
    linked = {"done": False}
    real_link = os.link

    def wrapped_link(source, target, *args, **kwargs):
        real_link(source, target, *args, **kwargs)
        linked["done"] = True

    def injected() -> None:
        if linked["done"]:
            raise DeadlineExceeded("injected fourth check")
        return real()

    monkeypatch.setattr(os, "link", wrapped_link)
    monkeypatch.setattr(view_mod, "check_deadline", injected)
    with pytest.raises(DeadlineExceeded, match="fourth"):
        view.write_artifact(category="reports", suffix="json", payload=b'{"ok":true}')
    finals = [
        item
        for item in (tmp_path / "art2").rglob("*")
        if item.is_file() and "partial" not in item.name
    ]
    assert finals == []


def test_timeout_does_not_unbounded_join_or_publish_late_success() -> None:
    import importlib.util
    import json
    import multiprocessing
    import sys
    import threading
    import time

    root = Path(__file__).resolve().parents[1]
    module_path = (
        root
        / "platform"
        / "workers"
        / "research-mass-eval"
        / "container"
        / "personal_research_service.py"
    )
    spec_mod = importlib.util.spec_from_file_location(
        "cloud_personal_research_service_p0", module_path
    )
    assert spec_mod is not None and spec_mod.loader is not None
    service = importlib.util.module_from_spec(spec_mod)
    sys.modules[spec_mod.name] = service
    spec_mod.loader.exec_module(service)

    from research.factor_cohorts import get_research_cohort, is_am_pm_factor_cohort
    from research.personal_universe import personal_research_universe_rule_digest

    process_context = multiprocessing.get_context("fork")
    entered = process_context.Event()
    uploads: list[tuple[str, dict]] = []
    wrote = threading.Event()

    def runner(item):
        entered.set()
        time.sleep(1)
        return {
            "job_id": item.job_id,
            "request_digest": item.request_digest,
            "status": "COMPLETED",
            "go": True,
        }

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers
        uploads.append((key, json.loads(data)))
        wrote.set()

    manager = service.JobManager(
        runner,
        max_job_seconds=0.05,
        terminal_uploader=uploader,
        process_context=process_context,
    )
    cohort_id = "diverse-core-am-pm-v1"
    body = {
        "cohort_digest": str(get_research_cohort(cohort_id).to_dict()["cohort_digest"]),
        "cohort_id": cohort_id,
        "job_id": "timeout-p0",
        "period_end": "2026-08-27",
        "period_start": "2022-04-19",
        "runner_version": service.RUNNER_VERSION,
        "snapshot_key": "research/personal/snapshots/sha256=" + ("a" * 64) + ".sqlite",
        "snapshot_sha256": "a" * 64,
        "universe_id": "topix_all",
        "universe_rule_digest": personal_research_universe_rule_digest(
            "topix_all", am_pm=is_am_pm_factor_cohort(cohort_id)
        ),
    }
    request_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    job = service.JobSpec.from_document(
        {
            **body,
            "request_digest": request_digest,
            "result_key": "research/personal/jobs/job=timeout-p0/result.tar.gz",
            "manifest_key": "research/personal/jobs/job=timeout-p0/manifest.json",
        }
    )
    started = time.monotonic()
    manager.submit(job)
    assert entered.wait(1)
    assert wrote.wait(2)
    assert time.monotonic() - started < 0.5
    assert uploads[0][1]["status"] == "FAILED"
    time.sleep(1.1)
    assert manager.status(job.job_id)["status"] == "FAILED"
    assert all(body["status"] != "COMPLETED" for _key, body in uploads)


def test_membership_runs_reject_malformed_order_overlap_and_duplicates() -> None:
    from data_contracts.membership_runs import (
        MembershipRun,
        validate_membership_runs,
        stream_membership_digest,
        codes_for_runs,
    )
    from research.universe_contract import ResolvedUniverseMembership
    from research.personal_universe import PersonalResolvedUniverseMembership
    from selection.budget_ledger import MassResearchDisabledError
    from research.personal_universe import PersonalUniverseError

    with pytest.raises(ValueError):
        MembershipRun(start="2025-01-03", end="2025-01-02", codes=("1301",))
    with pytest.raises(ValueError, match="sorted"):
        MembershipRun(start="2025-01-02", end="2025-01-02", codes=("1302", "1301"))
    with pytest.raises(ValueError, match="unique"):
        MembershipRun(start="2025-01-02", end="2025-01-02", codes=("1301", "1301"))
    with pytest.raises(ValueError, match="overlap|order"):
        validate_membership_runs(
            (
                MembershipRun(start="2025-01-03", end="2025-01-03", codes=("1301",)),
                MembershipRun(start="2025-01-02", end="2025-01-02", codes=("1302",)),
            ),
            period_start="2025-01-01",
            period_end="2025-01-31",
        )
    with pytest.raises(ValueError, match="overlap"):
        validate_membership_runs(
            (
                MembershipRun(start="2025-01-02", end="2025-01-05", codes=("1301",)),
                MembershipRun(start="2025-01-04", end="2025-01-06", codes=("1302",)),
            ),
            period_start="2025-01-01",
            period_end="2025-01-31",
        )
    with pytest.raises(ValueError, match="outside"):
        validate_membership_runs(
            (MembershipRun(start="2024-12-31", end="2025-01-02", codes=("1301",)),),
            period_start="2025-01-01",
            period_end="2025-01-31",
        )
    coalesced = validate_membership_runs(
        (
            MembershipRun(start="2025-01-02", end="2025-01-02", codes=("1301",)),
            MembershipRun(start="2025-01-03", end="2025-01-03", codes=("1301",)),
        ),
        period_start="2025-01-01",
        period_end="2025-01-31",
    )
    assert coalesced == (
        MembershipRun(start="2025-01-02", end="2025-01-03", codes=("1301",)),
    )
    runs = (
        MembershipRun(start="2025-01-02", end="2025-01-03", codes=("1301", "1302")),
    )
    digest = stream_membership_digest(
        rule_id="tse_prime_with_fins",
        rule_version="tse-prime-with-fins/v1",
        rule_digest="sha256:" + "ab" * 32,
        period_start="2025-01-02",
        period_end="2025-01-03",
        runs=runs,
    )
    assert codes_for_runs(runs, "2025-01-02") == ("1301", "1302")
    assert codes_for_runs(runs, "2025-01-03") == ("1301", "1302")
    with pytest.raises((MassResearchDisabledError, PersonalUniverseError, ValueError)):
        ResolvedUniverseMembership(
            period_start="2025-01-02",
            period_end="2025-01-03",
            decision_memberships=(("2025-01-02", ("1301",)),),
            membership_runs=(
                MembershipRun(start="2025-01-02", end="2025-01-03", codes=("9999",)),
            ),
        )


def test_run_length_and_mapping_adapter_agree_without_cartesian() -> None:
    from data_contracts.membership_runs import (
        MembershipRun,
        RunLengthMembershipMap,
        stream_membership_digest,
        codes_for_runs,
    )
    from research.personal_universe import PersonalResolvedUniverseMembership

    codes_a = tuple(f"{1000 + i:04d}" for i in range(50))
    codes_b = tuple(f"{3000 + i:04d}" for i in range(50))
    runs = (
        MembershipRun(start="2025-01-02", end="2025-01-02", codes=codes_a),
        MembershipRun(start="2025-01-03", end="2025-01-03", codes=codes_b),
    )
    universe = PersonalResolvedUniverseMembership(
        period_start="2025-01-02",
        period_end="2025-01-03",
        decision_memberships=(),
        membership_runs=runs,
        rule_id="topix_all",
        rule_version="personal-topix-scale-with-fins/v1",
        rule_digest="sha256:" + "cd" * 32,
    )
    mapping = universe.membership_by_date
    assert isinstance(mapping, RunLengthMembershipMap)
    assert universe.codes_for("2025-01-02") == mapping["2025-01-02"] == codes_a
    assert universe.codes_for("2025-01-03") == mapping["2025-01-03"] == codes_b
    assert dict(universe.decision_memberships)["2025-01-02"] is mapping["2025-01-02"]
    assert universe.resolved_membership_digest == stream_membership_digest(
        rule_id=universe.rule_id,
        rule_version=universe.rule_version,
        rule_digest=universe.rule_digest,
        period_start=universe.period_start,
        period_end=universe.period_end,
        runs=universe.membership_runs,
    )
