# COMPLETE +23 proof — parallel signed receipts (Track A3)

**Date:** 2026-08-12  
**Operator path:** `scripts/issue_receipts_parallel.py` (ThreadPool prepare + serial sign/write)  
**Mass / READY / Phase7:** still **NO-GO**

## Infrastructure

| Item | Path / value |
|------|----------------|
| Script | `scripts/issue_receipts_parallel.py` |
| Smoke tests | `tests/test_issue_receipts_parallel.py` |
| Workers | 6 |
| Datasets | `markets_short_ratio`, `markets_breakdown`, `markets_margin_alert` |
| Limit / dataset | 8 (24 candidates) |
| Empty raw ban | reject `[]` / `<8B` stubs (not honest evidence) |
| Backfill / Mass | **not** launched |

## PRE / POST

| Metric | PRE | POST |
|--------|----:|-----:|
| Local segment COMPLETE | **408** | **431** (**+23**) |
| Remote segment COMPLETE | **404** (guard probe) | **431** |
| Dataset-level COMPLETE | 2 (`markets_calendar`, `jsda_tokyo_repo_rates`) | 2 (unchanged) |

Guard: `complete_count_guard ok local=431 remote=404 force=False`  
Publish: `scripts/publish_ops_projection.py --apply-remote` (no force)  
Generation: `projgen-767c79b919b74c3085e01c255eade424`

Net ledger +23 while 24 signed SUCCESS rows were written (`run_id` 900419–900442); one net offset vs PRE is consistent with sticky inventory / prior local seal — all 24 issued segment_ids evaluate **COMPLETE** after refresh.

## Closed segments (24 signed SUCCESS → COMPLETE)

### `markets_short_ratio` (+8 sealed; COMPLETE 15/164)

| segment_id | run_id | structured_row_count |
|------------|-------:|---------------------:|
| 2026-08 | 900419 | 204 |
| 2025-12 | 900420 | 748 |
| 2025-11 | 900421 | 578 |
| 2025-10 | 900422 | 714 |
| 2025-09 | 900423 | 680 |
| 2025-08 | 900424 | 646 |
| 2025-07 | 900425 | 748 |
| 2025-06 | 900426 | 714 |

### `markets_margin_alert` (+8 sealed; COMPLETE 8/164)

| segment_id | run_id | structured_row_count |
|------------|-------:|---------------------:|
| 2026-08 | 900427 | 1094 |
| 2026-07 | 900428 | 4750 |
| 2026-06 | 900429 | 5343 |
| 2026-05 | 900430 | 4676 |
| 2026-04 | 900431 | 5912 |
| 2026-03 | 900432 | 6968 |
| 2026-02 | 900433 | 4715 |
| 2026-01 | 900434 | 4509 |

### `markets_breakdown` (+8 sealed; COMPLETE 15/164)

| segment_id | run_id | structured_row_count |
|------------|-------:|---------------------:|
| 2025-12 | 900435 | 84687 |
| 2025-11 | 900436 | 76092 |
| 2025-10 | 900437 | 92898 |
| 2025-09 | 900438 | 84441 |
| 2025-08 | 900439 | 84483 |
| 2025-07 | 900440 | 92722 |
| 2025-06 | 900441 | 88216 |
| 2025-05 | 900442 | 84311 |

Eligibility for each: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`  
`raw_row_count == structured_row_count`; `observed_items == expected_items == 1` (`source_query` unit).

## Reconciliation method

1. Index local `data/raw/jquants/**` once; match segment window (from/to or date=).
2. Reject empty `[]` stubs; require usable raw bytes.
3. RO ThreadPool: structured `COUNT(*)` per segment + raw load.
4. Serial: `SignedReceiptAuthority.issue` + `record_collection_receipt`.
5. `refresh_coverage_ledger` for touched datasets → COMPLETE.
6. Fail-closed `publish_ops_projection.py --apply-remote` (local ≥ remote).

## Explicit non-claims / DEFER

| Item | Status |
|------|--------|
| COMPLETE without raw | **Forbidden** — skipped by design |
| Empty `[]` raw as evidence | **Rejected** |
| Dataset-level COMPLETE for the three targets | Still PARTIAL overall |
| Mass / READY / Phase7 | **NO-GO** |
| Dual backfill launch | **Not** started |
| Remaining history months without usable local raw | **DEFER** until A-exec raw lands |
| `markets_margin_interest` STALE | Separate DEFER (P1-1); not touched |
| OTC / corporate bond deep history | Prior proofs; out of this batch |

## Command (reproduce scan)

```bash
.venv/bin/python scripts/issue_receipts_parallel.py \
  --datasets markets_short_ratio,markets_breakdown,markets_margin_alert \
  --limit 8 --workers 6 --order desc --dry-run --json-summary
```
