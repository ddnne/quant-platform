# Phase 6.3.1 operational status

> **Live residual SoT.** Current operational observation:
> `2026-09-10T00:50+09:00`. The Sept 7 snapshot
> [`proof/phase632-resume-20260907.json`](proof/phase632-resume-20260907.json)
> is **historical** (ingestion/D1 facts `2026-09-07` JST; projection age in
> that file `2026-09-06T15:54:43.152Z`). Do not treat `b6880f22` / PR98 Draft
> as today's baseline. These measurements are not READY evidence. Re-measure
> before changing any GO decision. No signed release evidence existed at this
> checkpoint.

The 2026-08-25 baseline is **history**, not current authority. This file holds
operational facts and GO flags only. Review findings live in
[`phase633_finding_ledger.md`](phase633_finding_ledger.md). Historical wave
reports remain in Git history and are not active authorities.

## Decision state

| Scope | Decision | Reason |
|-------|----------|--------|
| Phase 6.3 trust/operations foundation | **CONDITIONAL** | Code remediation and release verification are not complete |
| Phase 7 offline foundation | **GO** | Offline development may continue without production READY |
| exact-four Controlled Pilot | **NO-GO** | No current profile/closure-bound READY |
| Autonomous Mass Research | **NO-GO** | Pilot readiness is not Mass authority; Mass remains disabled |
| Phase 8 / FoF / live broker / real orders | **NO-GO** | Outside this phase and explicitly disabled |

Green code or a passing Cron does not change these decisions. Exact-four may
run once only after every Controlled Pilot gate is measured as passing. It may
not promote automatically.

## Current observation (2026-09-10T00:50+09:00)

Read-only. No market rows downloaded. No production DB/Queue/DLQ/Cron
mutation. No signed release evidence at this checkpoint. Policy remains
personal single-user/cloud-only; historical AM reconstruction uses J-Quants
daily `MC`/`MAdjC` with PM `AAdjC` (PR99). No local market DB. No Mass, live,
or automatic promotion.

