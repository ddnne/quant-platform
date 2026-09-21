# Current production runbook

<!-- CURRENT_PRODUCTION_RUNBOOK -->

This is the **only executable production operations document**. Historical
Phase 6.1 / 6.2 runbooks are non-executable. Live GO flags live in
[`../phase62_residual_status.md`](../phase62_residual_status.md); dated
observation tables there are history. Current source, staging-schema, and
read-only Ops facts live in
[`current_work_ledger.json`](current_work_ledger.json). Review findings
live in [`../phase633_finding_ledger.md`](../phase633_finding_ledger.md).

Do not print secret values. Check presence only.

## Resumed 2026-09-21 — PR229 repair

User subsequently approved one outcome: PR229/230 main integration after
review/native CI, limited staging rollout, and existing February same-operation
recovery using preserved raw/PREPARED evidence. Ordinary same-scope fixes and
verification are included without per-command reapproval. Production, READY,
Pilot, Mass/broker, fresh full acquisition and new full D1 backup remain excluded.
PR229 merged as `163170ad`. PR230 incorporates that main merge (no source-tree
change) and must pass native CI on its new final SHA before merging. The approval
supersedes the merge/staging/recovery HOLD below only for this bounded outcome.

Latest checkpoint: PR229 exact source `15639ffe` passed native check
`106166775570` (build `3799cbcc-a9b1-404f-87dd-bcb1ae2960bc`). No deployment
occurred. Stacked Draft PR230 now integrates historical complete-master
membership using explicit closure V3, preserving original acquisition clocks
and labeling contemporaneous observation unproven. Python 413, Worker 454
and workerd 55 tests passed; typecheck and generated-contract checks passed.
The independent review's Python/Worker provenance mismatch was fixed.
Existing fixtures cover late acquisition; no new test-count target or
authority layer was introduced. Final PR230 SHA still needs native CI.
Resume with that check, then obtain the single scoped merge/rollout outcome
approval before crossing the existing HOLD. Reprove cloud data before READY;
do not reuse old profile digests or claim actual 2023 observation.

**Status:** `RESUMED_BY_USER`. Grok's subscription ended; Codex now implements.
Remote main was rechecked at `26abffec`; PR229 remains Draft. Native CI on
the pause checkpoint `157ee2f2` failed. Local Receipt runtime tests reproduced
four failures, including signing despite canonical DB disagreement and losing
original ingestion time. Those regressions and crash/cursor replay are the
first repair unit. The next source repair replaces whole-body finalization
with streamed product bytes and bounded row resumes; local tests do not make
this PR merge/deploy-ready.

Repair checks: Receipt typecheck PASS and 66 workerd tests PASS, including
an interrupted page write with D1 ahead of the R2 progress cursor. Existing
`ensureKey` negative-RPC diagnostic is still printed by the suite. Readback
checks are batched and product bytes use canonical DB ingestion timestamps;
the change-feed match is part of the product query. Full native CI on the
pushed repair remains pending. No remote data/deployment changes were made.

Monthly repair: D1 writes/readback are batched in 50-row groups, each call
handles at most 6,000 rows and four raw pages, and large finalization starts
in a fresh invocation. Product measurement and upload read 1,000 rows at a
time; R2 readback hashes a stream. New v2 manifests contain metadata, not a
second copy of the product. Existing v1 indexed products retain their original
manifest after independent measurement/readback on recovery.
The synthetic 29-page / 80,707-row acquisition-to-signed-Receipt test passed
with a product larger than 100 MB, no vendor refetch and a manifest under
10 KB. This is workerd/D1/R2 local runtime evidence, not deployed CPU-limit
or live data acceptance. Independent source review found the v1 recovery
issue; the repair was rechecked with no additional blocker reported.
Final local checks: Receipt typecheck and all 67 workerd tests PASS; Premium
typecheck and 13 receipt-client tests PASS. Exact-SHA native CI and staging
acceptance are tracked separately in the ledger. Production, READY and Pilot
remain unchanged.

The table below preserves the **historical pause checkpoint**, not current
test or live acceptance. Existing production/data/READY/Pilot HOLDs remain.

