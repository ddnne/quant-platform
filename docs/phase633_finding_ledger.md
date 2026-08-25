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
| D2 | COMPLETE issuer accepted caller-originated parsed rows, counts, digests, and exhaustion state | OPEN | Must reparse immutable raw, normalize canonically, reread exact natural keys, prove exhaustion, and reject an unrelated same-count row |
| D3 | A generally importable issuer/service could mint signed SUCCESS outside governed ingestion | OPEN | COMPLETE capability must be private to the governed transaction; recovery scripts remain non-COMPLETE |
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
| R1 | exact-four closure required TOPIX but `indices_bars_daily_topix` had no V3 SourceCapability | OPEN | Add official capability and prove the full exact-four closure |
| R2 | READY/coherence paths hard-coded one global V2 policy and rejected valid per-dataset V3 evidence | OPEN | Bind signed policy id/version/digest per dataset and fail on unknown/missing evidence |
| R3 | ExperimentPlan embedded `ready_snapshot_id=not-declared`, making later immutable snapshot equality circular | OPEN | Remove the placeholder from plan identity; bind snapshot at signed execution authorization |
| R4 | exact-four bindings were caller-overridable | OPEN | Only the canonical four plan ids and exact digests may reach Controlled Pilot |
| R5 | Generic READY publication and implicit core-profile Mass minting remained reachable | OPEN | Production publication must be profile/closure-bound; Mass requires an explicit governed Mass policy and stays disabled |
| R6 | Missing natural-key ledger could pass through fixture compatibility | OPEN | Production missing evidence is UNKNOWN/FAIL; compatibility is private test-only policy |

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

### P1

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| C4 | Signed Ops metadata did not bind and reverify the projected D1 table contents | OPEN | Sign per-table row/digest manifest, seal the generation, recompute before reads, reject post-seal mutation |
| C5 | 17 MCP tools lacked closed output schemas and deployment schema-digest acceptance | OPEN | All tools require closed input/output schemas and deterministic aggregate digest parity |
| C6 | Production Cron triggers disappeared under non-inherited named environments | FIXED | `6a37f61f`; Premium and JSDA production triggers explicit |
| C7 | `ingestion-secrets` workers.dev endpoint is not protected by Access | HOLD | Zero Trust account activation requires explicit human agreement; header token remains enabled |
| C8 | Six Worker lockfiles remain instead of one npm workspace | DEFERRED | Build-isolation exception in `architecture/adr_worker_dependency_isolation.md`; exact dependency parity required |

## Architecture / Test / Operations

### P0

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| A1 | JSDA Queue repeatedly selected only the newest year/files and could not converge on history | FIXED | `7afffade`; stable child segment identity, cursor progress, retry/DLQ evidence |
| A2 | Readiness and receipt signing could share a private key | FIXED | `95b6c06d`; dedicated public registries and local private-key files |

### P1

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| A3 | Worker tests were almost entirely Node mocks | FIXED | `32a1ea7d`; focused workerd and `createTestHarness()` boundary tests |
| A4 | Legacy 2,254-strategy catalog was imported by the product runtime | FIXED | `e5969f50`; immutable replay artifact only |
| A5 | More than 70 Python tests inspect source text, AST, or implementation spelling | DEFERRED | Replace incrementally with type/capability/transaction invariants; do not increase this class |
| A6 | Release evidence existed only at local absolute paths | OPEN | Publish a content-addressed non-secret manifest after production acceptance; backup body remains private/encrypted |

## Integration gate

The latest independent adversarial review of the pre-remediation candidate found
P0 rows D2, D3, R1-R6 unresolved. Remediation is in progress. After those rows
are closed, run a fresh independent review against one immutable SHA, then run
the full native CI-equivalent suite. Only that reviewed SHA may be pushed for
the release PR.
