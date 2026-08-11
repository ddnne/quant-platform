# Phase 6.2 residual status (honest)

**HEAD**: `git log -1` (expect `5fd76a2` or later)  
**Date**: 2026-08-11  
**Track**: GLM parallel + orchestrated land (`glm-5.2`)

> **Phase 6.2 is code-complete but live NO-GO.** Do **not** assert
> `PHASE62_FULL_DONE`, live `COMPLETE`, or production `READY` without evidence.
> Phase 7 mass research is **NO-GO** until production READY ≥1 **and** real
> Coverage V2 COMPLETE evidence exist.

## Code-complete ✅

| Item | Evidence |
|------|----------|
| 31-endpoint inventory | `data_contracts/canonical_datasets.json` |
| Ops projection publisher + D1 apply | `scripts/publish_ops_projection.py` |
| Host cron projection path | `scripts/cron_publish_ops.sh` (+ runbook) |
| Coverage V2 granularities | `storage/coverage_ledger.py` |
| JQ collection receipt emit path | `ingestion/jquants/receipts.py` wired in `ingestion/pipeline.py` |
| Operational receipt CLI | `scripts/write_collection_receipts.py` |
| Historical backfill driver | `scripts/run_historical_backfill.py` |
| READY coherence integrated into publish | `paper_runtime/snapshot.py` + schema-aligned `coherence.py` |
| Remote Ops MCP tools | 16 tools / migration 0003 |
| Phase 7 stubs | `knowledge/`, `selection/`, `gateway/` |
| Offline pytest | green on land |

## Live operational — still OPEN 🚫

| Item | Status |
|------|--------|
| Coverage COMPLETE (receipts + full history) | **Open** — ledger honest PARTIAL; calendar history expanded; JQ receipts emit on **new** ingest |
| Production READY ≥1 | **Open** — gates correctly block |
| Full multi-year JQ/JSDA backfill finished | **Open** — long live runs partial (proxy fixed to secrets worker) |
| CF Worker cron auto-projection (edge) | **Partial** — host cron path complete; edge not claimed |

## Human-only / external gates

- JSDA HTML archive timeouts / site availability
- Full multi-year premium history wall-clock
- CF `INGESTION_RUN_TOKEN` for Worker `/v1/run` (local path uses secrets proxy)
- Live capital / broker (out of scope)

## Phase 7 mass research

**NO-GO** until READY + real COMPLETE evidence.

## Recent live notes

- `ingestion_proxy_url` must point at **ingestion-secrets** (`/v1/proxy/jquants`), not premium.
- `markets_calendar` backfill 2017→2026 succeeded (~3510 rows).
- New catalog ingests write `collection_receipts`; historical rows need re-fetch or raw-file receipt rebuild.
