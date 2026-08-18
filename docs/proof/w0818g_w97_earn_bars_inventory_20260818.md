# W97 / w0818g — Track E earn_cal / bars_am inventory

**Wave:** W97 / `w0818g` · Track E (lower priority)  
**Evidence:** [`.glm-logs/w0818g_w97_otc_master_hyps/earn_cal_bars_am_inventory.json`](../../.glm-logs/w0818g_w97_otc_master_hyps/earn_cal_bars_am_inventory.json)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## equities_earnings_calendar

| field | value |
|-------|-------|
| status | **PARTIAL** |
| COMPLETE / PARTIAL segs | **1 / 199** |
| tip COMPLETE | `2026-08` through **2026-08-14** |
| policy | vendor tip-only / event_reconciled; history DEFER |
| action this wave | **tip-wait** · no history invent |

## equities_bars_daily_am

| field | value |
|-------|-------|
| status | **PARTIAL** |
| COMPLETE / PARTIAL segs | **1 / 31** |
| observed | **2026-08-01 → 2026-08-11** |
| tip COMPLETE | `2026-08` |
| policy | tip_continuous; **history_reprobe FORBIDDEN** (PD-D4-BARS-AM) |
| action this wave | **tip-wait** premium cron nz raw · no densify |

No safe tip progress beyond current COMPLETE tip months this wave.
