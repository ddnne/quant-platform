"""Shared fins_summary page evidence is persisted once.

The full shared page evidence and full scanned digest list are stored
once. Bounded code-specific selection and contributing-page evidence
remain per code, because contributing_page_digests scale with
disclosures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Sequence

import pytest

from ingestion.personal_history import (
    PersonalHistoryError,
    PersonalHistoryHydrator,
    _canonical_digest,
    build_personal_history_plan,
)
from storage.sqlite_store import SqliteStore


def _completion(scanned: Sequence[str], source_row_count: int) -> str:
    return _canonical_digest(
        {
            "scanned_page_digests": list(scanned),
            "source_row_count": source_row_count,
            "page_count": len(scanned),
            "status": "COMPLETE",
        }
    )


@dataclass(frozen=True)
class _Page:
    request_path: str
    request_params: MappingProxyType
    response_status: int
    response_body: bytes
    pagination_in: str | None = None
    pagination_out: str | None = None
    evidence_state: str = "RAW_PAGE"


class _SharedFinsClient:
    def __init__(
        self,
        months: Sequence[str],
        codes: Sequence[str],
        *,
        page_universe: Sequence[str] | None = None,
    ) -> None:
        self.months = tuple(months)
        self.codes = tuple(codes)
        self.page_universe = tuple(page_universe or codes)
        self.pages: list[_Page] = []
        for month in self.months:
            rows = [
                {
                    "Code": code,
                    "DiscDate": f"{month}-02",
                    "DiscNo": f"n-{code}-{month}",
                    "EarningsPerShare": 1.5,
                    "Pad": "x" * 120,
                }
                for code in self.page_universe
            ]
            body = json.dumps({"data": rows}, separators=(",", ":")).encode()
            self.pages.append(
                _Page(
                    request_path="/v2/fins_summary",
                    request_params=MappingProxyType(
                        {"from": f"{month}-01", "to": f"{month}-28"}
                    ),
                    response_status=200,
                    response_body=body,
                )
            )
        self.scanned = tuple(
            "sha256:" + hashlib.sha256(page.response_body).hexdigest()
            for page in self.pages
        )
        self.source_row_count = sum(
            len(json.loads(page.response_body)["data"]) for page in self.pages
        )
        self.completion = _completion(self.scanned, self.source_row_count)

    def fetch_dataset_evidenced(self, dataset: str, **params: object) -> SimpleNamespace:
        if dataset != "fins_summary":
            raise AssertionError(dataset)
        code = str(params["code"])
        selected: list[dict] = []
        contributing: list[str] = []
        for page, digest in zip(self.pages, self.scanned, strict=True):
            rows = [
                row
                for row in json.loads(page.response_body)["data"]
                if row["Code"] == code
            ]
            if rows:
                contributing.append(digest)
                selected.extend(rows)
        selection = SimpleNamespace(
            query={"code": code},
            selected_row_count=len(selected),
            selected_digest=_canonical_digest(selected),
            source_row_count=self.source_row_count,
            scanned_page_digests=self.scanned,
            completion_digest=self.completion,
            contributing_page_digests=tuple(contributing),
        )
        return SimpleNamespace(
            rows=tuple(selected), pages=tuple(self.pages), selection=selection
        )


def _plan() -> object:
    return build_personal_history_plan(
        period_start="2019-01-04",
        period_end="2019-10-21",
        lookback_sessions=1,
        today=date(2019, 11, 1),
    )


def _hydrate_codes(
    tmp_path: Path,
    months: Sequence[str],
    codes: Sequence[str],
    *,
    page_universe: Sequence[str] | None = None,
) -> tuple[SqliteStore, PersonalHistoryHydrator]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    store = SqliteStore(tmp_path / f"history-{len(months)}-{len(codes)}.sqlite")
    hydrator = PersonalHistoryHydrator(
        client=_SharedFinsClient(months, codes, page_universe=page_universe),
        store=store,
        plan=_plan(),
    )
    hydrator._hydrate_fins(frozenset(codes))
    return store, hydrator


def _evidence_sizes(store: SqliteStore) -> tuple[int, int, int, int]:
    shared = int(
        store._conn.execute(
            "SELECT COALESCE(SUM(length(page_evidence_json)"
            "+length(scanned_page_digests_json)+length(completion_digest)),0) "
            "FROM personal_history_shared_scans"
        ).fetchone()[0]
    )
    selections = int(
        store._conn.execute(
            "SELECT COALESCE(SUM(length(selection_evidence_json)),0) "
            "FROM personal_history_segments WHERE dataset='fins_summary'"
        ).fetchone()[0]
    )
    local_pages = int(
        store._conn.execute(
            "SELECT COALESCE(SUM(length(page_evidence_json)),0) "
            "FROM personal_history_segments WHERE dataset='fins_summary'"
        ).fetchone()[0]
    )
    scans = int(
        store._conn.execute(
            "SELECT COUNT(*) FROM personal_history_shared_scans"
        ).fetchone()[0]
    )
    return shared, selections, local_pages, scans


def test_shared_monthly_scan_is_not_copied_onto_each_fins_code(
    tmp_path: Path,
) -> None:
    months = [f"2019-{month:02d}" for month in range(1, 6)]
    codes = [f"{1000 + index:04d}" for index in range(12)]
    store, hydrator = _hydrate_codes(tmp_path, months, codes)
    hydrator._validate_shared_fins_scan_evidence()

    shared, selections, local_pages, scans = _evidence_sizes(store)
    assert scans == 1
    assert local_pages == 0
    assert shared > 0
    assert selections > 0
    duplicated = shared * len(codes)
    assert shared + selections < duplicated / 2

    rows = store._conn.execute(
        "SELECT segment_id,page_evidence_json,selection_evidence_json,"
        "rows_fetched,page_count,response_digest FROM personal_history_segments "
        "WHERE dataset='fins_summary' ORDER BY segment_id"
    ).fetchall()
    assert len(rows) == len(codes)
    scan_digest = store._conn.execute(
        "SELECT scan_digest FROM personal_history_shared_scans"
    ).fetchone()[0]
    selected_digests = set()
    for row, code in zip(rows, sorted(codes), strict=True):
        assert row["segment_id"] == f"fins:{code}"
        assert row["page_evidence_json"] is None
        selection = json.loads(row["selection_evidence_json"])
        assert selection["query"] == {"code": code}
        assert selection["shared_scan_digest"] == scan_digest
        assert "scanned_page_digests" not in selection
        assert "source_row_count" not in selection
        assert "completion_digest" not in selection
        assert row["response_digest"] == scan_digest
        assert row["page_count"] == len(months)
        assert row["rows_fetched"] == len(months)
        selected_digests.add(selection["selected_digest"])
        facts = store._conn.execute(
            "SELECT available_at,payload FROM jquants_records "
            "WHERE dataset='fins_summary' AND json_extract(payload,'$.Code')=? "
            "ORDER BY available_at",
            (code,),
        ).fetchall()
        assert len(facts) == len(months)
        assert facts[0]["available_at"] == "2019-01-03T00:00:00+09:00"
        assert json.loads(facts[0]["payload"])["Code"] == code
    assert len(selected_digests) == len(codes)
    assert store._conn.execute(
        "SELECT DISTINCT research_state FROM personal_history_segments "
        "WHERE dataset='fins_summary'"
    ).fetchone()[0] == "PERSONAL_DRAFT"
    store.close()


def test_full_shared_scan_is_persisted_once_with_per_code_selection(
    tmp_path: Path,
) -> None:
    months = [f"2019-{month:02d}" for month in range(1, 5)]
    universe = [f"{1000 + index:04d}" for index in range(10)]
    small_codes = universe[:5]
    large_codes = universe
    small_store, small_hydrator = _hydrate_codes(
        tmp_path / "small", months, small_codes, page_universe=universe
    )
    large_store, large_hydrator = _hydrate_codes(
        tmp_path / "large", months, large_codes, page_universe=universe
    )
    small_hydrator._validate_shared_fins_scan_evidence()
    large_hydrator._validate_shared_fins_scan_evidence()

    small = _evidence_sizes(small_store)
    large = _evidence_sizes(large_store)
    assert small[3] == large[3] == 1
    assert small[2] == large[2] == 0
    assert large[0] == small[0]
    assert large[1] > small[1]
    ratio = large[1] / small[1]
    assert 1.6 <= ratio <= 2.4

    extra_months = [f"2019-{month:02d}" for month in range(1, 8)]
    wider_store, wider_hydrator = _hydrate_codes(
        tmp_path / "wider", extra_months, small_codes, page_universe=universe
    )
    wider_hydrator._validate_shared_fins_scan_evidence()
    wider = _evidence_sizes(wider_store)
    assert wider[0] > small[0]
    assert wider[3] == 1
    assert wider[2] == 0
    small_store.close()
    large_store.close()
    wider_store.close()


def test_missing_or_tampered_shared_scan_evidence_fails_closed(
    tmp_path: Path,
) -> None:
    months = ["2019-01", "2019-02", "2019-03"]
    codes = ["1001", "1002", "1003"]
    store, hydrator = _hydrate_codes(tmp_path, months, codes)
    hydrator._validate_shared_fins_scan_evidence()

    store._conn.execute("DELETE FROM personal_history_shared_scans")
    store._conn.commit()
    with pytest.raises(PersonalHistoryError, match="shared scan reference is missing"):
        hydrator._validate_shared_fins_scan_evidence()

    store.close()
    store, hydrator = _hydrate_codes(tmp_path / "pages", months, codes)
    pages = json.loads(
        store._conn.execute(
            "SELECT page_evidence_json FROM personal_history_shared_scans"
        ).fetchone()[0]
    )
    pages[0]["sha256"] = "a" * 64
    store._conn.execute(
        "UPDATE personal_history_shared_scans SET page_evidence_json=?",
        (json.dumps(pages),),
    )
    store._conn.commit()
    with pytest.raises(PersonalHistoryError, match="shared scan digest"):
        hydrator._validate_shared_fins_scan_evidence()
    store.close()

    store, hydrator = _hydrate_codes(tmp_path / "count", months, codes)
    store._conn.execute(
        "UPDATE personal_history_shared_scans SET source_row_count=source_row_count+1"
    )
    store._conn.commit()
    with pytest.raises(PersonalHistoryError, match="source row count"):
        hydrator._validate_shared_fins_scan_evidence()
    store.close()

    store, hydrator = _hydrate_codes(tmp_path / "completion", months, codes)
    store._conn.execute(
        "UPDATE personal_history_shared_scans SET completion_digest=?",
        ("sha256:" + "b" * 64,),
    )
    store._conn.commit()
    with pytest.raises(PersonalHistoryError, match="completion digest"):
        hydrator._validate_shared_fins_scan_evidence()
    store.close()

    store, hydrator = _hydrate_codes(tmp_path / "selection", months, codes)
    selection = json.loads(
        store._conn.execute(
            "SELECT selection_evidence_json FROM personal_history_segments "
            "WHERE dataset='fins_summary' LIMIT 1"
        ).fetchone()[0]
    )
    selection["selected_digest"] = "sha256:" + "c" * 64
    store._conn.execute(
        "UPDATE personal_history_segments SET selection_evidence_json=? "
        "WHERE dataset='fins_summary'",
        (json.dumps(selection),),
    )
    store._conn.commit()
    with pytest.raises(PersonalHistoryError, match="selection digest"):
        hydrator._validate_shared_fins_scan_evidence()
    store.close()


def test_caller_supplied_selection_digest_is_not_trusted(tmp_path: Path) -> None:
    client = _SharedFinsClient(["2019-01"], ["1001"])
    original = client.fetch_dataset_evidenced

    def lying_fetch(dataset: str, **params: object) -> SimpleNamespace:
        fetched = original(dataset, **params)
        fetched.selection.selected_digest = "sha256:" + "d" * 64
        return fetched

    client.fetch_dataset_evidenced = lying_fetch  # type: ignore[method-assign]
    store = SqliteStore(tmp_path / "lying.sqlite")
    hydrator = PersonalHistoryHydrator(client=client, store=store, plan=_plan())
    with pytest.raises(PersonalHistoryError, match="selection digest"):
        hydrator._hydrate_fins(frozenset({"1001"}))
    store.close()
