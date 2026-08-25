# Phase 6.3.1 finding ledger (live)

> **Single current finding ledger.** Operational measurements and GO flags live
> in [`phase62_residual_status.md`](phase62_residual_status.md). Historical
> review waves remain in Git history. Machine-readable rows are in
> [`phase633_finding_ledger.json`](phase633_finding_ledger.json).

Policy: [`architecture/adr_review_findings_sot.md`](architecture/adr_review_findings_sot.md).
Status vocabulary: **OPEN** / **FIXED** / **DEFERRED** / **HOLD**.

The merge gate is fail-closed: every P0 row must be `FIXED` and an independent
review of the final candidate must report unresolved P0 = 0. A candidate patch
does not change an `OPEN` row until its regression test and independent review
pass.

## Data / PIT / Receipt

### P0

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| D1 | Fixed allowlists were intersected with PIT master only on the first day | FIXED | `d99083f4`; daily listing/delisting invariant tests |
| D2 | COMPLETE issuer accepted caller-originated parsed rows, counts, digests, and exhaustion state | OPEN | Rotate the current key, then independently reparse immutable raw, normalize canonically, reread exact natural keys, prove exhaustion, and reject an unrelated same-count row |
| D3 | A same-UID importable signing oracle could mint signed SUCCESS outside governed ingestion | OPEN | Remove public PEM/sign APIs; a dedicated evidence authority accepts only an opaque governed reconciliation handle; recovery remains non-COMPLETE |
| D4 | JSDA publication labels were used as quote-effective dates | FIXED | `56d4fcf9`; `2002-08-02 -> 2002-08-01`, `2002-08-05 -> 2002-08-02` |

### P1

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| D5 | Existing 22 COMPLETE datasets were issued before the final trusted path | HOLD | Preserve audit history but remove eligibility until trusted reproof |
| D6 | Canonical Registry duplicated PIT/Coverage semantics | FIXED | `2bd96d69`; registry is membership/routing metadata only |

## READY / Plan / Execution

### P0

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| R1 | exact-four closure required TOPIX but `indices_bars_daily_topix` had no V3 SourceCapability | FIXED | `eb21e84a`; official 2008-05-07 boundary and exact-five-dataset closure independently verified |
| R2 | READY/coherence paths hard-coded one global V2 policy and rejected valid per-dataset V3 evidence | OPEN | Bind signed policy id/version/digest per dataset and fail on unknown/missing evidence |
| R3 | ExperimentPlan embedded `ready_snapshot_id=not-declared`, making later immutable snapshot equality circular | OPEN | Remove the placeholder from plan identity; bind snapshot at signed execution authorization |
| R4 | exact-four bindings were caller-overridable | OPEN | Only the canonical four plan ids and exact digests may reach Controlled Pilot |
| R5 | Generic READY publication and a same-UID arbitrary READY signer remained reachable | OPEN | Dedicated READY authority independently rechecks the authenticated mirror, exact-four closure and immutable copy; Mass requires a separate explicit policy and stays disabled |
| R6 | Missing natural-key ledger could pass through fixture compatibility | OPEN | Production missing evidence is UNKNOWN/FAIL; compatibility is private test-only policy |
| R10 | Trader authorization remained a same-UID HOME-key signing oracle over caller-constructed approval decisions | OPEN | Rotate/tombstone the current key; production is verify-only; a separately permissioned human-approval authority independently reconstructs and signs the exact READY/plan/universe/gross-limit decision |
| R11 | Controlled execution duplicated authority lineage into a caller-writable HOME store | OPEN | The authority UID is the only canonical Paper/Risk/Selection/Knowledge writer; the product client only verifies authority-returned content-addressed artifacts and exposes no production writer |

### P1

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| R7 | Snapshot publication swallowed a database publication exception | OPEN | Publication failure must abort and leave no READY authority |
| R8 | Controlled and fixture Paper shared a boolean readiness bypass | FIXED | `ddc85178`; separate OfflineFixture and ControlledPilot services |
| R9 | Pilot and Mass used nominally compatible readiness authority | FIXED | `ddc85178`; distinct verified types; Mass remains hard-disabled |

## Cloudflare / Ops / CI

### P0

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| C1 | Ops MCP was bound directly to production ingestion D1 | FIXED | `dbd5dc74`, `ca9c4410`; dedicated signed projection and quota D1 bindings |
| C2 | Mass-to-Gateway authorization copied a shared bearer secret | FIXED | `de7915d1`; typed Service Binding RPC capability |
| C3 | Caller-supplied CI receipts could impersonate the required gate | FIXED | `6421d89b`; native Cloudflare required check is authoritative |
| C4 | Ops Projection signer accepted a publisher-authored evidence envelope | OPEN | Dedicated authority must consume an authenticated full-source FD/opaque export handle and independently recompute tables, Coverage, B0/B4 and cursors before signing |
| C9 | Coverage V3 transition could omit required or failed segments and mark the remaining subset COMPLETE | OPEN | Exact equality with canonical bounded-history and authority-issued tip/index inventory; reject omitted, duplicate and unexpected identities |
| C10 | Domain-separated production Coverage transition authority was not provisioned or callable | OPEN | Authority independently verifies active and target states, signs the transition domain, and records a durable one-shot CAS tombstone |

### P1

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| C5 | 17 MCP tools lacked closed output schemas and deployment schema-digest acceptance | OPEN | All tools require closed input/output schemas and deterministic aggregate digest parity |
| C6 | Production Cron triggers disappeared under non-inherited named environments | FIXED | `6a37f61f`; Premium and JSDA production triggers explicit |
| C7 | `ingestion-secrets` workers.dev endpoint is not protected by Access | HOLD | Zero Trust account activation requires explicit human agreement; header token remains enabled |
| C8 | Six Worker lockfiles remain instead of one npm workspace | DEFERRED | Build-isolation exception in `architecture/adr_worker_dependency_isolation.md`; exact dependency parity required |

## Architecture / Test / Operations

### P0

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| A1 | JSDA Queue repeatedly selected only the newest year/files and could not converge on history | FIXED | `7afffade`; stable child segment identity, cursor progress, retry/DLQ evidence |
| A2 | Receipt, D1, Ops, READY, Trader, transition and execution keys had filenames but no complete principal/evidence-authority isolation | OPEN | Retire same-user keys; dedicated principals hold fresh private keys; public packages are verify-only; unprovisioned authorities remain PENDING/UNKNOWN |

### P1

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| A3 | Worker tests were almost entirely Node mocks | FIXED | `32a1ea7d`; focused workerd and `createTestHarness()` boundary tests |
| A4 | Legacy 2,254-strategy catalog was imported by the product runtime | FIXED | `e5969f50`; immutable replay artifact only |
| A5 | Python tests still inspect source text, AST, or implementation spelling where a behavioral boundary should suffice | DEFERRED | Replace incrementally with type/capability/transaction invariants; do not increase this class or treat a coarse text-search count as authority |
| A6 | Release evidence existed only at local absolute paths | OPEN | Publish a content-addressed non-secret manifest after production acceptance; backup body remains private/encrypted |

## Integration gate

The latest independent adversarial review rejected the Coverage/READY candidate
with P0 rows D2, D3, R2-R6, R10-R11, C4, C9, C10 and A2 unresolved. Remediation is in
progress. After those rows are closed, run a fresh independent review against
one immutable SHA, then run the full native CI-equivalent suite. Only that
reviewed SHA may be pushed for the release PR.
