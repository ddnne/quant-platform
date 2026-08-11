# D1 prune / rotate runbook (P0)

**Source:** GLM Worker1 + Orchestrator  
**DB:** `quant-ingest` only  
**Mass:** NO-GO  

## Preconditions

1. `cf_premium_backfill` **stopped** while D1 is full and high-vol still writes D1.  
2. Pre-snapshot: COMPLETE counts, receipt counts, projection status, D1 size.  
3. Archive candidates to R2 and verify object HEAD + content_hash.  
4. **Human confirm required** before any D1 DELETE batch.

## Never delete

- `coverage_segments` COMPLETE rows  
- `collection_receipts` / signed receipt material  
- `raw_retention_manifests` COMPLETE evidence  
- projection generation/metadata needed for FRESH control plane  
- `markets_calendar` COMPLETE chain (do not “touch” to fix size)

## Allowed delete targets (after R2 archive verify)

- Cold rows in high-vol structured tables (e.g. `jquants_records` for bars/breakdown older than hot window)  
- Optionally sealed `ingestion_change_log` tails (keep latest K)

## Batching

- Max **1000 rows** per DELETE statement (D1 safety)  
- Circuit breaker on batch count  
- After each batch: re-check COMPLETE counts must not drop; re-check D1 size

## Pre / post verification SQL (remote)

```sql
SELECT dataset,
  SUM(CASE WHEN status='COMPLETE' THEN 1 ELSE 0 END) AS complete_n,
  COUNT(*) AS total_n
FROM coverage_segments
GROUP BY dataset
ORDER BY complete_n DESC;

SELECT COUNT(*) AS receipt_n FROM collection_receipts;
-- projection: ops_projection_metadata.status should remain FRESH after republish if needed
```

## Abort conditions

- Any COMPLETE count decrease  
- Receipt count decrease  
- R2 archive missing for rows about to be deleted  
- Auth / D1 API errors mid-batch → stop and report

## Status 2026-08-11

- D1 at **10 GB** hard full  
- Destructive prune **not yet executed** (awaiting human confirm + archive tooling deploy)
