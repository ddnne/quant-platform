"""Signed receipt authority — COMPLETE only with verified Ed25519 signature."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from storage.coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    build_collection_receipt,
    compute_raw_digest,
)
from storage.receipt_crypto import (
    PARSER_NORMALIZER_VERSION,
    ReceiptSigningKey,
    build_signed_digest_fields,
    load_signing_key,
    partition_extra_digests,
)


@dataclass(frozen=True)
class SignedReceiptAuthority:
    """Non-forgeable issuer: holds private Ed25519 key material."""

    signing_key: ReceiptSigningKey
    parser_normalizer_version: str = PARSER_NORMALIZER_VERSION

    def issue(
        self,
        *,
        required: RequiredCoverageSegment,
        run_id: int,
        raw: bytes,
        observed_items: int,
        structured_row_count: int,
        raw_row_count: int | None = None,
        pagination_exhausted: bool = True,
        status: str = "SUCCESS",
        error: str | None = None,
        checked_at: str | None = None,
        source_request_digest: str | None = None,
        raw_manifest_digest: str | None = None,
        structured_generation: int | None = None,
        structured_digest: str | None = None,
        extra_digests: Mapping[str, Any] | None = None,
    ) -> CollectionReceipt:
        extras = partition_extra_digests(extra_digests)
        if status != "SUCCESS" or error:
            # Failed collections are unsigned evidence only.
            digests: dict[str, Any] = {
                "eligibility": "RECOVERED_RAW_ONLY",
                "origin": "failed-collection",
                "extra_digests": extras,
            }
            digests.update(extras)
            return build_collection_receipt(
                required=required,
                run_id=run_id,
                raw=raw,
                observed_items=observed_items,
                structured_row_count=structured_row_count,
                raw_row_count=raw_row_count,
                pagination_exhausted=pagination_exhausted,
                status=status,
                error=error,
                checked_at=checked_at,
                extra_digests=digests,
            )

        raw_digest = compute_raw_digest(raw)
        raw_count = int(raw_row_count) if raw_row_count is not None else int(structured_row_count)
        signed = build_signed_digest_fields(
            signing_key=self.signing_key,
            dataset=required.dataset,
            segment_id=required.segment_id,
            source=required.source,
            run_id=run_id,
            raw_digest=raw_digest,
            raw_count=raw_count,
            structured_count=int(structured_row_count),
            structured_digest=structured_digest,
            pagination_exhausted=pagination_exhausted,
            source_request_digest=source_request_digest,
            raw_manifest_digest=raw_manifest_digest or raw_digest,
            structured_generation=structured_generation
            if structured_generation is not None
            else run_id,
            checked_at=checked_at,
            segment_start=required.segment_start,
            segment_end=required.segment_end,
            extra_digests=extras,
        )
        return build_collection_receipt(
            required=required,
            run_id=run_id,
            raw=raw,
            observed_items=observed_items,
            structured_row_count=structured_row_count,
            raw_row_count=raw_row_count,
            pagination_exhausted=pagination_exhausted,
            status=status,
            error=error,
            checked_at=signed.get("checked_at") or checked_at,
            extra_digests=signed,
        )


def open_signed_receipt_authority(
    *,
    pem: bytes | str | None = None,
    path: Any = None,
    key_id: str | None = None,
) -> SignedReceiptAuthority:
    """Open signing authority from private key material. Raises if missing."""
    key = load_signing_key(pem=pem, path=path, key_id=key_id)
    if key is None:
        raise RuntimeError(
            "receipt signing key not configured "
            "(QUANT_RECEIPT_SIGNING_KEY_PEM or ~/.config/quant-platform/receipt_signing_key.pem)"
        )
    return SignedReceiptAuthority(signing_key=key)


# Backward-compatible name used in older call sites — now signature-based only.
TrustedReceiptIssuer = SignedReceiptAuthority


__all__ = [
    "SignedReceiptAuthority",
    "TrustedReceiptIssuer",
    "open_signed_receipt_authority",
]
