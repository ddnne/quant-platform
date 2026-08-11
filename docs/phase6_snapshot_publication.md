# Phase 6 research snapshot publication

Research data is published from a mutable staging SQLite database into a
content-addressed READY directory. Staging is the only ingestion target and is
never a research input after publication.

## Lifecycle and sole read path

The publication state machine is:

`BUILDING → SYNCED → VALIDATING → READY | REJECTED`

`publish_ready_snapshot(staging_db, snapshot_dir, required_datasets=...)`
runs the gate, copies SQLite with the backup API, embeds the READY manifest,
checks SQLite integrity, changes the copy to mode `0444`, and atomically renames
it to `sha256_<digest>.sqlite`. The immutable database and its manifest must
both verify before `latest_ready_snapshot`, `describe_snapshot`, or
`open_ready_snapshot` will return it. SQLite reads use
`mode=ro&immutable=1`. `latest-ready.json` is only a replaceable pointer; it
cannot make an incomplete artifact READY.

The mutable staging policy intentionally remains `snapshot_ready=0` after a
successful publication. Fact and revision-table insert/update/delete triggers
also invalidate an in-place snapshot generation at DB level. Ingestion and D1
sync therefore cannot silently turn a published research generation into a
different generation.

## Publication gate

Publication reuses the existing strict B0 scale gates, the Phase 3.5 daily
validation matrix, and Coverage V2. Any hard validation failure or governed
dataset whose required segment set is not completely backed by successful
receipts rejects the build. The manifest records the snapshot id, canonical contract version,
source run, D1 change sequence, coverage and quality policy versions, dataset
watermarks, validation/coverage summaries, a bounded Coverage V2 proof digest,
and commit time. Opening a READY artifact re-verifies that proof.

## Collection coverage policy

`data_contracts/collection_coverage.json` is paired one-for-one with the
governed J-Quants and JSDA dataset contracts. Its effective fields are:

- `collection_scope`
- `history_target_start`
- `history_target_end_rule`
- `coverage_mode`
- `expected_frequency`
- `universe_rule`
- `raw_retention_required`
- `structured_reconciliation_required`
- `segment_granularity`
- `governance_tier` (`governed` or `experimental`)

`coverage_segments` is the independent inventory of required collection units;
`collection_receipts` records expected scope/items, observed items, raw page/row
counts, structured row count, pagination exhaustion, digests, run, status,
error, and checked time. `dataset_coverage` persists the resulting `COMPLETE`,
`PARTIAL`, `STALE`, `UNKNOWN`, or `FAILED` state. Observed min/max bounds remain
diagnostics only.

Calendar/trading/periodic datasets need every required segment. A missing
middle segment is therefore `PARTIAL` even if early and late rows exist.
Irregular disclosures use `event_reconciled` mode: a successful bounded window
query with exhausted pagination, retained raw evidence, and a 0-to-0 structured
reconciliation is COMPLETE; an unrelated old row is not. Non-event segments
need an explicit expected item count.

The current policy deliberately makes Premium-core plus the governed JSDA
bond-reference, Tokyo Repo Rate, and corporate-bond transaction datasets
`governed`. Phase 7 may add experimental datasets, but an explicit tier is
required and no experimental series is silently promoted into governed research.
