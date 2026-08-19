# W103 / w0819f residual close (Tracks A+B+C+D+E)

**Wave:** W103 / `w0819f` · 2026-08-19  
**Status:** **CLOSED** as residual TOP for **all tracks** (OTC Batch7 + repo-linked short cost + dispersion_gate extra deep-dive + failure-constrained hyps + MISDATE wait + pins frozen).  
**Code tip:** `d779accdb2ffb5f4a88a8aa172573b4414ccac08`  
**Prior tip:** W102 `0b72ff9` · Track B `bfd32b9` · Track A Batch7 `2e0511a` · OTC COMPLETE **5152** / PARTIAL **3632** (Batch7 already on `origin/main` at `2e0511a`)  
**Primary proofs:**  
- [`w0819f_w103_otc_backfill_batch7_20260819.md`](w0819f_w103_otc_backfill_batch7_20260819.md) (Track A)  
- [`w0819f_w103_repo_short_cost_20260819.md`](w0819f_w103_repo_short_cost_20260819.md) (Track B) · [`w0819f_w103_repo_short_wiring_20260819.md`](w0819f_w103_repo_short_wiring_20260819.md)  
- [`w0819f_w103_dispersion_deepdive_20260819.md`](w0819f_w103_dispersion_deepdive_20260819.md) (Track C)  
- [`w0819f_w103_hyps_20260819.md`](w0819f_w103_hyps_20260819.md) (Track D)  
**Logs:** [`.glm-logs/w0819f_w103_otc7_repo_gate/`](../../.glm-logs/w0819f_w103_otc7_repo_gate/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

This residual is **not** TASK A only. It covers **A–D ALL TRACKS**.

---

## What landed this wave (A–E)

1. **A. OTC Batch7** — official archive newer-first **100** days before span start `2005-12-29` (`2005-12-28…2005-08-03`). Valid CSV → COMPLETE. COMPLETE **5052 → 5152 (+100)** · PARTIAL **3732 → 3632** · span **2005-08-03…2026-08-20** · dataset **PARTIAL** held (5152/8784) · tip `S260821+` **404** unpublished (no invent) · empty COMPLETE **0**.
2. **B. Repo-linked short cost** — JSDA Tokyo overnight (`overnight/翌日物/T+0`) wired into bars-MTM short-leg daily drag for gate + sticky only. n_obs **2594** · required dates **738/738** · **n_gaps=0** · **no ffill / no invent**. Contrast vs W102 fixed-50 bp placeholder. Ranking vs tx-only **unchanged**. **No** cost over-tune. **Not** GO/main.
3. **C. dispersion_gate extra deep-dive** — `xs_cs_dispersion_gate` vs sticky **STABLE_RESEARCH_ONLY**. Gate on/off interval returns/DD · 2023–25 activity driver (fatter CS-disp right tail + 2023-shard + sticky-carry) · coarse thresh **3 pts** (×0.9/1.0/1.1; first pass ×0.85/1.15 agrees) · repo-short overlay from B. Gate worst **−11.4%** (2023–25) is **slightly worse** than sticky **−10.8%** in that window. Gate is **not** uniformly safer. 2023–25 on-segment **is** the −10.8% path. Thresh retune does **not** delete it. **promote_as_main=false · go=false.** No hold/mom grid. Better-in-some-windows **≠** main.
4. **D. Hyps** — new failure-constrained pack **4/3/3** (xAI grok-4.6; 1 generation reject). Weak-template mapping **OFF**. daily_path_DD **required**. Not a count race. All three period-net survivors have daily_path_DD complete (event W102; vol W101; sticky this-wave C). Survivors are catalog maps, **not** new theses · research-only · **not** main/GO. W100 **6/6/3**, W101 **3/3/3**, W102 **4/4/2** **stand**.
5. **E. master / pins / projection** — MISDATE **KEEP PARTIAL** · sealed **0** · COMPLETE **220** / PARTIAL **21** held · live listed_info probe unavailable · **no floor raise**. 3-default pins **untouched**. Projection **FRESH** (`projgen-3e24d2d0297d45028a840cb80d32388f`; coverage_segments untouched). Mass **NO-GO**.

GLM implementer only. Grok did not implement.

---

## Explicit non-declarations (held)

- READY / Mass ON / Phase7 / operational GO / GO final declare — **not**
- continuous paper arm — **UNARMED**
- human main candidate selection — **not this wave**
- sticky / peer / hyp survivors / gate as production research_candidates — **not**
- 3 defaults retune — **forbidden / not done**
- OTC dataset COMPLETE / COMPLETE 23 invent / fake densify — **none** (Batch7 dataset **PARTIAL** held)
- master floor raise to 2008-05 invent COMPLETE — **forbidden / not done**
- Interpreting period-net DD=0 as “no risk” — **FORBIDDEN**
- S1–S5 unreject · simple_daily_sign mass · live orders — **none**
- Full catalog / hold/mom grid — **not run**
- Extra leverage / pick-best short band / pick-best thresh — **not**
- “Gate is uniformly safer” — **not claimed** (2023–25 is worse)

---

## Residual TOP (W103)

1. **COMPLETE 22 held** · DEFER/PARTIAL **4** (bars_am · earn_cal · master · OTC) · OTC Batch7 **5152 / 3632** · dataset **PARTIAL** · tip-wait `S260821+`
2. **equities_master** — PRE_PLAN **de-scoped** · MISDATE **21** PARTIAL until vendor Date in-window · this-wave re-probe **Δ COMPLETE 0**
3. **`xs_rank_ls_sticky`** — STABLE_RESEARCH_ONLY · true daily DD **material** · **not** main · **not** GO
4. **`xs_cs_dispersion_gate`** — extra deep-dive complete · research-only · worst **−11.4%** · not uniformly safer than sticky · **not** main/GO
5. **Hyps** — W100 **6/6/3** + W101 **3/3/3** + W102 **4/4/2** stand · W103 **4/3/3** · all daily complete via cite · **not** main/GO
6. **Repo-linked short** — wired on gate+sticky bars-MTM (B) · ranking unchanged · **not** a GO lever
7. **3 defaults frozen** — mom5 KEEP · mom3 PROMOTE · fund KEEP · **not retuned** · pins_untouched **True**
8. **GO deferred** · Mass/READY/ops GO closed · continuous paper **UNARMED** · human main **NOT selected**

---

## Key metrics

| metric | BEFORE (W102) | AFTER (W103) |
|--------|----------------:|---------------------:|
| OTC COMPLETE | 5052 | **5152** (+100) |
| OTC PARTIAL | 3732 | **3632** |
| COMPLETE span | 2005-12-29…2026-08-20 | **2005-08-03…2026-08-20** |
| platform COMPLETE segs | 8441 | **8541** |
| master COMPLETE/PARTIAL | 220/21 | **220/21** (Δ0 · KEEP PARTIAL) |
| sticky daily max DD | −0.1437 (w2017_2019) | **−0.1437** (reproduced; compare-only) |
| gate daily max DD | −0.1142 (w2023_2025) | **−0.1142** (deepen; not promoted; not uniformly safer) |
| gate 2023–25 vs sticky | −11.4% vs −10.8% | **same** (on-segment is the risk) |
| repo short on bars-MTM | fixed-bp placeholder | **wired** (overnight; 0 gaps; ranking unchanged) |
| Dataset COMPLETE | 22 | **22** |
| empty COMPLETE | 0 | **0** |
| hyps | 6/6/3 + 3/3/3 + 4/4/2 | **+ 4/3/3** (3/3 daily complete via cite) |
| Mass | NO-GO | NO-GO |
| 3-default pins | untouched | **untouched** |

---

## Close checklist

| item | status |
|------|--------|
| A OTC Batch7 official +50–100 days | **yes** (+100 · 2005-12-28…2005-08-03) |
| Valid CSV only COMPLETE · 404/holiday PARTIAL | **yes** |
| Tip `S260821+` sealed only if FULL_OK | **yes** (404 wait) |
| Dataset stays PARTIAL · no fake COMPLETE | **yes** (5152/8784) |
| B repo-linked short wired or inability pinned | **yes** (wired; 0 gaps; contrast vs placeholder) |
| period-net DD=0 NOT treated as no-risk | **yes** |
| C gate on/off · 2023–25 activity · 2–3 pt thresh | **yes** |
| repo-short overlay if B lands | **yes** |
| no hold/mom grid · promote/GO=false | **yes** |
| not uniformly safer · better-windows ≠ main | **yes** |
| D new hyps · weak-template mapping OFF · daily_path_DD required | **yes** (4/3/3) |
| Survivors not main / not GO | **yes** |
| E MISDATE wait · no fake COMPLETE | **yes** (Δ0) |
| 3-default pins unchanged | **yes** |
| projection FRESH | **yes** (`projgen-3e24d2d0297d45028a840cb80d32388f`) |
| Residual is ALL-TRACK (not TASK A only) | **yes** |
| Mass/READY/GO/live not declared | **yes** |
| must push origin/main | **yes** (this close) |
| GLM5.3 only. Grok did not implement. | **yes** |

---

## Remaining issues

1. OTC dataset still **PARTIAL** (Batch7 5152/8784) — continue planned official archive (remaining ~143 official 2005 days, then 2004→…); tip `S260821+` 404 wait; **no invent COMPLETE**.
2. `equities_master` MISDATE **21** PARTIAL until vendor in-window Date; live listed_info probe needs client `http` wiring on next optional re-probe.
3. `xs_cs_dispersion_gate` extra deep-dive is complete but **research-only**; 2023–25 worst path **−11.4%** lives **inside** the on-segment and is **not** safer than sticky that window. Not catalog-promoted / not GO.
4. Coarse thresh 3-pt does **not** remove 2023–25 −11.4%. Do not retune the gate to manufacture safety.
5. Repo-linked short is wired on a **small** set (gate+sticky) only; ranking unchanged. Not a GO lever / not a cost-tune ranking.
6. W103 hyp pack **4/3/3** — all daily-complete survivors are catalog maps of event/vol/sticky (not new theses). Not a count race. Not main/GO.
7. Contiguous 3y bars mirrors still absent (2018/2020/2022/2024) — honest shards only.
8. GO / Mass / READY / live / human main — **deferred**.

GLM implementer only. Grok did not implement.
