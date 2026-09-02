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

The legacy JSON field name `merge_policy` represents this strict release policy,
not a source-merge policy. Version 1 does not machine-model source status: CI
success proves ledger schema/inventory parity only, while independent review
decides whether an inactive source candidate is sufficiently contained to merge.

## Data / PIT / Receipt

### P0

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| D1 | Fixed allowlists were intersected with PIT master only on the first day | FIXED | `d99083f4`; daily listing/delisting invariant tests |
| D2 | COMPLETE issuer accepted caller-originated parsed rows, counts, digests, and exhaustion state | OPEN | **SOURCE-CLOSED (inactive):** `9823744e`, `65454330`, `2bed5ea1`, `cbfaf6df`, `6c46906e`, `7d6fe6cb`, `6518802c`, `c0bcfb37`, `6fe785aa`, `0ee5a9d5`; no caller claims DTO; claims v3 binds the expected environment/authority instance. Durable recovery accepts only the rollback-incompatible closed v2 capture envelope bound to the operation/request/attempt/nonce/start identity and current governed request/policy. It reloads the exact manifest, every raw page and official-calendar bytes, reconstructs each response from stored status/headers/raw, sequentially reruns the current validator, and re-derives pagination/provider exhaustion plus every signed raw/collection/terminal digest before structured reconciliation. The authority canonical-parses/normalizes, exact-compares D1, persists operation/attempt evidence create-only in its sole dedicated R2 bucket with immediate readback, and signs the structured/calendar-descriptor/raw/query/date/binding digests. The consumer enforces the exact J-Quants and equities-master digest inventory. **OPERATIONAL-OPEN:** register/activate fresh environment-scoped keys, deploy distinct production/staging resources, reprove exact dependency segments, and verify the complete export/sync/projection/READY chain; v1/v2, pre-v3 and old receipts remain audit-only. |
| D3 | A same-UID importable signing oracle could mint signed SUCCESS outside governed ingestion | OPEN | **SOURCE-PARTIAL (inactive):** prior Receipt isolation plus `d0c71f58` and `103cd4e6`. Premium has no operator `fetch()` and now separates argument-free PENDING registration from SELECT-only staging `AUDIT_ONLY` evidence into disjoint named entrypoints; the observer binds only the audit entrypoint, so its runtime capability has no registration RPC. The read path derives current source/version from `CF_VERSION_METADATA`, verifies the exact migration-0019 schema and canonical stored attestation, and returns the exact D1 TEXT UTF-8 bytes. The staging-only activation observer has no storage, Queue, DO, AI, or secret binding. Its sole success requires official Workers Access plus an exact random challenge and binds `ctx.access.aud` into canonical response evidence. The live gate owns fixed Access/key manifests and independently brackets four deployments, module bytes, binding/public surfaces, GETs the immutable observer Worker ID and binds its exact enabled non-preview `subdomain.url` to the HTTPS endpoint, verifies the exact worker-destination app AUD and single `non_identity` Service Auth policy/token with no covering app, and checks D1 schema/row/bytes before and after the authenticated request. It accepts no local/in-memory attestation, redirects, proxy inheritance, HTML, old version/key pair, drift, positive operation, release, COMPLETE, research, or `TRUSTED_COLLECTION` eligibility. **SOURCE-PARTIAL/OPERATIONAL-OPEN:** the observer/operator are not deployed and the Access manifest remains `PENDING`. Deploy/accept PENDING, provision/review the key, activate the scoped registry/vars, apply `0019`, deploy the exact observer/Premium versions, initialize Zero Trust if needed, record/review the immutable Worker ID and ID-derived subdomain URL, worker destination, app AUD, one Service Auth policy and exact token ID, run the `AUDIT_ONLY` canary and independent live gate, retire legacy signers, and independently review the evidence. The canary does not close D2 product reproof. Production remains C7 HOLD; D2/D3/A2 and the strict gate remain OPEN. |
| D4 | JSDA publication labels were used as quote-effective dates | FIXED | `56d4fcf9`; `2002-08-02 -> 2002-08-01`, `2002-08-05 -> 2002-08-02` |
| D7 | Signed receipt closure inputs could change between verification and serialization | FIXED | `3836f069`; exact receipt, digest and claims are frozen once before signing; independent review P0/P1=0 |

