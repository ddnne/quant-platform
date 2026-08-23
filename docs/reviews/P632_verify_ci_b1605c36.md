# P632 `scripts/verify_ci.sh` — code-lane PASS (not merge-gate)

**Lane:** code / `scripts/verify_ci.sh`  
**Full-run SHA:** `b1605c36e4a5f2c5048264d71baadea8589c4ed4` (`docs: P632 verify_ci code-lane result at b5f6f2de`)  
**Post-run Worker re-check SHA:** `208df8ec` (six Worker-unit commits on that SHA; pytest/catalog/IR/other workers unchanged).  
**Prior freeze:** [`P632_verify_ci_b5f6f2de.md`](P632_verify_ci_b5f6f2de.md) (`b5f6f2de`; 1500 passed / 4 skipped; premium **49** then). Do not copy 49.  
**GitHub check-runs / required context `ci-aggregate`:** **0**. Live Worker **absent** (Wrangler 10007).  
**Merge gate:** **not green**. This file is a local `verify_ci.sh` exit-0 plus a later Worker vitest re-run, not a GitHub status.

Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, or Phase 7 GO.

---

## Verdict

| Gate | Status |
|------|--------|
| `scripts/verify_ci.sh` at `b1605c36` as-is | **PASS** (code lane) |
| mass-eval + premium vitest at `208df8ec` | **PASS** (105 / 69) |
| GitHub required context `ci-aggregate` posted | **not posted** |
| Merge-gate green | **NO** |

`verify_ci: ok` is not a live coverage remeasure and is not merge-gate authority.

---

## Full `verify_ci.sh` at `b1605c36`

Parent tree `/Users/taku/GitHub/quant-platform`. PYTHONPATH unset. Python 3.11.15 via `.venv`. No `npm ci --legacy-peer-deps`. No live `wrangler deploy`. Exit **0**. Log tail: `verify_ci: ok`.

| Step | Result |
|------|--------|
| secret/path scan | pass (no tracked `.env` / `*.pem`) |
| `pip install -e ".[dev]"` | pass |
| `pytest tests/` | **1501 passed, 4 skipped, 0 failed** in 96.36s |
| catalog compile + `catalog_ids` freeze | pass |
| Evaluation IR `schema.json` + golden codec | pass |
| 7 workers `npm ci` / `npm test` / `typecheck` / `wrangler deploy --dry-run` / `npm run types -- --check` | pass |

Workers at `b1605c36`:

| Worker | Tests |
|--------|------:|
| ingestion-jsda | 4 |
| ingestion-premium | **67** / 16 files |
| ingestion-secrets | 6 |
| quant-ops-mcp | 27 |
| research-ai-gateway | 30 |
| research-mass-eval | **76** / 8 files |
| ci-aggregate | 13 |

Python collected **1501** (was 1500 at `b5f6f2de`). Count growth is **not** a win.

---

## Worker vitest after six test commits (`208df8ec`)

Full `verify_ci.sh` was **not** re-run for pytest/catalog/IR/jsda/secrets/mcp/gateway/ci-aggregate after the six commits (those trees were empty diffs vs `b1605c36` except new `*.test.ts`). Re-ran:

| Worker | At `b1605c36` | At `208df8ec` |
|--------|--------------:|--------------:|
| research-mass-eval | 76 / 8 files | **105** / 12 files |
| ingestion-premium | 67 / 16 files | **69** / 17 files |

New files: `persist_records.test.ts` (2), `metrics.test.ts` (9), `eval_orchestrate.test.ts` (5), `panels.test.ts` (5), `ai_gateway_client.test.ts` (6); `http.test.ts` 20→24 (grep 403 replaced by executed propose-thesis / mass-eval / daily-path capability HTTP).

Local PASS is still **not** merge-gate. Live `quant-platform-ci-aggregate` does not exist.
