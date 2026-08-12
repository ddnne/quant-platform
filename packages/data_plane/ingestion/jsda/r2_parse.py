"""JSDA R2 mirror parse — staging only, never false COMPLETE receipts.

Phase 6.2.3: this path must NOT write Trusted COMPLETE receipts from
parse-count alone. Formal path is:

  CF raw → R2 → source-specific adapter → fact table → independent re-read
  → reconcile → signed receipt → Coverage

This module only:
  * discovers raw artifacts
  * parses into staging rows (in-memory or staging table)
  * emits PARSED_STAGING_ONLY non-COMPLETE evidence
"""

from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from storage.coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    compute_raw_digest,
    record_collection_receipt,
)


@dataclass(frozen=True)
class JsdaRawArtifact:
    dataset: str
    segment_id: str
    path: Path
    digest: str
    source_url: str | None = None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def discover_local_jsda_raw(
    raw_root: Path,
    *,
    datasets: Sequence[str] | None = None,
) -> list[JsdaRawArtifact]:
    root = Path(raw_root)
    if not root.is_dir():
        return []
    allow = set(datasets) if datasets else {
        "jsda_otc_bond_reference_prices",
        "jsda_tokyo_repo_rates",
        "jsda_corporate_bond_transactions",
    }
    out: list[JsdaRawArtifact] = []
    base = root / "jsda" if (root / "jsda").is_dir() else root
    if not base.is_dir():
        return []
    for dataset_dir in sorted(base.iterdir()):
        if not dataset_dir.is_dir() or dataset_dir.name not in allow:
            continue
        for path in sorted(dataset_dir.rglob("*")):
            if not path.is_file():
                continue
            if "manifest" in path.name.lower() or path.name.startswith("MANIFEST"):
                continue
            if path.suffix.lower() not in {".csv", ".xls", ".xlsx"}:
                continue
            segment_id = path.parent.name if path.parent != dataset_dir else path.stem
            # Forbid placeholder 1970 segments — require real identity from path.
            if segment_id in {"1970-01-01", "unknown"}:
                segment_id = f"file_{path.stem}"
            out.append(
                JsdaRawArtifact(
                    dataset=dataset_dir.name,
                    segment_id=segment_id,
                    path=path,
                    digest=_sha256_file(path),
                )
            )
    return out


def parse_artifact_rows(artifact: JsdaRawArtifact) -> list[dict[str, Any]]:
    """Parse raw bytes into row dicts. Parser errors raise (not counted as rows)."""
    path = artifact.path
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".csv":
        text = data.decode("utf-8", errors="strict")
        try:
            # Prefer utf-8; fall back to cp932 for JP market files.
            pass
        except Exception:
            text = data.decode("cp932")
        # detect encoding if replacement chars dominate
        if text.count("\ufffd") > 0:
            text = data.decode("cp932")
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for row in reader:
            clean = {str(k): (v if v is not None else "") for k, v in row.items() if k}
            if clean:
                clean["_dataset"] = artifact.dataset
                clean["_segment_id"] = artifact.segment_id
                rows.append(clean)
        return rows
    if suffix in {".xls", ".xlsx"}:
        from ingestion.jsda import parse as jsda_parse

        if suffix == ".xls":
            parsed = jsda_parse.parse_repo_xls(data)
        else:
            parsed = jsda_parse.parse_repo_xlsx(data)
        return [
            {**r, "_dataset": artifact.dataset, "_segment_id": artifact.segment_id}
            for r in parsed
        ]
    raise ValueError(f"unsupported artifact type: {suffix}")


@dataclass
class JsdaParseRunResult:
    artifacts_seen: int
    rows_parsed: int
    staging_evidence_written: int
    errors: list[str]
    state: str = "PARSED_STAGING_ONLY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts_seen": self.artifacts_seen,
            "rows_parsed": self.rows_parsed,
            "staging_evidence_written": self.staging_evidence_written,
            "errors": list(self.errors),
            "state": self.state,
            "note": (
                "PARSED_STAGING_ONLY — not COMPLETE; final fact-table path "
                "with signed receipt required for Coverage COMPLETE"
            ),
        }


def run_jsda_staging_parse(
    *,
    raw_root: Path,
    conn: sqlite3.Connection,
    run_id: int,
    datasets: Sequence[str] | None = None,
) -> JsdaParseRunResult:
    """Parse JSDA raw into staging evidence only (never signed COMPLETE)."""
    artifacts = discover_local_jsda_raw(raw_root, datasets=datasets)
    rows_parsed = 0
    written = 0
    errors: list[str] = []
    for art in artifacts:
        try:
            rows = parse_artifact_rows(art)
            rows_parsed += len(rows)
            raw = art.path.read_bytes()
            # Derive segment dates from segment_id when possible (YYYY-MM or file_*).
            seg_start, seg_end = _segment_dates(art.segment_id)
            required = RequiredCoverageSegment(
                source="jsda",
                dataset=art.dataset,
                segment_id=art.segment_id,
                segment_start=seg_start,
                segment_end=seg_end,
                expected_scope={
                    "artifact": art.segment_id,
                    "digest": art.digest,
                    "state": "PARSED_STAGING_ONLY",
                },
                expected_items=None,
            )
            receipt = CollectionReceipt(
                source=required.source,
                dataset=required.dataset,
                segment_id=required.segment_id,
                segment_start=required.segment_start,
                segment_end=required.segment_end,
                expected_scope=required.expected_scope,
                expected_items=None,
                observed_items=len(rows),
                raw_page_count=1,
                raw_row_count=len(rows),
                # structured_row_count=0: no final fact table write in this path
                structured_row_count=0,
                pagination_exhausted=True,
                digests={
                    "raw": compute_raw_digest(raw),
                    "eligibility": "RECOVERED_RAW_ONLY",
                    "origin": "parsed-staging-only",
                    "state": "PARSED_STAGING_ONLY",
                    "parsed_row_count": len(rows),
                    "artifact_digest": art.digest,
                },
                run_id=int(run_id),
                status="SUCCESS",
                error=None,
                checked_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
            )
            record_collection_receipt(conn, receipt)
            written += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{art.path}: {exc}")
    conn.commit()
    return JsdaParseRunResult(
        artifacts_seen=len(artifacts),
        rows_parsed=rows_parsed,
        staging_evidence_written=written,
        errors=errors,
        state="PARSED_STAGING_ONLY",
    )


def _segment_dates(segment_id: str) -> tuple[str, str]:
    """Map segment_id to start/end; never invent 1970 for unknown."""
    # calendar month form
    if len(segment_id) == 7 and segment_id[4] == "-":
        y, m = segment_id.split("-")
        import calendar

        last = calendar.monthrange(int(y), int(m))[1]
        return f"{y}-{m}-01", f"{y}-{m}-{last:02d}"
    # ISO date
    if len(segment_id) == 10 and segment_id[4] == "-" and segment_id[7] == "-":
        return segment_id, segment_id
    # file identity — use unknown range marker that is NOT 1970 epoch fake complete
    return "unknown", "unknown"


# Backward-compatible name — clearly non-complete.
run_trusted_jsda_parse = run_jsda_staging_parse


__all__ = [
    "JsdaParseRunResult",
    "JsdaRawArtifact",
    "discover_local_jsda_raw",
    "parse_artifact_rows",
    "run_jsda_staging_parse",
    "run_trusted_jsda_parse",
]
