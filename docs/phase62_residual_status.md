# Phase 6.2 / 6.3 residual status

**Live verified:** 2026-08-12T13:01Z (wrangler remote D1)  
**origin/main tip (pre-docs):** `346c47c` · sticky COMPLETE impl: `4aaf424`

## Live snapshot

| Item | Value |
|------|--------|
| Dataset COMPLETE | **2** — `markets_calendar` (224/224 segs), `jsda_tokyo_repo_rates` (1/1) |
| Segment COMPLETE total | **400** |
| calendar segments | **224 COMPLETE / 0 PARTIAL** |
| master | `scd2_event_sourcing` / **128811** (D1 hot) |
| projection | **FRESH** (gen `projgen-304ec56e3d9b4d6da4c15334ae5f6757` after ops_reeval) |
| sticky COMPLETE | **in code** (`storage/coverage_ledger.py`: demotion blocked while SUCCESS receipt eligible) |
| Full publish guard | `scripts/publish_ops_projection.py` fail-closed |
| Targeted freshness | `scripts/ops_reeval_freshness.py` (no segment rewrite) |
| Mass / READY / B0 | **NO-GO** |

## Sticky observe note (2026-08-12 re-run)

- PRE→POST via `ops_reeval_freshness.py` only (no segment rewrite).
- **markets_calendar 224/224 held**; segment COMPLETE **400** unchanged; no demotion.
- Proof: `docs/proof/sticky_complete_verify_20260812.md`.
- Continue observing on day-roll; do not treat as READY.

## DONE vs DEFER

| Area | Status |
|------|--------|
| Sticky COMPLETE + aggregate resync | **DONE** (`4aaf424`) |
| Publish fail-closed guard | **DONE** (`fe6aafc`) |
| Local COMPLETE heal 400=remote | **DONE** |
| D1 cold prune | **DONE** (cold=0) |
| JSDA min COMPLETE (otc/corp/tokyo) | **DONE** (1 each) |
| Sticky day-progress observe (reeval path) | **OBSERVED** (2026-08-12T13:01Z; no demote) |
| Extra COMPLETE without raw | **DEFER** |
| Mass / READY / Phase7 switch ON | **NO-GO** |
| applied_cursor materialization | **DEFER** |

## Note on COMPLETE counts
- **Dataset-level COMPLETE = 2** means only two datasets have *all* required segments COMPLETE.
- **Segment COMPLETE = 400** counts every COMPLETE segment across datasets (includes master 94 segs, partial progress on others).
