# W94 / w0818d residual close

**Wave:** W94 / `w0818d` · 2026-08-18  
**Status:** **CLOSED** as residual TOP (research factory only)  
**Code tip:** `9b93f937232de572f72f7f880560975ff20efcb2`  
**Primary proof:** [`w0818d_w94_opt_skew_thick_20260818.md`](w0818d_w94_opt_skew_thick_20260818.md)  
**Logs:** [`.glm-logs/w0818d_w94_opt_skew_thick/`](../../.glm-logs/w0818d_w94_opt_skew_thick/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## What landed

1. **Canonical level** — BaseVol = canonical Nikkei vol SoT level; ATM = **compare-only** alias; spread = **non-informative** (off-mainline dual-eval)  
2. **Skew / CM-term / ΔBaseVol features** — series **v1.2** · factory **v2.5** · class-signals **v10** · logics `opt225_skew_abs_level` · `opt225_cm_term_abs_level` · `opt225_basevol_delta_abs` · fullspan **2452 / 2452 / 2451** days  
3. **Multi-year windows** — w2017_2019 / w2020_2022 / w2023_2025 (honest shards) · local real + CF `r2_panels` · job **`w94-skew-20260818T130829Z`** · status **ok** · aggregate survivors **3**  
4. **Failure-mode vs level** — shape/change logics survive where BaseVol abs level dies (esp. **w2020_2022**); signs diverge on **w2017_2019** → **not** smile≡level  
5. **Thick rate/flow/fund/mf** — worker **v5** · job **`w94-thick-20260818T125009Z`** · **mdh_fb=0** · wiring 8 CF / 3 local / 11 not_yet  
6. **Freezes held** — Mass NO-GO · READY 未宣言 · Phase7 OFF · ops GO 未宣言 · continuous paper UNARMED · 3 defaults not retuned · TOPIX proxy only · no grid mass  

---

## Explicit non-declarations (held)

- READY / Mass ON / Phase7 / operational GO / GO final declare — **not**  
- continuous paper arm — **UNARMED**  
- human main candidate selection — **not this wave**  
- factory survivors as production research_candidates — **not**  
- 3 defaults retune — **forbidden / not done**  
- synthetic-as-final success claim — **forbidden** (this wave used **r2_panels**)  
- TOPIX RV as primary Nikkei vol — **forbidden** (proxy only)  
- smile / surface identical to BaseVol level — **forbidden / not claimed**  
- COMPLETE 23 invent · S1–S5 unreject · simple_daily_sign mass · live orders — **none**

---

## Residual TOP (W94)

1. **Canonical level** — **BaseVol** mainline; ATM compare-only; spread off-mainline non-informative  
2. **Skew / CM-term / ΔBaseVol** — **landed** · multi-year windows executed (local+CF); failure modes ≠ level regime  
3. **Thick factor consume** — rate/flow/fund/mf on CF pure-TS with sidecars · **mdh_fb=0** · window nets thin (no lite survivors)  
4. **ATM dual-eval** — **off-mainline** (alias only; keep catalog, no quiet drop)  
5. **3 defaults frozen** — mom5 · mom3 · fund; **not retuned**  
6. **GO deferred** · Mass/READY/ops GO closed · continuous paper **UNARMED** · human main **NOT selected**  

---

## Skew / term / Δ window headlines

| window | skew surv (L/CF) | cm_term surv | ΔBaseVol surv | BaseVol level surv | note |
|--------|:----------------:|:------------:|:-------------:|:------------------:|------|
| w2017_2019 | T/T | T/T | T/T | T / F(low_act) | skew/Δ sign ≠ level |
| w2020_2022 | T/T | T/T | T/T | **F/F** | level dead; shape alive |
| w2023_2025 | T/T | T/T | T/T | T/T | signs align (−1) this shard |

---

## Rate / flow / fund / mf tables (summary)

| bucket | CF headline | mdh_fb |
|--------|-------------|------:|
| rate | act≈0.07–0.08 · sign flips 2017→2020→2023 · no lite survivors | 0 |
| flow | act≈0.01–0.10 · 2023 sign flip · no lite survivors | 0 |
| fund | slow-agree 2017 t artifact · 2023 sign flip · no lite survivors | 0 |
| mf | flow_price 2020 spike / low act · no lite survivors | 0 |

Primary thick job: **`w94-thick-20260818T125009Z`** (stale-isolate `w94-thick-20260818T124759Z` discarded).

---

## Wiring / freezes

- COMPLETE **22** held · DEFER **4** · no invent **23**  
- projection **FRESH**  
- factory **v2.5** · class-signals **v10** · cf-mass-eval **v5** · options series **v1.2**  
- CF wiring: **8** wired · **3** local_only · **11** not_yet  
- Mass **NO-GO** · READY **未宣言** · Phase7 **OFF** · continuous paper **UNARMED** · 3 defaults **frozen**

---

## Underneath held

- W93 BaseVol↔ATM differential + min_dte + thicken · W92 options_225 SoT · W91 real CF + nky proxy · W90 LLM+CF · W89 rate+multifactor · W88 logic diversity · W87 factory · W86 sign+repo+compare · 3 defaults  

---

## Close checklist

| item | status |
|------|--------|
| BaseVol canonical / ATM compare-only / spread off-mainline | **yes** |
| skew / CM-term / Δ features + logics | **yes** |
| multi-year windows local + CF | **yes** · `w94-skew-20260818T130829Z` |
| failure-mode ≠ level (no smile≡level claim) | **yes** |
| thick rate/flow/fund/mf mdh_fb=0 | **yes** · `w94-thick-20260818T125009Z` |
| 3 defaults frozen | **yes** |
| Mass/READY/GO/live closed | **yes** |
| proofs | this + primary |
| residual TOP=W94 | **yes** |
| pytest options_225 / factory / class_signals | **green** |
| git push origin main | **yes** (feature + residual pin) |
