"""Trusted ingestion runtime — sole holder of receipt signing keys.

General library callers import storage.trusted_receipt.SignedReceiptAuthority
but cannot obtain a signing key without runtime configuration. This module is
the choke point for opening signing authority during governed ingestion.
"""

from __future__ import annotations

from pathlib import Path

from storage.trusted_receipt import SignedReceiptAuthority, open_signed_receipt_authority

# Run states for governed ingestion (Phase 6.2.3 §2).
RUN_ACQUIRED = "ACQUIRED"
RUN_RAW_STORED = "RAW_STORED"
RUN_STRUCTURED_COMMITTED = "STRUCTURED_COMMITTED"
RUN_RECEIPT_VERIFIED = "RECEIPT_VERIFIED"
RUN_COVERAGE_COMPLETE = "COVERAGE_COMPLETE"
RUN_PARTIAL = "PARTIAL"
RUN_FAILED = "FAILED"


def open_ingestion_signing_authority(
    *,
    pem: bytes | str | None = None,
    path: Path | None = None,
    key_id: str | None = None,
) -> SignedReceiptAuthority:
    """Open signing authority for the current ingestion process only."""
    return open_signed_receipt_authority(pem=pem, path=path, key_id=key_id)


__all__ = [
    "RUN_ACQUIRED",
    "RUN_COVERAGE_COMPLETE",
    "RUN_FAILED",
    "RUN_PARTIAL",
    "RUN_RAW_STORED",
    "RUN_RECEIPT_VERIFIED",
    "RUN_STRUCTURED_COMMITTED",
    "open_ingestion_signing_authority",
]
