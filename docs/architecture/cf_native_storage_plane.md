# CF-native storage plane (SoT)

**Status:** adopted 2026-08-11 (GLM-main architecture directive)  
**Mass research:** NO-GO  
**Local DB:** not a SoT for analysis / features / strategy production

## Current correction: Receipt acquisition must also be R2-first

The adopted storage decision applies to the Receipt path, not just the older
Premium writer. At source `6d501d39`, `structured_reconciliation.ts` and
`product_materialization.ts` persist complete row bodies in
`receipt_authority_structured_rows`, `jquants_records`, and
`ingestion_change_log` before producing R2 products. That path violates the
historical-body rule below. The dated deployment claims at the end describe
the old writer only; they do not establish current compliance.

The 2026-09-23 staging read measured 8,309,817,344 D1 bytes. Fifty product
metadata rows reference 2,245,405,492 R2 bytes; this is not a per-table D1
size breakdown. Metadata/signature acceptance is not independent verification
of all product bytes. Evidence and independent dependency review:
[capacity review](https://github.com/ddnne/quant-platform/pull/248#issuecomment-5785172724).

### Required end state (not yet implemented)

- R2 owns immutable raw, normalized history and research products. Reuse
  existing buckets, services, parsers and full-segment verifiers; do not add
  a new Worker, signer or storage framework to enforce this decision.
- D1 holds operation/segment metadata, manifest references, independently
  measured counts/digests and cursors. A permanent natural-key-per-row shadow
  still grows with history: compacting only its payload is an intermediate
  optimization, not the final architecture.
- Row-level SQL, duplicate-key checking, ordering and feature computation use
  bounded scratch in existing cloud compute. Stream partitions; do not load
  full history into Worker memory or use the developer machine for market SQL.
- The trusted pipeline must independently compare canonical parsed raw with
  persisted structured R2 bytes, including keys/counts/exhaustion, before
  issuing its receipt. Caller-supplied summaries or HEAD/ETag alone do not
  replace byte verification. Failed/restarted publication cannot produce an
  eligible receipt from a partial object.
- Existing signed receipts and product serialization remain unchanged.
  Normalized-input `row_digest` includes the operation ingestion timestamp;
  governed rows may retain an earlier ingestion timestamp on identical replay.
  These are different identities, not interchangeable hashes.

### Implementation and migration boundary

Work in progress on `feat/receipt-r2-reconciliation` (not deployed): the
internal scratch producer, compact reconciliation metadata, Receipt commit
gate and mixed legacy/R2 readers are implemented. Migration 0024 is source
only. Scratch is released after durable finalization (and on finalized replay);
an empty workspace can restart from retained raw using the original timestamp.
The DO entrypoint now supplies scratch for new operations, with a 512 MiB
whole-database admission cap reserving the remaining platform capacity for
authority metadata; existing operations retain their recorded storage mode.
This source change is not deployed. On the next authority invocation, scratch
untouched for 24 hours is reclaimed except for in-flight operations. Activity
is committed atomically with row appends; no audit alarm is replaced. Evicted
or expired work reconstructs from retained raw, not from D1 history. Complete
legacy/R2 runtime validation and R2 source/export/applied generation wiring
remain required before activation. R2-mode
watermarks deliberately report a NULL legacy export cursor: an unrelated D1
row-change sequence must not make the new path look current or READY.

Entrypoint validation: the existing 80,707-row monthly synthetic scenario
completes with zero D1 fact/shadow/change rows, one compact measurement and
empty scratch after finalization. Pre-sign scratch-loss/eviction recovery and
both page-interruption scenarios pass without reacquisition. Legacy v1 recovery,
replay/re-proof and D1 append-only scenarios now seed persisted pre-upgrade
operations before resuming through the current entrypoint. Those cases preserve
the old assertions without a production legacy-mode switch or mocked writer.
The 61 non-monthly authority cases pass after entrypoint activation; the monthly
case passes separately. This is not deployment acceptance: retention, cursor
integration and final exact-SHA native CI remain open.

`receipt_product_publications/v1` is the new metadata-only source cursor:
one monotonically allocated sequence per atomic R2 receipt commit, independent
of run allocation order and of `ingestion_change_log`. Premium descriptors
expose before/after observations under that explicit namespace. This is not
an applied cursor, a finalized-authority acknowledgement or READY evidence;
consumer/export integration must verify the full receipt chain before advancing
its applied position. Do not substitute this number into legacy D1 feed fields.
Premium now binds each R2 segment descriptor to its exact publication sequence,
receipt digest and artifact digest. The cloud candidate records that selected
cursor with its independently verified receipt digest in
`receipt_candidate_source_cursors` only after full raw/product verification.
This scope-specific set is preserved in the candidate SQLite artifact and the
materialization digest; it is not a claim that every earlier global sequence
was applied. Legacy descriptors retain a null cursor, and generic Ops/READY
exported/applied cursor integration remains outstanding.

First change the new-operation producer and its consumers as one reviewed
contract: reconciliation/materialization, receipt finalization/watermarks,
Premium descriptors, Ops projection and cloud candidate. Descriptors and Ops
currently count shadow rows; recovery remeasures joins. Missing rows must never
silently become PASS by trusting a manifest count. Introduce a versioned
R2-evidence path while keeping existing immutable evidence readable; retire
obsolete full-history writes when that path is accepted.

Prove the path with a small synthetic runtime scenario covering restart and
partial/corrupt output plus unchanged legacy receipt/product verification.
Measure a bounded staging acquisition to show D1 metadata growth is not
proportional to market rows. Reuse existing tests instead of adding policy-text
tests or an exhaustive version matrix.

Existing D1 rows are not disposable merely because an R2 object exists.
Before any separately authorized reclamation, verify complete R2 bytes and
receipt binding, update all readers/recovery, resolve shared-writer/cursor
dependencies, and preserve terminal operation metadata. Append-only triggers
currently prohibit shadow mutation; do not drop them broadly or rewrite
historical hashes. No whole-DB restore after other writers resume.

The approved bounded 2022 acquisition is not permission to use the obsolete
D1-history path, delete data, rotate keys, or release production/Pilot HOLDs.
Source work and non-destructive verification can proceed while login is pending.

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

## Historical P0 order (2026-08-11; superseded)

This old sequence is retained as historical context, not executable guidance.
The current correction above requires producer/consumer/recovery acceptance
before bounded reclamation. Group related approval operations into one outcome;
do not request approval separately for every SQL batch.

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
