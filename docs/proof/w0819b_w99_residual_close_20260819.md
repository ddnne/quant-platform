# W99 / w0819b residual close

**Wave:** W99 / `w0819b` · 2026-08-19  
**Status:** **CLOSED** as residual TOP (OTC Batch3 + sticky true daily DD + constrained hyps + MISDATE re-probe)  
**Code tip:**   
**Prior tip:** W98 `00cf879` · OTC COMPLETE **4651** / PARTIAL **4132**  
**Primary proofs:**  
- [`w0819b_w99_otc_backfill_batch3_20260819.md`](w0819b_w99_otc_backfill_batch3_20260819.md)  
- [`w0819b_w99_sticky_daily_dd_20260819.md`](w0819b_w99_sticky_daily_dd_20260819.md)  
- [`w0819b_w99_hyps_continue_20260819.md`](w0819b_w99_hyps_continue_20260819.md)  
- [`w0819b_w99_master_misdate_20260819.md`](w0819b_w99_master_misdate_20260819.md)  
**Logs:** [`.glm-logs/w0819b_w99_otc_sticky_dd/`](../../.glm-logs/w0819b_w99_otc_sticky_dd/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## What landed

1. **OTC Batch3** — pre-2008 archive newer-first before `2007-08-13` via CF W80 `/fetch` → SUCCESS receipts → COMPLETE **4651→4751 (+100)** · PARTIAL **4132→4032** · span **2007-03-19…2026-08-19** · dataset **PARTIAL** held · tip `S260820+` **404** tip-wait · empty COMPLETE **0** · no invent  
2. **xs_rank_ls_sticky TRUE daily DD** — period-net DD=0 called out as aggregation artifact · daily equity-curve max DD **−14.4% / −3.8% / −10.8%** across windows · DD duration + recovery + after-cost returns tabled · **promote/GO=False** · no hold/mom grid · pins untouched · large daily DD **not hidden**  
3. **Failure-constrained hyps** — xAI grok-4.6 · **6 proposed / 5 accepted / 2 survivors** · `reduce_weak_template_mapping=True` · demoted/weak not main  
4. **master MISDATE optional re-probe** — no in-window Date → KEEP PARTIAL · sealed **0** · COMPLETE **220** / PARTIAL **21** held · no floor raise  
5. **Freezes held** — 3-default pins unchanged · Mass NO-GO · READY 未宣言 · Phase7 OFF · ops GO 未宣言 · continuous paper UNARMED · projection FRESH · no GO/live

---

## Explicit non-declarations (held)

- READY / Mass ON / Phase7 / operational GO / GO final declare — **not**  
- continuous paper arm — **UNARMED**  
- human main candidate selection — **not this wave**  
- sticky / hyp survivors as production research_candidates — **not**  
- 3 defaults retune — **forbidden / not done**  
- OTC dataset COMPLETE / COMPLETE 23 invent / fake densify — **none**  
- master floor raise to 2008-05 invent COMPLETE — **forbidden / not done**  
- Interpreting period-net DD=0 as “no risk” — **FORBIDDEN**  
- S1–S5 unreject · simple_daily_sign mass · live orders — **none**

---

## Residual TOP (W99)

1. **COMPLETE 22 held** · DEFER/PARTIAL **4** (bars_am · earn_cal · master · OTC) · OTC planned official archive batches continue · tip-wait `S260820+`  
2. **equities_master** — PRE_PLAN **de-scoped** · MISDATE **21** PARTIAL until vendor Date in-window · tip continuous 2008-05→latest  
3. **xs_rank_ls_sticky** — STABLE_RESEARCH_ONLY · true daily DD **material** (period-net DD=0 is artifact) · **not** main · **not** GO  
4. **New hyps** — failure-constrained xAI pack (**6/5/2**) · research-only · weak-template mapping reduced  
5. **3 defaults frozen** — mom5 KEEP · mom3 PROMOTE · fund KEEP · **not retuned** · pins_untouched **True**  
6. **GO deferred** · Mass/READY/ops GO closed · continuous paper **UNARMED** · human main **NOT selected**

---

## Key metrics

| metric | BEFORE (W98) | AFTER (W99) |
|--------|-------------:|------------:|
| OTC COMPLETE | 4651 | **4751** |
| OTC PARTIAL | 4132 | **4032** |
| OTC span start | 2007-08-13 | **2007-03-19** |
| master COMPLETE/PARTIAL | 220/21 | **220/21** |
| sticky period-net DD (artifact) | 0.0 | 0.0 (called out) |
| sticky daily max DD (worst window) | *(not measured)* | **−0.1437** (w2017_2019) |
| Dataset COMPLETE | 22 | **22** |
| empty COMPLETE | 0 | **0** |
| platform COMPLETE segs | 8040 | **8140** |
| hyps proposed/accepted/survivors | 6/4/2 | **6/5/2** |
| Mass | NO-GO | NO-GO |

---

## Close checklist

| item | status |
|------|--------|
| OTC Batch3 COMPLETE/PARTIAL progress | **yes** (PARTIAL held) |
| No invent / no empty COMPLETE / PARTIAL held | **yes** |
| sticky true daily DD table + period-net contrast | **yes** |
| period-net DD=0 NOT treated as no-risk | **yes** |
| master MISDATE optional re-probe | **yes** (Δ COMPLETE 0) |
| New hyp gen failure-constrained | **yes** (**6/5/2**) |
| Demoted/weak not resurrected as main | **yes** |
| 3-default pins unchanged | **yes** |
| projection FRESH · health local+remote pass | **yes** |
| residual TOP=W99 | **yes** |
| must push | **yes** |
| GLM5.3 only. Grok did not implement. | **yes** |
