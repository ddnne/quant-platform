# Research control plane

Personal DRAFT, Controlled Pilot and disabled Mass are separate paths.
Source availability is not operational authorization or evidence of live READY.

## Runtime entrypoints

- Personal DRAFT uses `personal_service.PersonalResearchService` through the
  [cloud research Worker](../../../platform/workers/research-mass-eval/README.md).
  Results cannot publish Controlled READY or authorize promotion.
- Controlled Paper uses `execution.paper_service.ControlledPilotExecutionService`
  and the Worker's `POST /v1/controlled-pilot` route. Exact plan/profile/closure,
  immutable snapshot, readiness and Trader checks remain required.
- `POST /v1/receipt-candidate` constructs a cloud candidate from receipt evidence;
  successful construction alone is not READY or permission to execute.
- `POST /v1/daily-path`, `POST /v1/mass-eval` and `POST /v1/propose-thesis`
  reject authenticated requests with 403. They are not alternative entrypoints.

The package barrel exports the fail-closed control plane lazily; use explicit
Personal/Controlled service entrypoints. `VerifiedPilotReadiness` and
`VerifiedMassReadiness` are distinct. Mass remains disabled.

## Replay and storage

The legacy catalog lives only in
`artifacts/replay/legacy_strategy_catalog/{manifest.json,migration.jsonl}`.
`catalog_compiler` validates its closed DSL and hashes; `occupancy_audit` is
explicit audit/replay only. Neither populates runtime strategy inventory.
Offline helpers and the local CLI are developer/recovery compatibility, not the
normal market-data or research path.

Market acquisition belongs to the ingestion plane. Research orchestration must
not fetch market HTTP or open fact SQLite directly. Cloud job SQLite is ephemeral;
do not persist authentic market history on a laptop. Keep PIT, AM-to-PM causality,
immutable evidence and bounded cost; no live orders or automatic promotion.

## Canonical references

- [Architecture](../../../docs/architecture.md): data and execution boundaries.
- [Research recording](../../../docs/architecture/adr_research_recording.md):
  durable artifact placement rather than wave scripts or scorecards.
- [Runbook](../../../docs/operations/current_production_runbook.md): operational
  procedures and staged authorization.
- [Work ledger](../../../docs/operations/current_work_ledger.json): accepted scope
  and cancel/HOLD records, not a substitute for live observations.
