from __future__ import annotations

from datetime import date, timedelta
from email.message import EmailMessage
import gzip
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

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = (
    ROOT
    / "platform"
    / "workers"
    / "research-mass-eval"
    / "container"
)
if str(CONTAINER) not in sys.path:
    sys.path.insert(0, str(CONTAINER))

MODULE_PATH = CONTAINER / "personal_history_source_client.py"
if "personal_history_source_client" not in sys.modules:
    SPEC = importlib.util.spec_from_file_location(
        "personal_history_source_client", MODULE_PATH
    )
    assert SPEC is not None and SPEC.loader is not None
    client_mod = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = client_mod
    SPEC.loader.exec_module(client_mod)
else:
    client_mod = sys.modules["personal_history_source_client"]

cache_mod = sys.modules["personal_acquisition_cache"]


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


def _http_error(url: str, code: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "error", EmailMessage(), io.BytesIO(body))


def _page_headers(state: str = "EXHAUSTED", continuation: str = "NONE", slice_date: str = "NONE"):
    return {
        "x-quant-acquisition-evidence-state": "RAW_PAGE",
        "x-quant-acquisition-pagination-state": state,
        "x-quant-acquisition-continuation": continuation,
        "x-quant-acquisition-slice-date": slice_date,
    }


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


class MemoryR2:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.gets = 0
        self.puts = 0
        self.get_status: int | None = None
        self.put_status: int | None = None
        self.get_exc: BaseException | None = None
        self.put_exc: BaseException | None = None
        self.seen_get_headers: list[dict[str, str]] = []
        self.seen_put_headers: list[dict[str, str]] = []

    def urlopen(self, request, timeout=15):
        key = request.full_url.split("://", 1)[1].split("/", 1)[1]
        method = request.get_method()
        headers = {name.lower(): value for name, value in request.header_items()}
        for name, value in headers.items():
            assert cache_mod.header_name_is_forbidden(name) is False
            assert cache_mod.header_name_is_forbidden(value) is False
        if method == "GET":
            self.gets += 1
            self.seen_get_headers.append(headers)
            if self.get_exc is not None:
                raise self.get_exc
            if self.get_status is not None:
                if self.get_status == 404:
                    raise _http_error(request.full_url, 404)
                if self.get_status >= 500:
                    raise _http_error(request.full_url, self.get_status)
                raise _http_error(request.full_url, self.get_status)
            stored = self.objects.get(key)
            if stored is None:
                raise _http_error(request.full_url, 404)
            body = stored["body"]
            assert isinstance(body, bytes)
            headers = stored.get("response_headers")
            if not isinstance(headers, dict):
                headers = {
                    "content-type": "application/gzip",
                    "content-length": str(len(body)),
                    "x-content-sha256": str(stored["sha256"]),
                    "x-acquisition-cache-raw-sha256": str(stored["raw_sha256"]),
                }
            return _Response(body, headers)
        if method != "PUT":
            raise _http_error(request.full_url, 403)
        self.puts += 1
        self.seen_put_headers.append(headers)
        if self.put_exc is not None:
            raise self.put_exc
        if self.put_status is not None:
            if self.put_status >= 500:
                raise _http_error(request.full_url, self.put_status)
            raise _http_error(request.full_url, self.put_status)
        body = bytes(request.data or b"")
        digest = headers.get("x-content-sha256", "")
        raw = headers.get("x-acquisition-cache-raw-sha256", "")
        actual = "sha256:" + hashlib.sha256(body).hexdigest()
        if digest != actual:
            raise _http_error(request.full_url, 502)
        existing = self.objects.get(key)
        if existing is not None:
            if existing["body"] == body and existing["sha256"] == digest:
                return _Response({"ok": True, "created": False, "key": key}, {}, status=200)
            raise _http_error(request.full_url, 409)
        self.objects[key] = {"body": body, "sha256": digest, "raw_sha256": raw}
        return _Response({"ok": True, "created": True, "key": key}, {}, status=201)