### P1

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| D5 | Existing 22 COMPLETE datasets were issued before the final trusted path | HOLD | Preserve audit history but remove eligibility until trusted reproof |
| D6 | Canonical Registry duplicated PIT/Coverage semantics | FIXED | `2bd96d69`; registry is membership/routing metadata only |

Disclosed P1 residuals under D2: the receipt does not carry a directly portable,
resolvable R2 locator for every product artifact/manifest; and a first-response
`RAW_ONLY` failure remains fail-closed but raises instead of returning a durable,
typed error envelope.

## READY / Plan / Execution

### P0

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| R1 | exact-four closure required TOPIX but `indices_bars_daily_topix` had no V3 SourceCapability | FIXED | `eb21e84a`; official 2008-05-07 boundary and exact-five-dataset closure independently verified |
| R2 | READY/coherence paths hard-coded one global V2 policy and rejected valid per-dataset V3 evidence | FIXED | `590a71d2`, `76d21575`; exact per-dataset policy triplets plus content-addressed local proof ID reverified from current ledgers/receipts/generation; independent review P0/P1=0 |
| R3 | ExperimentPlan embedded `ready_snapshot_id=not-declared`, making later immutable snapshot equality circular | FIXED | `76240e89`; plan identity is snapshot-free and immutable snapshot binding occurs only in authorization; independent review passed |
| R4 | exact-four bindings were caller-overridable | FIXED | `76240e89`; only the checked-in canonical four plans and exact plan/closure/profile digests reach the scheduler; independent attack tests passed |
| R5 | Generic READY publication and a same-UID arbitrary READY signer remained reachable | OPEN | **SOURCE-CONTAINED (inactive):** `ceaf9d21`, `e0fa86c4`, `52a8499d`, `367d7234`, `5b543e8a`; the generic candidate engine remains introspectable and is not claimed unreachable. It is non-authoritative, has no production signer/key fallback, and its output cannot pass the isolated signature verifier. Before signing, the dedicated authority descriptor-pins and bounded-copies the artifact, independently recompiles the exact plan/profile/closure, re-verifies signed projection/PIT scope, replays policy, and supplies the measured digest to `VerifiedPilotReadyPublication`. The public production READY SQLite opener is removed from package/snapshot exports; its direct-module compatibility trap rejects before resolver or descriptor-open hooks. QuantData database-reading methods now retain the verified descriptor and withhold results until post-read identity/digest revalidation; SQLite treats only that internal descriptor path as immutable. A root-only READY-to-Controlled installer now re-verifies the signed READY response, embedded exact-four manifest and signed projection, copies both to root-owned content-addressed create-only files, fsyncs file/parent, and commits an immutable custody manifest last. Controlled activation v3 removes caller-declared snapshot/projection paths, accepts only that independently reopened custody manifest, and replays the stored projection through the current verifier with attestation/document/file digest equality. The retained `O_RDWR` regression still means no general same-UID production-read integrity is claimed, and `VerifiedPilotReadyPublication` remains shallow metadata. Passive registry/socket metadata is `PENDING/UNKNOWN`, active keys=0. **SOURCE/OPERATIONAL-OPEN with A2/R11:** provision READY UID/socket/key/registry/protected store, execute and independently accept the custody install under real UID/GID ownership, independently recheck current mirror/closure/copy, and publish/verify one exact-four READY; Mass stays disabled. |
| R6 | Missing natural-key ledger could pass through fixture compatibility | FIXED | `d6a49e24`; production collector has no fixture/quality/raw override, exact run/build evidence is re-read fail-closed, fixture helpers are tests-only, and independent review reported P0/P1=0 |
| R10 | Trader authorization remained a same-UID HOME-key signing oracle over caller-constructed approval decisions | OPEN | **Git history / not on the Paper path.** Live-order six-principal and WebAuthn were deleted from the working tree. Active Controlled trader authorization is a signed `VerifiedTraderAuthorization` object loaded from a fixed R2 key and verified against the environment-specific ACTIVE public registry. Production and staging registries currently have no ACTIVE keys, so execute remains fail-closed. **OPERATIONAL-OPEN:** provision environment-scoped ACTIVE trader and READY public keys, publish one signed authorization plus READY sidecar, and accept one Cloudflare Paper run. |
| R11 | Controlled execution duplicated authority lineage into a caller-writable HOME store | OPEN | **Git history / not on the Paper path.** Live-order local HOME custody was deleted from the working tree. Persistent Mac market data is forbidden. The sole Controlled runtime is the existing `research-mass-eval` Worker plus Container: signed trader authorization, pinned ACTIVE registries, BudgetLedger paper occupancy, streamed R2 snapshot, create-only Paper/Risk/Selection/Knowledge children, and ephemeral `/tmp` cleanup. Local Python remains OfflineFixture DRAFT only. **SOURCE/OPERATIONAL-OPEN with A2/R5:** provision ACTIVE READY and trader registries, then accept one complete authorized Pilot artifact chain on Cloudflare. |

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
| C4 | Ops Projection signer accepted a publisher-authored evidence envelope | OPEN | **SOURCE-CLOSED (inactive):** `5fb40304`, `dbbf88ab`; signer injection is removed, the renderer implementation recomputes from a one-shot authenticated descriptor-bound mirror, and the D1 handoff dependency is crash-atomic with exact outer-event acknowledgement. **OPERATIONAL-OPEN:** provision distinct D1-sync/Ops-projection UIDs, keys and stores, execute an authenticated sync, and accept an independently rendered signed FRESH projection; no live FRESH generation has been produced. |
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
| C8 | Seven isolated active-Worker lockfiles remain instead of one npm workspace | DEFERRED | Build-isolation exception in `architecture/adr_worker_dependency_isolation.md`; the seventh is the reviewed dedicated Receipt-authority/rollback boundary, and exact dependency parity remains required |
| C12 | Coverage transition authorization accepted a backward-moving verification clock | FIXED | `b64b3af0`; authorization time is monotonic and rollback is rejected; independent review P0/P1=0 |
| C15 | SQLite scalar or container coercions and stale timestamps weakened exact evidence comparison | FIXED | `c0008890`, `8c61f840`, `e4ec03e1`, `6c048274`; exact scalar/container types and current exported-at evidence are checked through the retained descriptor; independent review `cfc377b4` / tree `075ddb4a` P0/P1=0 |

