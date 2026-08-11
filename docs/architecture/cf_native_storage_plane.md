# CF-native storage plane (SoT)

**Status:** adopted 2026-08-11 (GLM-main architecture directive)  
**Mass research:** NO-GO  
**Local DB:** not a SoT for analysis / features / strategy production

## Layers

| Layer | Role | Location | Contents | Write policy |
|-------|------|----------|----------|--------------|
| Control / evidence | Governance, freshness, evidence | **D1 `quant-ingest` (lightweight)** | coverage ledger, receipts, projection meta, change_log (+ hot window only) | Minimal |
| Historical SoT | Long structured history | **R2 `quant-structured` (Parquet/JSONL partitions)** | Full dataset history; receipt content_hash linkage | Batch writes; never via D1 full-history |
| Raw evidence | Source bytes | **R2 `quant-raw`** | Raw J-Quants/JSDA payloads | Append-oriented |
| Compute | JOIN / features / strategies | **Artifacts / Workers** | Read needed partitions from R2; write results to R2 (or D1 meta only) | Prefer R2 |

## Hard rules

1. Do not load full history into D1 (10 GB hard limit).
2. Do not create year-split or table-split D1 as primary design.
3. Never delete COMPLETE-linked raw retention / receipts / ledger / projection artifacts.
4. High-volume structured (`equities_bars_daily`, `markets_breakdown`, …) must not continue full-history INSERT into D1.
5. `equities_master` must move to SCD2 / event-sourcing (see `master_scd2_design.md`).

## Account D1 inventory (2026-08-11)

| name | size | role | action |
|------|------|------|--------|
| `quant-ingest` | **10 GB FULL** | quant control/evidence | KEEP + prune/rotate to R2 |
| `news-db` | ~3.5 GB | news product | **isolated; do not touch for quant** |

No surplus quant D1 exists to retire today.

## Live pressure (2026-08-11)

- D1 `database_size`: 10 GB  
- 24h: ~610k write queries, ~21.4M rows written  
- `equities_bars_daily` CF ingest: `D1_ERROR: Exceeded maximum DB size`  
- `cf_premium_backfill` must remain **stopped** while D1 is full and write path still targets D1 full history.

## P0 order

1. Stop D1-full-history writers (backfill + premium route guard).  
2. Archive cold structured rows to R2 (verify hash).  
3. Small-batch D1 DELETE of archived cold rows only (**human confirm per batch**).  
4. Wire high-volume path to R2-first permanently.  
5. SCD2 for master; change_log prune after evidence seal.

See also:

- `docs/architecture/r2_partition_scheme.md`
- `docs/architecture/write_routing_rules.md`
- `docs/architecture/master_scd2_design.md`
- `docs/operations/d1_prune_runbook.md`
- `docs/operations/surplus_d1_audit.md`

## Implementation status (2026-08-12)

- Deployed: `ingestion-premium` P0 write-path guard (`write_path_config.ts`, R2 JSONL).
- Ops: `POST /v1/ops/archive-cold`, `POST /v1/ops/prune-changelog`.
- Ops: `POST /v1/ops/jsonl-to-parquet-meta` (parquet-manifest/v1 bridge).
- Ops: `POST /v1/ops/artifacts-join-plan` (read-only Artifacts plan; Mass NO-GO).
- `equities_master` live path: SCD2 event log + CURRENT.json on R2 (not full daily dump).
- High-volume structured no longer inserts full history into D1.
- Live: D1 ~651MB, cold `<2026-07-01` = 0, COMPLETE preserved.
