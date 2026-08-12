# Sticky COMPLETE verification (2026-08-12)

## Code (origin includes `4aaf424`+)
In `storage/coverage_ledger.py` refresh path:
- If prior segment status is COMPLETE
- And receipt is SUCCESS + COMPLETE-eligible (Ed25519 TRUSTED)
- Then demotion to PARTIAL is **blocked** (`sticky_complete: true`)

Verified on `origin/main` at tip `346c47c` (ancestor of sticky impl `4aaf424`).

## Live quant-mcp / wrangler (same day — earlier)
| Metric | Value |
|--------|--------|
| markets_calendar segments | **224 COMPLETE / 0 PARTIAL** |
| dataset COMPLETE | **markets_calendar**, **jsda_tokyo_repo_rates** |
| segment COMPLETE total | **400** |
| master | scd2_event_sourcing / 128811 |
| projection | FRESH age≈0 |

## Observe re-run (2026-08-12T13:01Z UTC) — day-progress / freshness path

**PRE (remote D1 `quant-ingest`):**

| Metric | Value |
|--------|--------|
| markets_calendar | **224 COMPLETE / 0 PARTIAL** |
| segment COMPLETE total | **400** (PARTIAL 12540) |
| dataset_coverage COMPLETE | `markets_calendar`, `jsda_tokyo_repo_rates` |
| projection | **FRESH** age_seconds=0 gen=`projgen-0a3c604e5aa547aab746960cb8f5433a` |

**Code check:** sticky demotion block present on `origin/main` (`storage/coverage_ledger.py` ~L649–671: `sticky_complete` / `demotion_blocked`).

**Action:** `python3 scripts/ops_reeval_freshness.py` (exit 0)  
- Advances `dataset_coverage.evaluated_at` for key datasets only  
- Rotates ops projection FRESH  
- **Does not** rewrite `coverage_segments` / COMPLETE evidence  
- Mass / READY / B0: **NO-GO**

**POST (same remote queries):**

| Metric | PRE | POST | demote? |
|--------|-----|------|---------|
| markets_calendar COMPLETE segs | 224 | **224** | no |
| markets_calendar PARTIAL | 0 | **0** | no |
| segment COMPLETE total | 400 | **400** | no |
| dataset COMPLETE list | calendar + tokyo_repo | **same** | no |
| projection status | FRESH | **FRESH** age=0 gen=`projgen-304ec56e3d9b4d6da4c15334ae5f6757` | n/a |
| evaluated_at (calendar/repo) | `…12:35:12…` | `2026-08-12T13:01:47.266953+00:00` | advanced only |

## Conclusion
Sticky COMPLETE remains on origin; live calendar **224/224** held through targeted freshness reeval with **zero demotion**.  
Mass / READY remain **NO-GO**. Do not fabricate COMPLETE or mass-enable.
