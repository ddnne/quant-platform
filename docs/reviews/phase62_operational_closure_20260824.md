# Phase 6.2 operational closure record — 2026-08-24–25

This is an evidence record, not a GO declaration. Code/tree closure, isolated
staging deployment, and live data readiness are reported independently.

## Baseline and lossless integration

- Fresh `origin/main`: `b5c326a7f612563f2da4a84f08063a307ec38e0a`.
- Integration branch: `codex/phase62-operational-closure`.
- Existing PRs #1–#21 were audited. None was safe to merge directly; the old
  PR-12 stack omitted 298 authority-only files, including PIT and CI contracts.
- Replacement is a lossless, chronological 12-PR pointer stack. It preserves
  every final-tree file and commit; it does not cherry-pick, squash, or perform
  drop-based history surgery.
- The native Cloudflare GitHub App check is observed and required by expected
  source. Production deployment and `main` merge remain gated on the lossless
  PR sequence and its strict per-head checks.

## Implemented closure

- READY minting is bound to the exact research profile ID, version, digest,
  dataset set/cardinality, current generations, coverage/raw/validation/B0/PIT/
  feature/catalog proofs, and immutable publisher evidence. Legacy proof uplift
  is rejected.
- The product bridge publishes through the immutable verifier into signed
  `VerifiedResearchReadiness`; offline publisher-to-verifier E2E coverage exists.
- JSDA ingestion uses a typed Cloudflare Queue. Cron/manual requests enqueue;
  the consumer acknowledges only `pass && pagination_exhausted && filesStored>0`,
  retries failures, and routes exhausted messages to an isolated DLQ.
- Agent code execution requires an active OS-isolation backend. macOS uses a
  per-run `sandbox-exec` profile; unsupported production hosts fail closed.
  The unsafe backend is explicitly test-only and labels results non-isolated.
- Premium identity is directly importable under Node, schemas are runtime
  dependencies, and Worker entry exports remain handler-only.

## Verification

- Full repository CI at integration SHA `0ae9c3af`: PASS.
  - Python: 1,561 passed, 4 skipped.
  - Catalog freeze and Evaluation IR schema/golden checks: PASS.
  - Worker tests: JSDA 28, premium 138, secrets 22, Ops MCP 39,
    gateway 85, mass 147, CI 28.
  - Every Worker: clean `npm ci`, test, typecheck, Wrangler dry-run, generated
    types check; generated tree clean.
- Post-CI deltas were independently verified:
  - sandbox isolation: 25 targeted tests and 1,553-test lane PASS;
  - top-level Wrangler environment pin: verifier unit tests and shell syntax PASS.
- Final integrated Python suite on the closure tree: 1,572 tests collected,
  exit 0. A local PASS is not the GitHub merge authority.
- Native Workers Build `ce57148b-6c5f-4fc0-9edf-fcf15948011a` at closure commit
  `9b2397f1067781741b0bd8d72b5bc8015a42fec2`: PASS.
  - Python: 1,567 passed, 7 skipped in the Cloudflare image.
  - Catalog freeze and Evaluation IR schema/codec: PASS.
  - All seven Workers completed clean `npm ci`, tests, typecheck, Wrangler
    dry-run, and generated types checks; `verify_ci: ok`.
  - Deploy command `true`: PASS; no Worker version or product deployment.

## Isolated Cloudflare staging

No production database, bucket, KV namespace, secret, or deployment was reused.

| Resource | Staging identity |
|---|---|
| D1 | `quant-ingest-staging` / `d448d1c6-27c8-4aeb-8702-3e7a8b6bf2bb` |
| raw R2 | `quant-raw-staging` |
| structured R2 | `quant-structured-staging` |
| OAuth KV | `quant-ops-mcp-oauth-staging` / `4402f398df93412ebe6774d1bc603142` |
| JSDA queue | `quant-jsda-ingestion-staging` / `fb516bf6b072436ba39a74d1306ff2a3` |
| JSDA DLQ | `quant-jsda-ingestion-dlq-staging` / `d4de13479a1c4b988be754523bccc219` |

The staging D1 was exported before migration. Premium migrations 1–10 and Ops
migrations 1–7 applied successfully using distinct history tables
`d1_migrations_ingestion` and `d1_migrations_ops`.

Active 100% staging candidate versions:

| Worker | Version |
|---|---|
| research-ai-gateway | `6aff828e-17ac-480a-995c-938952a3e7d7` |
| ingestion-premium | `c3fb354c-01a5-4b92-97a3-7597f362cddb` |
| ingestion-jsda | `ba642c80-ce12-40c2-998d-4d55875f3dc4` |
| ingestion-secrets | `f621e1b1-1381-498f-8a9e-a51f3eb8e570` |
| quant-ops-mcp | `b29f4dea-dbbb-47e9-a3e3-be111216cd92` |
| ci-aggregate | `ae98854d-7766-4664-8f21-47651dfe51e1` |
| research-mass-eval | `1891c04f-acf8-414c-99ad-62319592c94d` |

