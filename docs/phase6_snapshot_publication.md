# Phase 6 research snapshot publication

Research data is published from a mutable staging SQLite database into a
content-addressed READY directory. Staging is the only ingestion target and is
never a research input after publication.

## Lifecycle and sole read path

The publication state machine is:

`BUILDING → SYNCED → VALIDATING → READY | REJECTED`

The production entry is the exact-four plan-bound publisher. It accepts a
signed Ops Projection document and has no caller-selected dataset membership,
plan binding, fixture switch, or verifier override. It compiles the canonical
four ExperimentPlans and their dependency closures, runs the gate, copies
SQLite with the backup API, embeds the READY manifest, checks SQLite integrity,
changes the copy to mode `0444`, and atomically renames it to
`sha256_<digest>.sqlite`. Generic publication is private and test-only and
cannot emit a production readiness capability. The immutable database and its
manifest must both verify before `latest_ready_snapshot`, `describe_snapshot`,
or `open_ready_snapshot` will return it. SQLite reads use
`mode=ro&immutable=1`. `latest-ready.json` is only a replaceable pointer; it
cannot make an incomplete artifact READY.

The mutable staging policy intentionally remains `snapshot_ready=0` after a
successful publication. Fact and revision-table insert/update/delete triggers
also invalidate an in-place snapshot generation at DB level. Ingestion and D1
sync therefore cannot silently turn a published research generation into a
different generation.

## Publication gate

Production publication is fail-closed for raw, trusted receipt, validation,
natural-key migration, B0/B4, sync generation, applied cursor, and Coverage
evidence. Missing tables or rows are UNKNOWN/FAIL, never fixture PASS. Any hard
validation failure or dependency-closure dataset whose required segment set is
not completely backed by current trusted receipts rejects the build.

The manifest binds the profile id/version/digest, exact-four plan-set digest,
dependency-closure digest, dataset membership digest, per-dataset Coverage
policy-set digest, raw/receipt/validation/B0/B4 proof digests,
source/export/applied cursor, immutable snapshot id/digest, and publication
time. Opening a READY artifact rebuilds and re-verifies those bindings.

## Collection coverage policy

`data_contracts/collection_coverage.json` is paired one-for-one with the
governed J-Quants and JSDA dataset contracts. Each dataset carries its own
effective policy id/version/digest; a document-root version never relabels a
legacy row as V3. Effective fields include:

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
`collection_receipts` records the issuer-derived expected scope/items,
observed items, raw page/row counts, structured row count,
pagination/discovery exhaustion, digests, run, status, error, and checked time.
`dataset_coverage` persists the resulting `COMPLETE`,
`PARTIAL`, `STALE`, `UNKNOWN`, or `FAILED` state. Observed min/max bounds remain
diagnostics only.

Calendar/trading/periodic datasets need every required segment. A missing
middle segment is therefore `PARTIAL` even if early and late rows exist.
Irregular disclosures use `event_reconciled` mode: a complete bounded query
set with exhausted pagination, retained raw evidence, and exact segment
structured reconciliation may be COMPLETE. An unrelated old row, a partial
window, a caller-provided expected-empty flag, or matching counts without
matching natural-key sets is not proof. Non-event segments need an explicit
issuer-derived expected item contract.

Pilot publication scopes this proof to the exact plan dependency closure.
Global Ops may remain PARTIAL for an unrelated dataset without hiding it or
turning it into Pilot proof. Mass requires a separate explicit Mass profile and
remains disabled.
