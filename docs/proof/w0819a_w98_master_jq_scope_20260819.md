# W98 / w0819a Track B — `equities_master` J-Quants scope (PRE_PLAN de-scope)

**Wave:** W98 / `w0819a` · Track B (equities_master J-Quants scope)  
**As of:** 2026-08-18T22:36:32Z  
**Prior:** W97 diagnosis [`w0818g_w97_master_partial_diagnosis_20260818.md`](w0818g_w97_master_partial_diagnosis_20260818.md) (PRE_PLAN 73 + MISDATE 21 + POST 220)  
**Evidence:** [`.glm-logs/w0819a_w98_otc_master_xs/master_jq_scope.md`](../../.glm-logs/w0819a_w98_otc_master_xs/master_jq_scope.md) · [`FINAL_metrics.json`](../../.glm-logs/w0819a_w98_otc_master_xs/FINAL_metrics.json)  
**Freezes:** **held** · empty-raw COMPLETE **FORBIDDEN** · floor→2008-05 invent **FORBIDDEN** · Mass/READY/Phase7 **OFF**

---

## User lock (this wave)

| lock | applied |
|------|---------|
| PRE_PLAN = **de-scope** (out of coverage; do not invent/fill) | **yes** — `history_target_start=2006-08-13` |
| Want correct COMPLETE for **2008→latest** | **yes** — island `2008-05…2026-08` **220/220**, holes **0** |
| MISDATE: re-fetch only if valid `Date`; else keep PARTIAL | **yes** — live `window_ok=0`, seal **0** |
| Never raise subscription/catalog floor to fake COMPLETE | **yes** — did **not** raise to `2008-05-01` |

---

## Verdict

**PRE_PLAN (73) is coverage OUT_OF_SCOPE, not “missing”.**  
**MISDATE (21) remains honest PARTIAL** under PD-D2-MASTER until vendor returns in-window `Date`.  
**POST island COMPLETE held at 220** with no post-2008-05 holes. Dataset stays **PARTIAL** (rule-legal).

---

## Before / after

| plane | BEFORE COMPLETE | BEFORE PARTIAL | AFTER COMPLETE | AFTER PARTIAL | Δ |
|-------|----------------:|---------------:|---------------:|--------------:|--:|
| local | 220 | 94 | 220 | **21** | PARTIAL **−73** |
| remote D1 | 220 | 94 | 220 | **21** | PARTIAL **−73** |

| band | span | before | after |
|------|------|-------:|------:|
| PRE_PLAN | `2000-07…2006-07` | 73 PARTIAL | **0** (OOS pruned) |
| MISDATE | `2006-08…2008-04` | 21 PARTIAL | 21 PARTIAL |
| POST_ISLAND | `2008-05…2026-08` | 220 COMPLETE | 220 COMPLETE |

- `history_target_start`: **2000-07-13 → 2006-08-13**  
- empty COMPLETE: **0 → 0**  
- Dataset COMPLETE invent: **none** (still PARTIAL)  
- COMPLETE 22 health: **pass** (PARTIAL set still includes master)  
- FRESH: `projgen-ace989071e524ed2a0382d83ef58bca8`

---

## What changed (policy / code)

| artifact | change |
|----------|--------|
| `collection_coverage.json` | master floor → **2006-08-13** |
| `canonical_datasets.json` | `historical_start` aligned |
| `cf_platform/.../coverage.py` `EXPECTED_START` | aligned |
| `range_batch_scheduler.py` Track A focus | aligned |
| `backfill_planner.py` `JQUANTS_SUBSCRIPTION_FLOOR` | live entitlement **2006-08-19** (HTTP 400 message; clamp only) |
| `permanent_defer.py` | `MASTER_JQ_SCOPE` — PRE_PLAN **OUT_OF_SCOPE** vs MISDATE **REQUIRED_PARTIAL** |
| tests | planner clamp + W98 scope guard |

---

## Continuity + MISDATE probe

1. **Continuity:** local/remote post-island PARTIAL holes = **0**; tip `2026-01…08` COMPLETE held.  
2. **Live MISDATE probe** (Premium `/v2/equities/master`): all 21 months return Date=`2008-05-07` only → `window_ok=0` → **no seal**.  
3. Subscription boundary: `date=2006-08-13/18` → HTTP 400 (`2006-08-19 ~`); planner floor updated to match live entitlement.

---

## Ops path executed

1. Contract + aligned copies  
2. Local inventory replan: delete `segment_id < 2006-08` (73 PARTIAL) + `sync_dataset_coverage_from_segments`  
3. `publish_ops_projection.py --apply-remote` fail-closed (COMPLETE local=remote)  
4. `ops_reeval_observed_window.py --dataset equities_master` (C8 pass)  
5. `ops_reeval_freshness.py` → FRESH  
6. `check_complete22_health.py` local+remote **pass**

---

## Explicit non-declarations

- Dataset COMPLETE for `equities_master` — **not** claimed  
- Floor raise to `2008-05-01` — **forbidden / not done**  
- MISDATE densify / misdated seal — **none**  
- Mass / READY / Phase7 / GO / live — **OFF / not declared**

---

## Unblock (later)

1. Vendor in-window `Date` for MISDATE → surgical seal only  
2. Until then: hold PD-D2-MASTER on MISDATE 21; tip-continuous POST island only
