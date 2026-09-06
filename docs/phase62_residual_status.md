# Phase 6.3.1 operational status

> **Live residual SoT.** Current read-only measurements are stored in
> [`proof/phase632-resume-20260907.json`](proof/phase632-resume-20260907.json).
> Ingestion and D1 migration facts were observed on `2026-09-07` JST.
> Projection observation in that file is `2026-09-06T15:54:43.152Z`
> (age derived from `projection_generated_at`; parallel calls may differ by
> seconds). These measurements are not READY evidence. Re-measure before
> changing any GO decision.

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

## Current measured facts (2026-09-07)

Read-only live measurements from
[`proof/phase632-resume-20260907.json`](proof/phase632-resume-20260907.json).
No market rows were downloaded. Current aggregation is not READY evidence.

| Item | Measured value |
|------|----------------|
| `origin/main` | `b6880f22b4b4add2dfcac2e1fe1ffa90db860817` |
| Current pull request | 98 (Draft) |
| Current CI completion / main merge | **not measured**; do not treat as complete or merged |
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
| Raw acquisition / Queue / Cron / Access / D1 size / preview URLs | **not verified today** |

The four v2 PARTIAL datasets are:

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

### Remaining source work (code integration)

See [`operations/current_production_runbook.md`](operations/current_production_runbook.md).
These are source/code integration gaps, not only missing keys or human
account settings:

- no cloud READY candidate-preparation or orchestration caller/Service Binding;
- Premium Ops metadata does not bind exact dependency scope, raw retention,
  receipt products, or validation proofs;
- Trader production signer is absent;
- release builder is unconditionally PENDING.

Activating keys alone does not close these gaps. A metadata-only Ops envelope
is not READY.

### JSDA early archive

Standing parser/reproof note, not a 2026-09-07 remeasurement: official 2002
archive files for publication labels `2002-08-02` and `2002-08-05` use the
early 21-column format. The parser accepts that format and binds the label to
the prior quote-effective business date. Both segments remain
**REPROOF_REQUIRED**, not COMPLETE, until immutable raw persistence, canonical
normalization, structured reread, and a new trusted receipt succeed.

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
activation remains a human-only account action and is not accepted implicitly;
that Access row was not re-verified on 2026-09-07.

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
