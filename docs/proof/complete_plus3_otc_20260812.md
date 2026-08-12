# COMPLETE +3 proof — `jsda_otc_bond_reference_prices` (2026-08-06 / 07 / 13)

**Date:** 2026-08-12  
**Operator path:** honest multi-segment close (raw digest + structured count + signed SUCCESS + fail-closed publish)  
**Mass / READY / Phase7:** still **NO-GO**

Companion quality scan: `docs/proof/data_quality_scan_20260812.md`.

## PRE (remote quant-ingest)

| Metric | Value |
|--------|-------|
| Segment COMPLETE | **401** |
| Segment PARTIAL | **12539** |
| Dataset COMPLETE | **2** (`markets_calendar`, `jsda_tokyo_repo_rates`) |
| OTC COMPLETE segments | `2026-08-10`, `2026-08-12` (2) |

## Closed segments (+3)

### 1) `2026-08-06` (run_id **900411**)

| Item | Value |
|------|-------|
| source | official JSDA OTC CSV `S260806.csv` |
| source_url | `https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/files/2026/S260806.csv` |
| R2 legacy | `raw/jsda/jsda_otc_bond_reference_prices/2026/S260806.csv` |
| R2 content-addressed | `raw/jsda/jsda_otc_bond_reference_prices/2026-08-06/ab22335fba9bf131cc6e2e69696066d142b9119f30202384284b2d844966c7c5.csv` |
| raw_digest | `sha256:ab22335fba9bf131cc6e2e69696066d142b9119f30202384284b2d844966c7c5` |
| raw bytes | 2_158_976 |
| raw_row_count / structured_row_count | **12405 / 12405** |
| eligibility | `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1` |
| body_digest | `sha256:851c9fa79996c908c4d38427c71d976780228b11610f07f54382aeffb503b9a1` |
| signature prefix | `ed25519:VLisqCYg2uv7C9ynSPlMUUVwVYN45Hkw…` |

Fetch: direct HTTP 200 from `market.jsda.or.jp`, then R2 put for retention evidence.

### 2) `2026-08-07` (run_id **900412**)

| Item | Value |
|------|-------|
| source | official JSDA OTC CSV `S260807.csv` |
| source_url | `https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/files/2026/S260807.csv` |
| R2 legacy | `raw/jsda/jsda_otc_bond_reference_prices/2026/S260807.csv` |
| R2 content-addressed | `raw/jsda/jsda_otc_bond_reference_prices/2026-08-07/cedf38d7138e68fc47f72fc17717f1af6a10dd506ba0fcb6f43201b4e74301f1.csv` |
| raw_digest | `sha256:cedf38d7138e68fc47f72fc17717f1af6a10dd506ba0fcb6f43201b4e74301f1` |
| raw bytes | 2_155_278 |
| raw_row_count / structured_row_count | **12402 / 12402** |
| eligibility | `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1` |
| body_digest | `sha256:ccb3a52d77736cbd6875c4b3059dc46e05ced11cf38025e0016767fbdc63494e` |
| signature prefix | `ed25519:TILfRJf/BEX7uPFqMbj5w9gyfDX7zlgG…` |

Fetch: same path as 08-06 (official CSV → local → R2).

### 3) `2026-08-13` (run_id **900413**)

| Item | Value |
|------|-------|
| source | official JSDA OTC XLS `S260813.xls` (CF worker discovery) |
| source_url | `https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/files/2026/S260813.xls` |
| R2 key | `raw/jsda/jsda_otc_bond_reference_prices/file_S260813.xls/ea7cb7c4fcd82bbbac819387a2389a486ab233f29cd5d8d37c3aa4680f3a676e.xls` |
| raw_digest | `sha256:ea7cb7c4fcd82bbbac819387a2389a486ab233f29cd5d8d37c3aa4680f3a676e` |
| raw bytes | 5_258_240 |
| raw_row_count / structured_row_count | **12402 / 12402** |
| eligibility | `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1` |
| body_digest | `sha256:91f188b62f4adc75de4a0f0f1aefdd25ee6db084fcd19357e7e2692355367043` |
| signature prefix | `ed25519:EzLYPf+OdYeUQZp3UPE57i72AKnRbkNg…` |
| parse note | operator xlrd column map on original XLS bytes; digest is full official file (not a re-encoded CSV) |

Inventory: required segment `2026-08-13` added from official publication identity (scope cloned from peer day template with start/end=`2026-08-13`) after R2 object confirmed. Not a fabricated day without source.

## Reconciliation method (each +1)

1. Stage raw under `data/raw/jsda/jsda_otc_bond_reference_prices/{day}/…`
2. Parse → `normalize_otc_reference_prices` → `SqliteStore.upsert` fact table
3. Set segment `expected_items` = structured count (identity match for `evaluate_segment`)
4. `SignedReceiptAuthority.issue` with raw bytes; `record_collection_receipt`
5. `refresh_coverage_ledger(..., datasets=['jsda_otc_bond_reference_prices'])` → COMPLETE
6. Sticky peers `2026-08-10` / `2026-08-12` retained COMPLETE throughout

## Publish (fail-closed)

```text
complete_count_guard ok local=404 remote=401 force=False
remote projection applied
generation: projgen-e5879899a5fb408eb97a1c253968c6f2
```

`scripts/publish_ops_projection.py --apply-remote` only — no `--force-apply-remote`.

## POST (remote quant-ingest)

| Metric | Value |
|--------|-------|
| Segment COMPLETE | **404** (+3) |
| Segment PARTIAL | **12537** |
| Dataset COMPLETE | **2** (unchanged) |
| OTC COMPLETE | `2026-08-06`, `2026-08-07`, `2026-08-10`, `2026-08-12`, `2026-08-13` (**5**) |

## DEFER (not closed this ticket)

| Candidate | Why deferred |
|-----------|----------------|
| OTC additional history (2002–2026-08-05) | No local/R2 raw on hand for remaining days; JSDA archive fetch intermittent/timeout; CF discover stores only MAX_DATA_FILES=3 |
| OTC `2026-08-08/09/11` | Non-trading / 山の日 — HTTP 404 on official CSV (honest empty; not COMPLETE) |
| Corporate bond years 2015–2025 | Only 2026 year COMPLETE; no full annual archive raw+structured for prior years in this run |
| `markets_margin_interest` STALE | Separate DEFER proof; C8 + monthly/weekly identity; no silent flip |
| equities_* SUCCESS-but-PARTIAL | Many SUCCESS receipts lack Ed25519 TRUSTED eligibility; not COMPLETE-eligible without re-sign + raw proof |
| Remote D1 OTC fact backfill for new days | Projection is coverage-plane only; fact tables remain hot/prior CF rows |

## Explicit non-claims

- No dataset-level COMPLETE for OTC/corporate (still PARTIAL overall).
- No Mass / READY / Phase7.
- No COMPLETE without raw; counts not invented.
- No `packages/` reorg changes; `storage/coverage_ledger` not modified this ticket.
- Collection receipts remain local research DB evidence; remote sees projected coverage ledgers.
