# Phase 6.3.2 Wave 0 — live remeasure (not a GO)

**Fetched:** `origin/main` = `b5c326a7f612563f2da4a84f08063a307ec38e0a`  
**Branch:** `grok/phase63-ci-source-closure`  
**Review SHA in brief was the same SHA; not used as a freeze.**  
Mass / READY / Phase 7 Controlled Pilot / reconstitution apply: **unchanged NO-GO / OFF / false**.

## Delta vs brief §4

| Surface | Brief review | This fetch |
|---------|--------------|------------|
| origin/main | `b5c326a` | **same** |
| GitHub branch protection | OFF | **OFF** (`gh api` 404 Branch not protected) |
| commit status checks | 0 | **0** (`total_count: 0`) |
| check-runs | 0 | **0** |
| Projection | STALE ~48h | **STALE** age **176248 s** (~49h); `refresh_success=false`; gen `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| B0 | UNKNOWN | **UNKNOWN** |
| READY | null | **null** |
| applied_feed_cursor | null | **null** (CURRENT datasets **0**) |
| latest_change_seq | 2890649 | **2890654** |
| Inventory | 26/5/31 | **26 governed / 5 experimental / 31** |
| Coverage | 22 COMPLETE / 4 PARTIAL | **unchanged** (AM 1/32, earnings 1/200, master 220/241, OTC 5886/8784) |

Cron PASS / row counts / raw retention are **not** Coverage COMPLETE or READY.

## Workers (this tree)

| Worker | lockfile | workers-types | typecheck script | test script |
|--------|----------|---------------|------------------|-------------|
| ingestion-jsda | **missing** | ^4.20250801.0 | no | no |
| ingestion-premium | present | ^4.20250101.0 | yes | no |
| ingestion-secrets | **missing** | ^4.20250101.0 | yes | no |
| quant-ops-mcp | present | ^5.20260820.1 | yes | yes |
| research-ai-gateway | present | ^5.20260820.1 | yes | yes |
| research-mass-eval | present | ^5.20260820.1 | yes | yes |

`--legacy-peer-deps` remains banned. `scripts/verify_all.sh` still covers 3 research workers and skips missing `node_modules`.

## Live honesty

- `applied_cursor=null` → never CURRENT.
- Last-known-good projection is **not** FRESH.
- 4 PARTIAL stay uninvented until Coverage V3 official-domain migration lands.

This file is a Wave-0 receipt, not a pass.
