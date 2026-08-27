# Phase 6.3.1 finding ledger (live)

> **Single current finding ledger.** Operational measurements and GO flags live
> in [`phase62_residual_status.md`](phase62_residual_status.md). Historical
> review waves remain in Git history. Machine-readable rows are in
> [`phase633_finding_ledger.json`](phase633_finding_ledger.json).

Policy: [`architecture/adr_review_findings_sot.md`](architecture/adr_review_findings_sot.md).
Status vocabulary: **OPEN** / **FIXED** / **DEFERRED** / **HOLD**.

`OPEN` is the operational release state. A fail-closed inactive source
implementation may merge, but remains `OPEN` until live provisioning,
activation, reproof, and independent acceptance are evidenced. The pinned
source-integration validator runs in required CI and does not authorize a
release. The production release/positive-operation gate is fail-closed: every
P0 row must be `FIXED` and independent review of the final candidate must report
unresolved P0 = 0.

## Data / PIT / Receipt

### P0

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| D1 | Fixed allowlists were intersected with PIT master only on the first day | FIXED | `d99083f4`; daily listing/delisting invariant tests |
| D2 | COMPLETE issuer accepted caller-originated parsed rows, counts, digests, and exhaustion state | OPEN | **SOURCE-CLOSED (inactive):** `9823744e`, `65454330`, `2bed5ea1`, `cbfaf6df`; no caller claims DTO; authority reacquires raw, canonical-parses/normalizes, exact-compares D1, and persists raw and product evidence create-only in its sole dedicated R2 bucket before atomic state/event recording. **OPERATIONAL-OPEN:** register/activate fresh environment-scoped keys, deploy distinct production/staging resources, reprove exact dependency segments, and verify the complete export/sync/projection/READY chain; v1/v2 and old receipts remain audit-only. |
| D3 | A same-UID importable signing oracle could mint signed SUCCESS outside governed ingestion | OPEN | **SOURCE-CLOSED (inactive):** the closed Service Binding accepts only environment/dataset/segment/nonce; private Ed25519 minting/finalization remains inside the DO and no production importable signer exists. **OPERATIONAL-OPEN:** deploy the isolated no-public-route Worker/DO/binding, provision a fresh secret/key, activate a reviewed registry entry, retire legacy signers, and pass recovery smoke. |
| D4 | JSDA publication labels were used as quote-effective dates | FIXED | `56d4fcf9`; `2002-08-02 -> 2002-08-01`, `2002-08-05 -> 2002-08-02` |
| D7 | Signed receipt closure inputs could change between verification and serialization | FIXED | `3836f069`; exact receipt, digest and claims are frozen once before signing; independent review P0/P1=0 |

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
| R5 | Generic READY publication and a same-UID arbitrary READY signer remained reachable | OPEN | **SOURCE-CLOSED (inactive):** `fa01ff3c`, `2b582aee`; product is verify-only, exact-four consumers require an immutable sidecar plus caller-owned expected environment/resource, and the registry has zero active keys. **OPERATIONAL-OPEN:** provision the dedicated READY UID/socket/key/store, independently recheck the authenticated current mirror/closure/copy, and publish and verify one immutable exact-four READY; Mass stays disabled. |
| R6 | Missing natural-key ledger could pass through fixture compatibility | FIXED | `d6a49e24`; production collector has no fixture/quality/raw override, exact run/build evidence is re-read fail-closed, fixture helpers are tests-only, and independent review reported P0/P1=0 |
| R10 | Trader authorization remained a same-UID HOME-key signing oracle over caller-constructed approval decisions | OPEN | **SOURCE-CLOSED (inactive):** `4f9decc1`, `f1d377eb`; product is verify-only, WebAuthn challenge/signature/one-use/counter handling is atomic, `fmt=none` enrollment is honestly `UNATTESTED/PENDING_TRUST_REVIEW`, and active keys=0. **OPERATIONAL-OPEN:** bind a human/root-reviewed witness or trusted attestation to the exact registration/environment/RP, provision Trader UID/store, retire the HOME key, activate the credential, and pass human-approval smoke. |
| R11 | Controlled execution duplicated authority lineage into a caller-writable HOME store | OPEN | **SOURCE-CLOSED (inactive):** `811d500c`, `b89cc23c`, `3601815e`; exact writer-domain/digest/immutable-byte checks hold, execution and promotion are false, and no active writer exists. **OPERATIONAL-OPEN:** provision the external writer UID/socket/fresh key/protected canonical store and accept one authorized Pilot artifact chain. |