## Architecture / Test / Operations

### P0

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| A1 | JSDA Queue repeatedly selected only the newest year/files and could not converge on history | FIXED | `7afffade`; stable child segment identity, cursor progress, retry/DLQ evidence |
| A2 | Receipt, D1, Ops, READY, Trader, transition and execution keys had filenames but no complete principal/evidence-authority isolation | OPEN | **SOURCE-PARTIAL (inactive; public canary is HOLD-only; D1 handoff crash-atomic):** `ceaf9d21`, `7871bd2c`, `61c55f58` through `ed5925d9`, `24a15c89`, `637d7c23`, `367d7234`, `5b543e8a`, `d96bdd87`; the manifest declares one Cloudflare Receipt authority and six distinct local UIDs/sockets/stores/key backends, and bootstrap/runner/runtime-config/launchd coverage includes Trader and Controlled. Journal schema v4 binds an unpredictable journal instance, immutable per-attempt challenge/resource/lease/boot/deadline/result evidence, a complete attempt-set digest, full run-state digest and canonical external-anchor candidate. Source includes a domain-separated Ed25519 challenge/commit/resolve protocol whose v2 lineage proof sends only event/attempt/run deltas while remote retained state rederives the complete history; rollback, fork, replay, response loss and concurrent collectors fail closed. The provider reference is in-memory only, no remote deployment or historical key registry exists, and the public run method and CLI remain HOLD-only. Controlled source takes a lifetime lifecycle lock before daemon construction and provides a same-UID, pinned-inode, durable-restart-marker, exclusive-checkpoint WAL-to-DELETE transition that never unlinks SQLite sidecars and fails closed if any remain. WAL restoration is deliberately unavailable until an externally anchored completion verifier is wired, so the transition is source-ready but not operationally accepted. The retained `O_RDWR` regression makes the boundary explicit: mode bits, descriptor pinning and rehashing do not isolate a same-UID writer. QuantData uses a descriptor-pinned/rehashed DB-read boundary, and source includes a root-only create-only content-addressed READY-to-Controlled custody installer plus activation-v3 manifest verifier with a flat Controlled-only supplementary reader group that rejects aliases, nested membership and primary-GID access; none has been exercised under distinct real principals. `VerifiedPilotReadyPublication` remains shallow metadata. Receipt remains PENDING-only and 0/6 local principals are provisioned. **OPERATIONAL-OPEN with R5/R11:** source command paths fail closed, but 0/1 Cloudflare Receipt authority and 0/6 local OS authorities are provisioned, all registries have active keys=0, and the all-P0 strict gate still blocks release/research eligibility. Before any operational canary, select and independently administer a persistent external anchor provider outside the local root trust boundary, provision and retain its remote/client keys and root-owned collector config, wire its bounded-completion verifier to the Controlled WAL restore boundary, and independently accept the quiescence transition under real principals. Then bootstrap six UIDs/sockets/root-owned stores/fresh in-authority keys, execute and independently accept the atomic root-owned READY-to-Controlled custody transition, and independently accept all seven protocols plus the full Pilot chain. Historical anchor key rotation remains unsupported and must fail closed with old keys retained. |
| A7 | Release workflows did not consume the machine-readable P0 finding gate | FIXED | `6a8fc1f9`; the pinned source-integration validator runs before required CI; the strict gate runs before authenticated deployment acceptance, release evidence, local-authority activation/positive operations, READY/Trader/Controlled execution. The v3 evidence payload binds the exact ledger digest and OPEN-P0 inventory. |

