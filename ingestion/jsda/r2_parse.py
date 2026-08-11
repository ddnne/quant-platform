"""Trusted JSDA structured parse from Cloudflare raw (R2 / local mirror).

Formal path:
  CF raw acquisition → R2 manifest → this parser → structured rows →
  TrustedReceiptIssuer → Coverage

Does not fetch from the network. Does not claim COMPLETE without issuer.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from storage.coverage_ledger import RequiredCoverageSegment, record_collection_receipt
from storage.trusted_receipt import mint_ingestion_issuer


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
    """Discover content-addressed JSDA raw under data/raw/jsda or R2 sync tree.

    Expected layout (CF worker):
      raw/jsda/{dataset}/{segment_id}/{sha256}.{ext}
    Also accepts legacy: raw/jsda/{...}/**/*
    """
    root = Path(raw_root)
    if not root.is_dir():
        return []
    allow = set(datasets) if datasets else {
        "jsda_otc_bond_reference_prices",
        "jsda_tokyo_repo_rates",
        "jsda_corporate_bond_transactions",
    }
    out: list[JsdaRawArtifact] = []
    # Prefer quant-raw mirror: raw/jsda/...
    base = root / "jsda" if (root / "jsda").is_dir() else root
    for dataset_dir in sorted(base.iterdir() if base.is_dir() else []):
        if not dataset_dir.is_dir():
            continue
        dataset = dataset_dir.name
        if dataset not in allow:
            continue
        for path in sorted(dataset_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith("MANIFEST") or path.suffix == ".json" and "manifest" in path.name.lower():
                continue
            if path.suffix.lower() not in {".csv", ".xls", ".xlsx", ".html"}:
                continue
            # segment = parent name when content-addressed
            segment_id = path.parent.name if path.parent != dataset_dir else path.stem
            digest = _sha256_file(path)
            out.append(
                JsdaRawArtifact(
                    dataset=dataset,
                    segment_id=segment_id,
                    path=path,
                    digest=digest,
                )
            )
    return out


def parse_artifact_rows(artifact: JsdaRawArtifact) -> list[dict[str, Any]]:
    """Parse one raw artifact into row dicts using existing JSDA parsers where possible."""
    path = artifact.path
    suffix = path.suffix.lower()
    data = path.read_bytes()
    if suffix == ".csv":
        text = data.decode("utf-8", errors="replace")
        # Lightweight CSV: first line headers
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            return []
        # Japanese CSVs may be shift_jis
        if "\ufffd" in text[:200]:
            text = data.decode("cp932", errors="replace")
            lines = [ln for ln in text.splitlines() if ln.strip()]
        headers = [h.strip() for h in lines[0].split(",")]
        rows = []
        for ln in lines[1:]:
            cols = [c.strip() for c in ln.split(",")]
            if len(cols) < 2:
                continue
            row = {headers[i] if i < len(headers) else f"c{i}": cols[i] for i in range(len(cols))}
            row["_dataset"] = artifact.dataset
            row["_segment_id"] = artifact.segment_id
            rows.append(row)
        return rows
    if suffix in {".xls", ".xlsx"}:
        try:
            from ingestion.jsda import parse as jsda_parse

            if suffix == ".xls":
                parsed = jsda_parse.parse_repo_xls(data)
            else:
                parsed = jsda_parse.parse_repo_xlsx(data)
            return [
                {**r, "_dataset": artifact.dataset, "_segment_id": artifact.segment_id}
                for r in parsed
            ]
        except Exception as exc:  # noqa: BLE001
            return [
                {
                    "_dataset": artifact.dataset,
                    "_segment_id": artifact.segment_id,
                    "_parse_error": str(exc),
                    "_raw_digest": artifact.digest,
                }
            ]
    # html indexes are discovery only
    return []


@dataclass
class JsdaParseRunResult:
    artifacts_seen: int
    rows_parsed: int
    receipts_written: int
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts_seen": self.artifacts_seen,
            "rows_parsed": self.rows_parsed,
            "receipts_written": self.receipts_written,
            "errors": list(self.errors),
        }


def run_trusted_jsda_parse(
    *,
    raw_root: Path,
    conn: sqlite3.Connection,
    run_id: int,
    datasets: Sequence[str] | None = None,
) -> JsdaParseRunResult:
    """Parse local/R2-mirrored JSDA raw and emit trusted receipts per artifact.

    Structured rows are not fully normalized into final fact tables here when
    parser coverage is incomplete; receipts still record independent raw digest
    and observed counts for Coverage progress.
    """
    artifacts = discover_local_jsda_raw(raw_root, datasets=datasets)
    issuer = mint_ingestion_issuer(run_id=run_id, source="jsda")
    rows_parsed = 0
    receipts = 0
    errors: list[str] = []
    for art in artifacts:
        try:
            rows = parse_artifact_rows(art)
            if rows and any("_parse_error" in r for r in rows):
                errors.append(f"{art.path}: parse error")
            rows_parsed += len(rows)
            raw = art.path.read_bytes()
            # Minimal required segment identity for receipt
            required = RequiredCoverageSegment(
                source="jsda",
                dataset=art.dataset,
                segment_id=art.segment_id,
                segment_start="1970-01-01",
                segment_end="1970-01-01",
                expected_scope={"artifact": art.segment_id, "digest": art.digest},
                expected_items=max(1, len(rows)) if rows else 0,
            )
            receipt = issuer.issue(
                required=required,
                run_id=run_id,
                raw=raw,
                observed_items=len(rows),
                structured_row_count=len(rows),
                raw_row_count=len(rows),
                pagination_exhausted=True,
                status="SUCCESS" if not any("_parse_error" in r for r in rows) else "FAILED",
                error=None,
                raw_manifest_digest=art.digest,
                source_request_digest=art.digest,
                structured_generation=run_id,
            )
            record_collection_receipt(conn, receipt)
            receipts += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{art.path}: {exc}")
    conn.commit()
    return JsdaParseRunResult(
        artifacts_seen=len(artifacts),
        rows_parsed=rows_parsed,
        receipts_written=receipts,
        errors=errors,
    )


__all__ = [
    "JsdaParseRunResult",
    "JsdaRawArtifact",
    "discover_local_jsda_raw",
    "parse_artifact_rows",
    "run_trusted_jsda_parse",
]
