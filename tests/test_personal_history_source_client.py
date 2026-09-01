from __future__ import annotations

from datetime import date, timedelta
from email.message import EmailMessage
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
import urllib.error
import urllib.request

import pytest

from data_contracts.identity import canonical_json
from ingestion.personal_history import (
    PERSONAL_HISTORY_DATASETS,
    PersonalHistoryError,
    PersonalHistoryHydrator,
    _page_evidence,
    build_personal_history_plan,
)
from storage.sqlite_store import SqliteStore

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "platform"
    / "workers"
    / "research-mass-eval"
    / "container"
    / "personal_history_source_client.py"
)
SPEC = importlib.util.spec_from_file_location(
    "personal_history_source_client", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
client_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = client_mod
SPEC.loader.exec_module(client_mod)


class _Response(io.BytesIO):
    def __init__(self, payload: dict | bytes, headers: dict[str, str], status: int = 200):
        body = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload, separators=(",", ":")).encode()
        )
        super().__init__(body)
        self.status = status
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def _calendar_month(month: str) -> list[dict]:
    start = date.fromisoformat(f"{month}-01")
    rows = []
    current = start
    while current.month == start.month:
        rows.append(
            {
                "Date": current.isoformat(),
                "HolidayDivision": "1" if current.weekday() < 5 else "0",
            }
        )
        current += timedelta(days=1)
    return rows


def _fins_month(month: str) -> list[dict]:
    return [
        {"Code": "1001", "DiscDate": f"{month}-02", "DiscNo": "a", "EarningsPerShare": 1},
        {"Code": "1002", "DiscDate": f"{month}-03", "DiscNo": "b", "EarningsPerShare": 2},
    ]


def test_python_generated_headers_are_the_closed_transport_set() -> None:
    body = b'{"dataset_id":"markets_calendar"}'
    request = client_mod.build_history_source_request(body)
    handler = urllib.request.AbstractHTTPHandler()
    handler.parent = urllib.request.OpenerDirector()
    handler.parent.addheaders = []
    finalized = handler.do_request_(request)
    headers = {key.lower(): value for key, value in finalized.header_items()}
    expected = client_mod.closed_history_source_headers(
        content_length=len(body), host="history.source"
    )
    assert headers == expected
    assert headers["user-agent"] == "quant-personal-history/v13"
    assert "authorization" not in headers


def test_spool_fetches_each_month_once_and_keeps_real_page_digests(
    tmp_path: Path,
) -> None:
    posted: list[dict] = []
    bodies: dict[str, bytes] = {}

    class Opener:
        def urlopen(self, request, timeout=120):
            assert dict(request.header_items())
            payload = json.loads(request.data.decode())
            posted.append(payload)
            month = payload["segment_id"]
            dataset = payload["dataset_id"]
            if dataset == "markets_calendar":
                rows = _calendar_month(month)
            else:
                rows = _fins_month(month)
            raw = json.dumps({"data": rows}, separators=(",", ":")).encode()
            bodies[f"{dataset}:{month}"] = raw
            return _Response(
                raw,
                {
                    "x-quant-acquisition-evidence-state": "RAW_PAGE",
                    "x-quant-acquisition-pagination-state": "EXHAUSTED",
                    "x-quant-acquisition-continuation": "NONE",
                    "x-quant-acquisition-slice-date": "NONE",
                },
            )

    client = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=tmp_path / "spool.sqlite",
        opener=Opener(),
    )
    first = client.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    second = client.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-11", "to": "2024-03-11"}
    )
    assert [row["Date"] for row in first.rows] == [
        "2024-03-10",
        "2024-03-11",
        "2024-03-12",
    ]
    assert [row["Date"] for row in second.rows] == ["2024-03-11"]
    assert client.fetch_calls == 1
    assert client._live_bodies == 0
    source_body = bodies["markets_calendar:2024-03"]
    assert first.pages[0].body_digest == "sha256:" + hashlib.sha256(source_body).hexdigest()
    assert first.pages[0].row_count == 31
    assert first.pages[0].response_body is None
    assert first.pages[0].evidence_state == "RAW_PAGE"
    assert first.selection is not None
    assert first.selection.selected_row_count == 3
    assert first.selection.source_row_count == 31
    assert first.pages[0].request_params["from"] == "2024-03-01"
    evidence, _digest, selection = _page_evidence(first)
    assert evidence[0]["sha256"] == hashlib.sha256(source_body).hexdigest()
    assert selection is not None
    assert selection["selected_row_count"] == 3

    fins_one = client.fetch_dataset_evidenced("fins_summary", code="1001")
    fins_two = client.fetch_dataset_evidenced("fins_summary", code="1002")
    months = {
        item["segment_id"]
        for item in posted
        if item["dataset_id"] == "fins_summary"
    }
    assert client.fetch_calls == 1 + len(months)
    again_one = client.fetch_dataset_evidenced("fins_summary", code="1001")
    assert client.fetch_calls == 1 + len(months)
    assert [row["Code"] for row in fins_one.rows] == ["1001"] * len(fins_one.rows)
    assert [row["Code"] for row in fins_two.rows] == ["1002"] * len(fins_two.rows)
    assert again_one.rows == fins_one.rows
    client.close()


def test_missing_day_does_not_invent_an_http_page(tmp_path: Path) -> None:
    class Opener:
        def urlopen(self, request, timeout=120):
            raw = json.dumps({"data": []}, separators=(",", ":")).encode()
            return _Response(
                raw,
                {
                    "x-quant-acquisition-evidence-state": "RAW_PAGE",
                    "x-quant-acquisition-pagination-state": "EXHAUSTED",
                    "x-quant-acquisition-continuation": "NONE",
                    "x-quant-acquisition-slice-date": "2024-03-01",
                },
            )

    client = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=tmp_path / "spool.sqlite",
        opener=Opener(),
    )
    fetched = client.fetch_dataset_evidenced("equities_bars_daily", date="2024-03-15")
    assert fetched.rows == ()
    assert fetched.pages[0].slice_date == "2024-03-01"
    assert fetched.selection is not None
    assert fetched.selection.selected_row_count == 0
    assert fetched.selection.scanned_page_digests == (fetched.pages[0].body_digest,)
    with pytest.raises(PersonalHistoryError, match="not a personal history dataset"):
        client.fetch_dataset_evidenced("fins_details", date="2024-03-01")
    client.close()