| Item | Value |
|------|-------|
| Repo | https://github.com/ddnne/quant-platform |
| Conversation | `01a0abdb-4795-7500-a5b7-6e9c1684932e` |
| Branch / PR | `fix/receipt-durable-capture-reconcile` / [PR229](https://github.com/ddnne/quant-platform/pull/229) |
| Original source head | `64c8e4d7bd0ed0f4e688aa9b160a2590b1f6b888` (native SUCCESS `104994000343` is historical on this SHA only) |
| WIP source commit | `8cc5aecc9c983ac2b2dc083f930c0cf11ee05d31` (unverified; not ready) |
| Docs checkpoint | this commit on the same branch |
| Accepted main | `26abffecd4463c5d052e9f28d862bc67a7c006a1` (PR228). Live SHA/status is `current_work_ledger.json`; do not copy stale PENDING `d37ef73` tables from older paragraphs below. |
| Edited files (WIP, not reviewed/accepted) | `product_materialization.ts`, `receipt_evidence.ts`, `structured_reconciliation.ts` |
| Validation this pause | `git diff --check` PASS; Receipt `tsc --noEmit` PASS; existing focused vitest `-t "resumes remaining structured pages from durable capture without a refetch"` PASS (1 passed, 64 skipped). Full CI/full test: notrun. |
| Open monthly blockers | Durable next-page progress and D1 2MB/1000-query product materialization are WIP; existing tests that assert nonempty D1 `artifact_body` are not updated; missing realistic-size synthetic E2E and duplicate-key tests; Feb 6738 still COLLECTING/PREPARED (15-min `MAX_CONTEXT_AGE` vs 21600s continuation TTL is a source-confirmed issuance block, not a proven live OOM). |
| Original source-unit scope | Source + local synthetic tests + read-only staging diagnosis + Git/PR/native CI only. No remote mutation/migration/deploy/merge. Existing Feb PREPARED/raw/same operation only. |
| Next step (explicit resume only) | Complete bounded finalization, end-to-end synthetic proof, final reviews and native CI **before** any merge/deploy. |
| Later / incomplete | Master P1 (`equities_master` `ingest_time_conservative` available_at vs 2023 PIT), global Ops, READY, Pilot. Original 2023 exact-four ideas, AM-PM, and budget stay. Source / staging / data / READY / Pilot remain separate. Preserve existing cloud raw/PREPARED/attempts; January bars 3/3 HOLD. No local market history, no new full D1 backup, no production/DLQ/Pilot/Mass/broker. Held worktree `exact-five-acquisition-recovery` and Draft PR137 unchanged. |

## Canonical machine-readable authorities

| Authority | Path | Check command |
|-----------|------|----------------|
| D1 migration owners, order, checksums | [`specs/cloudflare/d1_migration_manifest.json`](../../specs/cloudflare/d1_migration_manifest.json) | `.venv/bin/python scripts/cloudflare_d1_migration_manifest.py` |
| Active Worker bindings, toolchain, observability | [`specs/cloudflare/active_worker_bindings.json`](../../specs/cloudflare/active_worker_bindings.json) | `.venv/bin/python scripts/cloudflare_binding_manifest.py` |
| Ops read tool inventory | [`platform/workers/quant-ops-mcp/src/domain.js`](../../platform/workers/quant-ops-mcp/src/domain.js) `OPS_TOOLS` | count `tool("` entries in `OPS_TOOLS` |
| Native CI | [`scripts/verify_ci.sh`](../../scripts/verify_ci.sh) | `scripts/verify_ci.sh` |
| Authenticated production acceptance | [`scripts/verify_cloudflare_deployment_acceptance.sh`](../../scripts/verify_cloudflare_deployment_acceptance.sh) | `scripts/verify_cloudflare_deployment_acceptance.sh` |

`applied_state` in the migration manifest is `UNVERIFIED` on purpose. Record
remote apply results only in immutable release evidence.

## Honest holds

- **Cloudflare Access / Zero Trust:** HOLD remains for Worker Access
  JWT/hostname protection only. Read-only GET
  `/accounts/11233bca08d134a9b738eaa46b9751d9/access/organizations` returned
  error 9999 `access.api.error.not_enabled`. A 2026-09-15 GET recheck also
  returned 9999; no UI was inspected, so this is not a claim that a ToS or
  team-domain prompt is currently required. A Cloudflare account API token
  is control-plane auth, not a Worker Access JWT. `GET
  /v1/private/jsda-health-ready` requires `ctx.access.aud`. This is not a
  precondition for schema recovery, read-only Ops checks, or ordinary
  source fixes. Header token remains enabled. Do not treat Access as
  closed, and do not serialize it before all other work. Existing Wrangler
  OAuth works for real staging reads/migration. Separate Grok MCP auth
  errors remain; they are not a global source-work stop. Agreed Codex
  mechanical fallback may apply authorized operations after a Grok
  permission denial; that is not a HOLD bypass. No paid API fallback.
- **Controlled Pilot:** **NO-GO** until live evidence in
  `docs/phase62_residual_status.md` passes. Green tests do not arm exact-four.
  Runtime still requires signed READY, signed Trader authorization, an
  immutable snapshot, and BudgetLedger occupancy. Legacy v1 envelopes also
  require signed projection; PR168 native execution uses receipt-native signed
  evidence instead of `signed_projection_document`. Global live Ops projection
  freshness remains a separate outstanding acceptance gate. Do not infer GO.
- **READY publication path:** live publication is PENDING/undeployed. Mass
  submits Container `POST /v1/materialize-receipt-candidate`; COMPLETED PASS
  freezes one candidate snapshot and may emit a receipt-native v2 manifest,
  still `go:false` / `ready:false`. Current read-only Ops facts live in
  `current_work_ledger.json` `live_observation` (not GO). Ops projection/v3
  is not proof of Coverage V3 deployment. Do not replace unmeasured with 0
  or close global GO. Coverage, raw, and receipt proofs are last-recorded
  MISSING/unmeasured live evidence, not a claim that source cannot accept
  complete authentic proofs. Public v2 attestation stays PENDING until that
  live evidence exists. Product bytes use Service Binding `INGESTION_PREMIUM`
  → `PremiumReceiptProductInputService`. Source-only `raw_collection_manifest`
  re-reads collection-manifest bytes after in-place RAW_BUCKET page-body
  checks (256 pages / 64MiB total / 16MiB per page are local verification
  caps, not acquisition or platform limits; over-cap is HOLD). Live R2 page
  inventory is not verified here. Scheduled Ops publisher is
  `ops_projection.ts`; READY signer is `ready_publication.ts` (undeployed).
  Native envelope execution is accepted source (PR168) and consumes
  receipt-native evidence, not legacy `signed_projection_document`. Paired
  Paper Trader v2 mint is on main (PR169 / 59109819) inside existing
  `publishAdmittedReceiptCandidate`; runtime still PENDING without a dedicated
  trader secret and one ACTIVE trader key. Live secret/registry state was not
  remeasured; activation remains pending acceptance. PR170 (main 4e137) slimmed
  the PENDING release-evidence builder; A6 remains OPEN. PR171
  (https://github.com/ddnne/quant-platform/pull/171, feature `fe1b7f1`) Node Mass
  native lifecycle consumes Premium-serialized READY+Trader bytes with real
  verifiers; workerd publication RPC remains mocked; required native check
  103777783817 was in_progress at 2026-09-13T19:26Z (historical; lookup
  that PR for later acceptance, no success forecast from that timestamp). Existing Mass staging secret history is not
  this SHA deployed. `POST /v1/export/receipt-products` is undeployed read-only
  and is not READY. Generic v1/Python publication routes remain distinct.
  Activating keys is not live READY or GO. Inactive source rollout is not
  global live acceptance. Wire the existing trust root; do not add another
  authority or Worker.
- **Release evidence:** authenticated **STAGING JSDA AUDIT_ONLY** intake exists
  in `scripts/build_release_evidence.py`. Caller JSON is untrusted. Local
  digest-named output is `STAGED_LOCAL_NOT_PUBLISHED` / `release_allowed=false`,
  not a public release. A6 remains OPEN for independently accepted staging
  AND production authenticated collection of actual endpoint bytes, then a
  content-addressed non-secret published manifest. GitHub Release
  immutability and production collection are later repo/API or auth work,
  not inherently human-only; existing content-addressed R2/JSDA AUDIT_ONLY
  paths are not A6 closure. Staging JSDA intake cannot close global A6.
  On 2026-09-16 the operator chose no additional full D1 export / encrypted
  backup job (no `--initiate`, no new keys/bundle, no local price history).
  Missing backup recipient and key custody is not a blocker for the
  already-approved staging SHA-align. That choice does not mark A6 FIXED and
  does not authorize a replacement enterprise backup framework.
- **Mass Research:** **NO-GO**. Mass talks to Gateway only through typed
  Service Binding RPC `GatewayService`. `GATEWAY_TOKEN` is HTTP defense in
  depth if a closed route is attached later; it is not a shared Mass
  credential.

- **Encrypted D1 backup (source present, operator declined additional job):** Mass
  `POST /v1/d1-backup-encrypt` (MASS_EVAL_TOKEN, `go: false`) forwards to the
  existing snapshot Container `POST /v1/encrypt-d1-backup`. Container internet
  stays off. Operator helper from the repo root (project environment; it
  imports `scripts.encrypt_d1_backup`, so `python3 scripts/...` fails):
  `uv run --frozen python -m scripts.d1_export_poll_descriptor --help`.
  `--environment` and `--output` are required. Example only. Do **not** run
  `--initiate`: live export interrupts D1, and the operator declined an
  additional full D1 backup. Preserve existing cloud raw / observations /
  receipts / control / attempt history / key identity and existing backups.

  ```bash
  uv run --frozen python -m scripts.d1_export_poll_descriptor \
    --environment staging \
    --output "$HOME/.local/share/quant-platform/private/d1-export-bundle.json" \
    --initiate
  ```

  The helper polls the D1 export API (metadata only; SQL never touches the Mac)
  and writes one 0600 bundle (DB identity, `at_bookmark`, observed
  `export_completed_at`, `signed_url`). Worker secret
  `D1_BACKUP_EXPORT_BUNDLE` plus `D1_BACKUP_KEY`
  are checked before SUBMITTED/Container boot. Job digest includes
  `signed_url` sha256; `d1.export` download requires that fingerprint to match
  the current bundle. `children-then-manifest` cannot carry the dump.
  Ciphertext is a streaming create-only `research.r2` PUT under
  `research/d1-backups/`. Restore/schema/`integrity_check` stay
  `encrypt_d1_backup.py` QPDBENC2 on Container scratch with sqlite3 CLI.
  Accepted restored sqlite is a postcondition (<= 5 GiB), not a hard runtime
  disk cap. SQL dump stream is 4 GiB; ciphertext is dump plus QPDBENC2
  framing. Runtime structural bound is the existing standard-4 Container
  20 GB physical disk (image/files share it; not all usable scratch). The
  180-minute process-group watchdog is a finite bound, not exact billing;
  terminal publication, retry, shutdown, and cleanup can add time. Create-only
  R2; COMPLETE is not issued before verification and upload succeed. D1
  `file_size` is not dump size. Do not POST D1 export,
  generate keys, or deploy this image until one combined approval. Whole-DB
  restore after shared writers resume remains prohibited.
- **Mass product-lane deploy trigger:** deployment leg held. Trigger
  `b83cc2ee-8a40-4448-b517-80959796eb3e` had only its deploy command replaced
  via the Cloudflare API; build and test still run. Read-back verified
  `2026-09-09T15:04Z`. Original deploy command:
  `npm run deploy --prefix platform/workers/research-mass-eval`. Temporary
  deploy command:
  `python3 -c "raise SystemExit('DEPLOYMENT HOLD: coordinated staging rollout pending; see current_production_runbook.md')"`.
  Authoritative repo-root CI is unchanged. Restore only after staged then
  production code rollout is accepted for Secrets, Receipt, Premium
  product+READY-publication bindings, Gateway, then Mass. Inactive Worker
  code rollout is not key activation, READY mint, or Pilot GO. Staging Mass
  tagged deploy is Cloudflare Builds only and requires approved rollout
  scope; ordinary same-scope bug fixes and reverification do not need a
  fresh approval. Do not restore or retrigger production, data, READY,
  Pilot, or key HOLDs, and do not retry blindly after uncertain mutation:
  read back live Build/Worker/Container state. Native Cloudflare Builds
  checkout of this public repository may present HTTPS origin userinfo
  and unavailable `refs/remotes/origin/main`; tagged deploy still requires
  clean HEAD to equal live `https://github.com/ddnne/quant-platform.git`
  `refs/heads/main` and must not pass origin credentials to git. Native
  Node must be on PATH for Wrangler 4.125.0; Python deps use frozen
  `uv==0.11.26` with `/usr/bin/python3`. The native Builds deploy command,
  from the repository root with clean HEAD equal to current main, is:

  ```bash
  p=$(node -p process.execPath) && pipx run --spec "uv==0.11.26" uv sync --frozen --python /usr/bin/python3 && cd platform/workers/research-mass-eval && env -u CLOUDFLARE_ENV PATH="${p%/*}:$PATH" ../../../.venv/bin/python ../../../scripts/cloudflare_binding_manifest.py --deploy-tagged --worker research-mass-eval --env staging
  ```

  Local CLI invocation from the repository or Worker directory is not a
  working deployment path. Local and production Mass tagged deploy stay refused while a Container
  image is declared. Worker multipart module-byte verification is not
  Container image rollout or research GO. Image push can follow Worker
  upload and is not transactional. The 900s mutate timeout only waits on
  the Wrangler parent and does not confirm a detached Docker build/push
  was cancelled; after timeout mark state uncertain, STOP, and read actual
  Build/Worker/Container state before retry or a separately approved
  rollback. See [Workers Builds default vars](https://developers.cloudflare.com/workers/ci-cd/builds/configuration/),
  [Containers deploy](https://developers.cloudflare.com/containers/guides/deploy/),
  and the 20-minute [Builds execution cap](https://developers.cloudflare.com/workers/ci-cd/builds/limits-and-pricing/)
  (not a rollback or billing guarantee).
  Smoke must not execute market data or Containers. Global live acceptance
  is the final check, not a blocker for prerequisite Worker code rollout.
  This bounded repair does not run D1 migration, JSDA activation, or DLQ
  mutation.
- **Current staging code rollout (not acceptance):** This paragraph is not
  a live SHA table. Accepted Secrets/Receipt/Premium ACTIVE SHA, dated
  PENDING `d37ef73` history, and Mass checkpoint live in
  `current_work_ledger.json` `lanes.source_delivered` /
  `lanes.staging_deployed` (accepted main
  `26abffecd4463c5d052e9f28d862bc67a7c006a1`). Authenticated 403 smoke is
  pending location of existing `MASS_EVAL_TOKEN` (no rotation; ask only
  location or already-set process env; never print values). That gap
  blocks only that smoke. Gateway, Mass, JSDA, Ops, and the observer were
  not SHA-aligned in that unit. Worker/Container code rollout is not
  auth-smoke, data, READY, or Pilot. Staging schema is `SCHEMA_PREPARED`
  (canonical `0001`–`0023`), distinct from Worker code and from JSDA
  `--activate`. `--activate` and production stay SHA-tag strict.
- **JSDA cutover follow-ups (open):** whole shared-D1 Time Travel restore is
  removed from the operator. A Time Travel bookmark remains recovery-reference
  evidence only; Premium and Receipt writers are not fenced. `--rollback`
  refuses with `FORWARD_REPAIR_REQUIRED` and does not restore D1, resume old
  delivery, or roll a v2-only Worker onto v3 data. Production JSDA no longer
  declares a DLQ consumer; the main Queue still dead-letters onto
  `quant-jsda-ingestion-dlq`. This source change does not close Receipt
  checkpoint/O(N²), scoped READY, or any live rollout. A concrete incident
  needs its own reviewed forward correction from live state.
- **Quant Ops legacy agent:** `QuantOpsMcpAgent` remains on deprecated,
  feature-frozen `McpAgent` for un-inventoried legacy `/sse` compatibility.
  Source CI pins `agents` and the lock bytes and measures the complete
  post-construction workerd prototype. Exact module-byte acceptance is the live
  identity and transitively binds the embedded binding-manifest digest. It also
  brackets all active production Worker versions and rejects any live binding,
  handler, migration or runtime drift, including external Quant Ops Service
  Bindings and Durable Object stubs. The lockfile itself is not claimed as a
  live API observation. No deploy or legacy client drain has occurred. Follow
  [`../architecture/adr_quant_ops_mcpagent_migration.md`](../architecture/adr_quant_ops_mcpagent_migration.md): migrate `/mcp` to `createMcpHandler`, then drain
  `/sse` only after a real client inventory.
- **AM history:** do not treat V2 monthly AM completeness as a current target.
  V3 AM completeness remains tip-scoped. Residual PARTIAL rows are not
  permission to mint empty COMPLETE receipts. 2023-class historic reconstruction
  uses Premium daily `MC` / `MAdjC` / `AAdjC` with original `available_at` /
  `ingested_at` (`historical_daily_reconstruction` in `governed_am_view.py`).
  Tip Coverage and retrospective daily provenance are different; do not revive
  "AM history impossible". Historic AM+gross-cap engine artifacts that cannot
  prove `am_frozen_order_batch/v1` stay invalidated; do not overwrite or delete
  them. Cloud inventory of those artifacts is still pending.
- **Authority reachability:** Paper-only trust is the existing Cloudflare
  Receipt evidence authority, READY publisher, environment-scoped public-key
  registries, typed Service Bindings, content-addressed R2 snapshot, and
  BudgetLedger occupancy. Local six-principal OS users, root installers,
  WebAuthn, and external-anchor ceremonies are not production tasks on this
  path. Operational activation remains open: Receipt is PENDING-only, READY
  and trader registries have active keys=0, no accepted READY sidecar exists,
  no signed FRESH projection has been produced, Coverage V3 cloud transition
  is unaccepted, and A2, D2, D3, R5, R10, R11, C4 and C10 remain `OPEN`.
- **Staged activation:** source now includes a narrow Receipt staging ACTIVE
  validator and a Cron-only `AUDIT_ONLY` recovery canary whose operator RPC is
  read-only. The canary has dedicated Durable Object state/events, never calls
  ordinary Receipt issue/recover, and stores only its signed attestation in the
  Premium D1. The validator checks exact source/module/deployment/binding/
  migration/secret names, the pinned one-key registry, the real Ed25519
  signature and the complete initial/first-recovery/replay-confirmation digest
  chain. The first recover call remains unsigned and pending; only a second
  identical recover call appends the authority-owned replay event and signs the
  final attestation. It remains
  research-ineligible and cannot create Coverage or `TRUSTED_COLLECTION`.
  The gate binds an immutable authority-version/caller-version/key/registry
  pair. Every authority deploy, key rotation or registry change therefore
  requires a coordinated Premium redeploy after the authority and a new
  version-scoped D1 audit row. Old rows and attestations are never mutated or
  reused; the gate rejects an old authority attestation and rejects a new one
  until the newer Premium caller version is selected.
  The Receipt Durable Object's exact five-method RPC inventory is frozen in the
  binding manifest; internal key/state/event helpers are JavaScript-private and
  unavailable to workerd RPC. All four named WorkerEntrypoints separately pin
  ordinary RPC methods and the reserved `fetch` special.
  Staging source now also has two idle-by-default R2 control ticks on the
  existing Premium minute Cron (same lifecycle as
  `control/equities_valuation/backfill.json`):
  `control/receipt_pending_registration.json` invokes the existing
  `pending_public_key_registration` path once, idempotently, PENDING-only,
  and persists the validated public operator envelope (the 19-field
  registration plus caller provenance; never wrapped/private key);
  `control/exact_five_compiled_acquisition.json` admits explicit
  `{dataset, segment_id}` jobs pinned to the generated exact-four
  profile/closure identity. Worker admission is catalog month bounds
  (official history start, no future window, no month after the compiled
  period end) plus those pins; it does not compile warmup. Selector
  membership is `ops.exact_five_acquisition_control` from
  `compiled_candidate_selectors` /
  `compiled_period_collection_segments` bootstrap and
  `declared_coverage_segments` / `_missing_compiled_segments` fill,
  including pre-period master/fins/bar/split months. Canonical full-month
  windows come from the catalog (1/tick, 3 attempts, source parse max 24
  jobs; that ceiling is not an authorized cloud execution plan). Exact-five runs only when
  valuation is absent or complete, not leased/CAS/error. Fetch abort is 30s
  on the ingest callback only; it does not cancel D1/R2/Receipt and the 90s
  lease is not proof the prior owner stopped. Absent objects are no-ops.
  PENDING staging Cron does not run `recoverPreparedReceipts` (no governed
  issue). ACTIVE staging Cron recovers PREPARED identities then runs the
  existing AUDIT_ONLY canary. Tag alphabet is `rp-` PENDING / `ra-` ACTIVE
  (`ra-s-c` is the ACTIVE Premium caller, not a different Worker). PENDING
  Cron does not invoke the canary. They are not deployed until a later
  SHA-align. Writing either control object is a later approved mutation, not
  authorized by source merge. Do not add a public Premium route. Mass remains
  verify-only. This is still operational HOLD for ACTIVE keys, READY, and
  Pilot. Do not add a general bypass or execute ACTIVE instructions yet. The all-P0 gate remains the final
  release checklist. Runtime Worker paths separately enforce keys, READY,
  Trader authorization, and BudgetLedger occupancy; those checks are not the
  all-P0 gate.
- **Equities master:** the closed acquisition route is available only as
  `ACTIVE_RAW_ONLY`; COMPLETE/reproof eligibility remains
  `PENDING_AUTHORITY_ACTIVATION`. The current generated registry expresses
  those two axes by listing `equities_master` as both routed and PENDING. Do not
  interpret route availability as COMPLETE eligibility; the next contract PR
  must split those axes explicitly.

## 1. Preconditions

```bash
test -n "${INGESTION_RUN_TOKEN:-}" && echo INGESTION_RUN_TOKEN=present
test -n "${DATA_EXPORT_TOKEN:-}" && echo DATA_EXPORT_TOKEN=present
test -n "${CLOUDFLARE_API_TOKEN:-}" && echo CLOUDFLARE_API_TOKEN=present
test -n "${CLOUDFLARE_ACCOUNT_ID:-}" && echo CLOUDFLARE_ACCOUNT_ID=present
npx wrangler whoami
scripts/verify_cloudflare_deployment_acceptance.sh
```

Stop if production D1/R2/Queue names or IDs differ from
`specs/cloudflare/active_worker_bindings.json`. Every active environment has
`preview_urls = false`, `observability.enabled = true`,
`head_sampling_rate = 1`, and `[version_metadata] binding = "CF_VERSION_METADATA"`.
The authenticated acceptance gate also runs `wrangler secret list --env
production --format json` for all seven active Workers and requires the exact frozen
secret-name set. It reads names and binding kinds only; values are never
requested or printed. Missing authentication, missing names, and unexpected
names all fail closed. Wrangler is `4.125.0`.

## 2. D1 migration policy: single Cloudflare operator

Do not hand-loop SQL files or invoke `wrangler d1 migrations apply` directly.
`ingestion-premium` owns the `quant-ingest` chain.

Staging schema is `SCHEMA_PREPARED` (canonical `0001`–`0023`). Do not
generic-retry the failed `--prepare-staging-schema` incident, do not
automatically retry after a new partial apply, and do not rerun
`--repair-staging-schema-incident` (still in source; operationally closed).
Remaining 0011–0022 include 0017/0022 ADD COLUMN and 0020 rebuild, which are
not generic-idempotent. Exact live readback:
https://github.com/ddnne/quant-platform/pull/207#issuecomment-5676026212
(mutable operational evidence, not an immutable release). Original private
receipt/intent identity stayed original. The successful normal release left
the live lease vacant (`remote_spawned=0`, empty `source_sha`, expires 1970);
a vacant lease does not retain source. The pre-apply 78-object fingerprint
in the work ledger is PRE-APPLY ONLY: independently checked before and after
CAS before remote spawn, not a SQL CAS input/predicate, not the current
post-migration fingerprint, and not retry authority. Same-host overlapping
repairs remain refused by a nonblocking flock on the existing original
control-intent file; that is not a distributed lock and does not replace
remote D1 identity or CAS. Finish-only verifies a `verifying` /
`remote_spawned=0` lease without reapplying migrations.

Historical closed-incident command (do not rerun; not deleted from source):

```bash
.venv/bin/python scripts/activate_jsda_v3_cutover.py --environment staging --repair-staging-schema-incident --yes
```
Normal later staging schema-only preparation (no JSDA Worker deploy, no
`v3_active`) remains:

```bash
.venv/bin/python scripts/activate_jsda_v3_cutover.py --environment staging --prepare-staging-schema --yes
```

JSDA product activation is a separate later command and is not implied by
schema-prep:

```bash
.venv/bin/python scripts/activate_jsda_v3_cutover.py --environment staging --activate --yes
# After staging is ACTIVATED at the same reviewed source SHA:
.venv/bin/python scripts/activate_jsda_v3_cutover.py --environment production --activate --yes
```

Use `scripts/apply_ingestion_d1_migrations.py --environment ENV --check` for a
read-only observation. The canonical chain currently ends at
`0023_mutation_lease`; never apply only a prefix.

Migration 0012 copies the populated v2 JSDA graph into a separately constrained
v3 graph, installs v1/v2 retire triggers, and never drops v1/v2 data. Every
statement is resumable, but neither a migration-history row nor a local file
proves exact remote schema, data preservation, exclusion, or the source SHA
that executed.

[`scripts/d1_ingestion_migration_validation.py`](../../scripts/d1_ingestion_migration_validation.py)
provides exact ephemeral schema/history validation. The operator then:

1. records a small create-only control intent before changing JSDA Cron;
2. stops JSDA Cron, observes two stable drains, pauses the JSDA main Queue, and
   verifies the drain again so a post-pause enqueue cannot race the bookmark.
   This does not stop Premium or Receipt writers on the shared D1;
3. records a Time Travel bookmark as recovery-reference evidence before applying
   any migration. The bookmark is not restore authority;
4. acquires the same-D1 CAS lease, crosses the `remote_spawned` fence, applies
   the canonical chain with a bounded Wrangler subprocess, and verifies exact
   schema/history;
5. activates the new source SHA and restores the exact prior JSDA Queue/Cron
   state.

The local control intent is a few-kilobyte crash-recovery cache, not authority.
Remote D1 plus live Cloudflare version/config/Queue/Cron observations are the
source of truth. Whole-file local D1 exports are not part of cutover. The
operator does not restore `quant-ingest` / `quant-ingest-staging` via Time
Travel. `--rollback` fails closed with `FORWARD_REPAIR_REQUIRED`. Use `--check`
for read-only diagnosis. Any concrete incident requires an independently
reviewed forward corrective migration or compatible Worker release.

The source-manifest consistency check does not contact or mutate Cloudflare:

```bash
.venv/bin/python scripts/cloudflare_d1_migration_manifest.py
```

If the process exits after it has created a run, resume only that run ID:

```bash
.venv/bin/python scripts/activate_jsda_v3_cutover.py \
  --environment staging --resume --run-id RUN_ID --yes
```

`--rollback --yes` is a policy refusal, not a restore. It does not mutate Cron,
Queue, D1, Worker versions, leases, or local evidence.

JSDA observation identity lives in
`platform/workers/ingestion-premium/migrations/0012_jsda_observation_identity.sql`
and precedes migration 0013 in the canonical `quant-ingest` chain. The Worker
reads/writes v3 after this source revision. Do not deploy a v2-only Worker
against post-cutover D1 state. Reverse Worker rollback after a shared-D1
restore is removed from this operator.

When 0012 is applied it leaves `jsda_v3_cutover_control.phase` at `bridge`.
Safe JSDA writer sequence is: stop old v1/v2 Cron and the JSDA main consumer,
drain leases/jobs/main queue to zero, persist the bookmark as evidence, migrate,
deploy and activate v3. Product Cron/Queue stay fail-closed until
`v3_active`. Activation is one-way; D1 forbids reverse transition, INSERT
OR REPLACE, and late v1 `jsda_acquisition_jobs` writes.

[`scripts/activate_jsda_v3_cutover.py`](../../scripts/activate_jsda_v3_cutover.py)
directly observes Cloudflare state. `--check` never mutates. `--activate`
requires double-observed zero JSDA jobs/leases/backlog, stopped JSDA Cron and
main Queue delivery, the production main dead-letter route without a production
DLQ consumer, canonical bindings, and a pre-migration Time Travel bookmark used
only as recovery-reference evidence.
Production additionally requires a remote staging `ACTIVATED` run for the same
source SHA plus matching live Worker/config/Queue/Cron observations. Caller
JSON or a local admission file is not authority. Cloud Ops Projection
publication is the ingestion-premium scheduled publisher, not Mac-local SQLite.

`GET /health` is liveness only. Deployment acceptance must call
`GET /health/ready` and require HTTP 200, `product_ready:true`,
`cutover:"V3_ACTIVE"`, `activated_source_sha` equal to the Cloudflare build
commit SHA, plus distinct `cutover_config_digest` and
`drain_evidence_digest`. A generic `GET /health` `PASS` is not product
deployment.

The JSDA Worker has no public route. Cutover acceptance therefore uses the
remote D1 activation record and authenticated Cloudflare control-plane
observations; `/health/ready` remains an internal product-readiness response,
not migration authority.

## 3. Publish the signed Ops projection (HOLD)

Do not publish from Mac-local `data/structured/ingestion.sqlite` or
`data/research_snapshots`. Persistent data is R2 authority plus D1 metadata;
Container SQLite is ephemeral only.

Safe cloud-only order, still HOLD:

1. Apply projection/quota migrations `0001`/`0002` to **staging** dedicated D1
   (`quant-ops-projection-staging`, `quant-ops-quota-staging`).
2. Publish one SEALED generation from the ingestion-premium scheduled
   publisher into the dedicated staging projection D1. Mac-local
   `publish_ops_projection.py --apply-remote` is disabled. Do not switch MCP
   traffic onto an empty dedicated D1. `npm run deploy` in quant-ops-mcp
   fails closed unless a signed SEALED active generation is present.
3. Deploy staging MCP bound to the dedicated staging projection/quota D1.
4. 17-tool / schema / generation smoke against staging.
5. Repeat migrate/publish for production dedicated D1.
6. Switch production MCP bindings only after a SEALED generation exists.
7. Production 17-tool smoke.

Scheduled publisher source exists (`ops_projection.ts`). Keep live MCP on its
current binding and leave dedicated projection/quota DBs unpublished until an
accepted SEALED cloud generation is present. See
[`projection_publish_guard.md`](projection_publish_guard.md) for the
COMPLETE-count guard. Publish remains HOLD.

## 4. Remote Ops MCP

The repository surface is the frozen `OPS_TOOLS` list in
`platform/workers/quant-ops-mcp/src/domain.js` (**17** tools, including
`storage_plane_status`). Live Cloudflare may lag; do not operate from a 16-tool
memory. Unauthenticated `/mcp` must be `401`.

```bash
curl -i "$QUANT_OPS_MCP_URL/mcp" \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl-smoke","version":"1"}}}'
```

## 5. JSDA rolling locators

Current-year / current-file JSDA URLs are re-observed per governed run. Dated
archive URLs stay one observation. Each observation gets a D1-owned monotonic
sequence; `current_*` never regresses to an older completion. Artifacts are
content-addressed and may be observed from more than one SourceObject.
Discovery PASS is run-closure, not root-job completion: queued, running, or
transient descendants keep the run nonterminal; a rejected descendant is never
PASS. Cron roots are daily-stable. Queue redelivery of a completed observation
is idempotent, repairs ancestor aggregates, and does not permanently complete a
rolling URL.

```bash
curl -fsS -X POST \
  -H "X-Ingestion-Token: $INGESTION_RUN_TOKEN" \
  "$INGESTION_JSDA_URL/v1/run"
```

## 6. Failure rules

- Persist D1/R2 evidence before Queue ack. Evidence-write failure retries.
- Invalid Queue bodies keep reject/DLQ audit evidence without caller values.
- Controlled Pilot and Mass remain NO-GO until residual live evidence passes.
- Access 9999 remains open for Worker Access JWT/hostname protection only;
  it is not a stop on ordinary source fixes, read-only Ops, or already
  authorized staging schema work. Explicit production/data/JSDA-activate/
  key/READY/Pilot/Ops-publication HOLDs are unchanged by generic continue.
