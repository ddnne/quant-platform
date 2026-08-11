# R2 historical partition scheme (`quant-structured`)

**Source:** GLM Worker5 (`GLM_W5_R2PART_OK`)  
**Bucket:** `quant-structured`  
**Local FS is not SoT.**

## Key layout (Hive-style)

```
dataset=<DATASET>/year=YYYY/month=MM/day=DD/seg=<SEGMENT_ID>/<content_hash>.parquet
```

Examples:

```
dataset=equities_bars_daily/year=2024/month=03/day=15/seg=2024-03/<hash>.parquet
dataset=equities_master/year=2024/month=03/day=15/seg=listing_events/<hash>.parquet
dataset=markets_breakdown/year=2024/month=03/day=15/seg=2024-03/<hash>.parquet
_manifest/dataset=equities_bars_daily/year=2024/month=03/manifest.json
```

P0 may land **NDJSON/JSONL** envelopes first (`format=archive-ndjson-p0` or `jsonl-arrow-bridge`), then compact to Parquet in P1.

## Partition order

`dataset > year > month > day > seg`  
Sparse / SCD2: `dataset > year > quarter > seg`

Max object size guidance: 64–256 MB; split by ticker range if larger.

## Receipt linkage

Control-plane receipt (D1) stores at minimum:

- `content_hash` (sha256 of structured payload/object)
- `structured_r2_key` / `r2_key`
- optional `r2_object_etag`

Parquet/JSONL rows embed `receipt_hash = content_hash` for tamper-evident joins.

## Hot window (D1) vs cold (R2)

Default proposal (tune per dataset):

| dataset class | D1 hot | R2 cold |
|---------------|--------|---------|
| bars / breakdown / indices | last ~90 trade days | older |
| master | `is_current` + last ~90d events | full SCD2 history |
| calendar | full (tiny) | optional monthly mirror |
| fins | current + previous period | older |

Rotation is fail-closed: archive → HEAD verify → only then DELETE from D1 structured tables. **Never delete receipts / coverage COMPLETE.**