def test_empty_actual_day_page_is_kept_without_inventing_bytes(tmp_path: Path) -> None:
    raw = json.dumps({"data": []}, separators=(",", ":")).encode()

    class Opener:
        def urlopen(self, request, timeout=120):
            return _Response(
                raw,
                {
                    "x-quant-acquisition-evidence-state": "RAW_PAGE",
                    "x-quant-acquisition-pagination-state": "EXHAUSTED",
                    "x-quant-acquisition-continuation": "NONE",
                    "x-quant-acquisition-slice-date": "2024-03-15",
                },
            )

    client = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=tmp_path / "spool.sqlite",
        opener=Opener(),
    )
    fetched = client.fetch_dataset_evidenced("equities_bars_daily", date="2024-03-15")
    assert fetched.rows == ()
    assert fetched.pages[0].row_count == 0
    assert fetched.pages[0].response_status == 200
    assert fetched.pages[0].slice_date == "2024-03-15"
    assert fetched.pages[0].body_digest == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert fetched.pages[0].response_body is None
    evidence, _, selection = _page_evidence(fetched)
    assert evidence[0]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert selection is not None
    assert selection["selected_row_count"] == 0
    client.close()


def test_restart_reuses_ephemeral_spool_without_refetch(tmp_path: Path) -> None:
    calls = {"n": 0}
    spool = tmp_path / "spool.sqlite"

    class Opener:
        def urlopen(self, request, timeout=120):
            calls["n"] += 1
            month = json.loads(request.data.decode())["segment_id"]
            raw = json.dumps(
                {"data": _calendar_month(month)}, separators=(",", ":")
            ).encode()
            return _Response(
                raw,
                {
                    "x-quant-acquisition-evidence-state": "RAW_PAGE",
                    "x-quant-acquisition-pagination-state": "EXHAUSTED",
                    "x-quant-acquisition-continuation": "NONE",
                    "x-quant-acquisition-slice-date": "NONE",
                },
            )

    first = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=spool,
        opener=Opener(),
    )
    first.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    first.close()
    assert calls["n"] == 1
    second = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=spool,
        opener=Opener(),
    )
    selected = second.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-11", "to": "2024-03-11"}
    )
    assert calls["n"] == 1
    assert second.fetch_calls == 0
    assert [row["Date"] for row in selected.rows] == ["2024-03-11"]
    second.close()


def test_hydrator_records_source_and_selection_evidence(tmp_path: Path) -> None:
    class Opener:
        def urlopen(self, request, timeout=120):
            payload = json.loads(request.data.decode())
            month = payload["segment_id"]
            raw = json.dumps(
                {"data": _calendar_month(month)}, separators=(",", ":")
            ).encode()
            return _Response(
                raw,
                {
                    "x-quant-acquisition-evidence-state": "RAW_PAGE",
                    "x-quant-acquisition-pagination-state": "EXHAUSTED",
                    "x-quant-acquisition-continuation": "NONE",
                    "x-quant-acquisition-slice-date": "NONE",
                },
            )

    client = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2025-01-08",
        spool_path=tmp_path / "spool.sqlite",
        opener=Opener(),
    )
    plan = build_personal_history_plan(
        period_start="2025-01-06",
        period_end="2025-01-08",
        lookback_sessions=1,
        calendar_window_days=366,
        today=date(2025, 2, 1),
    )
    store = SqliteStore(tmp_path / "history.sqlite")
    hydrator = PersonalHistoryHydrator(client=client, store=store, plan=plan)
    hydrator._hydrate_calendar()
    row = store._conn.execute(
        "SELECT page_evidence_json, selection_evidence_json, rows_fetched "
        "FROM personal_history_segments WHERE dataset='markets_calendar' "
        "LIMIT 1"
    ).fetchone()
    pages = json.loads(row["page_evidence_json"])
    selection = json.loads(row["selection_evidence_json"])
    source_row_count = sum(int(page["row_count"]) for page in pages)
    assert source_row_count == selection["source_row_count"]
    assert source_row_count > row["rows_fetched"]
    assert selection["selected_row_count"] == row["rows_fetched"]
    assert pages[0]["request_params"]["from"].endswith("-01")
    assert pages[0]["evidence_state"] == "RAW_PAGE"
    assert "HolidayDivision" not in json.dumps(pages)
    assert selection["scanned_page_digests"] == [page["sha256"] for page in pages]
    store.close()
    client.close()


def _page_headers(state: str, continuation: str, slice_date: str) -> dict[str, str]:
    return {
        "x-quant-acquisition-evidence-state": "RAW_PAGE",
        "x-quant-acquisition-pagination-state": state,
        "x-quant-acquisition-continuation": continuation,
        "x-quant-acquisition-slice-date": slice_date,
    }


def test_partial_paginated_month_is_cleared_and_refetched(tmp_path: Path) -> None:
    calls: list[str | None] = []

    class FailSecond:
        def urlopen(self, request, timeout=120):
            token = json.loads(request.data.decode()).get("continuation_token")
            calls.append(token)
            if token is None:
                raw = json.dumps(
                    {"data": [{"Code": "1001", "Date": "2024-03-01"}]},
                    separators=(",", ":"),
                ).encode()
                return _Response(raw, _page_headers("CONTINUATION", "cursor-2", "2024-03-01"))
            raise RuntimeError("page-2 failed")

    class Complete:
        def urlopen(self, request, timeout=120):
            token = json.loads(request.data.decode()).get("continuation_token")
            calls.append(token)
            if token is None:
                raw = json.dumps(
                    {"data": [{"Code": "1001", "Date": "2024-03-01"}]},
                    separators=(",", ":"),
                ).encode()
                return _Response(raw, _page_headers("CONTINUATION", "cursor-2", "2024-03-01"))
            raw = json.dumps(
                {"data": [{"Code": "1002", "Date": "2024-03-02"}]},
                separators=(",", ":"),
            ).encode()
            return _Response(raw, _page_headers("EXHAUSTED", "NONE", "2024-03-02"))

    spool = tmp_path / "spool.sqlite"
    first = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=spool,
        opener=FailSecond(),
    )
    with pytest.raises(RuntimeError, match="page-2 failed"):
        first.fetch_dataset_evidenced("equities_bars_daily", date="2024-03-01")
    assert first.spool.has_month("equities_bars_daily", "2024-03") is False
    first.close()
    failed_calls = list(calls)
    second = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=spool,
        opener=Complete(),
    )
    fetched = second.fetch_dataset_evidenced("equities_bars_daily", date="2024-03-01")
    assert second.fetch_calls == 2
    assert calls[len(failed_calls) :] == [None, "cursor-2"]
    assert [row["Code"] for row in fetched.rows] == ["1001"]
    assert len(fetched.pages) == 2
    assert fetched.selection is not None
    assert fetched.selection.source_row_count == 2
    assert len(fetched.selection.scanned_page_digests) == 2
    assert fetched.selection.selected_row_count == 1
    second.close()