class HistoryOpener:
    def urlopen(self, request, timeout=120):
        payload = json.loads(request.data.decode())
        month = payload["segment_id"]
        dataset = payload["dataset_id"]
        if dataset == "markets_calendar":
            rows = _calendar_month(month)
        else:
            token = payload.get("continuation_token")
            if token is None:
                raw = json.dumps(
                    {"data": [{"Code": "1001", "Date": f"{month}-01"}]},
                    separators=(",", ":"),
                ).encode()
                return _Response(raw, _page_headers("CONTINUATION", "cursor-2", f"{month}-01"))
            raw = json.dumps(
                {"data": [{"Code": "1002", "Date": f"{month}-02"}]},
                separators=(",", ":"),
            ).encode()
            return _Response(raw, _page_headers("EXHAUSTED", "NONE", f"{month}-02"))
        raw = json.dumps({"data": rows}, separators=(",", ":")).encode()
        return _Response(raw, _page_headers())


def _client(tmp_path: Path, *, r2=None, spool=None, utc_today=None, dataset_end="2024-03-31"):
    return client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end=dataset_end,
        spool_path=spool or (tmp_path / "spool.sqlite"),
        opener=HistoryOpener(),
        r2_opener=r2,
        utc_today=utc_today,
    )


def test_second_job_loads_closed_month_without_live_fetch(tmp_path: Path) -> None:
    r2 = MemoryR2()
    first = _client(tmp_path / "job-a", r2=r2, spool=tmp_path / "a.sqlite")
    live = first.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    assert first.fetch_calls == 1
    assert first.cache_misses == 1
    assert first.cache_published == 1
    assert first.cache_hits == 0
    first.close()

    second = _client(tmp_path / "job-b", r2=r2, spool=tmp_path / "b.sqlite")
    cached = second.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    assert second.fetch_calls == 0
    assert second.cache_hits == 1
    assert second.cache_misses == 0
    assert [row["Date"] for row in cached.rows] == [row["Date"] for row in live.rows]
    assert cached.selection is not None and live.selection is not None
    assert cached.selection.selected_digest == live.selection.selected_digest
    assert cached.selection.completion_digest == live.selection.completion_digest
    assert tuple(page.body_digest for page in cached.pages) == tuple(
        page.body_digest for page in live.pages
    )
    assert tuple(page.row_count for page in cached.pages) == tuple(
        page.row_count for page in live.pages
    )
    second.close()


def test_live_and_cache_restored_page_evidence_match(tmp_path: Path) -> None:
    r2 = MemoryR2()
    first = _client(tmp_path / "job-a", r2=r2, spool=tmp_path / "a.sqlite")
    live = first.fetch_dataset_evidenced("equities_bars_daily", date="2024-03-01")
    first.close()
    second = _client(tmp_path / "job-b", r2=r2, spool=tmp_path / "b.sqlite")
    cached = second.fetch_dataset_evidenced("equities_bars_daily", date="2024-03-01")
    assert second.fetch_calls == 0
    assert cached.rows == live.rows
    assert cached.selection == live.selection
    assert len(cached.pages) == 2
    assert cached.pages[0].pagination_out == live.pages[0].pagination_out
    assert cached.pages[-1].pagination_out is None
    second.close()


def test_identity_epoch_and_contract_change_yield_different_keys(tmp_path: Path) -> None:
    client = _client(tmp_path)
    identity = client._cache_identity("markets_calendar", "2024-03")
    base = cache_mod.cache_object_key(
        environment="production",
        dataset="markets_calendar",
        month="2024-03",
        identity_hex=cache_mod.cache_identity_hex(identity),
    )
    mutated = {
        "schema_epoch": dict(identity, schema_epoch=2),
        "environment": dict(identity, environment="staging"),
        "dataset_contract_digest": dict(
            identity, dataset_contract_digest="sha256:" + "a" * 64
        ),
        "source_capability_digest": dict(
            identity, source_capability_digest="sha256:" + "b" * 64
        ),
        "coverage_policy_digest": dict(
            identity, coverage_policy_digest="sha256:" + "c" * 64
        ),
        "query_contract_digest": dict(
            identity, query_contract_digest="sha256:" + "d" * 64
        ),
        "target_registry_digest": dict(
            identity, target_registry_digest="sha256:" + "e" * 64
        ),
        "route_path": dict(identity, route_path="/v2/other"),
        "route_mode": dict(identity, route_mode="other_mode"),
        "segment_start": dict(identity, segment_start="2024-03-02"),
        "segment_end": dict(identity, segment_end="2024-03-30"),
    }
    keys = {
        name: cache_mod.cache_object_key(
            environment=str(value["environment"]),
            dataset=str(value["dataset_id"]),
            month=str(value["segment_id"]),
            identity_hex=cache_mod.cache_identity_hex(value),
        )
        for name, value in mutated.items()
    }
    assert base != keys["schema_epoch"]
    assert len({base, *keys.values()}) == 1 + len(keys)
    assert "job" not in canonical_json(identity)
    assert "acquisition_nonce" not in identity
    assert "lookback" not in canonical_json(identity)
    client.close()


