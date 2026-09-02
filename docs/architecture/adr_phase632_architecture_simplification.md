# ADR: Phase 6.3.2 architecture and identity simplification

| Field | Value |
|-------|--------|
| **Status** | **Accepted** |
| **Date** | 2026-09-02 |
| **Lane** | Architecture / identity / Paper-only Controlled Pilot |
| **Related** | [`../architecture.md`](../architecture.md), [`llm_nav_map.md`](./llm_nav_map.md), [`adr_authority_principal_isolation.md`](./adr_authority_principal_isolation.md) (live-order residual), [`adr_public_surface_staging.md`](./adr_public_surface_staging.md) |

**Hard constraints (unchanged):** Paper-only · Mass disabled · no broker/order · no auto-promotion · no new strategies/datasets/Workers/authorities · Phase 7 OFF · do not invent COMPLETE/READY/GO.

---

## Context

Phase 6.3.1 accumulated several identities that all sounded like “exact-four”:
the governed Controlled Pilot plan set, Personal/Draft four-candidate cohorts,
and future live-order six-principal / WebAuthn / external-anchor machinery.
For a single-user Cloudflare-first research product that is Paper-only, those
identities must not be interchangeable.

This tranche does not add a strategy, dataset, Worker, or signing authority.

## Decision

Exactly three active paths exist. No other execution or publication path may
be constructed.

### 1. Draft Research

Mutable/ephemeral snapshot is allowed. Output lifecycle is `DRAFT`.
`UNKNOWN` / `UNMANAGED_DRAFT` coverage is allowed. This path cannot mint
READY, Controlled identity, or promotion, and it has no broker or order
surface.

Real market data must not persist on the user's Mac. Draft execution against
real data runs in a Cloudflare Container with an ephemeral/R2-derived
snapshot. Only tiny synthetic fixtures may live locally.

Draft four-candidate cohorts use purpose IDs, not the Controlled Pilot
identity:

- `draft_factor_cohort_v1`
- `draft_vol_overlay_cohort_v1`
- `draft_am_pm_smile_cohort_v1`

New outputs and API responses must not emit a generic `exact_four: true` for
these cohorts. Historical artifact readers may still accept the old flag.

### 2. Controlled Pilot

Canonical identity is exactly `controlled_pilot_v1`. Content is an immutable
content-addressed snapshot. Plan, `PlanDependencyClosure`, research-data
profile, and snapshot digest must close exactly. Trusted receipt, Coverage V3,
B0/B4, and READY are required. Execution is one Paper run. No auto-promotion,
broker, or order.

The cloud Controlled Paper path lives in the existing `research-mass-eval`
Worker plus its Container; local Python is OfflineFixture DRAFT only.
Operator input is only an idempotency key, READY attestation id, and logical
snapshot id. The Worker loads a closed READY envelope (signed attestation,
exact ReadyManifest, physical `{key,digest,size}`) and one signed exact-four
Trader batch v2, verifies each against environment-specific ACTIVE public
registries, and only then reserves BudgetLedger paper occupancy through
`research-ai-gateway`. READY alone cannot authorize Paper. Snapshot bytes
never enter Worker memory: each Container's `outboundByHost` capability
streams exactly one signed physical snapshot. The Container streams that
object to `/tmp`, verifies physical size/hash, recomputes the logical
snapshot identity, runs the canonical four through the private Paper engine
plus independent Risk, writes HOLD Selection pending human approval and a
Knowledge artifact bound to it, and deletes the file in `finally`. Children
are ten create-only objects and are rehashed before the terminal manifest.
Persistent real market data is forbidden on the user's Mac.

`ControlledPilotExecutionService` is a fail-closed local facade; it does not
execute Paper. `VerifiedPilotReadiness` is distinct from
`VerifiedMassReadiness`. Historical wire formats such as
`controlled-pilot/exact-four` and `exact-four-execution-binding/v1` stay
readable; they are not a second active identity. Active daily-path writers
emit `eval_path=controlled_pilot_v1`.

Paper-only trust is the existing single Cloudflare / READY publication trust
root, the content-addressed R2 snapshot, typed Service Binding / public-key
verification, BudgetLedger occupancy, and one-shot policy. This ADR does not
create a replacement authority and does not require a local OS/six-principal
authority for Pilot. The READY issuer itself remains an Ops/ingestion-premium
concern and may be operationally unprovisioned; this path stays fail-closed
until that issuer emits a real signed sidecar.

`controlled_pilot_v1` is a required serialized discriminant. New Plan, READY,
authorization, and result writers emit it and bind it into the canonical
digest. Historical schemas remain readable at a legacy boundary; they are not
active writer defaults.

### 3. Mass

Mass remains disabled. It is constructible only with `VerifiedMassReadiness`
and must reject pilot readiness.

## Threat model

Guard against:

- a mistaken LLM or caller using Draft, Personal, or Mass identity as Pilot
- an unauthenticated caller
- mutable or stale data standing in for a READY snapshot
- budget overrun

Fail closed. If a current gate cannot be simplified without live operational
evidence, document and defer that edge rather than invent a bypass.

## Deferred to a future live-order ADR

Not in the active Controlled Pilot dependency graph, default Pilot
acceptance/CI, or this working tree:

- same-UID / root adversary
- local six-principal OS custody
- Trader WebAuthn human presence
- external anchor, quiescence, and staged canary

Those implementations, scripts, launch specs, and tests were deleted from the
working tree. Git history is the archive. Do not restore them as an active or
non-runtime in-tree replay unless a future live-order ADR says so.

## Consequences

- Runtime and serialized discriminant:
  `selection.controlled_pilot_policy.CONTROLLED_PILOT_IDENTITY`
  (`controlled_pilot_v1`).
- Controlled execute accepts only Cloudflare/READY public-key evidence plus
  that identity. It has no local socket/path/store injection.
- Default pytest has no live-order archive suite.

## Residual

| Item | Owner |
|---|---|
| Produce READY and run one Paper Controlled execution after measured gates | **agent** |
| Promotion and live trading | **HUMAN**; out of scope |
| Live-order six-principal, WebAuthn, external-anchor | Git history; future ADR |
| Mass scheduler | remains disabled |
