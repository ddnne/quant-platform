# W97 / w0818g Track B — `equities_master` PARTIAL diagnosis

**Wave:** W97 / `w0818g` · Track B (raised priority)  
**Dataset:** `equities_master` (PD-D2-MASTER)  
**As of:** 2026-08-18T14:35:29Z  
**Full evidence:** [`.glm-logs/w0818g_w97_otc_master_hyps/master_partial_diagnosis.md`](../../.glm-logs/w0818g_w97_otc_master_hyps/master_partial_diagnosis.md) · [`FINAL_metrics.json`](../../.glm-logs/w0818g_w97_otc_master_hyps/FINAL_metrics.json)  
**Freezes:** **held** · empty-raw COMPLETE **FORBIDDEN** · floor-raise invent **FORBIDDEN** · Mass/READY/Phase7 **OFF**

---

## Verdict

| Check | Result |
|-------|--------|
| Cause | **PD-D2-MASTER** structural: PRE_PLAN **73** + MISDATE **21** |
| SCD2 / eval bug | **no** |
| Post-island holes (`2008-05…2026-08`) | **0** |
| Surgical seal candidates | **0** |
| Fetch / seal this wave | **0 / 0** |
| Code fix | **none** |
| COMPLETE / PARTIAL (local = D1) | **220 / 94** (unchanged) |
| `dataset_coverage.status` | **PARTIAL** (honest) |

**PARTIAL is not a missing tip-month or SCD2 CURRENT hole.** Catalog requires months from `2000-07-13`; honest receipt island starts `2008-05`. Raising the floor to force Dataset COMPLETE would invent coverage — banned under freeze.

---

## Before / after

| plane | BEFORE COMPLETE | BEFORE PARTIAL | AFTER COMPLETE | AFTER PARTIAL | Δ |
|-------|----------------:|---------------:|---------------:|--------------:|--:|
| local | 220 | 94 | 220 | 94 | 0 |
| remote D1 | 220 | 94 | 220 | 94 | 0 |

### Band taxonomy (remote D1)

| band | span | n | sealable? |
|------|------|--:|-----------|
| PRE_PLAN | `2000-07…2006-07` | 73 | **no** — below `JQUANTS_SUBSCRIPTION_FLOOR=2006-08-13` |
| MISDATE | `2006-08…2008-04` | 21 | **no** — body `Date=2008-05-07` only (`window_ok=0`) |
| POST_ISLAND | `2008-05…2026-08` | 220 | already COMPLETE |

MISDATE Date proof reused from `.glm-logs/w0815b_g10_master/pages` (reconfirmed 2494/2494 rows `2008-05-07`).

---

## Policy / COMPLETE criteria (pointer)

- Contract: `packages/data_plane/data_contracts/collection_coverage.json` → `equities_master`  
  - `history_target_start=2000-07-13` · `coverage_mode=scd2_event_sourcing` · granularity `calendar_month`  
- COMPLETE chain: `docs/complete_segment_checklist.md` + `coverage_ledger.evaluate_segment` (signed SUCCESS receipt + raw + reconcile)  
- Dataset COMPLETE only if **all** required segs COMPLETE  
- Permanent DEFER: `packages/data_plane/data_contracts/permanent_defer.py` **PD-D2-MASTER**

`scd2_event_sourcing` is the write-path mode; monthly receipt ownership still governs COMPLETE. Not an eval bug.

---

## Track E light — earn_cal / bars_am

| dataset | COMPLETE | PARTIAL | tip | PD |
|---------|--------:|--------:|-----|----|
| `equities_earnings_calendar` | 1 | 199 | `2026-08` COMPLETE; history tip-dated | PD-D4-EARN-CAL |
| `equities_bars_daily_am` | 1 | 31 | `2026-08` COMPLETE; history LIVE_API_EMPTY (W71) | PD-D4-BARS-AM tip_continuous |

History densify **FORBIDDEN**; tip continuous only.

---

## Non-actions (held)

- densify 94 master PARTIAL  
- seal MISDATE on misdated raw  
- raise `history_target_start` to invent Dataset COMPLETE  
- Mass / READY / Phase7

## Unblock (product later)

1. Vendor in-window `Date` for MISDATE → surgical seal only  
2. Subscription before 2006-08-13 **or** explicit catalog de-scope under product gate