All seven staging Workers have `workers.dev` and preview publication disabled.
No staging OAuth or production secret was fabricated. The work queue has one
staging producer and one staging consumer; the DLQ is bound as dead-letter and
has no replay consumer.

Production queues were provisioned but no production Worker was deployed:
`quant-jsda-ingestion` (`f188568f680c472ba03860e6fdb03349`) and
`quant-jsda-ingestion-dlq` (`d64cf16a51e64601b1e464a80f7f7ae4`).

## Native Workers Builds gate

- Repository connection `31c86c8c-0883-4b4b-a8ca-dd821817dfab` is active for
  `ddnne/quant-platform`. The private CI Worker script tag is
  `6fb2d1474f884b33aa2be98b6a4bcacf`.
- Build token `c43eaa86-018f-47c3-a67d-327f98b424d6` was created through the
  authenticated dashboard. Its secret value was neither retrieved nor recorded.
- Non-production trigger `d9d45236-635c-42cc-a966-6360a6f3c076` and production
  trigger `53389400-a65c-467f-9634-72861cc3fe68` both run repository root `/`,
  build `bash scripts/workers_builds_verify_ci.sh`, deploy `true`, and set
  `SKIP_DEPENDENCY_INSTALL=1`.
- Bootstrap investigation remained fail-closed:
  - `422e0115-0433-4ef2-a51b-110326b87d50`: default Python 3.13 lacked `_sqlite3`.
  - `866d4d5f…`: asdf Python 3.11.15 also lacked `_sqlite3`.
  - `cc3d61f6…`: build user is unprivileged `buildbot`; sudo/apt repair is unavailable.
  - `a9f3099d…`: `/usr/bin/python3` 3.12.3 with SQLite 3.45.1 passed a live query.
  - `1fc9e3d4…`: distro stdlib `venv` lacked ensurepip.
  - `e071910a-2d79-4cd5-9ef5-c30d8f031e80`: pinned `virtualenv` wrapper worked; two helper PATH tests failed.
  - `b7daedbe-aabe-42ad-aa26-cd0d19cfd5af`: one remaining host `venv` package-dependent test failed; 1,566 passed.
  - `ce57148b-6c5f-4fc0-9edf-fcf15948011a`: corrected host-independent contract test; full PASS.
- Native context `Workers Builds: quant-platform-ci-aggregate-staging`, App ID
  `85455`, is the strict required check on `main`; legacy `ci-aggregate` is no
  longer required. Check run `97625670308` is the first full PASS evidence.
- Fail/pass protection smoke: PR #34 was `BLOCKED` on native `FAILURE`; PR #33,
  temporarily evaluated against `main`, was `CLEAN` on native `SUCCESS`. The
  disposable failed branch was deleted and #33 was restored to its stack base.

## Live quant-mcp remeasurement

Measured read-only on 2026-08-24; no live state was repaired or invented.

- Remote Ops MCP exposes 17 read-only tools; local quant-data MCP exposes 26.
- Latest run `14341`: PASS, 23 datasets ingested, 4,459 rows inserted,
  1,785,912 raw bytes.
- Coverage remains V2: 22 COMPLETE / 4 PARTIAL. Partial datasets are
  `equities_bars_daily_am`, `earnings_calendar`, `equities_master`, and
  `jsda_otc`.
- Projection is STALE: generation
  `projgen-ef18b4f86ee946048161d25e2a30a2a8`, generated
  2026-08-21T12:30:49Z; refresh attempted and failed.
- READY: null. B0: UNKNOWN. `applied_feed_cursor`: null.
- Raw manifests: 20,977 total, 18,762 complete/acquired alias, 2,215
  incomplete/failed. Recent zero-row records are classified
  `EXPECTED_EMPTY_WITH_EVIDENCE`; they are not silently upgraded.
- JSDA corporate and Tokyo repo are COMPLETE V2. JSDA OTC is PARTIAL V2:
  5,886/8,784 segments complete, 2,898 remaining.
- AM SLA current state is `PROJECTION_STALE`.

## Decision

**Exact-four Pilot / Mass Research: NO-GO. Phase 7 Foundation may continue.**
Cloudflare merge authority is live and required, but the operational readiness
conjunction remains false: projection stale, READY absent, B0 unknown, applied
cursor absent, and four coverage datasets partial. No receipt, local test,
staging deployment, or paper evidence is promoted into READY or GO authority.
