# COMPLETE +1 proof — jsda_otc_bond_reference_prices / 2026-08-10

**Date:** 2026-08-12  
**Operator path:** honest single-segment close (raw + structured + signed SUCCESS)  
**Mass / READY / Phase7:** still **NO-GO**

## PRE (remote quant-ingest)

| Metric | Value |
|--------|-------|
| Segment COMPLETE | **400** |
| Dataset COMPLETE | **2** (`markets_calendar`, `jsda_tokyo_repo_rates`) |
| OTC COMPLETE segments | `2026-08-12` only (1/8777) |

## Target segment

| Field | Value |
|-------|-------|
| dataset | `jsda_otc_bond_reference_prices` |
| segment_id | `2026-08-10` |
| source | official JSDA OTC reference CSV `S260810.csv` |
| source_url | `https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/files/2026/S260810.csv` |

## Raw evidence (no fabrication)

| Item | Value |
|------|-------|
| R2 key (legacy acquisition) | `raw/jsda/jsda_otc_bond_reference_prices/2026/S260810.csv` |
| R2 key (content-addressed) | `raw/jsda/jsda_otc_bond_reference_prices/2026-08-10/d9586d852b19f3fbde33751a344319124ffe66c73d61a5188008dc533e484a72.csv` |
| raw_digest | `sha256:d9586d852b19f3fbde33751a344319124ffe66c73d61a5188008dc533e484a72` |
| raw bytes | 2_200_139 |
| raw_row_count (parsed) | **12401** |

Notes:
- Direct fetch from `market.jsda.or.jp` was intermittently unreachable from the operator host; bytes were pulled from **R2** objects previously acquired by CF worker run `ingestion_run_log.id=72` (2026-08-11).
- Candidate `2026-08-11` / `S260811.csv` returned **HTTP 404** (non-trading day / 山の日) — **not** closed.

## Structured evidence

| Item | Value |
|------|-------|
| fact table | `jsda_otc_bond_reference_prices` |
| structured_row_count | **12401** |
| publication_label_date | `2026-08-10` |
| reconciliation | raw_row_count == structured_row_count |

## Signed receipt (local authority; secrets not recorded)

| Field | Value |
|-------|-------|
| run_id | `900410` |
| status | `SUCCESS` |
| eligibility | `TRUSTED_COLLECTION` |
| issuer_class | `SignedReceiptAuthority` |
| issuer_key_id | `dev-receipt-v1` |
| observed_items / expected_items | 12401 / 12401 |
| body_digest | `sha256:5e1a2990789ba3126056da35fb651ac773e8bf052b4da8f9472fcc3ac198339f` |
| signature prefix | `ed25519:PR9PN/yeUlZKaifVYF4CeF7Yp71/XTC8…` (full sig in local DB only) |

## Ledger + publish

1. Local `coverage_segments` → `2026-08-10` **COMPLETE** (reason: `receipt reconciled`).
2. Local segment COMPLETE **400 → 401**.
3. `publish_ops_projection.py --apply-remote` fail-closed guard: local≥remote.
4. Remote projection generation: `projgen-ae1e5bc60ec34085b79805ee4a0382f7` (then republish after calendar sticky restore).

## Collateral fix (sticky inventory)

`storage/coverage_ledger.py` inventory SELECT omitted `status`, so sticky COMPLETE demotion guards never saw prior COMPLETE. Fixed to load `status` + `receipt_run_id`. Verified OTC COMPLETE rows hold across refresh.

## POST (remote quant-ingest)

| Metric | Value |
|--------|-------|
| Segment COMPLETE | **401** (+1) |
| Dataset COMPLETE | **2** (`markets_calendar` 224/224, `jsda_tokyo_repo_rates` 1/1) |
| OTC COMPLETE segments | `2026-08-10`, `2026-08-12` (2/8777) |

## Explicit non-claims

- No dataset-level COMPLETE for OTC/corporate (still PARTIAL overall).
- No Mass ON / READY / Phase7 enablement.
- No COMPLETE without raw; counts not invented.
- Collection receipts remain local research DB evidence (ops projection projects coverage ledgers, not fact tables).