def test_crash_after_exhausted_before_complete_refetches(tmp_path: Path) -> None:
    class Opener:
        def urlopen(self, request, timeout=120):
            raw = json.dumps(
                {"data": [{"Code": "1001", "Date": "2024-03-01"}]},
                separators=(",", ":"),
            ).encode()
            return _Response(raw, _page_headers("EXHAUSTED", "NONE", "2024-03-01"))

    spool = tmp_path / "spool.sqlite"
    first = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=spool,
        opener=Opener(),
    )
    first._finish_month = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("crash before COMPLETE")
    )
    with pytest.raises(RuntimeError, match="crash before COMPLETE"):
        first.fetch_dataset_evidenced("equities_bars_daily", date="2024-03-01")
    assert first.spool.has_month("equities_bars_daily", "2024-03") is False
    first.close()
    second = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=spool,
        opener=Opener(),
    )
    fetched = second.fetch_dataset_evidenced("equities_bars_daily", date="2024-03-01")
    assert second.fetch_calls == 1
    assert [row["Code"] for row in fetched.rows] == ["1001"]
    assert second.spool.has_month("equities_bars_daily", "2024-03") is True
    second.close()


def test_zero_match_fins_binds_all_scanned_pages(tmp_path: Path) -> None:
    class Opener:
        def urlopen(self, request, timeout=120):
            month = json.loads(request.data.decode())["segment_id"]
            raw = json.dumps(
                {"data": _fins_month(month)}, separators=(",", ":")
            ).encode()
            return _Response(raw, _page_headers("EXHAUSTED", "NONE", "NONE"))

    client = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=tmp_path / "spool.sqlite",
        opener=Opener(),
    )
    fetched = client.fetch_dataset_evidenced("fins_summary", code="9999")
    assert fetched.rows == ()
    assert len(fetched.pages) == client.fetch_calls
    assert fetched.selection is not None
    assert fetched.selection.selected_row_count == 0
    assert fetched.selection.source_row_count == sum(page.row_count for page in fetched.pages)
    assert fetched.selection.source_row_count > 0
    assert fetched.selection.scanned_page_digests == tuple(
        page.body_digest for page in fetched.pages
    )
    assert fetched.selection.contributing_page_digests == ()
    evidence, _, selection = _page_evidence(fetched)
    assert len(evidence) == len(fetched.pages)
    assert selection["selected_row_count"] == 0
    client.close()


def test_match_on_first_page_still_scans_later_pages(tmp_path: Path) -> None:
    class Opener:
        def urlopen(self, request, timeout=120):
            token = json.loads(request.data.decode()).get("continuation_token")
            if token is None:
                raw = json.dumps(
                    {"data": [{"Code": "1001", "Date": "2024-03-01"}]},
                    separators=(",", ":"),
                ).encode()
                return _Response(raw, _page_headers("CONTINUATION", "cursor-2", "2024-03-01"))
            raw = json.dumps(
                {"data": [{"Code": "1002", "Date": "2024-03-02"}]},
                separators=(",", ":"),
            ).encode()
            return _Response(raw, _page_headers("EXHAUSTED", "NONE", "2024-03-02"))

    client = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=tmp_path / "spool.sqlite",
        opener=Opener(),
    )
    fetched = client.fetch_dataset_evidenced("equities_bars_daily", date="2024-03-01")
    assert [row["Code"] for row in fetched.rows] == ["1001"]
    assert len(fetched.pages) == 2
    assert fetched.selection is not None
    assert fetched.selection.source_row_count == 2
    assert fetched.selection.selected_row_count == 1
    assert len(fetched.selection.contributing_page_digests) == 1
    assert len(fetched.selection.scanned_page_digests) == 2
    client.close()


def test_omitted_scanned_page_digest_is_rejected() -> None:
    page = client_mod.SourcePage(
        request_path="/v2/fins/summary",
        request_params={"from": "2024-03-01", "to": "2024-03-31"},
        response_status=200,
        body_digest="sha256:" + "a" * 64,
        row_count=2,
    )
    later = client_mod.SourcePage(
        request_path="/v2/fins/summary",
        request_params={"from": "2024-04-01", "to": "2024-04-30"},
        response_status=200,
        body_digest="sha256:" + "b" * 64,
        row_count=2,
    )
    fetch = client_mod._Fetch(
        rows=(),
        pages=(page, later),
        selection=client_mod.SelectionEvidence(
            query={"code": "9999"},
            selected_row_count=0,
            selected_digest="sha256:" + hashlib.sha256(b"[]").hexdigest(),
            source_row_count=4,
            scanned_page_digests=(page.body_digest,),
            completion_digest="sha256:" + "c" * 64,
            contributing_page_digests=(),
        ),
    )
    with pytest.raises(PersonalHistoryError, match="scanned pages"):
        _page_evidence(fetch)


def test_spool_page_bound_fails_with_exact_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client_mod, "MAX_SPOOL_PAGES", 1)

    class Opener:
        def urlopen(self, request, timeout=120):
            month = json.loads(request.data.decode())["segment_id"]
            raw = json.dumps(
                {"data": _calendar_month(month)}, separators=(",", ":")
            ).encode()
            return _Response(raw, _page_headers("EXHAUSTED", "NONE", "NONE"))

    client = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-04-30",
        spool_path=tmp_path / "spool.sqlite",
        opener=Opener(),
    )
    client.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-01", "to": "2024-03-02"}
    )
    with pytest.raises(PersonalHistoryError, match="page bound exceeded"):
        client.fetch_dataset_evidenced(
            "markets_calendar", **{"from": "2024-03-01", "to": "2024-04-02"}
        )
    client.close()


def _spool_sidecar_sizes(path: Path) -> tuple[int, int, int]:
    wal = Path(str(path) + "-wal")
    shm = Path(str(path) + "-shm")
    return (
        path.stat().st_size if path.exists() else 0,
        wal.stat().st_size if wal.exists() else 0,
        shm.stat().st_size if shm.exists() else 0,
    )


def _large_spool_rows(count: int = 800, payload_bytes: int = 2048) -> list[dict]:
    blob = "x" * payload_bytes
    return [
        {
            "Code": f"{index:04d}",
            "Date": "2024-03-01",
            "Payload": blob,
        }
        for index in range(count)
    ]


def _write_committed_spool_page(
    spool: client_mod.AcquisitionSpool, rows: list[dict]
) -> None:
    spool.begin_month(
        "equities_bars_daily",
        "2024-03",
        {"dataset_id": "equities_bars_daily", "segment_id": "2024-03"},
    )
    spool.record_page(
        dataset="equities_bars_daily",
        month="2024-03",
        page_ordinal=0,
        slice_date="2024-03-01",
        body_digest="sha256:" + "a" * 64,
        row_count=len(rows),
        request_path="/v1/equities/bars/daily",
        request_params={"date": "2024-03-01"},
        response_status=200,
        pagination_in=None,
        pagination_out=None,
        evidence_state="RAW_PAGE",
        rows=rows,
    )


