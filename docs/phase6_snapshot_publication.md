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
validation matrix, and the persistent Coverage Ledger. Any hard validation
failure or governed dataset whose ledger state is not `COMPLETE` rejects the
build. The manifest records the snapshot id, canonical contract version,
source run, D1 change sequence, coverage and quality policy versions, dataset
watermarks, validation/coverage summaries, and commit time.

## Collection coverage policy

`data_contracts/collection_coverage.json` is paired one-for-one with the 23
canonical Premium-core dataset contracts. Its effective fields are:

- `collection_scope`
- `history_target_start`
- `history_target_end_rule`
- `coverage_mode`
- `expected_frequency`
- `universe_rule`
- `raw_retention_required`
- `structured_reconciliation_required`
- `governance_tier` (`governed` or `experimental`)

`dataset_coverage` persists `COMPLETE`, `PARTIAL`, `STALE`, `UNKNOWN`, or
`FAILED` plus observed bounds and the C1-C5/C8 evidence. Irregular disclosures
use `event_reconciled` mode. A successful empty endpoint response is not
treated as a missing daily row, but it also cannot prove historical
reconciliation, so it remains `PARTIAL` until reconciled evidence exists.

The current policy deliberately makes all Premium-core datasets `governed`.
Phase 7 may add experimental datasets, but an explicit tier is required and no
experimental series is silently promoted into governed research.
