# W93 / w0818c residual close

**Wave:** W93 / `w0818c` · 2026-08-18  
**Status:** **CLOSED** as residual TOP (research factory only)  
**Code tip:** `d48e70688f859a677b793e3c943e9ba34ff87d4a`  
**Primary proof:** [`w0818c_w93_opt225_basevol_atm_diff_20260818.md`](w0818c_w93_opt225_basevol_atm_diff_20260818.md)  
**Logs:** [`.glm-logs/w0818c_w93_opt225_diff/`](../../.glm-logs/w0818c_w93_opt225_diff/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## What landed

1. **Differential analysis (primary)** — BaseVol vs ATM IV vs spread dist/corr/CM-roll/quantiles · matching-transform delta table · noise-vs-structure note  
2. **Spread activation autopsy** — BaseVol≈ATM by J-Quants def; pre-fix nonzero residuals **100%** at DTE≤5; not a sign bug  
3. **Minimal ATM fix** — `min_dte_days=6` front-CM roll · series **v1.1** · corr **0.99994** · exact-zero spread **99.76%** · rebuild 2452 days  
4. **Multi-year windows** — w2017_2019 / w2020_2022 / w2023_2025 (honest shards) · local real + CF `r2_panels` · BaseVol≡ATM nets on matched transforms  
5. **CF thicken** — `cf-mass-eval-job/v4` · repo/margin/short/fins/calendar sidecars · job **`w93-opt225-20260818T120810Z`** · status **ok** · survivors **2**  
6. **Freezes held** — Mass NO-GO · READY 未宣言 · Phase7 OFF · ops GO 未宣言 · continuous paper UNARMED · 3 defaults not retuned · TOPIX proxy only  

---

## Explicit non-declarations (held)

- READY / Mass ON / Phase7 / operational GO / GO final declare — **not**  
- continuous paper arm — **UNARMED**  
- human main candidate selection — **not this wave**  
- factory survivors as production research_candidates — **not**  
- 3 defaults retune — **forbidden / not done**  
- synthetic-as-final success claim — **forbidden** (this wave used **r2_panels**)  
- TOPIX RV as primary Nikkei vol — **forbidden** (proxy only)  
- COMPLETE 23 invent · S1–S5 unreject · simple_daily_sign mass · live orders — **none**

---

## Residual TOP (W93)

1. **BaseVol ↔ ATM differential** — **landed** · twins post min_dte; keep both (no quiet drop)  
2. **Spread logics** — **diagnosed non-informative** at frozen thresholds; redesign deferred  
3. **Multi-year windows** — **executed** on available shards; contiguous 3y mirrors still absent  
4. **CF thicken sidecars** — **DONE** on panels; CF flow/fund TS consume = TODO  
5. **3 defaults frozen** — mom5 · mom3 · fund; **not retuned**  
6. **GO deferred** · Mass/READY/ops GO closed · continuous paper **UNARMED** · human main **NOT selected**  

---

## Underneath held

- W92 options_225 SoT + 8 opt225 logics · W91 real CF + nky vol proxy · W90 LLM+CF · W89 rate+multifactor · W88 logic diversity · W87 factory · W86 sign+repo+compare · 3 defaults  

---

## Health / inventory

- COMPLETE **22** held · DEFER **4** · no invent **23**  
- projection **FRESH**  
- factory templates include 8 opt225 · class-signals **v9** · factory **v2.4** · cf-mass-eval **v4**  
- options series **v1.1**

---

## Close checklist

| item | status |
|------|--------|
| differential BaseVol vs ATM (both kept) | **yes** |
| multi-year windows both families | **yes** |
| spread diagnosis + min_dte fix | **yes** |
| CF real job + thicken | **yes** · `w93-opt225-20260818T120810Z` |
| synthetic not claimed final | **yes** |
| TOPIX proxy label | **yes** |
| 3 defaults frozen | **yes** |
| projection FRESH | **yes** |
| proofs | this + primary |
| residual TOP=W93 | **yes** |
| pytest options_225 / factory | **green** |
| git push origin main | **yes** (feature + residual pin) |