Sources: observed `origin/main` after
[PR #100](https://github.com/ddnne/quant-platform/pull/100) merge; native
`Workers Builds: quant-platform-ci-aggregate-staging` **SUCCESS** on
[PR100 source head `23149d6b`](https://github.com/ddnne/quant-platform/commit/23149d6b8c153f8388785821147fa128d954b807);
live projection remeasure about `2026-09-10T00:00+09:00`; this branch's
independently reviewed descriptor source.
[`proof/phase632-resume-20260907.json`](proof/phase632-resume-20260907.json)
was not rewritten.

| Item | Observed value |
|------|----------------|
| Fresh-clone starting `main` | `b08b57e6` (PR98 and PR99 already merged) |
| PR100 | merged `2026-09-09T15:48:40Z`; [PR #100](https://github.com/ddnne/quant-platform/pull/100) |
| Observed baseline SHA (`origin/main` at observation) | `ced574c5366ce0249c867c9da743a7f65c553f20` — not a claim that future HEAD stays this value |
| PR100 source head | [`23149d6b8c153f8388785821147fa128d954b807`](https://github.com/ddnne/quant-platform/commit/23149d6b8c153f8388785821147fa128d954b807) |
| Required native check on that source head | [`Workers Builds: quant-platform-ci-aggregate-staging`](https://github.com/ddnne/quant-platform/commit/23149d6b8c153f8388785821147fa128d954b807) (Cloudflare `app85455`) **SUCCESS**; build `7568c558-549d-4dc9-9df2-339abea4e01b` |
| `verify_ci` | `ok`; Python 3572 passed / 4 skipped; Worker lane aggregate succeeded (lane total not restated) |
| Main-merge SHA CI | **pending** at this checkpoint |
| This branch descriptor commit | `25027dc28e7af8ac1987fc23feb8a9602b14d763` — source reviewed (188 Node + 7 workerd); **not deployed** |
| Live projection (~00:00 JST) | **STALE**, generation `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| Projection generated | `2026-08-21T12:30:49.152421+00:00` |
| Refresh | `refresh_attempt=false`, `refresh_success=false` |
| Source cursor | `2898387` |
| Applied cursor | **null** |
| B0 | **UNKNOWN** |
| READY | **null** |
| Ops envelope | envelope schema v3 is **not** proof of `collection-coverage/v3` |
| Tool/schema parity, D1 migration apply state | **not remeasured** 2026-09-10; Sept 7 rows stay historical |
| Access / Zero Trust | **not remeasured** 2026-09-10 |
| Mass production Worker version (at 00:50 observation) | `5341e76c-ce48-4261-8e28-58d3ea7a081b`; a later secret-only update may change a version |
| Mass staging Worker version (at 00:50 observation) | `f665e5d6-71d6-4202-8c36-21275d2abe98`; a later secret-only update may change a version |
| Mass auto-deploy command | **HOLD** unchanged |
| Secrets / Gateway staging | source tests and dry-runs passed on reviewed source; **no deploy** at this checkpoint |
| READY private key (Mass staging and production, at 00:50) | missing, **names-only** observation; operator automation can provision. READY key ID absent; registries **0 ACTIVE**. This is not itself a human-only task |

`POST /v1/export/receipt-products` on this branch is a metadata-only descriptor:
existing `trustedComplete`, exact current-reference checks, closed pins, UTF-8
SQL-side bounds. `profile_completeness`, `physical_availability` are
`NOT_CHECKED`; `readiness` is `NOT_EVALUATED`. No new READY candidate,
orchestrator, signer activation, or Pilot.

### Post-checkpoint staging secret provisioning (2026-09-09T15:53:10.636Z)

After the 00:50 observation (`2026-09-10T00:53+09:00`). Codex reviewed the
temporary Grok helper and provisioned a newly generated **staging-only**
dedicated Ed25519 PKCS8 secret directly to Cloudflare via stdin. No secret
value was printed or written locally. Readback secret **names**:
`MASS_EVAL_TOKEN` and `READY_ED25519_PRIVATE_KEY`. `READY_ED25519_KEY_ID`
remains absent. Public registries unchanged, **0 ACTIVE** keys; publisher
remains PENDING. Secret provisioning only — not a Worker source release and
not READY activation. Production was still missing the dedicated key at the
earlier 00:50 observation.

Recorded for future controlled registration only (Ed25519 **raw public key**
base64; public metadata, not a private secret, not ACTIVE verification
authority): `70z/1xGKnE2hZ3HRMHfArloIS07XtxSGqQlAWpfmeSQ=`

### Remaining source and operational blockers

See [`operations/current_production_runbook.md`](operations/current_production_runbook.md).
GO flags above are unchanged. Still open, honestly:

- no cloud READY candidate-preparation or orchestration caller/Service Binding;
- the undeployed receipt-product descriptor does not check profile completeness
  or physical availability and is not READY; Ops metadata still does not bind
  exact dependency scope, raw retention, or validation proofs;
- Trader production signer is absent;
- release builder is unconditionally PENDING;
- no FRESH signed projection; applied cursor remains null;
- READY/trader registries remain 0 ACTIVE.

Activating keys alone does not close these gaps. A metadata-only descriptor or
Ops envelope is not READY.

### JSDA early archive

Standing parser/reproof note, not a 2026-09-07 or 2026-09-10 remeasurement:
official 2002 archive files for publication labels `2002-08-02` and
`2002-08-05` use the early 21-column format. The parser accepts that format
and binds the label to the prior quote-effective business date. Both segments
remain **REPROOF_REQUIRED**, not COMPLETE, until immutable raw persistence,
canonical normalization, structured reread, and a new trusted receipt succeed.

## Historical measured facts (2026-09-07)

Read-only live measurements from
[`proof/phase632-resume-20260907.json`](proof/phase632-resume-20260907.json).
No market rows were downloaded. That day's aggregation is not READY evidence
and is not today's repository baseline.

| Item | Historical value |
|------|------------------|
| `origin/main` then | `b6880f22b4b4add2dfcac2e1fe1ffa90db860817` |
| Pull request then | 98 (Draft) |
| CI completion / main merge then | **not measured** that day |
| Latest J-Quants run | `14796`, `2026-09-07T00:15:15+09:00`, 23/23 PASS, 14 inserted rows, cloudflare Cron |
| Coverage policy projected live | `collection-coverage/v2` |
| Coverage | **INCOMPLETE**; 4 PARTIAL of 26 governed datasets |
| Projection | **STALE**, generation `projgen-ef18b4f86ee946048161d25e2a30a2a8` (same generation as 2026-08-21) |
| Projection generated | `2026-08-21T12:30:49.152421+00:00` |
| Refresh | `refresh_attempt=false`, `refresh_success=false` |
| Source cursor | `2897146` |
| Applied cursor | **null** |
| B0 | **UNKNOWN** (snapshot quality/B0 projection unavailable) |
| READY | **null** (no published READY generation bound to this Worker) |
| Ingestion D1 migrations | staging and production latest applied `0010_raw_acquisition_status.sql`; **0011 through 0023 pending both** |
| Production migration table | `d1_migrations` record_count 16; mixes ingestion and Ops names |
| Staging migration table | `d1_migrations_ingestion` record_count 10 |
| quant-mcp live 16-tool vs repository 17-tool schema parity | **not remeasured** |
| Raw acquisition / Queue / Cron / Access / D1 size / preview URLs | **not verified** that day |

The four v2 PARTIAL datasets (historical projection view, not a 2026-09-10
reproof) are:

| Dataset | Projected coverage | Note |
|---------|--------------------|------|
| `equities_bars_daily_am` | PARTIAL | V2 policy; V3 is tip-scoped |
| `equities_earnings_calendar` | PARTIAL | V2 policy; V3 is cutoff/tip-scoped |
| `equities_master` | PARTIAL | V2 policy |
| `jsda_otc_bond_reference_prices` | PARTIAL | V2 policy |

Do not create empty COMPLETE receipts to erase V2 false gaps. V3 exists in the
tree but is not operational until trusted reconciliation has reproved required
closure and a fresh projection is published. Passing Cron and 14 inserted rows
do not change GO flags.

## Historical 2026-08-25 baseline (not current authority)

Dated machine-readable snapshot:
[`proof/phase631-baseline-20260825T050447Z.json`](proof/phase631-baseline-20260825T050447Z.json).
Last direct measurement then: `2026-08-25T14:04:47+09:00`.

| Item | Historical value |
|------|------------------|
| `HEAD == origin/main` | `c718011a7407e8c601076e626ad4fc3a1377ae44` |
| Worktree | clean |
| Open pull requests | 0 |
| Required check | `Workers Builds: quant-platform-ci-aggregate-staging` |
| Required-check source | Cloudflare Workers and Pages app (`app_id=85455`) |
| Required-check result | success |
| Python | 1,567 passed / 7 skipped |
| Worker tests | 487 Node tests; this count alone is not runtime proof |
| Latest J-Quants run | `14357`, 23/23 PASS, 66,132 inserted rows |
| Coverage | 22 COMPLETE / 4 PARTIAL |
| Source cursor | `2891143` |
| quant-mcp | live 16 tools / repository 17; missing `storage_plane_status` |
| Raw acquisition | 21,322 attempts / 19,107 acquired |
| Production ingestion D1 | `quant-ingest` (`be6fdcf8-40be-41fc-9535-7facd1fc2ffc`) |
| D1 size | 717,897,728 bytes |
| Queue / DLQ backlog | 0 / 0 |
| Premium Cron | `15 * * * *` |
| JSDA Cron | `30 1 * * *` |
| Pending ingestion migration then | `0011_jsda_queue_v2.sql` |
| Dedicated Ops projection D1 | created; migration/publication pending |
| Dedicated Ops quota D1 | created; migration pending |
| `ingestion-secrets` Access | not enabled |
| production preview URLs | live baseline enabled; release config sets `preview_urls=false` |
| `jsda_tokyo_repo_rates` / `jsda_corporate_bond_transactions` | last-known projected COMPLETE 1/1 and 12/12 in that stale projection |

Do not use this table as the latest live measurement. Cloudflare Zero Trust
activation is not accepted implicitly. That Access row was not re-verified on
2026-09-07 and was **not remeasured** on 2026-09-10.

## Fail-closed Controlled Pilot gates

All of the following must be directly measured before exact-four executes:

- fixed allowlist intersected with PIT master on every trading day;
- COMPLETE receipts issued only from trusted raw-to-structured reconciliation;
- every dataset in the exact plan dependency closure reproved under its V3
  policy;
- current, non-null applied cursor and FRESH signed projection;
- B0 and B4 PASS with no production compatibility fallback;
- immutable profile/plan/closure/snapshot-bound READY;
- `VerifiedPilotReadiness` accepted only by the Controlled Pilot service;
- exact-four plans, versions, FeatureRefs, budgets, and digests match;
- AI Gateway reservations settle on success, reject, provider error, and timeout;
- quant-mcp tool-name and closed-schema digest parity;
- independent review reports unresolved P0 = 0.

Missing evidence is `UNKNOWN` or `FAIL` in production. Fixture compatibility is
test-only and can never mint Pilot or Mass authority.

## Recording policy

Do not add dated review-wave files, `run_wNN` scripts, or result scorecards to
this file. Paper, Risk, Selection, and Knowledge artifacts belong in immutable
artifact storage. The live finding ledger and its machine-readable companion
are updated in place; Git history preserves prior states.
