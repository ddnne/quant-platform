# Phase 6 research snapshot publication

Research data is published from a mutable staging SQLite database into a
content-addressed READY directory. Staging is the only ingestion target and is
never a research input after publication.

## Lifecycle and execution read boundary

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
manifest must both verify before `latest_ready_snapshot` or
`describe_snapshot` returns publication metadata. Those metadata APIs expose a
path and are not an execution-safe database capability. The package exports no
production READY SQLite opener; the legacy direct-module entry rejects before
resolution or descriptor transfer. This is necessary because changing an
artifact to mode `0444` cannot revoke a same-UID `O_RDWR` descriptor retained
before that change.

The sole accepted Controlled Pilot SQLite path is the Controlled activation
service. A root-only installer re-verifies the READY authority response,
embedded exact-four manifest and signed projection, writes create-only
content-addressed root-owned files, fsyncs them, and commits the immutable
custody manifest last. Activation v3 accepts that exact manifest/digest rather
than caller-declared snapshot/projection paths. Both install and activation
replay the stored projection through the current verifier and require the
attestation digest, verified document digest, and file digest to agree. Source
and destination directories stay descriptor-pinned through the bounded copy;
content links are directory-fsynced before the commit-last manifest. Activation
re-derives both Controlled groups from the canonical bootstrap deployment. The
socket caller group remains the process effective GID, while custody mode
`0440` uses the distinct supplementary
`qp_<environment>_controlled_execution_readers` group. That reader group must
contain exactly the Controlled service user; Trader is intentionally present
only in the socket caller group and cannot read custody. Neither group may
reuse the shared authority service GID. Activation then retains both files as
`PinnedControlledSnapshotV2` descriptors. Quant Data database reads likewise
retain a verified descriptor and rehash before returning, but this separate
read plane does not prove same-UID isolation. Execution of the install under
real UID/GID ownership and full authority-chain acceptance remain open under
A2/R5/R11. `latest-ready.json` is only a replaceable pointer; it cannot make an
incomplete artifact READY.

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
time. Describing a production READY publication rebuilds and re-verifies those
bindings, but does not mint a database-read capability.

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
