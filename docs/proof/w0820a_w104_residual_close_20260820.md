# W104 / w0820a residual close (Tracks A+B+C+D+E)

**Wave:** W104 / `w0820a` · 2026-08-20  
**Status:** **CLOSED** as residual TOP for **all tracks** (OTC Batch8 + NEW unique_logic hyps + gate/sticky confirm **without extra grid** + repo-short confirm + MISDATE wait + pins frozen).  
**Code tip:** `7bda5f7233463f747170bf9c246c42831a073b0d`  
**Prior tip:** W103 `0160e70` · Track B hyps `f94f290` · Track A Batch8 `4bee9eb` · OTC COMPLETE **5252** / PARTIAL **3532** (Batch8 already on `origin/main` at `4bee9eb`)  
**Primary proofs:**  
- [`w0820a_w104_otc_backfill_batch8_20260820.md`](w0820a_w104_otc_backfill_batch8_20260820.md) (Track A)  
- [`w0820a_w104_hyps_new_logic_20260820.md`](w0820a_w104_hyps_new_logic_20260820.md) (Track B — **NEW unique_logic** is the headline)  
- Track C confirm: no extra gate/sticky grid this wave (logs `.glm-logs/w0820a_w104_otc8_new_hyps/c_gate_sticky_confirm.json`)  
- Track D confirm: [`w0819f_w103_repo_short_cost_20260819.md`](w0819f_w103_repo_short_cost_20260819.md) still applies (logs `d_repo_short_confirm.json`)  
**Logs:** [`.glm-logs/w0820a_w104_otc8_new_hyps/`](../../.glm-logs/w0820a_w104_otc8_new_hyps/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

This residual is **not** TASK A only. It covers **A–D ALL TRACKS**.

---

## What landed this wave (A–E)

1. **A. OTC Batch8** — official archive newer-first **100** days before span start `2005-08-03` (`2005-08-02…2005-03-08`). Valid CSV → COMPLETE. COMPLETE **5152 → 5252 (+100)** · PARTIAL **3632 → 3532** · span **2005-03-08…2026-08-20** · dataset **PARTIAL** held (5252/8784) · tip `S260821+` **404** unpublished (no invent) · empty COMPLETE **0** · remaining official 2005 **43**.
2. **B. NEW unique_logic hyps (headline research track)** — pack **4 / 4 / 4** (proposed / accepted / min-impl daily_path_DD complete). Weak-template mapping **OFF**. daily_path_DD **required**. Not a count race. Headline logics: `event_funding_stress_skip` (PIT funding×disclosure skip; worst **−11.4%**) and `curve_steep_event_confirm` (funding×disclosure×macro combo; worst **−11.8%**). Also min-impl (not headline): `disclosure_cluster_mom_gate` · `surprise_xs_rank_hold`. **Catalog-map-only hyps are not the headline.** No remap onto sticky / event / vol. Survivors research-only · **not** main/GO. W100 **6/6/3**, W101 **3/3/3**, W102 **4/4/2**, W103 **4/3/3** **stand**.
3. **C. gate / sticky confirm — no extra grid this wave.** `xs_cs_dispersion_gate` stays **RESEARCH_ONLY** (worst **−11.4%**, 2023–25). `xs_rank_ls_sticky` stays **STABLE_RESEARCH_ONLY** (worst **−14.4%**, 2017–19). **No extra threshold grid. No hold/mom grid.** W103 3-pt coarse thresh is cited, not rerun. **promote_as_main=false · go=false.** Better-in-some-windows **≠** main.
4. **D. Repo short confirm** — JSDA Tokyo overnight (`overnight/翌日物/T+0`) still date-matches bars-MTM short-leg drag on gate+sticky only. n_obs **2594** · required dates **738/738** · **n_gaps=0** · **no ffill / no invent**. Ranking vs tx-only **unchanged**. **No** cost over-tune. Contrast vs W102 50 bp placeholder still holds. **Not** GO/main.
5. **E. master / pins / projection** — MISDATE **KEEP PARTIAL** · sealed **0** · COMPLETE **220** / PARTIAL **21** held · live listed_info probe unavailable · **no floor raise**. 3-default pins **untouched**. Projection **FRESH** (`projgen-6424a4bc0c0b4a75bfd6159c7fa0ef0b`; coverage_segments untouched; age not large — Batch8 already re-published). Mass **NO-GO**.

GLM implementer only. Grok did not implement.

---

## Explicit non-declarations (held)

- READY / Mass ON / Phase7 / operational GO / GO final declare — **not**
- continuous paper arm — **UNARMED**
- human main candidate selection — **not this wave**
- sticky / peer / hyp survivors / gate as production research_candidates — **not**
- 3 defaults retune — **forbidden / not done**
- OTC dataset COMPLETE / COMPLETE 23 invent / fake densify — **none** (Batch8 dataset **PARTIAL** held)
- master floor raise to 2008-05 invent COMPLETE — **forbidden / not done**
- Interpreting period-net DD=0 as “no risk” — **FORBIDDEN**
- S1–S5 unreject · simple_daily_sign mass · live orders — **none**
- Full catalog / hold/mom grid — **not run**
- Extra leverage / pick-best short band / pick-best thresh — **not**
- **No extra gate grid this wave** (no extra threshold / hold/mom grid)
- **Catalog-map-only hyps are not the headline** (W104 B is NEW unique_logic min-impl)
- “Gate is uniformly safer” — **not claimed**
- Complete unique_logic daily_path_DD = GO/main — **not**

---

## Residual TOP (W104)

1. **COMPLETE 22 held** · DEFER/PARTIAL **4** (bars_am · earn_cal · master · OTC) · OTC Batch8 **5252 / 3532** · dataset **PARTIAL** · tip-wait `S260821+`
2. **equities_master** — PRE_PLAN **de-scoped** · MISDATE **21** PARTIAL until vendor Date in-window · this-wave re-probe **Δ COMPLETE 0**
3. **`xs_rank_ls_sticky`** — STABLE_RESEARCH_ONLY · true daily DD **material** · **not** main · **not** GO
4. **`xs_cs_dispersion_gate`** — RESEARCH_ONLY · worst **−11.4%** · not uniformly safer than sticky · **no extra gate grid this wave** · **not** main/GO
5. **Hyps** — W100 **6/6/3** + W101 **3/3/3** + W102 **4/4/2** + W103 **4/3/3** stand · W104 **4/4/4** NEW unique_logic (headline `event_funding_stress_skip` / `curve_steep_event_confirm`) · **catalog-map-only hyps are not the headline** · **not** main/GO
6. **Repo-linked short** — still applies on gate+sticky bars-MTM (D confirm) · ranking unchanged · **not** a GO lever
7. **3 defaults frozen** — mom5 KEEP · mom3 PROMOTE · fund KEEP · **not retuned** · pins_untouched **True**
8. **GO deferred** · Mass/READY/ops GO closed · continuous paper **UNARMED** · human main **NOT selected**

---

## Key metrics

| metric | BEFORE (W103) | AFTER (W104) |
|--------|----------------:|---------------------:|
| OTC COMPLETE | 5152 | **5252** (+100) |
| OTC PARTIAL | 3632 | **3532** |
| COMPLETE span | 2005-08-03…2026-08-20 | **2005-03-08…2026-08-20** |
| platform COMPLETE segs | 8541 | **8641** |
| master COMPLETE/PARTIAL | 220/21 | **220/21** (Δ0 · KEEP PARTIAL) |
| sticky daily max DD | −0.1437 (w2017_2019) | **−0.1437** (confirm; STABLE_RESEARCH_ONLY) |
| gate daily max DD | −0.1142 (w2023_2025) | **−0.1142** (confirm; RESEARCH_ONLY; **no extra grid**) |
| extra gate/thresh/hold-mom grid | W103 3-pt cited | **not run this wave** |
| repo short on bars-MTM | wired (overnight; 0 gaps) | **still applies** (2594 obs · 738/738 · 0 gaps · ranking unchanged) |
| Dataset COMPLETE | 22 | **22** |
| empty COMPLETE | 0 | **0** |
| hyps | 6/6/3 + 3/3/3 + 4/4/2 + 4/3/3 | **+ 4/4/4 NEW unique_logic** (catalog maps **not** headline) |
| Mass | NO-GO | NO-GO |
| 3-default pins | untouched | **untouched** |
| projection | FRESH | **FRESH** (`projgen-6424a4bc0c0b4a75bfd6159c7fa0ef0b`) |

---

## Close checklist

| item | status |
|------|--------|
| A OTC Batch8 official +50–100 days | **yes** (+100 · 2005-08-02…2005-03-08) |
| Valid CSV only COMPLETE · 404/holiday PARTIAL | **yes** |
| Tip `S260821+` sealed only if FULL_OK | **yes** (404 wait) |
| Dataset stays PARTIAL · no fake COMPLETE | **yes** (5252/8784) |
| B NEW unique_logic hyps · weak-template mapping OFF · daily_path_DD required | **yes** (4/4/4) |
| Catalog-map-only hyps are **not** the headline | **yes** (explicit) |
| Survivors not main / not GO | **yes** |
| C no extra gate grid this wave | **yes** (no extra threshold / hold/mom grid) |
| gate RESEARCH_ONLY · sticky STABLE_RESEARCH_ONLY · GO=false | **yes** |
| D JSDA overnight still applies on gate+sticky | **yes** (738/738 · gaps=0 · no ffill/invent · not rank-tuned) |
| period-net DD=0 NOT treated as no-risk | **yes** |
| E MISDATE wait · no fake COMPLETE | **yes** (Δ0) |
| 3-default pins unchanged | **yes** |
| projection FRESH | **yes** (`projgen-6424a4bc0c0b4a75bfd6159c7fa0ef0b`) |
| Residual is ALL-TRACK (not TASK A only) | **yes** |
| Mass/READY/GO/live not declared | **yes** |
| must push origin/main | **yes** (this close) |
| GLM5.3 only. Grok did not implement. | **yes** |

---

## Remaining issues

1. OTC dataset still **PARTIAL** (Batch8 5252/8784) — continue planned official archive (remaining **~43** official 2005 days before `2005-03-08`, then 2004→…); tip `S260821+` 404 wait; **no invent COMPLETE**.
2. `equities_master` MISDATE **21** PARTIAL until vendor in-window Date; live listed_info probe needs client `http` wiring on next optional re-probe.
3. `xs_cs_dispersion_gate` remains **research-only**; 2023–25 worst path **−11.4%** is **not** safer than sticky that window. **No extra gate grid this wave.** Not catalog-promoted / not GO.
4. W104 NEW unique_logic is research-only. `event_funding_stress_skip` worst **−11.4%**; `curve_steep_event_confirm` worst **−11.8%** (sparse occupancy 2017–22). Complete measurement **≠** GO. **Catalog-map-only hyps are not the headline.**
5. Repo-linked short is wired on a **small** set (gate+sticky) only; ranking unchanged. Not a GO lever / not a cost-tune ranking.
6. Contiguous 3y bars mirrors still absent (2018/2020/2022/2024) — honest shards only.
7. GO / Mass / READY / live / human main — **deferred**.

GLM implementer only. Grok did not implement.
