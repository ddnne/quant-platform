# W98 / w0819a Track B — `equities_master` PRE_PLAN de-scope + MISDATE re-probe

**Wave:** W98 / `w0819a` · Track B  
**Dataset:** `equities_master` (PD-D2-MASTER)  
**As of:** 2026-08-19  
**Artifacts:** [`.glm-logs/w0819a_w98_otc_master_xs/`](../../.glm-logs/w0819a_w98_otc_master_xs/)  
**Policy module:** `packages/data_plane/data_contracts/permanent_defer.py` → `MASTER_JQ_SCOPE`  
**Canonical proof:** [`w0819a_w98_master_jq_scope_20260819.md`](w0819a_w98_master_jq_scope_20260819.md)
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| Check | Result |
|-------|--------|
| PRE_PLAN (`2000-07…2006-07`) | **coverage out-of-scope (de-scope)** — not “missing to invent” |
| Catalog `history_target_start` | `2000-07-13` → **`2006-08-13`** (subscription boundary) |
| Floor raise to `2008-05` to fake COMPLETE | **FORBIDDEN / not done** |
| MISDATE (`2006-08…2008-04`) live re-probe | **window_ok=0** (Date=`2008-05-07` only) → keep PARTIAL |
| POST_ISLAND (`2008-05→latest`) | **COMPLETE** continuous · holes **0** |
| COMPLETE / PARTIAL | **220 / 21** (was 220 / 94; PRE_PLAN −73 from inventory) |
| Dataset status | **PARTIAL** held (honest; MISDATE residual) |
| Sealed this wave | **0** |

---

## Before / after

| plane | BEFORE COMPLETE | BEFORE PARTIAL | AFTER COMPLETE | AFTER PARTIAL | Δ COMPLETE | Δ PARTIAL |
|-------|----------------:|---------------:|---------------:|--------------:|-----------:|----------:|
| local | 220 | 94 | **220** | **21** | 0 | **−73** |
| remote D1 | 220 | 94 | **220** | **21** | 0 | **−73** |

### Band taxonomy AFTER

| band | span | n | sealable? |
|------|------|--:|-----------|
| PRE_PLAN | `2000-07…2006-07` | **0** in inventory | **de-scoped OUT_OF_SCOPE** |
| MISDATE | `2006-08…2008-04` | **21** | **no** — Date misaligned |
| POST_ISLAND | `2008-05…2026-08` | **220** | already COMPLETE |

---

## PRE_PLAN de-scope (product)

PRE_PLAN months sit below Premium entitlement. Catalog previously required them from `2000-07-13`, creating 73 structural PARTIALs that could never honest-seal.

**W98 action:** raise `history_target_start` to **`2006-08-13`** (subscription floor boundary) and drop PRE_PLAN from required inventory.

This is **coverage out-of-scope**, not densify and not invent. Explicitly **not** raising to `2008-05-01` (that would fake Dataset COMPLETE while MISDATE remains).

Machine policy: `MASTER_JQ_SCOPE` / `MASTER_COVERAGE_POLICY` in `permanent_defer.py`.

Live entitlement note: J-Quants `/v2/equities/master?date=2006-08-15` returns HTTP 400 covering **`2006-08-19 ~`**. Planner clamp updated to `JQUANTS_SUBSCRIPTION_FLOOR=2006-08-19` (entitlement only — not a COMPLETE invent floor).

---

## MISDATE re-probe (live)

Sample days across `2006-08…2008-04` via `make_jquants_http` + `JQuantsClient.listed_info(date=…)`:

| day | n_rows | window_ok | top Date |
|-----|-------:|----------:|----------|
| 2006-08-15 | — | — | HTTP 400 (before live floor 2006-08-19) |
| 2006-12-15 … 2008-04-15 | 2494 | **0** | **2008-05-07** only |

**Verdict:** `NO_IN_WINDOW_DATE — keep MISDATE PARTIAL`. Sealed **0**.

Evidence: `equities_master_live_misdate_probe.json` · `equities_master_w98_probe.json` · `equities_master_progress.json`

---

## 2008-05→latest coverage

Post-island COMPLETE span **`2008-05…2026-08`** (n=220). Island PARTIAL holes: **0**. Tip continuous only; no gap invent.

---

## Non-actions (held)

- densify MISDATE / PRE_PLAN  
- seal MISDATE on misdated raw  
- raise floor to `2008-05` to invent Dataset COMPLETE  
- Mass / READY / Phase7

## Unblock (product later)

1. Vendor in-window `Date` for MISDATE → surgical seal only  
2. Dataset COMPLETE only when MISDATE honestly clears (or explicit further product gate)