### P1

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| R7 | Snapshot publication swallowed a database publication exception | FIXED | `4100f04e`; DB/pointer/marker/manifest post-replace failures remove discovery state and quarantine evidence; independent review passed |
| R8 | Controlled and fixture Paper shared a boolean readiness bypass | FIXED | `ddc85178`; separate OfflineFixture and ControlledPilot services |
| R9 | Pilot and Mass used nominally compatible readiness authority | FIXED | `ddc85178`; distinct verified types; Mass remains hard-disabled |
| R12 | READY lower-verifier evidence remained subclassable or mutable after verification | FIXED | `3e6eb822`; exact immutable lower-verifier DTOs are frozen before the READY decision; independent review P0/P1=0 |

## Cloudflare / Ops / CI

### P0

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| C1 | Ops MCP was bound directly to production ingestion D1 | FIXED | `dbd5dc74`, `ca9c4410`; dedicated signed projection and quota D1 bindings |
| C2 | Mass-to-Gateway authorization copied a shared bearer secret | FIXED | `de7915d1`; typed Service Binding RPC capability |
| C3 | Caller-supplied CI receipts could impersonate the required gate | FIXED | `6421d89b`; native Cloudflare required check is authoritative |
| C4 | Ops Projection signer accepted a publisher-authored evidence envelope | OPEN | **SOURCE-CLOSED (inactive):** `5fb40304`; signer injection is removed and the dedicated renderer recomputes from a one-shot authenticated descriptor-bound mirror. **OPERATIONAL-OPEN:** first close A2's D1-sync recovery gap, then provision distinct D1-sync/Ops-projection UIDs, keys and stores and accept an independently rendered signed FRESH projection. |
| C9 | Coverage V3 transition could omit required or failed segments and mark the remaining subset COMPLETE | FIXED | `18c2595d`; exact-five V3 inventory is regenerated at the authoritative build cutoff, every expected segment must bind one selected signed receipt, generic refresh/sync cannot mint first COMPLETE, and independent adversarial review reported P0/P1=0 |
| C10 | Domain-separated production Coverage transition authority was not provisioned or callable | OPEN | **SOURCE-CLOSED (inactive):** `071a0022`, `faf326a5`; verify-only in-transaction exact V3 inventory/receipt remeasurement, full-state CAS, tombstone, postcondition and expiry checks hold, and active keys=0. **OPERATIONAL-OPEN:** provision the transition UID/key/rollback-resistant store, activate the registry, and run exact-five transition smoke against the trusted current mirror. |
| C11 | Signed D1 or Ops document A could authorize a different downstream verified envelope B | FIXED | `80080d79`, `bf41f97b`, `222b9bd6`, `66f36ff4`; signed projection and READY evidence is frozen into exact one-shot opaque results; trusted renderer/signing remains PENDING under C4 |
| C13 | Authenticated SQLite acquisition, import, schema, or path identity could switch from database A to B | FIXED | `c0008890`, `8c61f840`, `f6538eb4`, `e4ec03e1`, `ac2cb420`, `c72bda77`, `7997670e`, `6c048274`; retained `O_NOFOLLOW` descriptor, exact schema/content identity, DELETE journal and writer lock; independent review `cfc377b4` / tree `075ddb4a` P0/P1=0; same-UID raw pwrite remains unresolved under A2 |
| C14 | COMPLETE publication could outlive final freshness, cursor, count, or policy postconditions | FIXED | `c7836bf4`, `ac2cb420`, `c72bda77`, `6c048274`; final descriptor-rendered state and exact policy postconditions are rechecked before publication; independent review `cfc377b4` / tree `075ddb4a` P0/P1=0 |