def test_incomplete_month_cannot_publish(tmp_path: Path) -> None:
    r2 = MemoryR2()
    client = _client(tmp_path, r2=r2)
    identity = client._cache_identity("markets_calendar", "2024-03")
    client.spool.begin_month("markets_calendar", "2024-03", identity)
    dest = tmp_path / "incomplete.sqlite"
    with pytest.raises(client_mod.PersonalHistoryError, match="not a verified COMPLETE"):
        cache_mod.write_month_shard(client.spool._conn, dest, identity=identity)
    with pytest.raises(client_mod.PersonalHistoryError, match="not a verified COMPLETE"):
        client._publish_month_cache("markets_calendar", "2024-03")
    assert r2.puts == 0
    assert dest.exists() is False
    client.close()


def _insert_orphan_row(conn) -> None:
    conn.execute(
        "UPDATE source_pages SET row_count = row_count + 1 WHERE page_ordinal = 0"
    )
    conn.execute(
        "INSERT INTO source_rows ("
        "dataset, month, page_ordinal, row_index, code, row_date, row_json"
        ") VALUES ('markets_calendar', '2024-03', 99, 0, NULL, NULL, '{}')"
    )


def _repack(blob: bytes, tmp_path: Path, mutate) -> bytes:
    raw = gzip.decompress(blob)
    path = tmp_path / "mutated.sqlite"
    path.write_bytes(raw)
    conn = sqlite3.connect(path)
    try:
        mutate(conn)
        conn.commit()
    finally:
        conn.close()
    return cache_mod.gzip_bytes(path)


def _publish_calendar(tmp_path: Path) -> tuple[MemoryR2, bytes, str]:
    r2 = MemoryR2()
    first = _client(tmp_path / "seed", r2=r2, spool=tmp_path / "seed.sqlite")
    first.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    key = next(iter(r2.objects))
    body = r2.objects[key]["body"]
    assert isinstance(body, bytes)
    first.close()
    return r2, body, key


