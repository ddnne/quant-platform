"""Revision-safe ingestion of official JSDA OTC-reference corrections."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlsplit

from data_contracts import coverage_contract_for
from storage.coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    evaluate_segment,
    read_collection_receipts,
)

from ..common.timeutil import now_iso, parse_dt, to_iso
from ..pipeline import Registrar, RunReport, _stamped, save_raw
from .fetch import JsdaFetcher
from .normalize import normalize_otc_reference_prices
from .parse import parse_otc_reference_csv, parse_otc_reference_xlsx
from .receipts import record_governed_receipt, require_jsda_receipt_authority
from .urls import (
    OTC_REFERENCE_DATASET,
    JsdaCorrectionArtifact,
    discover_otc_reference_corrections,
    discover_otc_reference_segments,
    discover_otc_reference_year_indexes,
    otc_reference_corrections_index_url,
    otc_reference_index_url,
)

_VALUE_FIELDS = (
    "coupon_rate", "maturity_date", "average_price", "average_yield",
    "median_price", "median_yield", "high_price", "high_yield",
    "low_price", "low_yield", "individual_investor_flag",
)


class CorrectionSourceGap(ValueError):
    """Correction cannot be safely applied to the captured baseline."""


@dataclass(frozen=True)
class OtcCorrectionReport:
    run_id: int
    discovered: int
    applied: int
    resumed: int
    deferred: int
    failed: int
    changed_rows: int
    revision_rows: int

    @property
    def ok(self) -> bool:
        return not (self.deferred or self.failed)

    def as_run_report(self) -> RunReport:
        if not self.ok:
            return RunReport(
                "jsda", "otc_reference_corrections",
                fetched=self.changed_rows,
                registered=self.changed_rows,
                error=(
                    f"{self.deferred} deferred correction(s), "
                    f"{self.failed} failed correction(s)"
                ),
            )
        return RunReport(
            "jsda", "otc_reference_corrections",
            fetched=self.changed_rows,
            registered=self.changed_rows,
            expected_empty=self.changed_rows == 0,
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


def _available_at(ingested_at: str, official_at: Optional[str]) -> str:
    """Later of ingested_at and official_at; never before either boundary."""
    if official_at is None:
        return ingested_at
    official = parse_dt(official_at)
    ingested = parse_dt(ingested_at)
    return to_iso(official if official >= ingested else ingested)


def _start_run(store, checked_at: str) -> int:
    cursor = store._conn.execute(  # noqa: SLF001
        "INSERT INTO ingestion_run_log (ran_at,source,runtime,status,detail) "
        "VALUES (?,?,?,'running',?)",
        (
            checked_at, "jsda", "local",
            json.dumps({"dataset": OTC_REFERENCE_DATASET, "kind": "corrections"}),
        ),
    )
    store._conn.commit()  # noqa: SLF001
    return int(cursor.lastrowid)


def _finish_run(store, report: OtcCorrectionReport) -> None:
    status = "ok" if report.ok else "partial" if report.deferred else "error"
    store._conn.execute(  # noqa: SLF001
        "UPDATE ingestion_run_log SET status=?,detail=? WHERE id=?",
        (
            status,
            json.dumps({
                "dataset": OTC_REFERENCE_DATASET,
                "kind": "corrections",
                "discovered": report.discovered,
                "applied": report.applied,
                "resumed": report.resumed,
                "deferred": report.deferred,
                "failed": report.failed,
                "changed_rows": report.changed_rows,
                "revision_rows": report.revision_rows,
            }, sort_keys=True),
            report.run_id,
        ),
    )
    store._conn.commit()  # noqa: SLF001


def _required(item: JsdaCorrectionArtifact) -> RequiredCoverageSegment:
    return RequiredCoverageSegment(
        source="jsda",
        dataset=OTC_REFERENCE_DATASET,
        segment_id=f"correction:{item.correction_id}",
        segment_start=item.affected_start,
        segment_end=item.affected_end,
        expected_scope={
            "collection_kind": "official_replacement_correction",
            "expected_item_unit": "official_correction_artifact",
            "correction_publication_label": item.correction_publication_label,
            "correction_published_at": item.correction_published_at,
            "source_format": item.source_format,
            "source_url": item.source_url,
        },
        expected_items=1,
    )


def _receipt_from_row(row: Mapping[str, Any]) -> CollectionReceipt:
    return CollectionReceipt(
        source=str(row["source"]), dataset=str(row["dataset"]),
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
        run_id=int(row["run_id"]), status=str(row["status"]),
        error=None if row["error"] is None else str(row["error"]),
        checked_at=str(row["checked_at"]),
    )


def _latest_receipt(store, required: RequiredCoverageSegment):
    rows = read_collection_receipts(
        store.path, dataset=required.dataset, segment_id=required.segment_id
    )
    candidates = [
        _receipt_from_row(row) for row in rows
        if row["segment_start"] == required.segment_start
        and row["segment_end"] == required.segment_end
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


def _parse_daily(segment, data: bytes, effective_date: str) -> list[dict]:
    kwargs = {
        "publication_label_date": segment.publication_label_date,
        "quote_effective_date": effective_date,
    }
    if segment.source_format == "csv":
        return parse_otc_reference_csv(data, **kwargs)
    if segment.source_format == "xlsx":
        return parse_otc_reference_xlsx(data, **kwargs)
    raise CorrectionSourceGap(
        f"corrected daily source format unsupported: {segment.source_format}"
    )


def _baseline(store, item: JsdaCorrectionArtifact) -> dict[tuple[str, str, str], dict]:
    cursor = store._conn.execute(  # noqa: SLF001
        "SELECT * FROM jsda_otc_bond_reference_prices "
        "WHERE publication_label_date BETWEEN ? AND ?",
        (item.affected_start, item.affected_end),
    )
    return {
        (
            str(row["publication_label_date"]),
            str(row["security_code"]),
            str(row["bond_name"]),
        ): dict(row)
        for row in cursor.fetchall()
    }


def _changed_records(
    records: Sequence[dict],
    baseline: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> list[dict]:
    if not records:
        raise CorrectionSourceGap("corrected daily source parsed zero rows")
    changed: list[dict] = []
    missing: list[str] = []
    source_keys: set[tuple[str, str, str]] = set()
    for record in records:
        key = (
            str(record.get("publication_label_date") or "")[:10],
            str(record.get("security_code") or "").strip(),
            str(record.get("bond_name") or "").strip(),
        )
        source_keys.add(key)
        current = baseline.get(key)
        if current is None:
            missing.append("/".join(key))
            continue
        if any(record.get(field) != current.get(field) for field in _VALUE_FIELDS):
            changed.append(dict(record))
    if missing:
        raise CorrectionSourceGap(
            "correction rows lack captured baseline keys: " + ", ".join(missing[:5])
        )
    source_dates = {key[0] for key in source_keys}
    omitted = [
        "/".join(key) for key in baseline
        if key[0] in source_dates and key not in source_keys
    ]
    if omitted:
        raise CorrectionSourceGap(
            "corrected daily source omits captured baseline keys: "
            + ", ".join(omitted[:5])
        )
    return changed


def run_otc_reference_corrections(
    *,
    http,
    store,
    data_base: Path,
    checked_at: Optional[str] = None,
    correction_ids: Optional[Sequence[str]] = None,
    force: bool = False,
) -> OtcCorrectionReport:
    """Apply section-1 replacement corrections as later PIT revisions."""
    checked_at = checked_at or now_iso()
    run_id = _start_run(store, checked_at)
    fetcher = JsdaFetcher(http)
    registrar = Registrar(store)
    policy = coverage_contract_for(OTC_REFERENCE_DATASET)
    authority = None
    authority_error: Optional[str] = None
    try:
        try:
            authority = require_jsda_receipt_authority()
        except RuntimeError as exc:
            authority_error = str(exc)
        correction_index_url = otc_reference_corrections_index_url()
        correction_index_raw = fetcher.fetch_file(correction_index_url)
        correction_index_path = save_raw(
            data_base, "jsda",
            _stamped("otc_reference_corrections_index.html", checked_at),
            correction_index_raw, _fetch_day(checked_at),
        )
        corrections = discover_otc_reference_corrections(
            _decode_html(correction_index_raw), base=correction_index_url
        )
        if correction_ids is not None:
            selected = set(correction_ids)
            corrections = [item for item in corrections if item.correction_id in selected]

        root_url = otc_reference_index_url()
        root_raw = fetcher.fetch_file(root_url)
        root_path = save_raw(
            data_base, "jsda", _stamped("otc_reference_index.html", checked_at),
            root_raw, _fetch_day(checked_at),
        )
        year_indexes = {
            item.year: item for item in discover_otc_reference_year_indexes(
                _decode_html(root_raw), base=root_url
            )
        }
        annual_cache: dict[int, list] = {}
        annual_evidence: dict[int, dict[str, str]] = {}
        applied = resumed = deferred = failed = changed_total = revision_total = 0

        for item in corrections:
            required = _required(item)
            previous = _latest_receipt(store, required)
            if not force and evaluate_segment(policy, required, previous)[0] == "COMPLETE":
                resumed += 1
                continue
            if (
                not force
                and previous is not None
                and previous.status == "SUCCESS"
                and int(previous.structured_row_count or 0) > 0
            ):
                # Already applied; do not double-apply on unsigned/PARTIAL SUCCESS.
                resumed += 1
                continue
            artifact_path: Optional[Path] = None
            artifact_digest: Optional[str] = None
            artifact_bytes = b""
            source_raw_pages: list[bytes] = []
            changed_records: list[dict] = []
            changed_count = structured_count = 0
            normalized_rows: list[dict] = []
            before_revisions = store.count(
                "jsda_otc_bond_reference_prices_revisions"
            )
            evidence: dict[str, Any] = {
                "correction_index_digest": _sha256(correction_index_raw),
                "correction_index_raw_path": str(correction_index_path),
                "correction_index_url": correction_index_url,
                "correction_publication_label": item.correction_publication_label,
                "correction_published_at": item.correction_published_at,
                "root_index_raw_path": str(root_path),
                "source_url": item.source_url,
            }
            try:
                artifact = fetcher.fetch_file(item.source_url)
                artifact_bytes = artifact
                source_raw_pages.append(artifact)
                artifact_name = Path(urlsplit(item.source_url).path).name
                artifact_path = save_raw(
                    data_base, "jsda", _stamped(artifact_name, checked_at),
                    artifact, _fetch_day(checked_at),
                )
                artifact_digest = _sha256(artifact)
                evidence.update({
                    "raw": artifact_digest,
                    "raw_path": str(artifact_path),
                    "fetched_at": checked_at,
                })
                if item.source_format == "pdf":
                    raise CorrectionSourceGap(
                        "official correction is PDF-only and cannot be applied safely"
                    )
                baseline = _baseline(store, item)
                if not baseline:
                    raise CorrectionSourceGap(
                        "no captured baseline exists for affected publication range"
                    )
                daily_segments = []
                for year in range(
                    int(item.affected_start[:4]), int(item.affected_end[:4]) + 1
                ):
                    if year not in annual_cache:
                        index = year_indexes.get(year)
                        if index is None:
                            raise CorrectionSourceGap(
                                f"official annual archive index missing for {year}"
                            )
                        annual_raw = fetcher.fetch_file(index.url)
                        annual_path = save_raw(
                            data_base, "jsda",
                            _stamped(f"otc_reference_archive_{year}.html", checked_at),
                            annual_raw, _fetch_day(checked_at),
                        )
                        annual_cache[year] = discover_otc_reference_segments(
                            _decode_html(annual_raw), year=year, index_url=index.url
                        )
                        annual_evidence[year] = {
                            "digest": _sha256(annual_raw), "raw_path": str(annual_path)
                        }
                    daily_segments.extend(
                        segment for segment in annual_cache[year]
                        if item.affected_start
                        <= segment.publication_label_date
                        <= item.affected_end
                    )
                if not daily_segments:
                    raise CorrectionSourceGap(
                        "no official daily source found in affected publication range"
                    )

                corrected_source_evidence = []
                availability = _available_at(
                    checked_at, item.correction_published_at
                )
                for segment in daily_segments:
                    if segment.source_url is None:
                        raise CorrectionSourceGap(
                            f"corrected daily source link missing for {segment.segment_id}"
                        )
                    effective_dates = {
                        str(row["quote_effective_date"])
                        for key, row in baseline.items()
                        if key[0] == segment.publication_label_date
                    }
                    if len(effective_dates) != 1:
                        raise CorrectionSourceGap(
                            "captured baseline does not provide one effective date for "
                            + segment.publication_label_date
                        )
                    daily_raw = fetcher.fetch_file(segment.source_url)
                    source_raw_pages.append(daily_raw)
                    daily_name = Path(urlsplit(segment.source_url).path).name
                    daily_path = save_raw(
                        data_base, "jsda", _stamped(daily_name, checked_at),
                        daily_raw, _fetch_day(checked_at),
                    )
                    daily_digest = _sha256(daily_raw)
                    parsed = _parse_daily(
                        segment, daily_raw, next(iter(effective_dates))
                    )
                    changed = _changed_records(parsed, baseline)
                    changed_records.extend(changed)
                    changed_count += len(changed)
                    rows = normalize_otc_reference_prices(
                        changed,
                        ingested_at=checked_at,
                        available_at=availability,
                        source_url=segment.source_url,
                        raw_digest=daily_digest,
                        segment_id=required.segment_id,
                        source_format=str(segment.source_format),
                        correction_publication_label=(
                            item.correction_publication_label
                        ),
                        correction_published_at=item.correction_published_at,
                        correction_source_url=item.source_url,
                        correction_raw_digest=artifact_digest,
                    )
                    normalized_rows.extend(rows)
                    corrected_source_evidence.append({
                        "digest": daily_digest,
                        "publication_label_date": segment.publication_label_date,
                        "raw_path": str(daily_path),
                        "url": segment.source_url,
                    })
                if not normalized_rows:
                    # Already at corrected values — resume, do not stamp empty SUCCESS.
                    resumed += 1
                    continue
                if authority is None:
                    raise RuntimeError(
                        authority_error
                        or "receipt signing key not configured"
                    )
                # Whole affected range in one transaction — no partial correction.
                structured_count = registrar.register(
                    "jsda_otc_bond_reference_prices", normalized_rows
                )
                evidence.update({
                    "annual_indexes": annual_evidence,
                    "corrected_sources": corrected_source_evidence,
                })
                after_revisions = store.count(
                    "jsda_otc_bond_reference_prices_revisions"
                )
                revision_count = after_revisions - before_revisions
                _record(
                    store, required=required, run_id=run_id,
                    checked_at=checked_at, status="SUCCESS", error=None,
                    pagination_exhausted=True, digests=evidence,
                    authority=authority,
                    raw_pages=source_raw_pages,
                    raw_records=changed_records,
                    structured_records=normalized_rows,
                )
                applied += 1
                changed_total += changed_count
                revision_total += revision_count
            except Exception as exc:  # noqa: BLE001
                is_deferred = isinstance(exc, CorrectionSourceGap)
                evidence.update({
                    "raw": artifact_digest,
                    "raw_path": None if artifact_path is None else str(artifact_path),
                    "failure_kind": (
                        "DEFERRED_SOURCE_GAP" if is_deferred else "COLLECTION_FAILURE"
                    ),
                })
                _record(
                    store, required=required, run_id=run_id,
                    checked_at=checked_at, status="FAILED", error=str(exc),
                    observed_items=1 if artifact_path is not None else 0,
                    raw_page_count=1 if artifact_path is not None else 0,
                    raw_row_count=changed_count,
                    structured_row_count=structured_count,
                    pagination_exhausted=False, digests=evidence,
                    raw_pages=source_raw_pages,
                )
                deferred += int(is_deferred)
                failed += int(not is_deferred)

        report = OtcCorrectionReport(
            run_id=run_id, discovered=len(corrections), applied=applied,
            resumed=resumed, deferred=deferred, failed=failed,
            changed_rows=changed_total, revision_rows=revision_total,
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
    "CorrectionSourceGap", "OtcCorrectionReport",
    "run_otc_reference_corrections",
]
