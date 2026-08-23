# P632 `scripts/verify_ci.sh` — code-lane PASS (not merge-gate)

**Lane:** code / `scripts/verify_ci.sh`  
**Requested base:** `40d1aa9009ca1e7a6bd9fdc2df4d4da4cf92eab4` (`origin/grok/phase63-ci-source-closure`)  
**Isolation worktree:** `/private/tmp/qp-p632-verify-ci-40d1aa90` on `grok/p632-verify-ci-40d1aa90` (do not push `main`)  
**PASS SHA:** `40d1aa9009ca1e7a6bd9fdc2df4d4da4cf92eab4` (as-is; no local code fixes)  
**Fetched:** 2026-08-23T15:12:17Z  
**GitHub check-runs / required context `ci-aggregate`:** **not measured, not claimed**  
**Merge gate:** **not green**. This file is a local `verify_ci.sh` exit-0, not a GitHub status.

Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, or Phase 7 GO.

---

## Verdict

| Gate | Status |
|------|--------|
| `scripts/verify_ci.sh` at `40d1aa90` as-is | **PASS** (code lane) |
| GitHub required context `ci-aggregate` posted | **not this lane** |
| Merge-gate green | **NO** |

`verify_ci: ok` is not a live coverage remeasure and is not merge-gate authority.

---

## What ran (PASS SHA)

Isolation worktree used parent `/Users/taku/GitHub/quant-platform/.venv` (Python 3.11.15). No `npm ci --legacy-peer-deps`. No live `wrangler deploy`. npm 11.13.0 / node v24.17.0 / wrangler 4.125.0.

| Step | Result |
|------|--------|
| secret/path scan | pass (no tracked `.env` / `*.pem`) |
| `pip install -e ".[dev]"` | pass |
| `pytest tests/` | **1422 passed, 4 skipped** in 94.88s |
| catalog compile + `catalog_ids` freeze | pass |
| Evaluation IR `schema.json` + golden codec | pass |
| 7 workers `npm ci` / `npm test` / `typecheck` / `wrangler deploy --dry-run` / `npm run types -- --check` | pass (types up to date, `--include-runtime false`) |
| working tree clean after generated types | pass |

Workers: `ingestion-jsda` (2 tests), `ingestion-premium` (6), `ingestion-secrets` (2), `quant-ops-mcp` (26), `research-ai-gateway` (29), `research-mass-eval` (72), `ci-aggregate` (13).

Wall clock: 190.27s (`real`). Log: `/tmp/qp-p632-verify-ci-40d1aa90-logs/verify_ci.log`.

No lockfile, skip, types, or generated `worker-configuration.d.ts` holes. No COMPLETE invention. Invariants not weakened.

Log tail: `verify_ci: ok`