### P1

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| C5 | 17 MCP tools lacked closed output schemas and deployment schema-digest acceptance | OPEN | Repository code now defines 17 closed input/output schemas and pins aggregate digest `sha256:dad7cd29ef002e76ee1f9802b8685a179f94fcbd0bb2e6df685858e41c1778d3`, but live `tools/list` still exposes 16 tools and omits `storage_plane_status`; close only after deployment acceptance proves exact name/schema parity |
| C6 | Production Cron triggers disappeared under non-inherited named environments | FIXED | `6a37f61f`; Premium and JSDA production triggers explicit |
| C7 | `ingestion-secrets` workers.dev endpoint is not protected by Access | HOLD | Zero Trust account activation requires explicit human agreement; header token remains enabled |
| C8 | Six Worker lockfiles remain instead of one npm workspace | DEFERRED | Build-isolation exception in `architecture/adr_worker_dependency_isolation.md`; exact dependency parity required |
| C12 | Coverage transition authorization accepted a backward-moving verification clock | FIXED | `b64b3af0`; authorization time is monotonic and rollback is rejected; independent review P0/P1=0 |
| C15 | SQLite scalar or container coercions and stale timestamps weakened exact evidence comparison | FIXED | `c0008890`, `8c61f840`, `e4ec03e1`, `6c048274`; exact scalar/container types and current exported-at evidence are checked through the retained descriptor; independent review `cfc377b4` / tree `075ddb4a` P0/P1=0 |

## Architecture / Test / Operations

### P0

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| A1 | JSDA Queue repeatedly selected only the newest year/files and could not converge on history | FIXED | `7afffade`; stable child segment identity, cursor progress, retry/DLQ evidence |
| A2 | Receipt, D1, Ops, READY, Trader, transition and execution keys had filenames but no complete principal/evidence-authority isolation | OPEN | **SOURCE-PARTIAL / OPERATIONAL-OPEN:** manifests/bootstrap/descriptor isolation and strict positive gate exist; 0/7 OS authorities are provisioned and all registries have active keys=0. D1 sync still couples a generic ledger transaction to remote/live-mirror side effects and is not crash-recoverable. First implement a phased short-transaction, same-directory temporary backup/apply/sign/fsync/atomic-replace and identity-based recovery; then an administrator bootstraps seven UIDs/sockets/root-owned stores/fresh in-authority keys and independently accepts each protocol. |
| A7 | Release workflows did not consume the machine-readable P0 finding gate | FIXED | `6a8fc1f9`; the pinned source-integration validator runs before required CI; the strict gate runs before authenticated deployment acceptance, release evidence, authority activation/positive operations, READY/Trader/Controlled execution. The v3 evidence payload binds the exact ledger digest and OPEN-P0 inventory. |

### P1

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| A3 | Worker tests were almost entirely Node mocks | FIXED | `32a1ea7d`; focused workerd and `createTestHarness()` boundary tests |
| A4 | Legacy 2,254-strategy catalog was imported by the product runtime | FIXED | `e5969f50`; immutable replay artifact only |
| A5 | Python tests still inspect source text, AST, or implementation spelling where a behavioral boundary should suffice | DEFERRED | Replace incrementally with type/capability/transaction invariants; do not increase this class or treat a coarse text-search count as authority |
| A6 | Release evidence existed only at local absolute paths | OPEN | Publish a content-addressed non-secret manifest after production acceptance; backup body remains private/encrypted |

## Integration gate

The latest independent adversarial reviews accepted the fail-closed source
boundaries listed above. That source-versus-operational distinction is prose in
the v1 ledger, not a second machine-enforced status. D2, D3, R5, R10, R11, C4,
C10 and A2 remain operationally `OPEN`; required source-integration CI may
merge an inactive candidate, while the strict production/positive-operation
gate rejects it. The D1-sync crash-atomicity gap is explicitly part of A2 and C4
depends on it. Receipt uses a sole dedicated create-only/readback R2 evidence
surface; live environment-scoped key activation and reproof still remain.
Release, publication and Controlled Pilot remain blocked.
R7's authority-owned append-only history and
sidecar-retention residuals remain tracked by R5/A2 rather than reopening the
fail-closed publication row. PENDING service bootstrap needs a separately
reviewed narrow gate; it must not be achieved by marking operational rows
`FIXED` early or bypassing the strict gate. After all P0 rows are closed, run a fresh
independent review against one immutable SHA, then run the full native
CI-equivalent suite. Only that reviewed SHA may be pushed for the release PR.
