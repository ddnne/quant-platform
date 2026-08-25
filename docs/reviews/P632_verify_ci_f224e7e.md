# P632 `scripts/verify_ci.sh` — code-lane PASS (not merge-gate)

**Lane:** code / `scripts/verify_ci.sh`  
**Requested base:** `f224e7e922d93dfdcc14ae86578883cad337ebca` (`origin/grok/phase63-ci-source-closure`)  
**Isolation worktree:** `/private/tmp/qp-p632-verify-ci-f224e7e` on `grok/p632-verify-ci-f224e7e` (do not push `main`)  
**PASS SHA:** `f113cc0570cc0aaabe025dabee34b7f55a5d5100`  
**Fetched:** 2026-08-23T15:02:05Z  
**GitHub check-runs / required context `ci-aggregate`:** **not measured, not claimed**  
**Merge gate:** **not green**. This file is a local `verify_ci.sh` exit-0, not a GitHub status.

Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, or Phase 7 GO.

---

## Verdict

| Gate | Status |
|------|--------|
| `scripts/verify_ci.sh` at `f224e7e` as-is | **FAIL** |
| `scripts/verify_ci.sh` at `f113cc05` (after three local commits) | **PASS** (code lane) |
| GitHub required context `ci-aggregate` posted | **not this lane** |
| Merge-gate green | **NO** |

`verify_ci: ok` is not a live coverage remeasure and is not merge-gate authority.

---

## What ran (PASS SHA)

Isolation `.venv` Python 3.11.15. No `npm ci --legacy-peer-deps`. No live `wrangler deploy`.

| Step | Result |
|------|--------|
| secret/path scan | pass (no tracked `.env` / `*.pem`) |
| `pip install -e ".[dev]"` | pass |
| `pytest tests/` | **1412 passed, 4 skipped** in 76.91s |
| catalog compile + `catalog_ids` freeze | pass |
| Evaluation IR `schema.json` + golden codec | pass |
| 7 workers `npm ci` / `npm test` / `typecheck` / `wrangler deploy --dry-run` / `npm run types -- --check` | pass (types up to date, `--include-runtime false`) |
| working tree clean after generated types | pass |

Workers: `ingestion-jsda`, `ingestion-premium`, `ingestion-secrets`, `quant-ops-mcp`, `research-ai-gateway`, `research-mass-eval`, `ci-aggregate`.

---

## Base `f224e7e` failures (not ignored)

1. **pytest** `tests/test_phase6_snapshot_publication.py::test_ready_publication_is_atomic_content_addressed_and_read_only`  
   `SnapshotRejected: coverage not COMPLETE=[('equities_earnings_calendar', 'PARTIAL')]`.  
   Tip-snapshot `evaluate_segment` keeps empty receipts PARTIAL. The READY fixture still planted event-zero receipts as if this were a fins window. **Not** a product COMPLETE invention.

2. **`wrangler types --check` (ingestion-jsda)**  
   `npx wrangler types --check` ignored `scripts.types` `--include-runtime false` and demanded workerd runtime types. Committed JSDA `worker-configuration.d.ts` was also missing `ProductionEnv` vs wrangler 4.125.0.

---

## Local commits (this worktree)

| SHA | Concern |
|-----|---------|
| `60804102` | test: READY fixture collects tip-snapshot receipts, not empty COMPLETE |
| `7d7d798a` | workers: regenerate ingestion-jsda wrangler types (`--include-runtime false`) |
| `f113cc05` | scripts: `verify_ci` types `--check` honors `scripts.types` (`npm run types -- --check`) |

Invariants not weakened: empty tip-snapshot receipts stay PARTIAL; no `--legacy-peer-deps`; no GitHub Actions added.

Log tail: `verify_ci: ok`
