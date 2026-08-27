# Phase 6.3.1 operational status

> **Live residual SoT.** Last direct measurement:
> `2026-08-25T14:04:47+09:00`. A dated machine-readable baseline is stored in
> [`proof/phase631-baseline-20260825T050447Z.json`](proof/phase631-baseline-20260825T050447Z.json).
> Re-measure before changing any GO decision.

This file holds operational facts and GO flags only. Review findings live in
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

## Repository and CI baseline

| Item | Measured value |
|------|----------------|
| `HEAD == origin/main` at fresh-clone baseline | `c718011a7407e8c601076e626ad4fc3a1377ae44` |
| Baseline worktree | clean |
| Open pull requests | 0 |
| Required check | `Workers Builds: quant-platform-ci-aggregate-staging` |
| Required-check source | Cloudflare Workers and Pages app (`app_id=85455`) |
| Required-check result at baseline | success |
| Python baseline | 1,567 passed / 7 skipped |
| Worker baseline | 487 Node tests; this count alone is not runtime proof |

The active release branch is not live evidence until it is reviewed, merged,
deployed, and re-measured. The deprecated caller-receipt CI Worker is removed;
the required-check name is retained as a compatibility name for the native
Cloudflare check.

## Live data and projection

| Item | Measured value |
|------|----------------|
| Latest J-Quants run | `14357`, 23/23 PASS, 66,132 inserted rows |
| Coverage policy projected live | `collection-coverage/v2` |
| Coverage | 22 COMPLETE / 4 PARTIAL |
| Projection | **STALE**, generation `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| Projection generated | `2026-08-21T12:30:49.152421Z` |
| Refresh | `refresh_attempt=false`, `refresh_success=false` |
| Source cursor | `2891143` |
| Applied cursor | **null** |
| B0 | **UNKNOWN** |
| READY | **null** |
| quant-mcp | live 16 tools / repository 17 |
| Missing live tool | `storage_plane_status` |
| Raw acquisition | 21,322 attempts / 19,107 acquired |

The four projected PARTIAL datasets are:

| Dataset | Projected coverage | Current interpretation |
|---------|--------------------|------------------------|
| `equities_bars_daily_am` | 1 / 32 | V2 asks for false monthly history; V3 is tip-scoped |
| `equities_earnings_calendar` | 1 / 200 | V2 asks for false monthly history; V3 is cutoff/tip-scoped |
| `equities_master` | 220 / 241 | V2 includes dates before official availability |
| `jsda_otc_bond_reference_prices` | 5,886 / 8,784 | V2 includes non-publication days; two real early parser/reproof gaps remain |

Do not create empty COMPLETE receipts to erase V2 false gaps. V3 exists in the
release tree but is not operational until the trusted reconciliation path has
reproved the required closure and a fresh projection is published.

### JSDA early archive

The official 2002 archive files for publication labels `2002-08-02` and
`2002-08-05` use the early 21-column format. The parser now accepts that format
and binds the label to the prior quote-effective business date. Both segments
remain **REPROOF_REQUIRED**, not COMPLETE, until immutable raw persistence,
canonical normalization, structured reread, and a new trusted receipt succeed.

`jsda_tokyo_repo_rates` remains 1/1 COMPLETE and
`jsda_corporate_bond_transactions` remains 12/12 COMPLETE in the stale live
projection. These are last-known projected facts, not proof of current READY.

## Cloudflare operations

| Item | Measured value |
|------|----------------|
| Production ingestion D1 | `quant-ingest` (`be6fdcf8-40be-41fc-9535-7facd1fc2ffc`) |
| D1 size | 717,897,728 bytes |
| Queue backlog | 0 |
| DLQ backlog | 0 |
| Premium Cron | `15 * * * *` |
| JSDA Cron | `30 1 * * *` |
| Pending ingestion migration | `0011_jsda_queue_v2.sql` |
| Dedicated Ops projection D1 | created; migration/publication pending |
| Dedicated Ops quota D1 | created; migration pending |
| `ingestion-secrets` Access | **not enabled** |
| production preview URLs | live baseline enabled; release config sets `preview_urls=false` |

Cloudflare Zero Trust activation requires an account agreement in the current
UI. It is a human-only conditional action and is not accepted implicitly. The
existing header token stays as defense-in-depth; the proxy is not deleted until
legacy-client dependency is disproved.

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
