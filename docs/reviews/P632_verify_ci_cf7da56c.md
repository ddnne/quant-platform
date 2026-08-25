# P632 `scripts/verify_ci.sh` — code-lane PASS (not merge-gate)

**Lane:** code / `scripts/verify_ci.sh`  
**Requested base:** `cf7da56c17260da2c2693540f28af91c849bd542` (`origin/grok/phase63-ci-source-closure`)  
**Isolation worktree:** `/private/tmp/qp-p632-verify-ci-cf7da56c` on `grok/p632-verify-ci-cf7da56c` (do not push `main`)  
**PASS SHA:** `cf7da56c17260da2c2693540f28af91c849bd542` (as-is; no local code fixes)  
**Fetched:** 2026-08-23T17:14:42Z  
**GitHub check-runs / required context `ci-aggregate`:** **not measured, not claimed**  
**Merge gate:** **not green**. This file is a local `verify_ci.sh` exit-0, not a GitHub status.

Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, or Phase 7 GO.

---

## Verdict

| Gate | Status |
|------|--------|
| `scripts/verify_ci.sh` at `cf7da56c` as-is | **PASS** (code lane) |
| GitHub required context `ci-aggregate` posted | **not this lane** |
| Merge-gate green | **NO** |

`verify_ci: ok` is not a live coverage remeasure and is not merge-gate authority.

---

## What ran (PASS SHA)

Isolation worktree used parent `/Users/taku/GitHub/quant-platform/.venv` (Python 3.11.15). PYTHONPATH unset (did not point at another worktree). No `npm ci --legacy-peer-deps`. No live `wrangler deploy`. npm 11.13.0 / node v24.17.0 / wrangler 4.125.0 (ingestion-premium lockfile 4.120.1). HEAD includes python IR codec+types freeze (`c9764ff4` / `e20be4d9`), premium NK rebuild Worker tests (`8fc9fa30`), JSDA fail-closed run-token extras (`afd94e58`), and catalog `dateMode` JSON contract (`2218b861`).

| Step | Result |
|------|--------|
| secret/path scan | pass (no tracked `.env` / `*.pem`) |
| `pip install -e ".[dev]"` | pass |
| `pytest tests/` | **1500 passed, 4 skipped, 0 failed** in 86.90s |
| catalog compile + `catalog_ids` freeze | pass |
| Evaluation IR `schema.json` + golden codec (generated py+ts freeze) | pass |
| 7 workers `npm ci` / `npm test` / `typecheck` / `wrangler deploy --dry-run` / `npm run types -- --check` | pass (types up to date, `--include-runtime false`) |
| working tree clean after generated types | pass |

Workers: `ingestion-jsda` (4 tests; fail-closed run-token extras), `ingestion-premium` (38; including `catalog.test.ts` 2 identity+dateMode, `availability.test.ts` 8, `collection_receipts.test.ts` 2, `natural_key_migration.test.ts` 5 NK rebuild), `ingestion-secrets` (6), `quant-ops-mcp` (27), `research-ai-gateway` (30), `research-mass-eval` (76), `ci-aggregate` (13).

Wall clock: 170.33s (`total`). Exit code: **0**. Log: `/private/tmp/qp-p632-verify-ci-cf7da56c-logs/verify_ci.log`.

No lockfile, skip, types, or generated `worker-configuration.d.ts` holes. No COMPLETE invention. Invariants not weakened.

Log tail: `verify_ci: ok`
