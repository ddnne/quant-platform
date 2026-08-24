# Phase 6.3.3 finding ledger (live)

> **Single current finding ledger.** Independent reviewers fill rows.
> Live residual **flags** remain [`phase62_residual_status.md`](phase62_residual_status.md).
> `docs/reviews/P632_wave*` and Independent A/B/C revisit files are **historical freezes**, not this ledger.
> Do **not** declare GO, Mass ON, production READY, Phase 7 ON, Projection FRESH, or invented COMPLETE from this file.

Policy: [`architecture/adr_review_findings_sot.md`](architecture/adr_review_findings_sot.md).
Index of freezes: [`reviews/README.md`](reviews/README.md) (keep; do not add a new wave).

Status vocabulary: **OPEN** / **FIXED** / **DEFERRED** / **HOLD**. Empty sections are empty — not a pass.

Independent reviews of `58133512` (full write-ups, not this table): `docs/phase633_findings_data_pit.md`, `docs/phase633_findings_cloudflare_ci.md`, `docs/phase633_findings_architecture_test.md`, `docs/phase633_findings_integration.md`. Code fixes on `grok/p633-authority-closure` `be84b6fb` are **tree** status; live Cloudflare/GitHub is unchanged until HUMAN.

Unresolved live P0 (merge gate) remains **>0**. Do not merge PR #1.

## Data / PIT

### P0

| ID | Finding | Status | Evidence | Notes |
|----|---------|--------|----------|-------|
| D1 | Signed claims not bound to outer receipt; no VerifiedReceipt | FIXED (tree) | `verified_receipt.py`; `ec848bc4` | Independent review `6e112837` |
| D2 | `extra_digests` overwrites standard claims | FIXED (tree) | `partition_extra_digests` | |
| D3 | Empty-raw signed SUCCESS can evaluate COMPLETE | FIXED (tree) | `4caaa813` evaluate_segment + envelope classification | `{"data":[]}` not COMPLETE |
| D4 | Master CURRENT parse miss → empty snapshot put | FIXED (tree) | `master_scd2/write.ts` quarantine | Lane I `8fa95798` |

### P1

| ID | Finding | Status | Evidence | Notes |
|----|---------|--------|----------|-------|
| D5 | Recovery origin still not COMPLETE-eligible | HOLD | `is_complete_eligible_receipt` | Keep ineligible |

## Cloudflare / CI

### P0

| ID | Finding | Status | Evidence | Notes |
|----|---------|--------|----------|-------|
| C1 | `ci-aggregate` is caller-supplied receipts, not native CF Build | OPEN | Worker 10007 absent; check-runs 0 | HUMAN: GitHub App + repo-root Build |
| C2 | Required GitHub check never posted | OPEN | `gh` check-runs total 0 | Same as C1 |
| C3 | GitHub Actions present | FIXED | `.github/workflows` absent | Must stay absent |
| C4 | `workers_dev=false` still serves `*.workers.dev` on live deploys | OPEN | live `/health` 200 | HUMAN dashboard disable |
| C5 | Caller `budget_id` minted occupancy via `idFromName` | FIXED (tree) | control-plane DO run id | Live Edge unproven |

### P1

| ID | Finding | Status | Evidence | Notes |
|----|---------|--------|----------|-------|
| C6 | GATEWAY_TOKEN dual copy; CF-Worker not auth | HOLD | P632B-03 | |
| C7 | Secrets proxy public host | OPEN | HUMAN Access/mTLS/Tunnel | |
| C8 | `verify_all` skippable ≠ merge gate | HOLD | keep split; native check is SoT | |

## Architecture / Test

### P0

| ID | Finding | Status | Evidence | Notes |
|----|---------|--------|----------|-------|
| A1 | Two `PaperExecutionService` paths; weak `run_paper` | FIXED (tree) | DTO delegates to product service | `c1b5caf6` |

### P1

| ID | Finding | Status | Evidence | Notes |
|----|---------|--------|----------|-------|
| A2 | `ProcessIsolatedRunner` defaulted `sys.executable` | FIXED (tree) | closed tool-id map | Lane J |
| A3 | ReadyManifest split publisher/coherence/readiness | FIXED (tree) | `ready_manifest.py` | No live READY |
| A4 | `pilot_candidates()==active` 2092 | FIXED (tree) | `87f5d7d7` four ExperimentPlan ids | start() still OFF |
| A5 | leftover occupancy | HOLD | `daily_path.ts` | Do not extract |
| A6 | live math size | KEEP | `cost_models` / `options_225` | Do not split |
| A7 | `skipLibCheck` hides Env mismatch | PARTIAL | ci-aggregate/secrets/jsda/premium `false`; gateway/mass-eval/ops-mcp still true | generated Env vs source still split on ci-aggregate |
| A8 | Ops MCP still JS | PARTIAL | `checkJs: true` (`536ffe14`); source remains JS | skipLibCheck still true on MCP |

## Integration

### P0

| ID | Finding | Status | Evidence | Notes |
|----|---------|--------|----------|-------|
| N1 | PR #1 unreviewable (450 commits / 421 files) | OPEN | ADR `adr_phase633_pr_stack.md` | Do not force-push; 10 PRs from main not assembled |
| N2 | Live merge gate dead | OPEN | ci-aggregate absent | HUMAN |
| N3 | Projection STALE, READY null, B0 UNKNOWN, applied_cursor null | OPEN | quant-mcp this turn | Lane M HUMAN |
| N4 | Coverage JSON v3 in tree vs live V2 ledger | OPEN | Lane E derive helper | Do not claim live V3 |
| N5 | Four independent reviews required | FIXED (process) | four finding files on this SHA | Unresolved live P0 ≠ 0 |

### P1

| ID | Finding | Status | Evidence | Notes |
|----|---------|--------|----------|-------|
| N6 | 89 `docs/reviews` files in PR #1 | HOLD | historical freezes | Do not add waves |