@pytest.mark.parametrize(
    "mutator,match",
    [
        (lambda conn: None, "gzip"),
        (
            lambda conn: conn.execute(
                "UPDATE cache_identity SET identity_hex=?",
                ("a" * 64,),
            ),
            "identity",
        ),
        (
            lambda conn: conn.execute(
                "UPDATE source_pages SET row_count=99 WHERE page_ordinal=0"
            ),
            "row counts do not match pages",
        ),
        (
            lambda conn: conn.execute(
                "UPDATE source_rows SET code='NOPE' WHERE row_index=0"
            ),
            "row index does not match row_json",
        ),
        (
            lambda conn: conn.execute(
                "UPDATE source_rows SET row_date='1999-01-01' WHERE row_index=0"
            ),
            "row index does not match row_json",
        ),
        (_insert_orphan_row, "orphan"),
        (
            lambda conn: conn.execute(
                "UPDATE source_pages SET pagination_out='cursor' "
                "WHERE page_ordinal=(SELECT MAX(page_ordinal) FROM source_pages)"
            ),
            "exhausted",
        ),
        (
            lambda conn: conn.execute(
                "UPDATE month_state SET completion_digest=?",
                ("sha256:" + "f" * 64,),
            ),
            "completion digest",
        ),
    ],
)
def test_corrupt_cache_is_rejected_without_live_fallback(
    tmp_path: Path, mutator, match: str
) -> None:
    r2, body, key = _publish_calendar(tmp_path)
    if match == "gzip":
        r2.objects[key]["body"] = b"not-a-gzip-payload"
        r2.objects[key]["sha256"] = "sha256:" + hashlib.sha256(
            r2.objects[key]["body"]
        ).hexdigest()
    else:
        mutated = _repack(body, tmp_path, mutator)
        raw = gzip.decompress(mutated)
        r2.objects[key] = {
            "body": mutated,
            "sha256": "sha256:" + hashlib.sha256(mutated).hexdigest(),
            "raw_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }
    second = _client(tmp_path / "job-b", r2=r2, spool=tmp_path / "b.sqlite")
    with pytest.raises(cache_mod.AcquisitionCacheInvalid, match=match):
        second.fetch_dataset_evidenced(
            "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
        )
    assert second.fetch_calls == 0
    second.close()


def _with_get_headers(r2: MemoryR2, key: str, mutate) -> None:
    stored = r2.objects[key]
    body = stored["body"]
    assert isinstance(body, bytes)
    headers = {
        "content-type": "application/gzip",
        "content-length": str(len(body)),
        "x-content-sha256": str(stored["sha256"]),
        "x-acquisition-cache-raw-sha256": str(stored["raw_sha256"]),
    }
    mutate(headers, stored, body)
    stored["response_headers"] = headers


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda headers, stored, body: headers.pop("x-content-sha256"), "content digest is missing"),
        (
            lambda headers, stored, body: headers.__setitem__(
                "x-content-sha256", "sha256:not-a-digest"
            ),
            "content digest is invalid",
        ),
        (
            lambda headers, stored, body: headers.__setitem__(
                "x-content-sha256", "sha256:" + "0" * 64
            ),
            "content digest does not match body",
        ),
        (
            lambda headers, stored, body: headers.pop("x-acquisition-cache-raw-sha256"),
            "raw digest is missing",
        ),
        (
            lambda headers, stored, body: headers.__setitem__(
                "x-acquisition-cache-raw-sha256", "not-a-digest"
            ),
            "raw digest is invalid",
        ),
        (
            lambda headers, stored, body: headers.__setitem__(
                "x-acquisition-cache-raw-sha256", "sha256:" + "0" * 64
            ),
            "raw digest does not match sqlite",
        ),
        (
            lambda headers, stored, body: headers.pop("content-type"),
            "content-type is invalid",
        ),
        (
            lambda headers, stored, body: headers.__setitem__(
                "content-type", "application/octet-stream"
            ),
            "content-type is invalid",
        ),
        (
            lambda headers, stored, body: headers.pop("content-length"),
            "content-length is invalid",
        ),
        (
            lambda headers, stored, body: headers.__setitem__("content-length", "03"),
            "content-length is invalid",
        ),
        (
            lambda headers, stored, body: headers.__setitem__(
                "content-length", str(len(body) + 1)
            ),
            "content-length does not match body",
        ),
        (
            lambda headers, stored, body: headers.__setitem__(
                "content-length", str(len(body) - 1) if len(body) > 1 else "0"
            ),
            "content-length",
        ),
    ],
)
def test_missing_or_mismatched_get_contract_is_rejected_without_live_fallback(
    tmp_path: Path, mutate, match: str
) -> None:
    r2, _body, key = _publish_calendar(tmp_path)
    _with_get_headers(r2, key, mutate)
    second = _client(tmp_path / "job-b", r2=r2, spool=tmp_path / "b.sqlite")
    with pytest.raises(cache_mod.AcquisitionCacheInvalid, match=match):
        second.fetch_dataset_evidenced(
            "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
        )
    assert second.fetch_calls == 0
    second.close()


def test_cache_404_is_a_live_miss(tmp_path: Path) -> None:
    r2 = MemoryR2()
    r2.get_status = 404
    client = _client(tmp_path, r2=r2)
    fetched = client.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    assert [row["Date"] for row in fetched.rows] == [
        "2024-03-10",
        "2024-03-11",
        "2024-03-12",
    ]
    assert client.cache_misses == 1
    assert client.fetch_calls == 1
    client.close()


def test_bounded_5xx_records_unavailable_and_live_fetches(tmp_path: Path) -> None:
    r2 = MemoryR2()
    r2.get_status = 503
    client = _client(tmp_path, r2=r2)
    fetched = client.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    assert fetched.selection is not None
    assert client.cache_unavailable >= 1
    assert client.fetch_calls == 1
    client.close()


def test_cache_transport_timeout_records_unavailable_and_live_fetches(
    tmp_path: Path,
) -> None:
    r2 = MemoryR2()
    r2.get_exc = TimeoutError("cache get timed out")
    client = _client(tmp_path, r2=r2)
    client.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    assert client.cache_unavailable >= 1
    assert client.fetch_calls == 1
    client.close()


