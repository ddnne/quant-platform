# equities_master SCD2 / event-sourcing design

**Source:** GLM Worker3 (`GLM_W3_MASTER_SCD2_OK`)  
**Status:** design only (not migrated)  
**Mass:** NO-GO  

## Problem

Daily full-universe copies of listed info inflate D1 (`jquants_records` / master path).  
Remote snapshot 2026-08-11: `equities_master` ≈ **284k** rows in D1 `jquants_records` (local historical copies can be larger). Write volume scales with universe × days.

## Target

| Store | Content |
|-------|---------|
| D1 hot | `equities_master_current` — one row per active code (`is_current=1`) + short change_log |
| R2 cold | SCD2 / event Parquet (year partitions) linked by `receipt_id` / content hash |

## Event types

`LISTED`, `DELISTED`, `NAME_CHANGE`, `SECTOR_33_CHANGE`, `SECTOR_17_CHANGE`, `SCALE_CHANGE`, `MARKET_CHANGE`, `MERGER`, `ABSORBED`, `SPLIT`, `SYMBOL_CHANGE`, `ATTRIBUTE_CORRECT`, `CORP_ACTION`

## Daily write path

1. Load ~universe current map from D1 (~thousands of rows).  
2. Diff incoming listed_info vs `version_hash`.  
3. Skip unchanged (majority).  
4. Write only deltas to change_log + upsert current.  
5. Receipt / coverage still sealed on control plane; raw remains on `quant-raw`.

## Write reduction (order of magnitude)

| metric | full daily copy | SCD2 |
|--------|-----------------|------|
| D1 writes/day | ~4.5k rows | ~5–15 events |
| Multi-year accumulation | millions of rows | ~current snapshot + small event log |
| Reduction | — | **~10²–10³×** on D1 master writes |

## Migration rules (evidence-safe)

1. Derive events from consecutive daily snapshots without inventing segments.  
2. Every change_log row keeps `receipt_id` to COMPLETE evidence.  
3. Archive full snapshots to R2 and verify hash **before** any D1 prune of old master rows.  
4. Never delete COMPLETE receipts / coverage / raw retention.  
5. Human confirm before destructive prune batches.

## as_of rebuild

Artifacts / DuckDB-Wasm: read R2 event Parquet (+ unarchived hot log) → window by `effective_date` / `effective_to` → latest row per `local_code` at as_of.  
D1 alone serves only hot/current lookups, not full history.

## Implementation notes (next CODE_PATCH session)

- Prefer adapting `platform/workers/ingestion-premium` listed_info path over inventing new D1 product DBs.  
- Do not create year-split D1.  
- Coordinate with `write_routing_rules.md` and `r2_partition_scheme.md`.

## Full GLM artifact

Raw GLM output: `.glm-logs/cf-arch/w3_master_scd2.log`