def _verified_fins_cache_month(rows: list[dict]):
    cache_mod = sys.modules["personal_acquisition_cache"]
    encoded = [canonical_json(dict(row)) for row in rows]
    return cache_mod.VerifiedCacheMonth(
        identity={"dataset_id": "fins_summary", "segment_id": "2024-03"},
        identity_hex="ab" * 32,
        environment="production",
        dataset="fins_summary",
        month="2024-03",
        completion_digest="sha256:" + "b" * 64,
        page_count=1,
        pages=(
            {
                "dataset": "fins_summary",
                "month": "2024-03",
                "page_ordinal": 0,
                "slice_date": None,
                "body_digest": "sha256:" + "c" * 64,
                "row_count": len(rows),
                "request_path": "/v2/fins/summary",
                "request_params_json": canonical_json(
                    {"from": "2024-03-01", "to": "2024-03-31"}
                ),
                "response_status": 200,
                "pagination_in": None,
                "pagination_out": None,
                "evidence_state": "RAW_PAGE",
            },
        ),
        rows=tuple(
            {
                "dataset": "fins_summary",
                "month": "2024-03",
                "page_ordinal": 0,
                "row_index": index,
                "code": row["Code"],
                "row_date": row["Date"],
                "row_json": encoded[index],
            }
            for index, row in enumerate(rows)
        ),
    )


def test_retained_checkpointed_wal_is_reclaimed_at_committed_capacity_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spool = client_mod.AcquisitionSpool(tmp_path / "spool.sqlite")
    spool._conn.execute("PRAGMA wal_autocheckpoint=0")
    spool._checkpoint_committed_wal = lambda: None
    _write_committed_spool_page(spool, _large_spool_rows())
    busy, _log, checkpointed = spool._conn.execute(
        "PRAGMA wal_checkpoint(PASSIVE)"
    ).fetchone()
    assert busy == 0
    assert checkpointed > 0
    main, wal, shm = _spool_sidecar_sizes(spool.path)
    pages, usage = spool.usage()
    assert pages == 1
    assert wal > 0
    assert usage == main + wal + shm
    retained_bound = main + shm + (wal // 2)
    assert main + shm < retained_bound < usage
    monkeypatch.setattr(client_mod, "MAX_SPOOL_BYTES", retained_bound)
    with pytest.raises(PersonalHistoryError, match="byte bound exceeded"):
        spool.guard_bounds()
    spool._checkpoint_committed_wal = (
        lambda: client_mod.AcquisitionSpool._checkpoint_committed_wal(spool)
    )
    spool.guard_bounds()
    main_after, wal_after, shm_after = _spool_sidecar_sizes(spool.path)
    _pages_after, usage_after = spool.usage()
    assert wal_after == 0
    assert usage_after == main_after + wal_after + shm_after
    assert usage_after <= retained_bound
    spool.close()


def test_busy_reader_blocks_truncate_and_fails_closed(tmp_path: Path) -> None:
    spool = client_mod.AcquisitionSpool(tmp_path / "spool.sqlite")
    _write_committed_spool_page(spool, _large_spool_rows(count=8, payload_bytes=64))
    spool._conn.execute("PRAGMA busy_timeout=0")
    reader = sqlite3.connect(str(spool.path), timeout=0)
    try:
        reader.execute("BEGIN")
        assert reader.execute("SELECT COUNT(*) FROM source_pages").fetchone()[0] == 1
        spool.begin_month(
            "equities_bars_daily",
            "2024-04",
            {"dataset_id": "equities_bars_daily", "segment_id": "2024-04"},
        )
        _main, wal, _shm = _spool_sidecar_sizes(spool.path)
        assert wal > 0
        with pytest.raises(
            PersonalHistoryError, match="could not acquire a safe lock"
        ):
            spool.guard_bounds()
    finally:
        reader.close()
    spool.guard_bounds()
    _main_after, wal_after, _shm_after = _spool_sidecar_sizes(spool.path)
    assert wal_after == 0
    spool.close()


def test_committed_cache_import_truncates_wal_and_keeps_true_byte_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cached = _verified_fins_cache_month(_large_spool_rows())
    spool = client_mod.AcquisitionSpool(tmp_path / "spool.sqlite")
    spool._conn.execute("PRAGMA wal_autocheckpoint=0")
    spool.import_complete_month(cached)
    main, wal, shm = _spool_sidecar_sizes(spool.path)
    pages, usage = spool.usage()
    assert pages == 1
    assert wal == 0
    assert usage == main + wal + shm
    monkeypatch.setattr(client_mod, "MAX_SPOOL_BYTES", usage - 1)
    with pytest.raises(PersonalHistoryError, match="byte bound exceeded"):
        spool.guard_bounds()
    monkeypatch.setattr(client_mod, "MAX_SPOOL_BYTES", usage)
    spool.guard_bounds()
    spool.close()


def _two_page_opener():
    class Opener:
        def urlopen(self, request, timeout=120):
            token = json.loads(request.data.decode()).get("continuation_token")
            if token is None:
                raw = json.dumps(
                    {"data": [{"Code": "1001", "Date": "2024-03-01"}]},
                    separators=(",", ":"),
                ).encode()
                return _Response(raw, _page_headers("CONTINUATION", "cursor-2", "2024-03-01"))
            raw = json.dumps(
                {"data": [{"Code": "1002", "Date": "2024-03-02"}]},
                separators=(",", ":"),
            ).encode()
            return _Response(raw, _page_headers("EXHAUSTED", "NONE", "2024-03-02"))

    return Opener()


def _two_page_client(tmp_path: Path):
    client = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=tmp_path / "spool.sqlite",
        opener=_two_page_opener(),
    )
    fetched = client.fetch_dataset_evidenced("equities_bars_daily", date="2024-03-01")
    assert len(fetched.pages) == 2
    return client


def _wrap_verified_complete_month(client):
    calls: list[tuple[str, str]] = []
    original = client.spool.verified_complete_month

    def wrapped(dataset: str, month: str):
        calls.append((dataset, month))
        return original(dataset, month)

    client.spool.verified_complete_month = wrapped
    return calls


def _wrap_assert_verified_complete(client):
    scans: list[tuple[str, str]] = []
    original = client.spool._assert_verified_complete

    def wrapped(state, pages, dataset: str, month: str):
        scans.append((dataset, month))
        return original(state, pages, dataset, month)

    client.spool._assert_verified_complete = wrapped
    return scans


def _fins_client(tmp_path: Path, *, spool_path: Path | None = None):
    class Opener:
        def urlopen(self, request, timeout=120):
            month = json.loads(request.data.decode())["segment_id"]
            raw = json.dumps(
                {"data": _fins_month(month)}, separators=(",", ":")
            ).encode()
            return _Response(raw, _page_headers("EXHAUSTED", "NONE", "NONE"))

    return client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=spool_path or (tmp_path / "spool.sqlite"),
        opener=Opener(),
    )


def test_verified_complete_month_accepts_untouched_pages(tmp_path: Path) -> None:
    client = _two_page_client(tmp_path)
    pages = client.spool.verified_complete_month("equities_bars_daily", "2024-03")
    assert pages is not None and len(pages) == 2
    fetched = client.fetch_dataset_evidenced("equities_bars_daily", date="2024-03-01")
    assert client.fetch_calls == 2
    assert len(fetched.pages) == 2
    client.close()