def test_put_transport_outage_allows_valid_snapshot_month(tmp_path: Path) -> None:
    r2 = MemoryR2()
    r2.put_status = 503
    client = _client(tmp_path, r2=r2)
    fetched = client.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    assert fetched.selection is not None
    assert client.spool.has_month("markets_calendar", "2024-03") is True
    assert client.cache_unavailable >= 1
    assert client.cache_published == 0
    client.close()


def test_put_conflict_fails_the_snapshot(tmp_path: Path) -> None:
    r2 = MemoryR2()
    first = _client(tmp_path / "a", r2=r2, spool=tmp_path / "a.sqlite")
    first.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    key = next(iter(r2.objects))
    r2.objects[key]["body"] = b"\x1f\x8b different-immutable-bytes"
    first.close()
    second = _client(tmp_path / "b", r2=r2, spool=tmp_path / "b.sqlite")
    r2.get_status = 404
    with pytest.raises(cache_mod.AcquisitionCacheConflict, match="conflict"):
        second.fetch_dataset_evidenced(
            "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
        )
    second.close()


def test_identical_put_is_idempotent(tmp_path: Path) -> None:
    r2 = MemoryR2()
    first = _client(tmp_path / "a", r2=r2, spool=tmp_path / "a.sqlite")
    first.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    first.close()
    replay = _client(tmp_path / "b", r2=r2, spool=tmp_path / "b.sqlite")
    replay._load_month_from_cache = lambda *args, **kwargs: False
    replay.cache_misses += 1
    replay.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    assert replay.cache_published == 1
    assert len(r2.objects) == 1
    replay.close()


def test_current_month_does_not_cache(tmp_path: Path) -> None:
    r2 = MemoryR2()
    client = _client(tmp_path, r2=r2, utc_today=lambda: date(2024, 3, 15))
    client.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    assert r2.gets == 0
    assert r2.puts == 0
    assert client.cache_published == 0
    assert client.cache_hits == 0
    assert client.cache_misses == 0
    assert client.fetch_calls == 1
    client.close()


def test_cache_requests_omit_credential_headers(tmp_path: Path) -> None:
    r2 = MemoryR2()
    client = _client(tmp_path, r2=r2)
    client.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    assert r2.seen_get_headers and r2.seen_put_headers
    for headers in r2.seen_get_headers + r2.seen_put_headers:
        serialized = json.dumps(headers).lower()
        assert "authorization" not in serialized
        assert "cookie" not in serialized
        assert "api_key" not in serialized
        assert "password" not in serialized
        assert "secret" not in serialized
        assert "x-personal-job-id" not in headers
    gzip_body = next(iter(r2.objects.values()))["body"]
    assert isinstance(gzip_body, bytes)
    raw = gzip.decompress(gzip_body).lower()
    assert b"authorization" not in raw
    assert b"api_key" not in raw
    client.close()


def test_python_cache_headers_are_the_closed_transport_set() -> None:
    key = cache_mod.cache_object_key(
        environment="production",
        dataset="markets_calendar",
        month="2024-03",
        identity_hex="a" * 64,
    )
    get_request = cache_mod.build_cache_get_request(key)
    handler = urllib.request.AbstractHTTPHandler()
    handler.parent = urllib.request.OpenerDirector()
    handler.parent.addheaders = []
    get_final = handler.do_request_(get_request)
    get_headers = {name.lower(): value for name, value in get_final.header_items()}
    assert get_headers == cache_mod.closed_cache_get_headers(host="research.r2")
    body = b"\x1f\x8b" + b"\x00" * 20
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    raw = "sha256:" + "b" * 64
    put_request = cache_mod.build_cache_put_request(
        key, body, content_digest=digest, raw_digest=raw
    )
    put_final = handler.do_request_(put_request)
    put_headers = {name.lower(): value for name, value in put_final.header_items()}
    assert put_headers == cache_mod.closed_cache_put_headers(
        host="research.r2",
        content_length=len(body),
        content_digest=digest,
        raw_digest=raw,
    )
    assert "authorization" not in put_headers
    assert "cookie" not in put_headers


def test_cache_metrics_are_integers(tmp_path: Path) -> None:
    r2 = MemoryR2()
    client = _client(tmp_path, r2=r2)
    client.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    metrics = client.cache_metrics()
    assert set(metrics) == {
        "cache_hits",
        "cache_misses",
        "cache_published",
        "cache_unavailable",
        "live_fetch_calls",
    }
    assert metrics["live_fetch_calls"] == client.fetch_calls == 1
    assert metrics["cache_published"] == 1
    client.close()
