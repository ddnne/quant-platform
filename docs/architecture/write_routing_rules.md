# Write routing rules (D1 vs R2)

**Source:** GLM Worker2 (`GLM_W2_WRITEPATH_OK`) + orchestrator (`GLM_ORCH_OK`)

## Target path for `/v1/run`

| Data class | Destination | Notes |
|------------|-------------|-------|
| Raw pages | R2 `quant-raw` | Unchanged evidence path |
| High-volume structured | R2 `quant-structured` partitions | **Not** full-history D1 |
| Low-volume structured | D1 hot window only | calendar, small refs |
| Receipts / coverage / watermarks / projection | D1 control plane | Always |
| change_log | D1, pruned after seal | Keep latest K per dataset |

## High-volume set (initial)

- `equities_bars_daily` (+ am/weekly/monthly if present)
- `markets_breakdown`
- large fins series as needed
- other multi-million-row JQ datasets

## Feature flags (proposed)

| flag | default | meaning |
|------|---------|---------|
| R2 parquet/jsonl route for high-vol | **ON** | stop D1 full-history for those datasets |
| `DISABLE_R2_PARQUET_ROUTE=1` | off | emergency dual-write/D1 fallback only |
| D1 size guard | ~9.5 GB | refuse high-vol D1 inserts when over |

## change_log prune

Only after segment evidence sealed (signed COMPLETE + projection healthy for that control plane). Keep latest K sequences per dataset (e.g. 64). Never prune by deleting receipts.

## Implementation anchors (existing code)

- `platform/workers/ingestion-premium/src/index.ts` — `INSERT INTO jquants_records` / `ingestion_change_log` (~887–953)
- R2 bindings already: `STRUCTURED_BUCKET` → `quant-structured`, raw bucket → `quant-raw`

## Migration order (no COMPLETE breakage)

1. Deploy route guard + dual-write optional  
2. Backfill/archive existing high-vol D1 rows to R2 with hashes  
3. Verify R2 objects  
4. Batch-delete archived D1 rows (**human confirm**)  
5. Disable high-vol D1 inserts permanently  
6. MCP verify COMPLETE counts / projection FRESH / raw retention
