# Phase 6.2 / 6.3 residual status

**Live verified:** 2026-08-12 (wrangler remote D1 after COMPLETE +1 publish)  
**Proof:** `docs/proof/complete_plus1_20260812.md`

## Live snapshot

| Item | Value |
|------|--------|
| Dataset COMPLETE | **2** — `markets_calendar` (224/224 segs), `jsda_tokyo_repo_rates` (1/1) |
| Segment COMPLETE total | **401** (+1 vs prior 400) |
| calendar segments | **224 COMPLETE / 0 PARTIAL** |
| JSDA OTC COMPLETE segs | **2** — `2026-08-10`, `2026-08-12` (dataset still PARTIAL: 2/8777) |
| JSDA corporate COMPLETE segs | **1** — year `2026` (dataset still PARTIAL: 1/12) |
| master | `scd2_event_sourcing` / D1 hot |
| projection | FRESH (full publish after +1) |
| sticky COMPLETE | **fixed inventory status load** + demotion guard in `storage/coverage_ledger.py` |
| Full publish guard | `scripts/publish_ops_projection.py` fail-closed |
| Targeted freshness | `scripts/ops_reeval_freshness.py` (no segment rewrite) |
| Mass / READY / B0 | **NO-GO** |
| Phase 7 | **OFF / foundation only** |

## DONE vs DEFER

| Area | Status |
|------|--------|
| Sticky COMPLETE + inventory status fix | **DONE** |
| Publish fail-closed guard | **DONE** |
| Honest segment COMPLETE +1 (OTC 2026-08-10) | **DONE** (raw R2 + 12401 structured + signed SUCCESS) |
| JSDA min COMPLETE (otc/corp/tokyo) | **DONE** (otc now 2 segs; corp/tokyo 1 each) |
| Extra COMPLETE without raw | **DEFER** |
| Mass / READY / Phase7 switch ON | **NO-GO** |
| applied_cursor materialization | **DEFER** |
| OTC full archive COMPLETE | **DEFER** (thousands of trading days remain) |

## Note on COMPLETE counts
- **Dataset-level COMPLETE = 2** means only two datasets have *all* required segments COMPLETE.
- **Segment COMPLETE = 401** counts every COMPLETE segment across datasets (calendar 224, master, JSDA progress, etc.).
- Next honest +1 requires additional **real raw** (R2 or official fetch); do not invent.
