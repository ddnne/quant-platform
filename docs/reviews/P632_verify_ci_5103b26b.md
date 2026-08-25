# P632 `scripts/verify_ci.sh` — code-lane PASS (not merge-gate)

**Lane:** code / `scripts/verify_ci.sh`  
**Requested base:** `5103b26bb40b2d73b49d079e03f8cf5b9c2a4c58` (`origin/grok/phase63-ci-source-closure`)  
**Isolation worktree:** `/private/tmp/qp-p632-verify-ci-5103b26b` on `grok/p632-verify-ci-5103b26b` (do not push `main`)  
**PASS SHA:** `5103b26bb40b2d73b49d079e03f8cf5b9c2a4c58` (as-is; no local code fixes)  
**Fetched:** 2026-08-23T15:54:37Z  
**GitHub check-runs / required context `ci-aggregate`:** **not measured, not claimed**  
**Merge gate:** **not green**. This file is a local `verify_ci.sh` exit-0, not a GitHub status.

Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, or Phase 7 GO.

---

## Verdict

| Gate | Status |
|------|--------|
| `scripts/verify_ci.sh` at `5103b26b` as-is | **PASS** (code lane) |
| GitHub required context `ci-aggregate` posted | **not this lane** |
| Merge-gate green | **NO** |

`verify_ci: ok` is not a live coverage remeasure and is not merge-gate authority.

---

## What ran (PASS SHA)

Isolation worktree used parent `/Users/taku/GitHub/quant-platform/.venv` (Python 3.11.15). No `npm ci --legacy-peer-deps`. No live `wrangler deploy`. npm 11.13.0 / node v24.17.0 / wrangler 4.125.0 (ingestion-premium lockfile 4.120.1).

| Step | Result |
|------|--------|
| secret/path scan | pass (no tracked `.env` / `*.pem`) |
| `pip install -e ".[dev]"` | pass |
| `pytest tests/` | **1492 passed, 4 skipped** in 93.63s |
| catalog compile + `catalog_ids` freeze | pass |
| Evaluation IR `schema.json` + golden codec | pass |
| 7 workers `npm ci` / `npm test` / `typecheck` / `wrangler deploy --dry-run` / `npm run types -- --check` | pass (types up to date, `--include-runtime false`) |
| working tree clean after generated types | pass |

Workers: `ingestion-jsda` (2 tests), `ingestion-premium` (6), `ingestion-secrets` (2), `quant-ops-mcp` (27), `research-ai-gateway` (30), `research-mass-eval` (75), `ci-aggregate` (13).

Wall clock: 195.15s (`real`). Log: `/tmp/qp-p632-verify-ci-5103b26b-logs/verify_ci.log`.

No lockfile, skip, types, or generated `worker-configuration.d.ts` holes. No COMPLETE invention. Invariants not weakened.

Log tail: `verify_ci: ok`
