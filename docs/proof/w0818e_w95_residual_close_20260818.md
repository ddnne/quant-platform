# W95 / w0818e residual close

**Wave:** W95 / `w0818e` · 2026-08-18  
**Status:** **CLOSED** as residual TOP (research factory only)  
**Code tip:** `99e05ad17e548e0b80cd83d234546b7459ee9c78`  
**Primary proof:** [`w0818e_w95_shape_factor_decomp_20260818.md`](w0818e_w95_shape_factor_decomp_20260818.md)  
**Logs:** [`.glm-logs/w0818e_w95_shape_factor_decomp/`](../../.glm-logs/w0818e_w95_shape_factor_decomp/)  
**Prior tip:** W94 `d855116`  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## What landed

1. **Shape deep-dive** — few-point threshold sensitivity + mom3 binds on skew / CM-term / ΔBaseVol; per-window sign/act/t; **2020–22 divergence vs level** confirmed; **weak → not promoted**
2. **Rate / flow / fund decomp** — change vs level sign-flips; soft≡off disclosed; classifications data_gap / weak_thesis / impl_bug
3. **fund 2017 giant-t** — reproduced t≈153 as n=2 low-variance artifact → **demoted**
4. **Worth-fixing** — low-variance / inflated-t gate in stats + factory screen + CF worker **v6**; live re-eval survivors **8→7**
5. **Promising-few re-eval** — shape (+ binds/anchors) on CF `r2_panels`; dead rate/flow/fund blast skipped; survivor count **not** forced to 2
6. **Freezes held** — Mass NO-GO · READY 未宣言 · Phase7 OFF · ops GO 未宣言 · continuous paper UNARMED · 3 defaults not retuned · BaseVol canonical · ATM compare-only · spread off-mainline · no smile≡level · no grid mass

---

## Explicit non-declarations (held)

- READY / Mass ON / Phase7 / operational GO / GO final declare — **not**  
- continuous paper arm — **UNARMED**  
- human main candidate selection — **not this wave**  
- factory survivors as production research_candidates — **not**  
- 3 defaults retune — **forbidden / not done**  
- smile / surface identical to BaseVol level — **forbidden / not claimed**  
- COMPLETE 23 invent · S1–S5 unreject · simple_daily_sign mass · live orders — **none**

---

## Residual TOP (W95)

1. **Canonical level** — **BaseVol** mainline; ATM compare-only; spread off-mainline non-informative  
2. **Skew / CM-term / ΔBaseVol** — deep-dived · research-only · **not** main candidates · failure modes ≠ level (esp. w2020_2022)  
3. **Thick factors** — rate/flow weak_thesis; fund_slow demoted (inflated_t gate); soft≡off disclosed  
4. **Low-variance t-gate** — live on Python + CF worker v6  
5. **3 defaults frozen** — mom5 · mom3 · fund; **not retuned**  
6. **GO deferred** · Mass/READY/ops GO closed · continuous paper **UNARMED** · human main **NOT selected**

---

## Key jobs

| job | role |
|-----|------|
| `w95-shape-20260818T133241Z` | shape promising CF `r2_panels` |
| `w95-decomp-20260818T133302Z` | thick factor re-eval worker v6 (fund demotion) |
| W94 `w94-thick-20260818T125009Z` | source period_rows for decomp |

---

## Close checklist

| item | status |
|------|--------|
| Shape sens + binds + 2020–22 note | **yes** |
| Shape not promoted as main | **yes** |
| Rate/flow/fund decomp + taxonomy | **yes** |
| fund2017 artifact demoted | **yes** |
| low-variance gate + CF v6 re-eval | **yes** |
| Promising-few re-eval (no dead blast) | **yes** |
| 3 defaults frozen | **yes** |
| Mass/READY/GO/live closed | **yes** |
| proofs | this + primary |
| residual TOP=W95 | **yes** |
| pytest options/factory/class_signals/stats | **green** |
| git push origin main | **yes** (this close) |
| GLM5.3 only. Grok did not implement. | **yes** |
