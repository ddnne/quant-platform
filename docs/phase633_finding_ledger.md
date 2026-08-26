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
| D2 | COMPLETE issuer accepted caller-originated parsed rows, counts, digests, and exhaustion state | OPEN | `3ced05dc` contains product minting behind a one-shot reconciled-evidence handle, but a separately privileged authority must still reparse immutable raw, normalize canonically, reread exact natural keys, prove exhaustion, rotate the key, and reprove eligible datasets |
| D3 | A same-UID importable signing oracle could mint signed SUCCESS outside governed ingestion | OPEN | `3ced05dc` makes product receipt crypto verify-only and removes HOME/env private-key fallback; closure still requires a dedicated evidence-authority principal with a fresh key and a non-COMPLETE recovery path |
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
| R2 | READY/coherence paths hard-coded one global V2 policy and rejected valid per-dataset V3 evidence | FIXED | `590a71d2`, `76d21575`; exact per-dataset policy triplets plus content-addressed local proof ID reverified from current ledgers/receipts/generation; independent review P0/P1=0 |
| R3 | ExperimentPlan embedded `ready_snapshot_id=not-declared`, making later immutable snapshot equality circular | FIXED | `76240e89`; plan identity is snapshot-free and immutable snapshot binding occurs only in authorization; independent review passed |
| R4 | exact-four bindings were caller-overridable | FIXED | `76240e89`; only the checked-in canonical four plans and exact plan/closure/profile digests reach the scheduler; independent attack tests passed |
| R5 | Generic READY publication and a same-UID arbitrary READY signer remained reachable | OPEN | `fa01ff3c` removes product mint/sign/private-key paths, pins every consumer to the exact-four verify-only trust root, and verifies the same immutable sidecar bytes; the registry has zero active keys, so a dedicated READY authority must still independently recheck the authenticated mirror, exact closure and immutable copy before activation; Mass stays disabled |
| R6 | Missing natural-key ledger could pass through fixture compatibility | FIXED | `d6a49e24`; production collector has no fixture/quality/raw override, exact run/build evidence is re-read fail-closed, fixture helpers are tests-only, and independent review reported P0/P1=0 |
| R10 | Trader authorization remained a same-UID HOME-key signing oracle over caller-constructed approval decisions | OPEN | `4f9decc1` makes the product boundary verify-only and exact-binds READY/plan/closure/universe/spec/period/cost/gross/issued/expiry values; the registry has zero active keys, so the old key must still be retired and a separately permissioned human-approval authority provisioned |
| R11 | Controlled execution duplicated authority lineage into a caller-writable HOME store | OPEN | `811d500c`, `b89cc23c`, `3601815e` verify the separate writer domain, exact four non-empty content digests and retained immutable bytes as evidence-only, with execution/promotion disabled; the canonical external writer principal/store is still unprovisioned |

### P1

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| R7 | Snapshot publication swallowed a database publication exception | FIXED | `4100f04e`; DB/pointer/marker/manifest post-replace failures remove discovery state and quarantine evidence; independent review passed |
| R8 | Controlled and fixture Paper shared a boolean readiness bypass | FIXED | `ddc85178`; separate OfflineFixture and ControlledPilot services |
| R9 | Pilot and Mass used nominally compatible readiness authority | FIXED | `ddc85178`; distinct verified types; Mass remains hard-disabled |

## Cloudflare / Ops / CI

### P0

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| C1 | Ops MCP was bound directly to production ingestion D1 | FIXED | `dbd5dc74`, `ca9c4410`; dedicated signed projection and quota D1 bindings |
| C2 | Mass-to-Gateway authorization copied a shared bearer secret | FIXED | `de7915d1`; typed Service Binding RPC capability |
| C3 | Caller-supplied CI receipts could impersonate the required gate | FIXED | `6421d89b`; native Cloudflare required check is authoritative |
| C4 | Ops Projection signer accepted a publisher-authored evidence envelope | OPEN | `5fb40304` removes product signer injection and binds a one-shot read-only source handle to path/inode/schema/count/digest/cursor identity; a dedicated principal must still own the renderer/signing authority and independently recompute the full projection |
| C9 | Coverage V3 transition could omit required or failed segments and mark the remaining subset COMPLETE | FIXED | `18c2595d`; exact-five V3 inventory is regenerated at the authoritative build cutoff, every expected segment must bind one selected signed receipt, generic refresh/sync cannot mint first COMPLETE, and independent adversarial review reported P0/P1=0 |
| C10 | Domain-separated production Coverage transition authority was not provisioned or callable | OPEN | `071a0022`, `faf326a5` provide a fail-closed verify/apply boundary with independent in-transaction V3 inventory/receipt remeasurement, full-state CAS, immutable tombstone, postcondition and pre-commit expiry checks; the public registry has zero active keys and the external signing principal/store remain unprovisioned |

