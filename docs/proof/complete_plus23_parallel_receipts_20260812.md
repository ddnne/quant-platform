# COMPLETE +71 proof — parallel signed receipts (Track A3)

**Date:** 2026-08-12  
**Operator path:** `scripts/issue_receipts_parallel.py` (ThreadPool prepare + serial sign/write)  
**Mass / READY / Phase7:** still **NO-GO**

> First batch closed **+23** (local/remote **408→431**). Continuation batches sealed
> remaining months that already held **usable local raw + structured** (no backfill),
> then fail-closed republish closed the remote lag. Final remote COMPLETE = **479**.

## Infrastructure

| Item | Path / value |
|------|----------------|
| Parallel script | `scripts/issue_receipts_parallel.py` |
| Serial sibling | `scripts/issue_signed_receipts_for_segments.py` (`--datasets`, `date=` raw match, parallel hint) |
| Smoke tests | `tests/test_issue_receipts_parallel.py` |
| Workers | 6–8 (prepare pool); sign/write serial |
| Primary datasets | `markets_short_ratio`, `markets_breakdown`, `markets_margin_alert` |
| Also sealed | `equities_investor_types` (2020-01…07 with from/to raw) |
| Empty raw ban | reject `[]` / `<8B` / stub payloads (not honest evidence) |
| Backfill / Mass | **not** launched |

## PRE / POST (full A3 window)

| Metric | PRE (A3 start) | After batch-1 publish | POST (final) |
|--------|---------------:|----------------------:|-------------:|
| Local segment COMPLETE | **408** | **431** | **479** (**+71**) |
| Remote segment COMPLETE | **404** | **431** | **479** |
| Dataset-level COMPLETE | 2 | 2 | 2 (unchanged) |

### Publish (fail-closed, no `--force-apply-remote`)

| Step | Guard | Generation |
|------|-------|------------|
| Batch-1 | `local=431 remote=404 force=False` | `projgen-767c79b919b74c3085e01c255eade424` |
| Catch-up | `local=476 remote=431 force=False` | `projgen-0264a603480c4b48b930cffb2f575ec6` |
| Final | `local=479 remote=476 force=False` → applied | `projgen-0ca2910127a84d0fa3b7b8d770736da9` |

Verified after final publish: **local COMPLETE = remote COMPLETE = 479**.

## Dataset COMPLETE after A3

| dataset | COMPLETE / total | Notes |
|---------|-----------------:|-------|
| `markets_short_ratio` | **32 / 164** | 2024-01 … 2026-08 sealed |
| `markets_breakdown` | **32 / 164** | 2024-01 … 2026-08 sealed |
| `markets_margin_alert` | **18 / 164** | 2025-03 … 2026-08 sealed |
| `equities_investor_types` | **7 / 164** | 2020-01…07 windows with from/to raw |
| `jsda_otc_bond_reference_prices` | **5 / 8778** | unchanged this track (OTC +3 prior) |
| `markets_calendar` | **224 / 224** | sticky |

Signed SUCCESS rows for this track: `run_id` **900419–900491**.  
Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`.  
Reconciliation: `raw_row_count == structured_row_count`.

| Unit | observed / expected |
|------|---------------------|
| `source_query` (short_ratio, breakdown, investor_types) | `observed_items == expected_items == 1` |
| `source_event` (margin_alert, event_driven) | `observed_items == structured_row_count`, `expected_items` null |

### Batch-1 sample (first 24 receipts → +23 net COMPLETE)

#### `markets_short_ratio` (run 900419–900426)

| segment_id | structured_row_count |
|------------|---------------------:|
| 2026-08 … 2025-06 (8 months) | 204–748 |

#### `markets_margin_alert` (run 900427–900434)

| segment_id | structured_row_count |
|------------|---------------------:|
| 2026-08 … 2026-01 (8 months) | 1094–6968 |

#### `markets_breakdown` (run 900435–900442)

| segment_id | structured_row_count |
|------------|---------------------:|
| 2025-12 … 2025-05 (8 months) | 76092–92898 |

### Continuation batch (run 900443–900491 → local 431→479)

| dataset | segments | run_id range |
|---------|----------|--------------|
| `markets_short_ratio` | 2025-05 … 2024-01 (17) | 900443–900459 |
| `markets_margin_alert` | 2025-12 … 2025-03 (10) | 900460–900469 |
| `markets_breakdown` | 2026-08 + 2025-04 … 2024-01 (17) | 900470–900486 |
| `equities_investor_types` | 2020-04 … 2020-07 (+ earlier 2020-01…03) | 900414–900416, 900487–900491 |

## Reconciliation method

1. Index local `data/raw/jquants/**` once; match segment window (from/to or date=).
2. Reject empty `[]` stubs; prefer larger non-stub payload over newest empty file.
3. RO ThreadPool: structured `COUNT(*)` per segment + raw load.
4. Serial: `SignedReceiptAuthority.issue` + `record_collection_receipt`.
5. `refresh_coverage_ledger` for touched datasets → COMPLETE.
6. Fail-closed `publish_ops_projection.py --apply-remote` (local ≥ remote).

## Explicit non-claims / DEFER

| Item | Status |
|------|--------|
| COMPLETE without raw | **Forbidden** — skipped by design |
| Empty `[]` raw as evidence | **Rejected** |
| Dataset-level COMPLETE for sealed series | Still **PARTIAL** overall (history incomplete) |
| Mass / READY / Phase7 | **NO-GO** |
| Dual / historical backfill launch | **Not** started by this track |
| Months without local structured or usable raw | **DEFER** until A-exec raw + structure land |
| `markets_margin_interest` STALE | Separate DEFER (P1-1); not touched |
| OTC additional trading days | No extra local raw+structured beyond already-closed days — **DEFER** |
| JSDA corporate years 2015–2025 | No structured rows locally (only 2026 COMPLETE) — **DEFER** |
| Non-trading OTC days (08/09/11) | Honest 404 / non-trading — not COMPLETE |

## Command (reproduce dry scan)

```bash
.venv/bin/python scripts/issue_receipts_parallel.py \
  --datasets markets_short_ratio,markets_breakdown,markets_margin_alert \
  --limit 12 --workers 6 --order desc --dry-run --json-summary
```
