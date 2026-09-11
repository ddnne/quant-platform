"""Complete master selection with existing receipt authority."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from core.execution import close_as_of
from ingestion.jquants.normalize import normalize_generic
from ingestion.jquants.official_business_calendar import (
    derive_official_business_calendar,
)
from ops.receipt_product import (
    canonical_product_artifact_bytes,
    product_artifact_digest,
)
from pit.complete_master import _owned_complete_master_selection_from_connection
from pit.errors import PitError
from pit.query import connect_readonly
from pit.universe_pit import resolve_universe_day_slices
from storage.coverage_ledger import RequiredCoverageSegment, record_collection_receipt
from storage.sqlite_store import SqliteStore
from tests.receipt_test_support import (
    TestSignedReceiptAuthority,
    reconcile_test_evidence,
)


SEGMENT_START = "2022-12-30"
SEGMENT_END = "2023-01-06"
PERIOD_START = "2023-01-04"
PERIOD_END = "2023-01-06"
BUSINESS_DATES = (
    "2022-12-30",
    "2023-01-04",
    "2023-01-05",
    "2023-01-06",
)
OBSERVED_THROUGH = "2023-01-09T16:00:00+09:00"
CHECKED_AT = "2026-08-25T00:00:00+00:00"


def _as_of_for_day(start: str = PERIOD_START, end: str = PERIOD_END) -> dict[str, str]:
    values: dict[str, str] = {}
    cursor = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while cursor <= stop:
        day = cursor.isoformat()
        values[day] = close_as_of(day)
        cursor += timedelta(days=1)
    return values


def _official_calendar_bytes(
    start: str = SEGMENT_START,
    end: str = SEGMENT_END,
    business: tuple[str, ...] = BUSINESS_DATES,
) -> bytes:
    rows = []
    cursor = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    wanted = set(business)
    while cursor <= stop:
        day = cursor.isoformat()
        rows.append({"Date": day, "HolDiv": "1" if day in wanted else "0"})
        cursor += timedelta(days=1)
    return json.dumps({"data": rows}, separators=(",", ":")).encode("utf-8")


def _calendar_extras(raw: bytes, *, start: str, end: str) -> dict[str, str]:
    calendar = derive_official_business_calendar(
        raw, segment_start=start, segment_end=end
    )
    return {
        "official_calendar_raw_body_digest": calendar.raw_body_digest,
        "official_calendar_query_digest": calendar.calendar_query_digest,
        "official_business_dates_digest": calendar.business_dates_digest,
        "official_calendar_binding_digest": calendar.binding_digest,
    }


def _calendar_bodies(*raw: bytes) -> tuple[bytes, ...]:
    return raw if raw else (_official_calendar_bytes(),)


def _indented_calendar_bytes(raw: bytes) -> bytes:
    return json.dumps(json.loads(raw.decode("utf-8")), indent=2).encode("utf-8")


def _master_payload(
    code: str,
    snapshot: str,
    *,
    market: str = "0111",
    scale: str = "TOPIX Core30",
) -> dict[str, str]:
    return {
        "Code": code,
        "Date": snapshot,
        "MarketCode": market,
        "ScaleCategory": scale,
    }


def _stamp(day: str, hour: int = 8) -> str:
    return f"{day}T{hour:02d}:00:00+09:00"


def _catalog_rows(
    payloads: list[dict[str, str]],
    *,
    dataset: str,
    stamp: str,
) -> list[dict[str, str]]:
    return normalize_generic(
        payloads,
        dataset=dataset,
        ingested_at=stamp,
        available_at=stamp,
    )


def _prepare_store(path: Path) -> SqliteStore:
    store = SqliteStore(path)
    store._conn.execute(  # noqa: SLF001
        "ALTER TABLE ingestion_run_log ADD COLUMN authority_operation_id TEXT"
    )
    store._conn.execute(  # noqa: SLF001
        "CREATE TABLE IF NOT EXISTS snapshot_observation_clock "
        "(observed_through TEXT NOT NULL)"
    )
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO snapshot_observation_clock VALUES (?)",
        (OBSERVED_THROUGH,),
    )
    store._conn.commit()  # noqa: SLF001
    return store


def _insert_calendar_and_fins(
    store: SqliteStore,
    codes: tuple[str, ...],
    *,
    period_start: str = PERIOD_START,
    period_end: str = PERIOD_END,
    trading_dates: tuple[str, ...] | None = None,
) -> None:
    trading = set(trading_dates or BUSINESS_DATES)
    calendar = []
    cursor = date.fromisoformat(period_start)
    stop = date.fromisoformat(period_end)
    while cursor <= stop:
        day = cursor.isoformat()
        calendar.append(
            {
                "Date": day,
                "HolidayDivision": "1" if day in trading else "0",
            }
        )
        cursor += timedelta(days=1)
    store.upsert(
        "jquants_records",
        _catalog_rows(
            calendar,
            dataset="markets_calendar",
            stamp="2022-12-01T00:00:00+09:00",
        ),
    )
    fins = [
        {"Code": code, "DiscDate": "2022-12-29", "DiscNo": str(index)}
        for index, code in enumerate(codes, start=1)
    ]
    store.upsert(
        "jquants_records",
        _catalog_rows(
            fins,
            dataset="fins_summary",
            stamp="2022-12-29T15:00:00+09:00",
        ),
    )


def _issue_master_product(
    store: SqliteStore,
    *,
    authority: TestSignedReceiptAuthority,
    run_id: int,
    structured: list[dict[str, str]],
    calendar_raw: bytes,
    extras: dict[str, str],
    segment_id: str = "2023-01",
    segment_start: str = SEGMENT_START,
    segment_end: str = SEGMENT_END,
) -> None:
    artifact_body = canonical_product_artifact_bytes(structured).decode("utf-8")
    artifact_digest = product_artifact_digest(structured)
    operation_id = f"sha256:operation-{run_id:02d}" + ("0" * 45)
    required = RequiredCoverageSegment(
        source="jquants",
        dataset="equities_master",
        segment_id=segment_id,
        segment_start=segment_start,
        segment_end=segment_end,
        expected_scope={
            "coverage_mode": "scd2_event_sourcing",
            "expected_frequency": "trading_day",
            "expected_item_unit": "source_event",
            "segment_start": segment_start,
            "segment_end": segment_end,
        },
        expected_items=len(structured),
    )
    evidence = reconcile_test_evidence(
        required=required,
        run_id=run_id,
        raw_pages=[calendar_raw],
        raw_records=[{"Date": segment_start, "Code": "seed"}],
        structured_records=structured,
        checked_at=CHECKED_AT,
        structured_digest=artifact_digest,
        extra_evidence=extras,
    )
    record_collection_receipt(store._conn, authority.issue(evidence))  # noqa: SLF001
    raw_manifest_digest = str(evidence.claims["raw_manifest_digest"])
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO ingestion_run_log "
        "(id,ran_at,source,runtime,status,detail,authority_operation_id) "
        "VALUES (?,?,'jquants','receipt-evidence-authority','SUCCESS','{}',?)",
        (run_id, CHECKED_AT, operation_id),
    )
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO raw_retention_manifests "
        "(dataset,run_id,manifest_key,page_count,row_count,raw_bytes,"
        "data_digest,completeness,created_at) "
        "VALUES ('equities_master',?,?,?,?,?,?,'COMPLETE',?)",
        (
            run_id,
            f"raw/equities_master/{run_id}.manifest.json",
            1,
            1,
            len(calendar_raw),
            raw_manifest_digest,
            CHECKED_AT,
        ),
    )
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO receipt_product_materializations "
        "(operation_id,run_id,source,dataset,segment_id,artifact_key,"
        "artifact_digest,artifact_body,row_count,byte_count,manifest_key,"
        "manifest_digest,raw_manifest_key,raw_manifest_digest,"
        "raw_page_count,raw_row_count,raw_bytes,committed_at) "
        "VALUES (?,?,'jquants','equities_master',?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            operation_id,
            run_id,
            segment_id,
            f"structured/equities_master/{run_id}.jsonl",
            artifact_digest,
            artifact_body,
            len(structured),
            len(artifact_body.encode("utf-8")),
            f"structured/equities_master/{run_id}.manifest.json",
            f"sha256:manifest-{run_id}",
            f"raw/equities_master/{run_id}.manifest.json",
            raw_manifest_digest,
            1,
            1,
            len(calendar_raw),
            CHECKED_AT,
        ),
    )
    store._conn.commit()  # noqa: SLF001


def _read_master(store: SqliteStore) -> list[dict[str, str]]:
    return [
        dict(row)
        for row in store._conn.execute(  # noqa: SLF001
            "SELECT source,dataset,natural_key,event_time,available_at,"
            "ingested_at,payload,raw_payload FROM jquants_records "
            "WHERE source='jquants' AND dataset='equities_master' "
            "ORDER BY natural_key"
        )
    ]


def _seed_complete_master(
    path: Path,
    receipt_ed25519_keys,
    *,
    snapshots: dict[str, list[dict[str, str]]],
    extra_unrelated: dict[str, str] | None = None,
    poison_unrelated: bool = False,
    period_end: str = PERIOD_END,
) -> dict[tuple[str, str], bytes]:
    calendar_raw = _official_calendar_bytes()
    extras = _calendar_extras(
        calendar_raw, start=SEGMENT_START, end=SEGMENT_END
    )
    store = _prepare_store(path)
    codes = tuple(
        sorted(
            {
                payload["Code"]
                for members in snapshots.values()
                for payload in members
            }
        )
    )
    _insert_calendar_and_fins(
        store, codes, period_start=PERIOD_START, period_end=period_end
    )
    structured: list[dict[str, str]] = []
    for snapshot, members in snapshots.items():
        rows = []
        for payload in members:
            rows.extend(
                _catalog_rows(
                    [payload],
                    dataset="equities_master",
                    stamp=_stamp(snapshot),
                )
            )
        store.upsert("jquants_records", rows)
        structured.extend(rows)
    if extra_unrelated is not None:
        unrelated = _catalog_rows(
            [extra_unrelated],
            dataset="equities_master",
            stamp=_stamp(extra_unrelated["Date"]),
        )
        store.upsert("jquants_records", unrelated)
        structured.extend(unrelated)
    if poison_unrelated:
        store._conn.execute(  # noqa: SLF001
            "UPDATE jquants_records SET payload='{\"poison\":true}' "
            "WHERE dataset='equities_master' AND payload LIKE '%9999%'"
        )
        store._conn.commit()  # noqa: SLF001
    authority = TestSignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    )
    current = _read_master(store)
    _issue_master_product(
        store,
        authority=authority,
        run_id=1,
        structured=current if not poison_unrelated else structured,
        calendar_raw=calendar_raw,
        extras=extras,
    )
    store.close()
    return _calendar_bodies(calendar_raw)


def _open(path: Path):
    return connect_readonly(path)


def _strict(
    conn,
    calendars: tuple[bytes, ...],
    *,
    period_end: str = PERIOD_END,
):
    return _owned_complete_master_selection_from_connection(
        conn,
        period_start=PERIOD_START,
        period_end=period_end,
        as_of_for_day=_as_of_for_day(end=period_end),
        official_calendar_raw=calendars,
    )


def _member_codes(slices) -> dict[str, tuple[str, ...]]:
    return {
        item.decision_date: tuple(member.code for member in item.members)
        for item in slices
    }


def test_seed_older_than_warmup_agrees_with_draft(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    path = tmp_path / "seed.sqlite"
    calendar_raw = _official_calendar_bytes()
    extras = _calendar_extras(
        calendar_raw, start=SEGMENT_START, end=SEGMENT_END
    )
    store = _prepare_store(path)
    _insert_calendar_and_fins(store, ("1001", "1002"))
    rows = _catalog_rows(
        [
            _master_payload("1001", "2022-12-30"),
            _master_payload("1002", "2022-12-30"),
        ],
        dataset="equities_master",
        stamp=_stamp("2022-12-30"),
    )
    for day in ("2023-01-04", "2023-01-05", "2023-01-06"):
        rows.extend(
            normalize_generic(
                [
                    _master_payload("1001", day),
                    _master_payload("1002", day),
                ],
                dataset="equities_master",
                ingested_at=_stamp(day, 16),
                available_at=_stamp(day, 16),
            )
        )
    store.upsert("jquants_records", rows)
    _issue_master_product(
        store,
        authority=TestSignedReceiptAuthority(
            signing_key=receipt_ed25519_keys.signing_key
        ),
        run_id=1,
        structured=_read_master(store),
        calendar_raw=calendar_raw,
        extras=extras,
    )
    store.close()
    draft = resolve_universe_day_slices(
        path,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        as_of_for_day=_as_of_for_day(),
    )
    conn = _open(path)
    try:
        owned = _strict(conn, _calendar_bodies(calendar_raw))
    finally:
        conn.close()
    assert owned.proof.format == "complete-master-selection-evidence/v1"
    assert owned.proof.seed_snapshot_date == "2022-12-30"
    assert owned.slices[0].snapshot_date == "2022-12-30"
    assert _member_codes(owned.slices) == _member_codes(draft)
    assert [item.snapshot_date for item in owned.slices] == [
        item.snapshot_date for item in draft
    ]


def test_entrant_and_delisting(tmp_path: Path, receipt_ed25519_keys) -> None:
    path = tmp_path / "churn.sqlite"
    snapshots = {
        "2022-12-30": [
            _master_payload("1001", "2022-12-30"),
            _master_payload("1002", "2022-12-30"),
        ],
        "2023-01-04": [
            _master_payload("1001", "2023-01-04"),
            _master_payload("1003", "2023-01-04"),
        ],
        "2023-01-05": [
            _master_payload("1001", "2023-01-05"),
            _master_payload("1003", "2023-01-05"),
        ],
        "2023-01-06": [_master_payload("1003", "2023-01-06")],
    }
    calendars = _seed_complete_master(
        path, receipt_ed25519_keys, snapshots=snapshots
    )
    conn = _open(path)
    try:
        owned = _strict(conn, calendars)
    finally:
        conn.close()
    assert _member_codes(owned.slices) == {
        "2023-01-04": ("1001", "1003"),
        "2023-01-05": ("1001", "1003"),
        "2023-01-06": ("1003",),
    }


def test_split_visibility_rejects_strict_and_leaves_draft_partial(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    path = tmp_path / "split.sqlite"
    calendar_raw = _official_calendar_bytes()
    extras = _calendar_extras(
        calendar_raw, start=SEGMENT_START, end=SEGMENT_END
    )
    store = _prepare_store(path)
    _insert_calendar_and_fins(store, ("1001", "1003"))
    early = _catalog_rows(
        [_master_payload("1001", "2022-12-30")],
        dataset="equities_master",
        stamp=_stamp("2022-12-30"),
    )
    visible = _catalog_rows(
        [_master_payload("1001", "2023-01-04")],
        dataset="equities_master",
        stamp=_stamp("2023-01-04"),
    )
    late = normalize_generic(
        [_master_payload("1003", "2023-01-04")],
        dataset="equities_master",
        ingested_at=_stamp("2023-01-04"),
        available_at="2023-01-04T16:00:00+09:00",
    )
    later_days = []
    for day in ("2023-01-05", "2023-01-06"):
        later_days.extend(
            _catalog_rows(
                [
                    _master_payload("1001", day),
                    _master_payload("1003", day),
                ],
                dataset="equities_master",
                stamp=_stamp(day),
            )
        )
    store.upsert("jquants_records", early + visible + late + later_days)
    _issue_master_product(
        store,
        authority=TestSignedReceiptAuthority(
            signing_key=receipt_ed25519_keys.signing_key
        ),
        run_id=1,
        structured=_read_master(store),
        calendar_raw=calendar_raw,
        extras=extras,
    )
    store.close()
    draft = resolve_universe_day_slices(
        path,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        as_of_for_day=_as_of_for_day(),
    )
    assert draft[0].snapshot_date == "2023-01-04"
    assert tuple(member.code for member in draft[0].members) == ("1001",)
    conn = _open(path)
    try:
        with pytest.raises(PitError, match="partially PIT-visible"):
            _strict(conn, _calendar_bodies(calendar_raw))
    finally:
        conn.close()


def test_wholly_future_candidate_ignored_until_visible(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    path = tmp_path / "future.sqlite"
    calendar_raw = _official_calendar_bytes()
    extras = _calendar_extras(
        calendar_raw, start=SEGMENT_START, end=SEGMENT_END
    )
    store = _prepare_store(path)
    _insert_calendar_and_fins(store, ("1001",))
    rows = _catalog_rows(
        [_master_payload("1001", "2022-12-30")],
        dataset="equities_master",
        stamp=_stamp("2022-12-30"),
    )
    for day in ("2023-01-04", "2023-01-05"):
        rows.extend(
            _catalog_rows(
                [_master_payload("1001", day)],
                dataset="equities_master",
                stamp=_stamp(day),
            )
        )
    future = normalize_generic(
        [_master_payload("1001", "2023-01-06")],
        dataset="equities_master",
        ingested_at=_stamp("2023-01-06"),
        available_at="2023-01-06T16:00:00+09:00",
    )
    store.upsert("jquants_records", rows + future)
    _issue_master_product(
        store,
        authority=TestSignedReceiptAuthority(
            signing_key=receipt_ed25519_keys.signing_key
        ),
        run_id=1,
        structured=_read_master(store),
        calendar_raw=calendar_raw,
        extras=extras,
    )
    store.close()
    conn = _open(path)
    try:
        owned = _strict(conn, _calendar_bodies(calendar_raw))
    finally:
        conn.close()
    by_day = {item.decision_date: item.snapshot_date for item in owned.slices}
    assert by_day["2023-01-04"] == "2023-01-04"
    assert by_day["2023-01-05"] == "2023-01-05"
    assert by_day["2023-01-06"] == "2023-01-05"


def test_earlier_backed_correction_and_unbacked_same_key_revision(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    path = tmp_path / "revision.sqlite"
    calendar_raw = _official_calendar_bytes()
    extras = _calendar_extras(
        calendar_raw, start=SEGMENT_START, end=SEGMENT_END
    )
    store = _prepare_store(path)
    _insert_calendar_and_fins(store, ("1001", "1002"))
    snapshots = []
    for day in BUSINESS_DATES:
        snapshots.extend(
            _catalog_rows(
                [
                    _master_payload("1001", day, market="0111"),
                    _master_payload("1002", day, market="0111"),
                ],
                dataset="equities_master",
                stamp=_stamp(day),
            )
        )
    store.upsert("jquants_records", snapshots)
    first = _read_master(store)
    authority = TestSignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    )
    _issue_master_product(
        store,
        authority=authority,
        run_id=1,
        structured=first,
        calendar_raw=calendar_raw,
        extras=extras,
    )
    corrected = []
    for day in BUSINESS_DATES:
        corrected.extend(
            normalize_generic(
                [_master_payload("1001", day, market="0111", scale="TOPIX Large70")],
                dataset="equities_master",
                ingested_at="2023-01-06T12:00:00+09:00",
                available_at="2023-01-06T12:00:00+09:00",
            )
        )
    store.upsert("jquants_records", corrected)
    _issue_master_product(
        store,
        authority=authority,
        run_id=2,
        structured=_read_master(store),
        calendar_raw=calendar_raw,
        extras=extras,
    )
    store.close()
    calendars = _calendar_bodies(calendar_raw)
    conn = _open(path)
    try:
        owned = _strict(conn, calendars)
        by_day = {
            item.decision_date: tuple(
                (member.code, member.scale_category) for member in item.members
            )
            for item in owned.slices
        }
        assert by_day["2023-01-04"] == (
            ("1001", "TOPIX Core30"),
            ("1002", "TOPIX Core30"),
        )
        assert by_day["2023-01-05"] == (
            ("1001", "TOPIX Core30"),
            ("1002", "TOPIX Core30"),
        )
        assert by_day["2023-01-06"] == (
            ("1001", "TOPIX Large70"),
            ("1002", "TOPIX Core30"),
        )
        store = SqliteStore(path)
        unbacked = normalize_generic(
            [_master_payload("1001", "2023-01-05", scale="TOPIX Mid400")],
            dataset="equities_master",
            ingested_at="2023-01-05T12:00:00+09:00",
            available_at="2023-01-05T12:00:00+09:00",
        )[0]
        store._conn.execute(  # noqa: SLF001
            "INSERT INTO jquants_records_revisions ("
            "source,dataset,natural_key,event_time,available_at,ingested_at,"
            "payload,raw_payload) VALUES (?,?,?,?,?,?,?,?)",
            (
                unbacked["source"],
                unbacked["dataset"],
                unbacked["natural_key"],
                unbacked["event_time"],
                unbacked["available_at"],
                unbacked["ingested_at"],
                unbacked["payload"],
                unbacked["raw_payload"],
            ),
        )
        store._conn.commit()  # noqa: SLF001
        store.close()
    finally:
        conn.close()
    conn = _open(path)
    try:
        with pytest.raises(PitError, match="not bound to a verified artifact"):
            _strict(conn, calendars)
    finally:
        conn.close()


def test_old_artifact_requires_every_materialized_version(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    path = tmp_path / "old-artifact-row.sqlite"
    calendar_raw = _official_calendar_bytes()
    extras = _calendar_extras(
        calendar_raw, start=SEGMENT_START, end=SEGMENT_END
    )
    store = _prepare_store(path)
    _insert_calendar_and_fins(store, ("1001",))
    first_rows = []
    for day in BUSINESS_DATES:
        first_rows.extend(
            _catalog_rows(
                [_master_payload("1001", day)],
                dataset="equities_master",
                stamp=_stamp(day),
            )
        )
    store.upsert("jquants_records", first_rows)
    first = _read_master(store)
    authority = TestSignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    )
    _issue_master_product(
        store,
        authority=authority,
        run_id=1,
        structured=first,
        calendar_raw=calendar_raw,
        extras=extras,
    )
    corrected = []
    for day in BUSINESS_DATES:
        corrected.extend(
            normalize_generic(
                [_master_payload("1001", day, scale="TOPIX Large70")],
                dataset="equities_master",
                ingested_at="2023-01-06T12:00:00+09:00",
                available_at="2023-01-06T12:00:00+09:00",
            )
        )
    store.upsert("jquants_records", corrected)
    _issue_master_product(
        store,
        authority=authority,
        run_id=2,
        structured=_read_master(store),
        calendar_raw=calendar_raw,
        extras=extras,
    )
    deleted = store._conn.execute(  # noqa: SLF001
        "DELETE FROM jquants_records_revisions WHERE dataset='equities_master' "
        "AND payload LIKE '%2022-12-30%' AND payload LIKE '%TOPIX Core30%'"
    ).rowcount
    store._conn.commit()  # noqa: SLF001
    store.close()
    assert deleted == 1
    conn = _open(path)
    try:
        with pytest.raises(
            PitError,
            match="not bound to a verified artifact|not materialized|"
            "no usable verified equities_master generation|"
            "no PIT-visible complete artifact|partially PIT-visible",
        ):
            _strict(conn, _calendar_bodies(calendar_raw))
    finally:
        conn.close()


def test_missing_entire_official_date(tmp_path: Path, receipt_ed25519_keys) -> None:
    path = tmp_path / "missing-date.sqlite"
    snapshots = {
        "2022-12-30": [_master_payload("1001", "2022-12-30")],
        "2023-01-04": [_master_payload("1001", "2023-01-04")],
        "2023-01-06": [_master_payload("1001", "2023-01-06")],
    }
    calendars = _seed_complete_master(
        path, receipt_ed25519_keys, snapshots=snapshots
    )
    conn = _open(path)
    try:
        with pytest.raises(PitError, match="official business date is missing"):
            _strict(conn, calendars)
    finally:
        conn.close()


def test_missing_tail_segment_is_not_masked_by_markets_calendar(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    path = tmp_path / "missing-tail.sqlite"
    snapshots = {day: [_master_payload("1001", day)] for day in BUSINESS_DATES}
    calendars = _seed_complete_master(
        path,
        receipt_ed25519_keys,
        snapshots=snapshots,
        period_end="2023-01-09",
    )
    store = SqliteStore(path)
    _insert_calendar_and_fins(
        store,
        ("1001",),
        period_start=PERIOD_START,
        period_end="2023-01-09",
        trading_dates=(*BUSINESS_DATES[1:], "2023-01-09"),
    )
    store.close()
    draft = resolve_universe_day_slices(
        path,
        period_start=PERIOD_START,
        period_end="2023-01-09",
        as_of_for_day=_as_of_for_day(end="2023-01-09"),
    )
    assert draft[-1].decision_date == "2023-01-09"
    assert draft[-1].snapshot_date == "2023-01-06"
    conn = _open(path)
    try:
        with pytest.raises(PitError, match="does not cover source date"):
            _strict(conn, calendars, period_end="2023-01-09")
    finally:
        conn.close()


def test_failed_receipt_is_audit_history(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    path = tmp_path / "failed-audit.sqlite"
    snapshots = {day: [_master_payload("1001", day)] for day in BUSINESS_DATES}
    calendars = _seed_complete_master(
        path, receipt_ed25519_keys, snapshots=snapshots
    )
    store = SqliteStore(path)
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO collection_receipts ("
        "source,dataset,segment_id,segment_start,segment_end,expected_scope,"
        "expected_items,observed_items,raw_page_count,raw_row_count,"
        "structured_row_count,pagination_exhausted,digests_json,run_id,"
        "status,error,checked_at) VALUES ("
        "'jquants','equities_master','failed-audit',?,?, '{}',0,0,0,0,0,0,"
        "'{}',99,'FAILED','audit attempt',?)",
        (SEGMENT_START, SEGMENT_END, CHECKED_AT),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()
    conn = _open(path)
    try:
        owned = _strict(conn, calendars)
    finally:
        conn.close()
    assert _member_codes(owned.slices) == {
        "2023-01-04": ("1001",),
        "2023-01-05": ("1001",),
        "2023-01-06": ("1001",),
    }


def test_monthly_segments_compose_the_source_domain(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    path = tmp_path / "two-months.sqlite"
    dec_raw = _official_calendar_bytes(
        "2022-12-30", "2022-12-31", ("2022-12-30",)
    )
    jan_raw = _official_calendar_bytes(
        "2023-01-01", "2023-01-06", ("2023-01-04", "2023-01-05", "2023-01-06")
    )
    store = _prepare_store(path)
    _insert_calendar_and_fins(store, ("1001",))
    dec_rows = _catalog_rows(
        [_master_payload("1001", "2022-12-30")],
        dataset="equities_master",
        stamp=_stamp("2022-12-30"),
    )
    jan_rows = []
    for day in ("2023-01-04", "2023-01-05", "2023-01-06"):
        jan_rows.extend(
            normalize_generic(
                [_master_payload("1001", day)],
                dataset="equities_master",
                ingested_at=_stamp(day, 16),
                available_at=_stamp(day, 16),
            )
        )
    store.upsert("jquants_records", dec_rows + jan_rows)
    authority = TestSignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    )
    all_rows = _read_master(store)
    _issue_master_product(
        store,
        authority=authority,
        run_id=1,
        structured=[
            row for row in all_rows if str(row["event_time"])[:10] <= "2022-12-31"
        ],
        calendar_raw=dec_raw,
        extras=_calendar_extras(dec_raw, start="2022-12-30", end="2022-12-31"),
        segment_id="2022-12",
        segment_start="2022-12-30",
        segment_end="2022-12-31",
    )
    _issue_master_product(
        store,
        authority=authority,
        run_id=2,
        structured=[
            row for row in all_rows if str(row["event_time"])[:10] >= "2023-01-01"
        ],
        calendar_raw=jan_raw,
        extras=_calendar_extras(jan_raw, start="2023-01-01", end="2023-01-06"),
        segment_id="2023-01",
        segment_start="2023-01-01",
        segment_end="2023-01-06",
    )
    store.close()
    conn = _open(path)
    try:
        owned = _strict(conn, (dec_raw, jan_raw))
    finally:
        conn.close()
    assert owned.proof.seed_snapshot_date == "2022-12-30"
    assert [item.snapshot_date for item in owned.slices] == [
        "2022-12-30",
        "2023-01-04",
        "2023-01-05",
    ]
    assert _member_codes(owned.slices) == {
        "2023-01-04": ("1001",),
        "2023-01-05": ("1001",),
        "2023-01-06": ("1001",),
    }


def test_distinct_full_keysets_are_ambiguous(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    path = tmp_path / "ambiguous-sets.sqlite"
    calendar_run1 = _official_calendar_bytes()
    calendar_run2 = _indented_calendar_bytes(calendar_run1)
    extras1 = _calendar_extras(
        calendar_run1, start=SEGMENT_START, end=SEGMENT_END
    )
    extras2 = _calendar_extras(
        calendar_run2, start=SEGMENT_START, end=SEGMENT_END
    )
    store = _prepare_store(path)
    _insert_calendar_and_fins(store, ("1001", "1003"))
    first_rows = []
    for day in BUSINESS_DATES:
        first_rows.extend(
            _catalog_rows(
                [_master_payload("1001", day)],
                dataset="equities_master",
                stamp=_stamp(day),
            )
        )
    store.upsert("jquants_records", first_rows)
    authority = TestSignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    )
    _issue_master_product(
        store,
        authority=authority,
        run_id=1,
        structured=_read_master(store),
        calendar_raw=calendar_run1,
        extras=extras1,
    )
    added = []
    for day in BUSINESS_DATES:
        added.extend(
            _catalog_rows(
                [_master_payload("1003", day)],
                dataset="equities_master",
                stamp=_stamp(day),
            )
        )
    store.upsert("jquants_records", added)
    _issue_master_product(
        store,
        authority=authority,
        run_id=2,
        structured=_read_master(store),
        calendar_raw=calendar_run2,
        extras=extras2,
    )
    store.close()
    conn = _open(path)
    try:
        with pytest.raises(
            PitError, match="official calendar raw body is missing"
        ):
            _strict(conn, _calendar_bodies(calendar_run2))
        with pytest.raises(PitError, match="ambiguous complete generations"):
            _strict(conn, (calendar_run1, calendar_run2))
    finally:
        conn.close()

    subset_path = tmp_path / "subset-sets.sqlite"
    calendar_raw = _official_calendar_bytes()
    extras = _calendar_extras(
        calendar_raw, start=SEGMENT_START, end=SEGMENT_END
    )
    store = _prepare_store(subset_path)
    _insert_calendar_and_fins(store, ("1001", "1002", "1003"))
    first_rows = []
    for day in BUSINESS_DATES:
        first_rows.extend(
            _catalog_rows(
                [
                    _master_payload("1001", day),
                    _master_payload("1002", day),
                    _master_payload("1003", day),
                ],
                dataset="equities_master",
                stamp=_stamp(day),
            )
        )
    store.upsert("jquants_records", first_rows)
    authority = TestSignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    )
    _issue_master_product(
        store,
        authority=authority,
        run_id=1,
        structured=_read_master(store),
        calendar_raw=calendar_raw,
        extras=extras,
    )
    store.upsert(
        "jquants_records",
        normalize_generic(
            [
                _master_payload("1001", day, scale="TOPIX Large70")
                for day in BUSINESS_DATES
            ],
            dataset="equities_master",
            ingested_at="2023-01-06T12:00:00+09:00",
            available_at="2023-01-06T12:00:00+09:00",
        ),
    )
    subset_rows = [
        row
        for row in _read_master(store)
        if '"Code":"1003"' not in str(row["payload"])
    ]
    _issue_master_product(
        store,
        authority=authority,
        run_id=2,
        structured=subset_rows,
        calendar_raw=calendar_raw,
        extras=extras,
    )
    store.close()
    conn = _open(subset_path)
    try:
        with pytest.raises(PitError, match="partially PIT-visible"):
            _strict(conn, _calendar_bodies(calendar_raw))
    finally:
        conn.close()


def test_poisoned_unrelated_full_segment_row_is_rejected(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    path = tmp_path / "poison.sqlite"
    snapshots = {day: [_master_payload("1001", day)] for day in BUSINESS_DATES}
    calendars = _seed_complete_master(
        path,
        receipt_ed25519_keys,
        snapshots=snapshots,
        extra_unrelated=_master_payload("9999", "2022-12-30"),
        poison_unrelated=True,
    )
    conn = _open(path)
    try:
        with pytest.raises(
            PitError,
            match="not materialized|no usable verified equities_master generation",
        ):
            _strict(conn, calendars)
    finally:
        conn.close()


def test_missing_run_rejects_verified_receipt(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    path = tmp_path / "missing-run.sqlite"
    snapshots = {day: [_master_payload("1001", day)] for day in BUSINESS_DATES}
    calendars = _seed_complete_master(
        path, receipt_ed25519_keys, snapshots=snapshots
    )
    store = SqliteStore(path)
    store._conn.execute("DELETE FROM ingestion_run_log")  # noqa: SLF001
    store._conn.commit()  # noqa: SLF001
    store.close()
    conn = _open(path)
    try:
        with pytest.raises(PitError, match="no usable verified equities_master generation"):
            _strict(conn, calendars)
    finally:
        conn.close()


def test_draft_output_unchanged_without_complete_operation(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    path = tmp_path / "draft.sqlite"
    snapshots = {day: [_master_payload("1001", day)] for day in BUSINESS_DATES}
    _seed_complete_master(path, receipt_ed25519_keys, snapshots=snapshots)
    draft = resolve_universe_day_slices(
        path,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        as_of_for_day=_as_of_for_day(),
    )
    assert [item.snapshot_date for item in draft] == [
        "2023-01-04",
        "2023-01-05",
        "2023-01-06",
    ]
    assert all(
        tuple(member.code for member in item.members) == ("1001",) for item in draft
    )