def test_deleted_page_is_cleared_and_refetched(tmp_path: Path) -> None:
    client = _two_page_client(tmp_path)
    client.spool._conn.execute(
        "DELETE FROM source_pages WHERE dataset=? AND month=? AND page_ordinal=1",
        ("equities_bars_daily", "2024-03"),
    )
    client.spool._conn.execute(
        "DELETE FROM source_rows WHERE dataset=? AND month=? AND page_ordinal=1",
        ("equities_bars_daily", "2024-03"),
    )
    client.spool._conn.commit()
    assert client.spool.has_month("equities_bars_daily", "2024-03") is False
    fetched = client.fetch_dataset_evidenced("equities_bars_daily", date="2024-03-01")
    assert client.fetch_calls == 4
    assert len(fetched.pages) == 2
    client.close()


def test_broken_pagination_and_dangling_cursor_are_rejected(tmp_path: Path) -> None:
    client = _two_page_client(tmp_path)
    client.spool._conn.execute(
        "UPDATE source_pages SET pagination_in='wrong' "
        "WHERE dataset=? AND month=? AND page_ordinal=1",
        ("equities_bars_daily", "2024-03"),
    )
    client.spool._conn.commit()
    assert client.spool.verified_complete_month("equities_bars_daily", "2024-03") is None
    client.close()

    client = _two_page_client(tmp_path)
    client.spool._conn.execute(
        "UPDATE source_pages SET pagination_out='cursor-3' "
        "WHERE dataset=? AND month=? AND page_ordinal=1",
        ("equities_bars_daily", "2024-03"),
    )
    client.spool._conn.commit()
    assert client.spool.has_month("equities_bars_daily", "2024-03") is False
    client.close()


def test_forged_completion_digest_and_mutated_page_are_rejected(tmp_path: Path) -> None:
    client = _two_page_client(tmp_path)
    client.spool._conn.execute(
        "UPDATE month_state SET completion_digest=? WHERE dataset=? AND month=?",
        ("sha256:" + "f" * 64, "equities_bars_daily", "2024-03"),
    )
    client.spool._conn.commit()
    assert client.spool.has_month("equities_bars_daily", "2024-03") is False
    client.close()

    client = _two_page_client(tmp_path)
    client.spool._conn.execute(
        "UPDATE source_pages SET body_digest=? "
        "WHERE dataset=? AND month=? AND page_ordinal=0",
        ("sha256:" + "a" * 64, "equities_bars_daily", "2024-03"),
    )
    client.spool._conn.commit()
    assert client.spool.verified_complete_month("equities_bars_daily", "2024-03") is None
    client.close()

    client = _two_page_client(tmp_path)
    client.spool._conn.execute(
        "UPDATE source_pages SET row_count=99 "
        "WHERE dataset=? AND month=? AND page_ordinal=0",
        ("equities_bars_daily", "2024-03"),
    )
    client.spool._conn.commit()
    assert client.spool.has_month("equities_bars_daily", "2024-03") is False
    client.close()


def test_duplicate_and_gapped_ordinals_are_rejected(tmp_path: Path) -> None:
    client = _two_page_client(tmp_path)
    client.spool._conn.execute(
        "UPDATE source_pages SET page_ordinal=2 "
        "WHERE dataset=? AND month=? AND page_ordinal=1",
        ("equities_bars_daily", "2024-03"),
    )
    client.spool._conn.commit()
    assert client.spool.verified_complete_month("equities_bars_daily", "2024-03") is None
    client.close()

    client = _two_page_client(tmp_path)
    state = client.spool._conn.execute(
        "SELECT * FROM month_state WHERE dataset=? AND month=?",
        ("equities_bars_daily", "2024-03"),
    ).fetchone()
    pages = client.spool._conn.execute(
        "SELECT * FROM source_pages WHERE dataset=? AND month=? ORDER BY page_ordinal",
        ("equities_bars_daily", "2024-03"),
    ).fetchall()
    duplicated = [pages[0], pages[0]]
    with pytest.raises(PersonalHistoryError, match="contiguous"):
        client.spool._assert_verified_complete(
            state, duplicated, "equities_bars_daily", "2024-03"
        )
    client.close()


def test_fins_codes_reuse_verified_source_page_scan(tmp_path: Path) -> None:
    client = _fins_client(tmp_path)
    verifies = _wrap_verified_complete_month(client)
    scans = _wrap_assert_verified_complete(client)
    progress = {"n": 0}
    original_progress = client._refresh_progress

    def wrapped_progress() -> None:
        progress["n"] += 1
        original_progress()

    client._refresh_progress = wrapped_progress

    first = client.fetch_dataset_evidenced("fins_summary", code="1001")
    after_first_verifies = len(verifies)
    after_first_scans = len(scans)
    after_first_progress = progress["n"]
    assert after_first_scans > 0
    assert after_first_verifies >= after_first_scans

    second = client.fetch_dataset_evidenced("fins_summary", code="1002")
    assert len(verifies) == after_first_verifies
    assert len(scans) == after_first_scans
    assert progress["n"] == after_first_progress
    assert client.fetch_calls == after_first_scans

    assert first.selection is not None and second.selection is not None
    assert [row["Code"] for row in first.rows] == ["1001"] * len(first.rows)
    assert [row["Code"] for row in second.rows] == ["1002"] * len(second.rows)
    assert first.rows != second.rows
    assert first.selection.selected_digest != second.selection.selected_digest
    assert first.selection.query == {"code": "1001"}
    assert second.selection.query == {"code": "1002"}
    assert first.selection.selected_row_count == len(first.rows)
    assert second.selection.selected_row_count == len(second.rows)
    assert first.selection.scanned_page_digests == second.selection.scanned_page_digests
    assert first.selection.completion_digest == second.selection.completion_digest
    assert first.selection.source_row_count == second.selection.source_row_count
    assert tuple(page.body_digest for page in first.pages) == tuple(
        page.body_digest for page in second.pages
    )
    assert first.selection.contributing_page_digests
    assert second.selection.contributing_page_digests
    again = client.fetch_dataset_evidenced("fins_summary", code="1001")
    assert again.rows == first.rows
    assert again.selection == first.selection
    _, _, first_selection = _page_evidence(first)
    _, _, second_selection = _page_evidence(second)
    assert first_selection is not None and second_selection is not None
    assert first_selection["scanned_page_digests"] == second_selection["scanned_page_digests"]
    assert first_selection["completion_digest"] == second_selection["completion_digest"]
    assert first_selection["source_row_count"] == second_selection["source_row_count"]
    assert first_selection["selected_digest"] != second_selection["selected_digest"]
    client.close()


