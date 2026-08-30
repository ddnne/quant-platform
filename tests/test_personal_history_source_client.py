from __future__ import annotations

from datetime import date, timedelta
from email.message import EmailMessage
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

import pytest

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