### P1

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| C5 | 17 MCP tools lacked closed output schemas and deployment schema-digest acceptance | OPEN | Repository code now defines 17 closed input/output schemas and pins aggregate digest `sha256:dad7cd29ef002e76ee1f9802b8685a179f94fcbd0bb2e6df685858e41c1778d3`, but live `tools/list` still exposes 16 tools and omits `storage_plane_status`; close only after deployment acceptance proves exact name/schema parity |
| C6 | Production Cron triggers disappeared under non-inherited named environments | FIXED | `6a37f61f`; Premium and JSDA production triggers explicit |
| C7 | `ingestion-secrets` workers.dev endpoint is not protected by Access | HOLD | Zero Trust account activation requires explicit human agreement; header token remains enabled |
| C8 | Six Worker lockfiles remain instead of one npm workspace | DEFERRED | Build-isolation exception in `architecture/adr_worker_dependency_isolation.md`; exact dependency parity required |

## Architecture / Test / Operations

### P0

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| A1 | JSDA Queue repeatedly selected only the newest year/files and could not converge on history | FIXED | `7afffade`; stable child segment identity, cursor progress, retry/DLQ evidence |
| A2 | Receipt, D1, Ops, READY, Trader, transition and execution keys had filenames but no complete principal/evidence-authority isolation | OPEN | 2026-08-26 read-only audit: 0/7 authorities provisioned; Receipt/D1/Ops/READY/Trader are contract-only `PARTIAL`, Coverage transition/Controlled execution are `NOT_PROVISIONED`; no dedicated account/service/socket/root-owned store or authority Cloudflare binding exists, all checked registries have active keys=0, and legacy PEM filenames are same-UID only; admin bootstrap, fresh in-authority keys and scoped identities remain required |
| A7 | Release workflows did not consume the machine-readable P0 finding gate | OPEN | Independent audit of `e1241c40`: `verify_ci`, deployment acceptance, and release evidence accepted execution without reading the finding ledger; close by using one strict repo-pinned gate in every entrypoint and binding its exact digest and OPEN-P0 inventory into release evidence |

### P1

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| A3 | Worker tests were almost entirely Node mocks | FIXED | `32a1ea7d`; focused workerd and `createTestHarness()` boundary tests |
| A4 | Legacy 2,254-strategy catalog was imported by the product runtime | FIXED | `e5969f50`; immutable replay artifact only |
| A5 | Python tests still inspect source text, AST, or implementation spelling where a behavioral boundary should suffice | DEFERRED | Replace incrementally with type/capability/transaction invariants; do not increase this class or treat a coarse text-search count as authority |
| A6 | Release evidence existed only at local absolute paths | OPEN | Publish a content-addressed non-secret manifest after production acceptance; backup body remains private/encrypted |

## Integration gate

The latest independent adversarial reviews accepted the code boundaries for R3,
R4, R5, R6, R7, R10, R11, C9 and C10. R5/R10/R11/C10 remain `OPEN`
because verify-only containment with zero active keys is not an operational
authority.
The Coverage/READY candidate still has P0 rows D2, D3, R5, R10, R11, C4,
C10, A2 and A7 unresolved. Receipt and Ops Projection code containment does not
substitute for the dedicated principals required by D2/D3/C4/A2; C9 likewise
does not close the separately provisioned transition authority required by C10.
R7's authority-owned append-only history and
sidecar-retention residuals remain tracked by R5/A2 rather than reopening the
fail-closed publication row. After all P0 rows are closed, run a fresh
independent review against one immutable SHA, then run the full native
CI-equivalent suite. Only that reviewed SHA may be pushed for the release PR.