def test_incomplete_or_tampered_month_fails_before_cache_creation(
    tmp_path: Path,
) -> None:
    client = _fins_client(tmp_path)
    client.spool.begin_month(
        "fins_summary",
        "2024-03",
        {"dataset_id": "fins_summary", "segment_id": "2024-03"},
    )
    verifies = _wrap_verified_complete_month(client)
    assert client.spool._cached_verified_month("fins_summary", "2024-03") is None
    assert ("fins_summary", "2024-03") not in client.spool._verified_pages
    incomplete_calls = len(verifies)
    assert incomplete_calls == 1
    assert client.spool._cached_verified_month("fins_summary", "2024-03") is None
    assert len(verifies) == incomplete_calls + 1
    assert ("fins_summary", "2024-03") not in client.spool._verified_pages
    client.close()

    seeded = _two_page_client(tmp_path / "tamper")
    spool_path = seeded.spool.path
    seeded.close()
    tampered = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=spool_path,
        opener=_two_page_opener(),
    )
    tampered.spool._conn.execute(
        "UPDATE month_state SET completion_digest=? WHERE dataset=? AND month=?",
        ("sha256:" + "f" * 64, "equities_bars_daily", "2024-03"),
    )
    tampered.spool._conn.commit()
    tamper_verifies = _wrap_verified_complete_month(tampered)
    assert tampered.spool._cached_verified_month("equities_bars_daily", "2024-03") is None
    assert ("equities_bars_daily", "2024-03") not in tampered.spool._verified_pages
    assert tamper_verifies == [("equities_bars_daily", "2024-03")]
    assert tampered.spool._cached_verified_month("equities_bars_daily", "2024-03") is None
    assert len(tamper_verifies) == 2
    assert ("equities_bars_daily", "2024-03") not in tampered.spool._verified_pages
    tampered.close()


def test_verified_page_cache_does_not_cross_client_or_job(tmp_path: Path) -> None:
    spool = tmp_path / "spool.sqlite"
    first = _fins_client(tmp_path, spool_path=spool)
    first_one = first.fetch_dataset_evidenced("fins_summary", code="1001")
    first_two = first.fetch_dataset_evidenced("fins_summary", code="1002")
    first.close()

    second = _fins_client(tmp_path, spool_path=spool)
    verifies = _wrap_verified_complete_month(second)
    scans = _wrap_assert_verified_complete(second)
    selected = second.fetch_dataset_evidenced("fins_summary", code="1002")
    assert scans
    assert verifies
    assert selected.rows == first_two.rows
    assert selected.selection is not None and first_two.selection is not None
    assert selected.selection == first_two.selection
    assert first_one.selection is not None
    assert selected.selection.selected_digest != first_one.selection.selected_digest
    assert selected.selection.scanned_page_digests == first_one.selection.scanned_page_digests
    second.close()

    other_job = _fins_client(tmp_path, spool_path=tmp_path / "other-job.sqlite")
    other_verifies = _wrap_verified_complete_month(other_job)
    other = other_job.fetch_dataset_evidenced("fins_summary", code="1002")
    assert other_verifies
    assert other.selection is not None
    assert other.selection.selected_digest == first_two.selection.selected_digest
    other_job.close()


def _http_error(
    url: str,
    code: int,
    *,
    retry_after: str | None = None,
    body: bytes = b"",
) -> urllib.error.HTTPError:
    headers = EmailMessage()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(url, code, "error", headers, io.BytesIO(body))


def _post_client(tmp_path: Path, opener: object, **kwargs):
    return client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        spool_path=tmp_path / "spool.sqlite",
        opener=opener,
        _sleep=kwargs.get("_sleep", lambda _delay: None),
        _max_attempts=kwargs.get("_max_attempts"),
    )


def test_post_retries_429_then_succeeds_with_same_request_bytes(tmp_path: Path) -> None:
    calls: list[bytes] = []
    slept: list[float] = []
    payload = {
        "dataset_id": "markets_calendar",
        "acquisition_nonce": "a" * 64,
        "continuation_token": "cursor-keep",
    }

    class Opener:
        def urlopen(self, request, timeout=120):
            calls.append(bytes(request.data))
            if len(calls) == 1:
                raise _http_error(
                    request.full_url,
                    429,
                    retry_after="60",
                    body=b'{"error":"rate_limited"}',
                )
            raw = json.dumps({"data": []}, separators=(",", ":")).encode()
            return _Response(raw, _page_headers("EXHAUSTED", "NONE", "NONE"))

    client = _post_client(tmp_path, Opener(), _sleep=slept.append)
    raw, headers, status = client._post(payload)
    assert status == 200
    assert headers["x-quant-acquisition-pagination-state"] == "EXHAUSTED"
    assert json.loads(raw) == {"data": []}
    assert slept == [60]
    assert len(calls) == 2
    assert calls[0] == calls[1]
    decoded = json.loads(calls[0])
    assert decoded["continuation_token"] == "cursor-keep"
    assert decoded["acquisition_nonce"] == "a" * 64
    client.close()


def test_post_exhausts_bounded_429_retries(tmp_path: Path) -> None:
    calls = {"n": 0}
    slept: list[float] = []

    class Opener:
        def urlopen(self, request, timeout=120):
            calls["n"] += 1
            raise _http_error(request.full_url, 429, retry_after="12")

    client = _post_client(tmp_path, Opener(), _sleep=slept.append)
    with pytest.raises(PersonalHistoryError, match="history.source returned HTTP 429"):
        client._post({"continuation_token": "keep"})
    assert calls["n"] == 4
    assert slept == [12, 12, 12]
    client.close()


@pytest.mark.parametrize(
    "retry_after",
    [None, "", "abc", "0", "121", "60.5", "+60", "60 ", "Wed, 21 Oct 2015 07:28:00 GMT"],
)
def test_post_fail_closes_malformed_retry_after(
    tmp_path: Path, retry_after: str | None
) -> None:
    calls = {"n": 0}
    slept: list[float] = []

    class Opener:
        def urlopen(self, request, timeout=120):
            calls["n"] += 1
            raise _http_error(request.full_url, 429, retry_after=retry_after)

    client = _post_client(tmp_path, Opener(), _sleep=slept.append)
    with pytest.raises(PersonalHistoryError, match="history.source returned HTTP 429"):
        client._post({"continuation_token": "keep"})
    assert calls["n"] == 1
    assert slept == []
    client.close()


@pytest.mark.parametrize("status", [400, 500, 501])
def test_post_does_not_retry_non_transient_status(
    tmp_path: Path, status: int
) -> None:
    errors: list[urllib.error.HTTPError] = []
    slept: list[float] = []

    class Opener:
        def urlopen(self, request, timeout=120):
            error = _http_error(
                request.full_url,
                status,
                retry_after="60",
                body=b'{"error":"not_retryable"}',
            )
            errors.append(error)
            raise error

    client = _post_client(tmp_path, Opener(), _sleep=slept.append)
    with pytest.raises(
        PersonalHistoryError, match=f"history.source returned HTTP {status}"
    ):
        client._post({"continuation_token": "keep"})
    assert len(errors) == 1
    assert errors[0].fp is None or errors[0].fp.closed
    assert slept == []
    client.close()


