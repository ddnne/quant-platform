# Segment COMPLETE checklist (Phase 6.2.3)

Live COMPLETE **counts** live only in [phase62_residual_status.md](phase62_residual_status.md).  
Mass / READY / Phase7 remain **NO-GO / OFF** unless residual says otherwise.

A coverage segment is **COMPLETE** only when **all** of the following hold.
Row counts, raw retention alone, or Cloudflare fetch success are **not** enough.

## Required evidence chain

1. **Required segment** exists in `coverage_segments` (`collection-coverage/v2`)
2. **Structured rows** for the segment window (`jquants_records` or governed JSDA fact table)
3. **Raw bytes retained** with digests on the receipt (`raw_page_count >= 1`, `digests.raw`)
4. **Signed SUCCESS receipt** (Ed25519 via `SignedReceiptAuthority`)
   - `eligibility=TRUSTED_COLLECTION`
   - Verifiable against `data_contracts/receipt_verify_public_keys.json`
5. **Identity match**: receipt source/dataset/segment_id/start/end/scope/expected_items == required
6. **Non-event segments**: `expected_items` must be explicit (for `source_query` unit → typically `1`)
7. **Pagination exhausted** and raw_row_count == structured_row_count when reconciliation required
8. **Ledger refresh** promotes segment to COMPLETE via `evaluate_segment`
9. **Ops projection** published so MCP shows COMPLETE:
   - Prefer `scripts/ops_reeval_freshness.py` (targeted; never rewrites segments)
   - Full `publish_ops_projection.py --apply-remote` only if local COMPLETE ≥ remote
     (fail-closed guard refuses otherwise; see `docs/operations/projection_publish_guard.md`)

## Explicitly NOT COMPLETE

| State | Why |
|-------|-----|
| `RECOVERED_RAW_ONLY` | Rebuild without signed issuer |
| `PARSED_STAGING_ONLY` | JSDA staging parse (structured_row_count forced 0) |
| raw only / CF 200 | No structured + signed receipt |
| validation PASS with 0 inserts | Idempotent window, not coverage COMPLETE |
| projection FRESH alone | Ops plane freshness ≠ Research READY |

## Operator commands (honest path)

```bash
# Issue signed receipts only where raw+structured exist
.venv/bin/python scripts/issue_signed_receipts_for_segments.py \
  --dataset markets_calendar --limit 50 --order asc

# Refresh + export (remote needs wrangler auth)
.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite \
  --refresh-coverage --apply-remote
```

## Mass / Phase 7

Mass Autonomous Research stays **NO-GO** until VerifiedResearchReadiness
(attestation + READY snapshot + B0 + coverage gates). Do not equate
`markets_calendar COMPLETE` with platform READY.
