"""Governed, resumable ingestion for JSDA's Tokyo Repo Rate history."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlsplit

from data_contracts import coverage_contract_for, jsda_contract_for
from storage.coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    evaluate_segment,
    read_collection_receipts,
    record_required_segments,
    refresh_coverage_ledger,
)

from ..common.timeutil import now_iso, parse_dt
from ..pipeline import Registrar, RunReport, _stamped, save_raw
from .fetch import JsdaFetcher
from .normalize import normalize_repo_rates
from .parse import parse_repo_csv, parse_repo_xls, parse_repo_xlsx
from .receipts import record_governed_receipt, require_jsda_receipt_authority
from .urls import (
    TOKYO_REPO_DATASET,
    TOKYO_REPO_JSDA_START,
    discover_repo_timeseries,
    repo_index_url,
)


class RepoSourceGap(ValueError):
    """The official workbook cannot prove the complete governed interval."""


@dataclass(frozen=True)
class TokyoRepoBackfillReport:
    run_id: int
    completed: int
    resumed: int
    deferred: int
    failed: int
    raw_rows: int
    structured_rows: int
    required_segment: RequiredCoverageSegment

    @property
    def ok(self) -> bool:
        return self.completed + self.resumed == 1 and not (
            self.deferred or self.failed
        )

    def as_run_report(self) -> RunReport:
        if self.deferred or self.failed:
            return RunReport(
                "jsda",
                "tokyo_repo_timeseries",
                fetched=self.raw_rows,
                registered=self.structured_rows,
                error=(
                    f"{self.deferred} deferred source gap(s), "
                    f"{self.failed} failed segment(s)"
                ),
            )
        return RunReport(
            "jsda",
            "tokyo_repo_timeseries",
            fetched=self.raw_rows,
            registered=self.structured_rows,
            expected_empty=self.resumed == 1,
        )


def _decode_html(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp932", "shift_jis"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _fetch_day(timestamp: str) -> str:
    return parse_dt(timestamp).date().isoformat()


def _start_run(store, checked_at: str) -> int:
    cursor = store._conn.execute(  # noqa: SLF001
        "INSERT INTO ingestion_run_log (ran_at,source,runtime,status,detail) "
        "VALUES (?,?,?,'running',?)",
        (
            checked_at,
            "jsda",
            "local",
            json.dumps({"dataset": TOKYO_REPO_DATASET}, sort_keys=True),
        ),
    )
    store._conn.commit()  # noqa: SLF001
    return int(cursor.lastrowid)


def _finish_run(store, report: TokyoRepoBackfillReport) -> None:
    status = "ok" if report.ok else "partial" if report.deferred else "error"
    store._conn.execute(  # noqa: SLF001
        "UPDATE ingestion_run_log SET status=?,detail=? WHERE id=?",
        (
            status,
            json.dumps({
                "dataset": TOKYO_REPO_DATASET,
                "completed": report.completed,
                "resumed": report.resumed,
                "deferred": report.deferred,
                "failed": report.failed,
                "raw_rows": report.raw_rows,
                "structured_rows": report.structured_rows,
            }, sort_keys=True),
            report.run_id,
        ),
    )
    store._conn.commit()  # noqa: SLF001


def _required(discovery, checked_at: str) -> RequiredCoverageSegment:
    segment_end = discovery.latest_publication_date or _fetch_day(checked_at)
    return RequiredCoverageSegment(
        source="jsda",
        dataset=TOKYO_REPO_DATASET,
        segment_id=discovery.segment_id,
        segment_start=TOKYO_REPO_JSDA_START,
        segment_end=segment_end,
        expected_scope={
            "coverage_mode": "authoritative_time_series_reconciled",
            "expected_frequency": "trading_day",
            "expected_item_unit": "official_full_timeseries_file",
            "history_target_start": TOKYO_REPO_JSDA_START,
            "index_url": discovery.index_url,
            "latest_publication_date": discovery.latest_publication_date,
            "source_format": discovery.source_format,
            "source_url": discovery.source_url,
            "universe_rule": "all_tenors_and_publication_days_in_official_timeseries_file",
        },
        expected_items=1,
    )


def _receipt_from_row(row: Mapping[str, Any]) -> CollectionReceipt:
    return CollectionReceipt(
        source=str(row["source"]),
        dataset=str(row["dataset"]),
        segment_id=str(row["segment_id"]),
        segment_start=str(row["segment_start"]),
        segment_end=str(row["segment_end"]),
        expected_scope=json.loads(str(row["expected_scope"])),
        expected_items=(
            None if row["expected_items"] is None else int(row["expected_items"])
        ),
        observed_items=int(row["observed_items"]),
        raw_page_count=int(row["raw_page_count"]),
        raw_row_count=int(row["raw_row_count"]),
        structured_row_count=int(row["structured_row_count"]),
        pagination_exhausted=bool(row["pagination_exhausted"]),
        digests=json.loads(str(row["digests_json"])),
        run_id=int(row["run_id"]),
        status=str(row["status"]),
        error=None if row["error"] is None else str(row["error"]),
        checked_at=str(row["checked_at"]),
    )


def _latest_receipt(store, required: RequiredCoverageSegment):
    rows = read_collection_receipts(
        store.path, dataset=TOKYO_REPO_DATASET, segment_id=required.segment_id
    )
    exact = [
        _receipt_from_row(row) for row in rows
        if row["segment_start"] == required.segment_start
        and row["segment_end"] == required.segment_end
    ]
    return max(exact, key=lambda item: (item.checked_at, item.run_id), default=None)


def _record(
    store,
    *,
    required: RequiredCoverageSegment,
    run_id: int,
    checked_at: str,
    status: str,
    error: Optional[str],
    observed_items: int | None = None,
    raw_page_count: int | None = None,
    raw_row_count: int | None = None,
    structured_row_count: int | None = None,
    pagination_exhausted: bool,
    digests: Mapping[str, Any],
    authority=None,
    raw_pages: Sequence[bytes] = (),
    raw_records: Sequence[Any] = (),
    structured_records: Sequence[Mapping[str, Any]] = (),
) -> None:
    record_governed_receipt(
        store,
        required=required,
        run_id=run_id,
        checked_at=checked_at,
        status=status,
        error=error,
        observed_items=observed_items,
        raw_page_count=raw_page_count,
        raw_row_count=raw_row_count,
        structured_row_count=structured_row_count,
        pagination_exhausted=pagination_exhausted,
        digests=digests,
        authority=authority,
        raw_pages=raw_pages,
        raw_records=raw_records,
        structured_records=structured_records,
    )


def _parse(data: bytes, source_format: Optional[str]) -> list[dict]:
    if source_format == "xls":
        return parse_repo_xls(data)
    if source_format == "xlsx":
        return parse_repo_xlsx(data)
    if source_format == "csv":
        return parse_repo_csv(data)
    raise ValueError(f"unsupported Tokyo Repo Rate format: {source_format}")


def _governed_records(records: list[dict], latest: str) -> list[dict]:
    governed = [
        row for row in records
        if TOKYO_REPO_JSDA_START <= str(row.get("as_of_date") or "")[:10] <= latest
    ]
    if not governed:
        raise RepoSourceGap("official workbook contains no JSDA-era observations")
    dates = sorted({str(row["as_of_date"])[:10] for row in governed})
    reasons: list[str] = []
    if dates[0] != TOKYO_REPO_JSDA_START:
        reasons.append(
            f"first JSDA-era observation is {dates[0]}, expected {TOKYO_REPO_JSDA_START}"
        )
    if dates[-1] != latest:
        reasons.append(f"latest workbook observation is {dates[-1]}, expected {latest}")
    years = {int(item[:4]) for item in dates}
    missing_years = [
        year for year in range(2012, int(latest[:4]) + 1) if year not in years
    ]
    if missing_years:
        reasons.append("missing calendar years: " + ",".join(map(str, missing_years)))
    natural_keys = [
        (str(row["as_of_date"])[:10], str(row.get("tenor") or ""))
        for row in governed
    ]
    if len(natural_keys) != len(set(natural_keys)):
        reasons.append("duplicate as_of_date/tenor observations")
    if reasons:
        raise RepoSourceGap("; ".join(reasons))
    return governed


def run_tokyo_repo_backfill(
    *,
    http,
    store,
    data_base: Path,
    checked_at: Optional[str] = None,
    force: bool = False,
) -> TokyoRepoBackfillReport:
    """Ingest and reconcile JSDA's complete authoritative TRR workbook."""
    checked_at = checked_at or now_iso()
    contract = jsda_contract_for(TOKYO_REPO_DATASET)
    if contract.history_target_start != TOKYO_REPO_JSDA_START:
        raise ValueError("Tokyo Repo Rate contract/start constant mismatch")
    policy = coverage_contract_for(TOKYO_REPO_DATASET)
    fetcher = JsdaFetcher(http)
    registrar = Registrar(store)
    run_id = _start_run(store, checked_at)
    authority = None
    authority_error: Optional[str] = None

    try:
        try:
            authority = require_jsda_receipt_authority()
        except RuntimeError as exc:
            authority_error = str(exc)
        index_url = repo_index_url()
        index_raw = fetcher.fetch_file(index_url)
        index_path = save_raw(
            data_base,
            "jsda",
            _stamped("tokyo_repo_index.html", checked_at),
            index_raw,
            _fetch_day(checked_at),
        )
        index_digest = _sha256(index_raw)
        discovery = discover_repo_timeseries(_decode_html(index_raw), base=index_url)
        required = _required(discovery, checked_at)
        record_required_segments(store._conn, [required])  # noqa: SLF001
        store._conn.commit()  # noqa: SLF001

        previous = _latest_receipt(store, required)
        if not force and evaluate_segment(policy, required, previous)[0] == "COMPLETE":
            report = TokyoRepoBackfillReport(
                run_id, 0, 1, 0, 0, 0, 0, required
            )
            # Tokyo repo is not official-archive-index. Explicit None is omit-honesty.
            refresh_coverage_ledger(
                store._conn, store.path,  # noqa: SLF001
                datasets=[TOKYO_REPO_DATASET],
                today=required.segment_end,
                index_text=None,
            )
            _finish_run(store, report)
            return report

        base_evidence = {
            "index_digest": index_digest,
            "index_raw_path": str(index_path),
            "index_url": index_url,
            "latest_publication_date": discovery.latest_publication_date,
            "source_url": discovery.source_url,
        }
        if discovery.discovery_status != "DISCOVERED":
            error = "official index discovery incomplete: " + discovery.discovery_status
            _record(
                store,
                required=required,
                run_id=run_id,
                checked_at=checked_at,
                status="FAILED",
                error=error,
                observed_items=0,
                raw_page_count=0,
                raw_row_count=0,
                structured_row_count=0,
                pagination_exhausted=False,
                digests={**base_evidence, "failure_kind": "DEFERRED_SOURCE_GAP"},
            )
            report = TokyoRepoBackfillReport(
                run_id, 0, 0, 1, 0, 0, 0, required
            )
        else:
            raw_path: Optional[Path] = None
            raw_digest: Optional[str] = None
            raw_bytes = b""
            parsed_rows = source_parsed_rows = structured_rows = 0
            try:
                assert discovery.source_url is not None
                assert discovery.latest_publication_date is not None
                data = fetcher.fetch_file(discovery.source_url)
                raw_bytes = data
                filename = Path(urlsplit(discovery.source_url).path).name or "trrts.xls"
                raw_path = save_raw(
                    data_base,
                    "jsda",
                    _stamped(filename, checked_at),
                    data,
                    _fetch_day(checked_at),
                )
                raw_digest = _sha256(data)
                all_records = _parse(data, discovery.source_format)
                source_parsed_rows = len(all_records)
                parsed_rows = sum(
                    TOKYO_REPO_JSDA_START
                    <= str(row.get("as_of_date") or "")[:10]
                    <= discovery.latest_publication_date
                    for row in all_records
                )
                governed = _governed_records(
                    all_records, discovery.latest_publication_date
                )
                parsed_rows = len(governed)
                if authority is None:
                    raise RuntimeError(
                        authority_error
                        or "receipt signing key not configured"
                    )
                rows = normalize_repo_rates(governed, ingested_at=checked_at)
                structured_rows = registrar.register("jsda_repo_rates", rows)
                _record(
                    store,
                    required=required,
                    run_id=run_id,
                    checked_at=checked_at,
                    status="SUCCESS",
                    error=None,
                    pagination_exhausted=True,
                    digests={
                        **base_evidence,
                        "raw": raw_digest,
                        "raw_path": str(raw_path),
                        "fetched_at": checked_at,
                        "source_parsed_rows": source_parsed_rows,
                    },
                    authority=authority,
                    raw_pages=(raw_bytes,),
                    raw_records=governed,
                    structured_records=rows,
                )
                report = TokyoRepoBackfillReport(
                    run_id, 1, 0, 0, 0, parsed_rows, structured_rows, required
                )
            except Exception as exc:  # noqa: BLE001
                deferred = isinstance(exc, RepoSourceGap)
                _record(
                    store,
                    required=required,
                    run_id=run_id,
                    checked_at=checked_at,
                    status="FAILED",
                    error=str(exc),
                    observed_items=1 if raw_path is not None else 0,
                    raw_page_count=1 if raw_path is not None else 0,
                    raw_row_count=parsed_rows,
                    structured_row_count=structured_rows,
                    pagination_exhausted=False,
                    digests={
                        **base_evidence,
                        "raw": raw_digest,
                        "raw_path": None if raw_path is None else str(raw_path),
                        "fetched_at": checked_at,
                        "source_parsed_rows": source_parsed_rows,
                        "failure_kind": (
                            "DEFERRED_SOURCE_GAP" if deferred else "COLLECTION_FAILURE"
                        ),
                    },
                    raw_pages=(raw_bytes,) if raw_bytes else (),
                )
                report = TokyoRepoBackfillReport(
                    run_id, 0, 0, int(deferred), int(not deferred),
                    parsed_rows, structured_rows, required
                )

        # Tokyo repo is not official-archive-index. Explicit None is omit-honesty.
        refresh_coverage_ledger(
            store._conn, store.path,  # noqa: SLF001
            datasets=[TOKYO_REPO_DATASET],
            today=required.segment_end,
            index_text=None,
        )
        _finish_run(store, report)
        return report
    except Exception as exc:
        store._conn.execute(  # noqa: SLF001
            "UPDATE ingestion_run_log SET status='error',detail=? WHERE id=?",
            (str(exc), run_id),
        )
        store._conn.commit()  # noqa: SLF001
        raise


__all__ = [
    "RepoSourceGap", "TokyoRepoBackfillReport", "run_tokyo_repo_backfill"
]