@pytest.mark.parametrize("status", [502, 503, 504])
def test_post_retries_transient_gateway_status_with_same_request_bytes(
    tmp_path: Path, status: int
) -> None:
    calls: list[bytes] = []
    errors: list[urllib.error.HTTPError] = []
    slept: list[float] = []
    payload = {
        "dataset_id": "markets_calendar",
        "acquisition_nonce": "b" * 64,
        "continuation_token": "cursor-keep",
    }

    class Opener:
        def urlopen(self, request, timeout=120):
            calls.append(bytes(request.data))
            if len(calls) == 1:
                error = _http_error(
                    request.full_url,
                    status,
                    retry_after="60",
                    body=b'{"error":"temporary_gateway_failure"}',
                )
                errors.append(error)
                raise error
            raw = json.dumps({"data": []}, separators=(",", ":")).encode()
            return _Response(raw, _page_headers("EXHAUSTED", "NONE", "NONE"))

    client = _post_client(tmp_path, Opener(), _sleep=slept.append)
    raw, _headers, response_status = client._post(payload)
    assert response_status == 200
    assert json.loads(raw) == {"data": []}
    assert slept == [1]
    assert len(calls) == 2
    assert calls[0] == calls[1]
    decoded = json.loads(calls[0])
    assert decoded["continuation_token"] == "cursor-keep"
    assert decoded["acquisition_nonce"] == "b" * 64
    assert errors[0].fp is None or errors[0].fp.closed
    client.close()


def test_post_exhausts_bounded_transient_gateway_retries(tmp_path: Path) -> None:
    calls: list[bytes] = []
    errors: list[urllib.error.HTTPError] = []
    slept: list[float] = []

    class Opener:
        def urlopen(self, request, timeout=120):
            calls.append(bytes(request.data))
            error = _http_error(
                request.full_url,
                502,
                body=b'{"error":"temporary_gateway_failure"}',
            )
            errors.append(error)
            raise error

    client = _post_client(tmp_path, Opener(), _sleep=slept.append)
    with pytest.raises(PersonalHistoryError, match="history.source returned HTTP 502"):
        client._post(
            {
                "acquisition_nonce": "c" * 64,
                "continuation_token": "cursor-keep",
            }
        )
    assert len(calls) == 4
    assert calls == [calls[0]] * 4
    assert slept == [1, 2, 4]
    assert all(error.fp is None or error.fp.closed for error in errors)
    client.close()


def test_429_retry_does_not_change_fetch_call_evidence(tmp_path: Path) -> None:
    calls = {"n": 0}
    slept: list[float] = []

    class Opener:
        def urlopen(self, request, timeout=120):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _http_error(request.full_url, 429, retry_after="1")
            month = json.loads(request.data.decode())["segment_id"]
            raw = json.dumps(
                {"data": _calendar_month(month)}, separators=(",", ":")
            ).encode()
            return _Response(raw, _page_headers("EXHAUSTED", "NONE", "NONE"))

    client = _post_client(tmp_path, Opener(), _sleep=slept.append)
    fetched = client.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    assert slept == [1]
    assert calls["n"] == 2
    assert client.fetch_calls == 1
    assert len(fetched.pages) == 1
    assert [row["Date"] for row in fetched.rows] == [
        "2024-03-10",
        "2024-03-11",
        "2024-03-12",
    ]
    client.close()


def test_spool_reset_recreates_empty_schema_and_rejects_fetching(
    tmp_path: Path,
) -> None:
    spool = client_mod.AcquisitionSpool(tmp_path / "spool.sqlite")
    _write_committed_spool_page(spool, _large_spool_rows())
    with pytest.raises(PersonalHistoryError, match="is FETCHING"):
        spool.reset()
    assert (
        spool._conn.execute("SELECT status FROM month_state").fetchone()[0]
        == "FETCHING"
    )
    pages_before, size_before = spool.usage()
    assert pages_before == 1
    spool.complete_month(
        "equities_bars_daily",
        "2024-03",
        page_count=1,
        completion_digest="sha256:" + "a" * 64,
    )
    spool.reset()
    pages, size = spool.usage()
    assert pages == 0
    assert spool._conn.execute("SELECT COUNT(*) FROM source_rows").fetchone()[0] == 0
    assert spool._conn.execute("SELECT COUNT(*) FROM source_pages").fetchone()[0] == 0
    assert spool._conn.execute("SELECT COUNT(*) FROM month_state").fetchone()[0] == 0
    assert spool.path.exists()
    assert size < size_before
    spool.close()


def test_source_client_preserves_metrics_across_spool_reset(tmp_path: Path) -> None:
    client = _two_page_client(tmp_path)
    metrics = client.cache_metrics()
    assert client.fetch_calls == 2
    assert client.spool.usage()[0] == 2
    client.release_acquired_raw()
    assert client.cache_metrics() == metrics
    assert client.fetch_calls == 2
    assert client.spool.usage()[0] == 0
    assert client.spool.has_month("equities_bars_daily", "2024-03") is False
    client.close()


