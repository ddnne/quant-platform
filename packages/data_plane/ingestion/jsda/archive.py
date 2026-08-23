"""Resumable governed ingestion for the JSDA OTC-reference archive."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import urlsplit

from data_contracts import coverage_contract_for
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
from .normalize import normalize_otc_reference_prices
from .parse import parse_otc_reference_csv, parse_otc_reference_xlsx
from .receipts import record_governed_receipt, require_jsda_receipt_authority
from .urls import (
    OTC_REFERENCE_DATASET,
    JsdaArchiveSegment,
    discover_otc_reference_segments,
    discover_otc_reference_year_indexes,
    otc_reference_index_url,
)

_FIRST_PUBLICATION_LABEL = "2002-08-02"
_FIRST_QUOTE_EFFECTIVE_DATE = "2002-08-01"


@dataclass(frozen=True)
class OtcArchiveBackfillReport:
    run_id: int
    discovered: int
    completed: int
    resumed: int
    failed: int
    required_segments: tuple[RequiredCoverageSegment, ...]

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.completed + self.resumed == self.discovered

    def as_run_report(self) -> RunReport:
        if self.failed:
            return RunReport(
                "jsda",
                "otc_reference_archive",
                fetched=self.completed,
                registered=self.completed,
                error=f"{self.failed} expected archive segment(s) incomplete",
            )
        return RunReport(
            "jsda",
            "otc_reference_archive",
            fetched=self.completed,
            registered=self.completed + self.resumed,
            expected_empty=self.discovered == 0,
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


def _fetch_day(iso_timestamp: str) -> str:
    return parse_dt(iso_timestamp).date().isoformat()


def _start_run(store, checked_at: str, from_year: int, to_year: int) -> int:
    cursor = store._conn.execute(  # noqa: SLF001
        "INSERT INTO ingestion_run_log (ran_at,source,runtime,status,detail) "
        "VALUES (?,?,?,'running',?)",
        (
            checked_at,
            "jsda",
            "local",
            json.dumps({
                "dataset": OTC_REFERENCE_DATASET,
                "from_year": from_year,
                "to_year": to_year,
            }, sort_keys=True),
        ),
    )
    store._conn.commit()  # noqa: SLF001
    return int(cursor.lastrowid)


def _finish_run(store, run_id: int, report: OtcArchiveBackfillReport) -> None:
    store._conn.execute(  # noqa: SLF001
        "UPDATE ingestion_run_log SET status=?, detail=? WHERE id=?",
        (
            "ok" if report.ok else "partial",
            json.dumps({
                "dataset": OTC_REFERENCE_DATASET,
                "discovered": report.discovered,
                "completed": report.completed,
                "resumed": report.resumed,
                "failed": report.failed,
            }, sort_keys=True),
            run_id,
        ),
    )
    store._conn.commit()  # noqa: SLF001


def _required(segment: JsdaArchiveSegment) -> RequiredCoverageSegment:
    return RequiredCoverageSegment(
        source="jsda",
        dataset=OTC_REFERENCE_DATASET,
        segment_id=segment.segment_id,
        segment_start=segment.segment_start,
        segment_end=segment.segment_end,
        expected_scope=dict(segment.expected_scope),
        expected_items=1,
    )


def _missing_year_required(year: int, root_url: str) -> RequiredCoverageSegment:
    return RequiredCoverageSegment(
        source="jsda",
        dataset=OTC_REFERENCE_DATASET,
        segment_id=f"archive-index:{year:04d}",
        segment_start=f"{year:04d}-01-01",
        segment_end=f"{year:04d}-12-31",
        expected_scope={
            "coverage_mode": "official_archive_index_reconciled",
            "expected_frequency": "trading_day",
            "expected_item_unit": "official_archive_index",
            "root_index_url": root_url,
            "year": year,
            "universe_rule": "all_bonds_in_official_publication_file",
        },
        expected_items=1,
    )


def _receipt_objects(rows: Iterable[Mapping[str, Any]]) -> list[CollectionReceipt]:
    out: list[CollectionReceipt] = []
    for row in rows:
        expected_scope = json.loads(str(row["expected_scope"]))
        digests = json.loads(str(row["digests_json"]))
        out.append(CollectionReceipt(
            source=str(row["source"]),
            dataset=str(row["dataset"]),
            segment_id=str(row["segment_id"]),
            segment_start=str(row["segment_start"]),
            segment_end=str(row["segment_end"]),
            expected_scope=expected_scope,
            expected_items=(
                None if row["expected_items"] is None
                else int(row["expected_items"])
            ),
            observed_items=int(row["observed_items"]),
            raw_page_count=int(row["raw_page_count"]),
            raw_row_count=int(row["raw_row_count"]),
            structured_row_count=int(row["structured_row_count"]),
            pagination_exhausted=bool(row["pagination_exhausted"]),
            digests=digests,
            run_id=int(row["run_id"]),
            status=str(row["status"]),
            error=None if row["error"] is None else str(row["error"]),
            checked_at=str(row["checked_at"]),
        ))
    return out


def _latest_matching_receipt(
    required: RequiredCoverageSegment,
    receipts: Sequence[CollectionReceipt],
) -> Optional[CollectionReceipt]:
    candidates = [
        receipt for receipt in receipts
        if receipt.source == required.source
        and receipt.dataset == required.dataset
        and receipt.segment_id == required.segment_id
        and receipt.segment_start == required.segment_start
        and receipt.segment_end == required.segment_end
    ]
    return max(
        candidates, key=lambda item: (item.checked_at, item.run_id), default=None
    )


def _record(
    store,
    *,
    required: RequiredCoverageSegment,
    run_id: int,
    checked_at: str,
    status: str,
    error: Optional[str],
    observed_items: int,
    raw_page_count: int,
    raw_row_count: int,
    structured_row_count: int,
    pagination_exhausted: bool,
    digests: Mapping[str, Any],
    authority=None,
    raw: bytes = b"",
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
        raw=raw,
    )


def _quote_effective_dates(
    segments: Sequence[JsdaArchiveSegment],
    *,
    stored_labels: Sequence[str] = (),
) -> dict[str, str]:
    labels = sorted({
        *(item.publication_label_date for item in segments),
        *(str(item)[:10] for item in stored_labels),
    })
    effective: dict[str, str] = {}
    for index, label in enumerate(labels):
        if label == _FIRST_PUBLICATION_LABEL:
            effective[label] = _FIRST_QUOTE_EFFECTIVE_DATE
        elif index > 0:
            # Publication label is the next business day; previous label is the quote day.
            effective[label] = labels[index - 1]
    return effective


def _stored_publication_labels(store) -> list[str]:
    return [
        str(row[0])
        for row in store._conn.execute(  # noqa: SLF001
            "SELECT DISTINCT publication_label_date "
            "FROM jsda_otc_bond_reference_prices"
        ).fetchall()
    ]


def _save_index_raw(
    data_base: Path,
    name: str,
    data: bytes,
    checked_at: str,
) -> Path:
    return save_raw(
        data_base,
        "jsda",
        _stamped(name, checked_at),
        data,
        _fetch_day(checked_at),
    )


def run_otc_reference_backfill(
    *,
    http,
    store,
    data_base: Path,
    from_year: int = 2002,
    to_year: Optional[int] = None,
    checked_at: Optional[str] = None,
    force: bool = False,
) -> OtcArchiveBackfillReport:
    """Discover and ingest official OTC-reference files one day at a time."""
    checked_at = checked_at or now_iso()
    to_year = to_year or date.today().year
    if from_year < 2002 or to_year < from_year:
        raise ValueError("OTC archive range must satisfy 2002 <= from_year <= to_year")

    policy = coverage_contract_for(OTC_REFERENCE_DATASET)
    fetcher = JsdaFetcher(http)
    registrar = Registrar(store)
    run_id = _start_run(store, checked_at, from_year, to_year)
    root_url = otc_reference_index_url()
    requirements: list[RequiredCoverageSegment] = []
    selected_segments: list[JsdaArchiveSegment] = []
    index_digests: dict[str, str] = {}
    authority = None
    authority_error: Optional[str] = None

    try:
        try:
            authority = require_jsda_receipt_authority()
        except RuntimeError as exc:
            authority_error = str(exc)
        root_raw = fetcher.fetch_file(root_url)
        root_path = _save_index_raw(
            data_base, "otc_reference_archive_index.html", root_raw, checked_at
        )
        root_digest = _sha256(root_raw)
        year_indexes = discover_otc_reference_year_indexes(
            _decode_html(root_raw), base=root_url
        )
        by_year = {item.year: item for item in year_indexes}

        # Preceding archive page is calendar lookback, not this run's inventory.
        discovery_years = list(range(from_year, to_year + 1))
        if from_year - 1 in by_year:
            discovery_years.insert(0, from_year - 1)
        all_discovered: list[JsdaArchiveSegment] = []
        for year in discovery_years:
            archive_index = by_year.get(year)
            if archive_index is None:
                if year >= from_year:
                    requirements.append(_missing_year_required(year, root_url))
                continue
            year_raw = fetcher.fetch_file(archive_index.url)
            _save_index_raw(
                data_base, f"otc_reference_archive_{year}.html", year_raw, checked_at
            )
            index_digests[str(year)] = _sha256(year_raw)
            segments = discover_otc_reference_segments(
                _decode_html(year_raw), year=year, index_url=archive_index.url
            )
            all_discovered.extend(segments)
            if year >= from_year:
                selected_segments.extend(segments)
                requirements.extend(_required(segment) for segment in segments)

        pending_years = [
            item.year for item in year_indexes
            if item.year >= 2002 and not (from_year <= item.year <= to_year)
        ]
        pending_requirements = [
            _missing_year_required(year, root_url) for year in pending_years
        ]
        for year in range(from_year, to_year + 1):
            store._conn.execute(  # noqa: SLF001
                "DELETE FROM coverage_segments WHERE source='jsda' AND dataset=? "
                "AND segment_id=?",
                (OTC_REFERENCE_DATASET, f"archive-index:{year:04d}"),
            )
        record_required_segments(
            store._conn, [*requirements, *pending_requirements]  # noqa: SLF001
        )
        store._conn.commit()  # noqa: SLF001

        prior_receipts = _receipt_objects(read_collection_receipts(
            store.path, dataset=OTC_REFERENCE_DATASET
        ))
        effective_dates = _quote_effective_dates(
            all_discovered,
            stored_labels=_stored_publication_labels(store),
        )
        segment_by_id = {segment.segment_id: segment for segment in selected_segments}
        completed = resumed = failed = 0

        for required in requirements:
            previous = _latest_matching_receipt(required, prior_receipts)
            if not force and evaluate_segment(policy, required, previous)[0] == "COMPLETE":
                resumed += 1
                continue
            segment = segment_by_id.get(required.segment_id)
            if segment is None or segment.source_url is None:
                reason = (
                    "official annual archive index missing"
                    if segment is None
                    else "official archive row has no source file link"
                )
                _record(
                    store,
                    required=required,
                    run_id=run_id,
                    checked_at=checked_at,
                    status="FAILED",
                    error=reason,
                    observed_items=0,
                    raw_page_count=0,
                    raw_row_count=0,
                    structured_row_count=0,
                    pagination_exhausted=False,
                    digests={
                        "failure_kind": "MISSING_EXPECTED_SEGMENT",
                        "root_index_raw": str(root_path),
                        "root_index_digest": root_digest,
                    },
                )
                failed += 1
                continue

            raw_path: Optional[Path] = None
            raw_digest: Optional[str] = None
            raw_bytes = b""
            raw_rows = structured_rows = 0
            try:
                data = fetcher.fetch_file(segment.source_url)
                raw_bytes = data
                filename = Path(urlsplit(segment.source_url).path).name or (
                    f"otc_reference_{segment.segment_id}.{segment.source_format}"
                )
                raw_path = save_raw(
                    data_base,
                    "jsda",
                    _stamped(filename, checked_at),
                    data,
                    _fetch_day(checked_at),
                )
                raw_digest = _sha256(data)
                effective_date = effective_dates.get(segment.publication_label_date)
                if effective_date is None:
                    raise ValueError(
                        "calendar-resolved quote effective date unavailable"
                    )
                if segment.source_format == "csv":
                    records = parse_otc_reference_csv(
                        data,
                        publication_label_date=segment.publication_label_date,
                        quote_effective_date=effective_date,
                    )
                elif segment.source_format == "xlsx":
                    records = parse_otc_reference_xlsx(
                        data,
                        publication_label_date=segment.publication_label_date,
                        quote_effective_date=effective_date,
                    )
                else:
                    raise ValueError(
                        f"unsupported OTC archive format: {segment.source_format}"
                    )
                raw_rows = len(records)
                if raw_rows == 0:
                    raise ValueError("official OTC archive file parsed zero rows")
                if authority is None:
                    raise RuntimeError(
                        authority_error
                        or "receipt signing key not configured"
                    )
                rows = normalize_otc_reference_prices(
                    records,
                    ingested_at=checked_at,
                    source_url=segment.source_url,
                    raw_digest=raw_digest,
                    segment_id=segment.segment_id,
                    source_format=str(segment.source_format),
                )
                structured_rows = registrar.register(
                    "jsda_otc_bond_reference_prices", rows
                )
                _record(
                    store,
                    required=required,
                    run_id=run_id,
                    checked_at=checked_at,
                    status="SUCCESS",
                    error=None,
                    observed_items=1,
                    raw_page_count=1,
                    raw_row_count=raw_rows,
                    structured_row_count=structured_rows,
                    pagination_exhausted=True,
                    digests={
                        "raw": raw_digest,
                        "source_url": segment.source_url,
                        "fetched_at": checked_at,
                        "raw_path": str(raw_path),
                        "archive_index": index_digests.get(
                            segment.publication_label_date[:4]
                        ),
                    },
                    authority=authority,
                    raw=raw_bytes,
                )
                completed += 1
            except Exception as exc:  # noqa: BLE001
                _record(
                    store,
                    required=required,
                    run_id=run_id,
                    checked_at=checked_at,
                    status="FAILED",
                    error=str(exc),
                    observed_items=1 if raw_path is not None else 0,
                    raw_page_count=1 if raw_path is not None else 0,
                    raw_row_count=raw_rows,
                    structured_row_count=structured_rows,
                    pagination_exhausted=False,
                    digests={
                        "raw": raw_digest,
                        "source_url": segment.source_url,
                        "fetched_at": checked_at,
                        "raw_path": None if raw_path is None else str(raw_path),
                    },
                    raw=raw_bytes,
                )
                failed += 1

        report = OtcArchiveBackfillReport(
            run_id=run_id,
            discovered=len(requirements),
            completed=completed,
            resumed=resumed,
            failed=failed,
            required_segments=tuple(requirements),
        )
        refresh_coverage_ledger(
            store._conn,  # noqa: SLF001
            store.path,
            datasets=[OTC_REFERENCE_DATASET],
            today=_fetch_day(checked_at),
        )
        _finish_run(store, run_id, report)
        return report
    except Exception as exc:
        store._conn.execute(  # noqa: SLF001
            "UPDATE ingestion_run_log SET status='error', detail=? WHERE id=?",
            (str(exc), run_id),
        )
        store._conn.commit()  # noqa: SLF001
        raise


__all__ = ["OtcArchiveBackfillReport", "run_otc_reference_backfill"]