### P1

| ID | Finding | Status | Evidence / closure condition |
|----|---------|--------|------------------------------|
| A3 | Worker tests were almost entirely Node mocks | FIXED | `32a1ea7d`; focused workerd and `createTestHarness()` boundary tests |
| A4 | Legacy 2,254-strategy catalog was imported by the product runtime | FIXED | `e5969f50`; immutable replay artifact only |
| A5 | Python tests still inspect source text, AST, or implementation spelling where a behavioral boundary should suffice | DEFERRED | Replace incrementally with type/capability/transaction invariants; do not increase this class or treat a coarse text-search count as authority |
| A6 | Release evidence existed only at local absolute paths | OPEN | **SOURCE-HOLD:** the production builder rejects every caller-supplied observation document. `specs/cloudflare/release_observation_authority.json` pins PENDING, active keys 0 and publication disabled; the private JSDA `/health/ready` Service Binding collector is absent. Close only after an isolated authority signs exact response bytes, staging/production acceptance succeeds, and a content-addressed non-secret manifest is published; backup body remains private/encrypted. |

Disclosed P1 residuals under A2: there is no quarantine/recovery runbook for a
non-`COMMITTED` journal older than one hour; runtime/tool/policy digests are not
retained in the signed D1 audit after journal cleanup; and the generic outer
event ledger holds `BEGIN IMMEDIATE` across the potentially long remote handler.

## Integration gate

Independent adversarial review has accepted some fail-closed boundaries, while
R5, R10, R11 and A2 remain explicitly inactive and operationally `OPEN`, even
where a source-reachable adapter now exists. The source-versus-operational distinction is prose in the v1 ledger,
not a second machine-enforced status. Required CI validates only ledger format
and inventory; independent review decides whether an inactive source candidate
is sufficiently contained to merge. This ledger does not claim source P0 = 0
or Operational Closure. D2, D3, R5, R10, R11, C4, C10 and A2 remain `OPEN`, and
the strict production/positive-operation gate rejects the candidate.
Receipt uses a sole dedicated create-only/readback R2 evidence surface, but the
portable-locator and typed-`RAW_ONLY` error-envelope work remains disclosed P1.
Cloudflare has a checked-in PENDING-only bootstrap path; the local PENDING daemon
is deferred because of ACTIVE-socket evidence ambiguity. Live environment-scoped
key activation, one Cloudflare plus six local-OS authority provisioning,
authenticated sync, FRESH projection,
and receipt reproof still remain.
Release, publication and Controlled Pilot remain blocked.
R7's authority-owned append-only history and
sidecar-retention residuals remain tracked by R5/A2 rather than reopening the
fail-closed publication row. Local PENDING daemon bootstrap remains deferred
until ACTIVE-socket evidence and the transition protocol cannot be confused;
it must not be achieved by marking operational rows `FIXED` early or adding a
general strict-gate bypass. The current all-P0 gate cannot also serve as the
staged activation gate because the required smoke evidence is itself needed to
close the OPEN rows. The source now includes a narrowly scoped, expiring,
authority/action/environment/SHA/resource-bound staged gate whose canary output
remains research-ineligible, but its live read-only operator caller and Service
Binding are not provisioned. The all-P0 gate remains mandatory for final
release, READY eligibility and Controlled Pilot. After all P0 rows are
closed, run a fresh independent review
against one immutable SHA, then run the full native
CI-equivalent suite. Only that reviewed SHA may be pushed for the release PR.