def test_guard_bounds_admits_measured_full_fins_and_rejects_over_nine_gib(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client_mod.MAX_SPOOL_BYTES == 9 * 1024 ** 3
    spool = client_mod.AcquisitionSpool(tmp_path / "spool.sqlite")
    monkeypatch.setattr(spool, "_checkpoint_committed_wal", lambda: None)
    measured_full_fins = 8_596_356_272
    monkeypatch.setattr(spool, "usage", lambda: (1, measured_full_fins))
    spool.guard_bounds()
    monkeypatch.setattr(
        spool, "usage", lambda: (1, client_mod.MAX_SPOOL_BYTES + 1)
    )
    with pytest.raises(PersonalHistoryError, match="byte bound exceeded"):
        spool.guard_bounds()
    spool.close()


def _synthetic_master_day(day: str) -> list[dict]:
    topix = ["1001", "1002"] if day < "2025-01-07" else ["1001", "1002", "1003"]
    return [
        {
            "Code": code,
            "Date": day,
            "Mkt": {"1001": "0111", "1002": "0112", "1003": "0113"}[code],
            "S17": "1",
            "S33": "0050" if code != "1003" else "1050",
            "ScaleCat": "TOPIX Core30" if code == "1001" else "TOPIX Small 1",
        }
        for code in topix
    ] + [{"Code": "9001", "Date": day, "Mkt": "0112", "ScaleCat": "-"}]


def _synthetic_bars_day(day: str) -> list[dict]:
    rows = []
    for ordinal, code in enumerate(("1001", "1002", "1003", "9001"), start=1):
        rows.append(
            {
                "Code": code,
                "Date": day,
                "Close": 100 + ordinal,
                "AdjustmentClose": 100 + ordinal,
                "Volume": 1_000 * ordinal,
                "AdjustmentVolume": 1_000 * ordinal,
                "TurnoverValue": 1_000_000 * ordinal,
                "MktCap": 10_000_000 * ordinal,
                "MAdjC": 10 + ordinal,
                "AAdjC": 20 + ordinal,
                "MVa": 100 * ordinal,
                "AVa": 200 * ordinal,
                "MAdjVo": 10 * ordinal,
                "AAdjVo": 20 * ordinal,
                "Open": 90,
                "CompanyName": "must-not-be-kept",
            }
        )
    return rows


_FINS_DISCLOSURES = {
    "1001": ("2024-12-02", "09:00:00"),
    "1002": ("2025-01-03", None),
    "1003": ("2025-01-07", "09:00:00"),
}


def _synthetic_history_opener():
    class Opener:
        def urlopen(self, request, timeout=120):
            payload = json.loads(request.data.decode())
            dataset = payload["dataset_id"]
            month = payload["segment_id"]
            if dataset == "markets_calendar":
                rows = _calendar_month(month)
                slice_date = "NONE"
            elif dataset == "equities_master":
                rows = []
                current = date.fromisoformat(f"{month}-01")
                while current.isoformat()[:7] == month:
                    if current.weekday() < 5:
                        rows.extend(_synthetic_master_day(current.isoformat()))
                    current += timedelta(days=1)
                slice_date = f"{month}-01"
            elif dataset == "equities_bars_daily":
                rows = []
                current = date.fromisoformat(f"{month}-01")
                while current.isoformat()[:7] == month:
                    if current.weekday() < 5:
                        rows.extend(_synthetic_bars_day(current.isoformat()))
                    current += timedelta(days=1)
                slice_date = f"{month}-01"
            elif dataset == "fins_summary":
                rows = []
                for code, (disc, clock) in _FINS_DISCLOSURES.items():
                    if disc[:7] != month:
                        continue
                    row = {
                        "Code": code,
                        "DiscDate": disc,
                        "DiscNo": f"disc-{code}",
                        "EarningsPerShare": 123.4,
                        "Narrative": "must-not-be-kept",
                    }
                    if clock:
                        row["DiscTime"] = clock
                    rows.append(row)
                slice_date = "NONE"
            else:
                raise AssertionError(dataset)
            raw = json.dumps({"data": rows}, separators=(",", ":")).encode()
            return _Response(
                raw,
                {
                    "x-quant-acquisition-evidence-state": "RAW_PAGE",
                    "x-quant-acquisition-pagination-state": "EXHAUSTED",
                    "x-quant-acquisition-continuation": "NONE",
                    "x-quant-acquisition-slice-date": slice_date,
                },
            )

    return Opener()


def _committed_history(store: SqliteStore) -> dict:
    def rows(sql: str) -> list[dict]:
        return [dict(row) for row in store._conn.execute(sql)]

    return {
        "segments": rows(
            "SELECT dataset, segment_id, state, rows_fetched, rows_written, "
            "page_count, page_evidence_json, selection_evidence_json, "
            "response_digest, facts_digest, membership_digest, expected_rows, "
            "observed_ratio, pit_policy FROM personal_history_segments "
            "ORDER BY dataset, segment_id"
        ),
        "scans": rows(
            "SELECT scan_digest, dataset, page_count, source_row_count, "
            "completion_digest, scanned_page_digests_json, page_evidence_json "
            "FROM personal_history_shared_scans ORDER BY scan_digest"
        ),
        "master": [
            {key: value for key, value in row.items() if key != "ingested_at"}
            for row in rows(
                "SELECT * FROM personal_history_compact_master "
                "ORDER BY snapshot_date, code"
            )
        ],
        "bars": [
            {key: value for key, value in row.items() if key != "ingested_at"}
            for row in rows(
                "SELECT * FROM personal_history_compact_bars ORDER BY date, code"
            )
        ],
        "records": [
            {key: value for key, value in row.items() if key != "ingested_at"}
            for row in rows(
                "SELECT dataset, natural_key, event_time, available_at, payload "
                "FROM jquants_records ORDER BY dataset, natural_key"
            )
        ],
    }


def _hydrate_source_client(
    tmp_path: Path,
    *,
    plan,
    release: bool = True,
    on_release=None,
):
    client = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end=plan.period_end,
        spool_path=tmp_path / "spool.sqlite",
        opener=_synthetic_history_opener(),
    )
    original = client.release_acquired_raw
    if on_release is not None:
        def wrapped() -> None:
            on_release(client)
            original()

        client.release_acquired_raw = wrapped  # type: ignore[method-assign]
    elif not release:
        client.release_acquired_raw = lambda: None  # type: ignore[method-assign]
    store = SqliteStore(tmp_path / "history.sqlite")
    summary = PersonalHistoryHydrator(client=client, store=store, plan=plan).hydrate()
    return client, store, summary


def test_full_hydrate_evidence_remains_equivalent_after_spool_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ingestion.personal_history.now_iso",
        lambda: "2025-03-01T16:00:00+09:00",
    )
    plan = build_personal_history_plan(
        period_start="2025-01-06",
        period_end="2025-01-08",
        lookback_sessions=1,
        calendar_window_days=366,
        today=date(2025, 2, 1),
    )
    kept = tmp_path / "kept"
    reclaimed = tmp_path / "reclaimed"
    kept.mkdir()
    reclaimed.mkdir()
    kept_client, kept_store, _kept_summary = _hydrate_source_client(
        kept, plan=plan, release=False
    )
    reclaimed_client, reclaimed_store, _reclaimed_summary = _hydrate_source_client(
        reclaimed, plan=plan, release=True
    )
    assert _committed_history(kept_store) == _committed_history(reclaimed_store)
    assert reclaimed_client.spool.usage()[0] == 0
    assert kept_client.spool.usage()[0] > 0
    kept_store.close()
    reclaimed_store.close()
    kept_client.close()
    reclaimed_client.close()


def test_bar_months_are_released_so_physical_usage_is_not_cumulative(
    tmp_path: Path,
) -> None:
    plan = build_personal_history_plan(
        period_start="2025-02-03",
        period_end="2025-02-05",
        lookback_sessions=5,
        calendar_window_days=366,
        today=date(2025, 3, 1),
    )
    peaks: list[tuple[frozenset[str], int, int]] = []

    def on_release(client) -> None:
        datasets = frozenset(
            str(row[0])
            for row in client.spool._conn.execute(
                "SELECT DISTINCT dataset FROM month_state"
            )
        )
        pages, size = client.spool.usage()
        peaks.append((datasets, pages, size))

    client, store, _summary = _hydrate_source_client(
        tmp_path, plan=plan, on_release=on_release
    )
    bar_peaks = [
        item for item in peaks if item[0] == frozenset({"equities_bars_daily"})
    ]
    assert len(bar_peaks) == 2
    assert [pages for _datasets, pages, _size in bar_peaks] == [1, 1]
    assert client.spool.usage()[0] == 0
    store.close()
    client.close()
