# W101 / w0819d residual close (Tracks A+B+C+D+E+F)

**Wave:** W101 / `w0819d` · 2026-08-19  
**Status:** **CLOSED** as residual TOP for **all tracks** (OTC Batch5 + cited peer daily_path_DD + continue-hyps + sticky STABLE_RESEARCH_ONLY + MISDATE re-probe + projection FRESH).  
**Code tip:** `4fa87f72764aef4b7973d418e0a220b08b56db40`  
**Prior tip:** W100 `b54a436` · OTC COMPLETE **4852** / PARTIAL **3932** · `84874fb` already on `origin/main`  
**Primary proofs:**  
- [`w0819d_w101_otc_backfill_batch5_20260819.md`](w0819d_w101_otc_backfill_batch5_20260819.md) (Track A)  
- [`w0819c_w100_peer_daily_dd_20260819.md`](w0819c_w100_peer_daily_dd_20260819.md) (Track B — **cited, not rerun**)  
- [`w0819d_w101_hyps_20260819.md`](w0819d_w101_hyps_20260819.md) (Track C)  
- [`w0819c_w100_daily_path_dd_gate_20260819.md`](w0819c_w100_daily_path_dd_gate_20260819.md) (W100 gate, underneath)  
**Logs:** [`.glm-logs/w0819d_w101_otc5_dd_close/`](../../.glm-logs/w0819d_w101_otc5_dd_close/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

This residual is **not** TASK A only.

---

## What landed this wave (A–F)

1. **A. OTC Batch5** — official 2006 archive newer-first **100** days before span start `2006-10-19` (`2006-10-18…2006-05-29`). CF `/discover`+`/fetch` → FULL_OK_HISTORICAL (size **896–940 KB**, html=0) → signed SUCCESS receipts → COMPLETE **4852 → 4952 (+100)** · PARTIAL **3932 → 3832** · span **2006-05-29…2026-08-20** · dataset **PARTIAL** held (4952/8784) · tip `S260821+` **404** unpublished (no invent) · empty COMPLETE **0**.
2. **B. Peer daily_path_DD** — W100 table **reused** (`xs_rank_ls_sticky` · `xs_rank_ls_daily` · `xs_rank_mom_slow` · `mdh_sticky_momentum` · `xs_cs_dispersion_gate`). **No catalog grid. No hold/mom grid.** Daily rebalance still worst (**−37%**). Sticky still most stable catalog peer, **not** riskless (worst **−14.4%**).
3. **C. Hyps** — W100 pack **stands** as continue-hyps baseline (**6/6/3**; daily_path_DD required; dispersion-gate complete). Small additional pack **3/3/3** (xAI grok-4.6; weak-template mapping reduced). W100 survivor `vol_risk_adjusted_mom` evaluated **with daily_path_DD** (complete; worst **−23.4%**). Event/rate survivors still incomplete (extra-dataset). All research-only · **not** main/GO.
4. **D. Sticky** — `xs_rank_ls_sticky` **STABLE_RESEARCH_ONLY** · `promote_as_main=false` · `go=false` · no hold/mom grid · W99/W100 daily numbers cited, not re-gridded.
5. **E. master / pins** — MISDATE optional re-probe **KEEP PARTIAL** · sealed **0** · COMPLETE **220** / PARTIAL **21** held · live listed_info probe unavailable (`JQuantsClient` needs `http`) · **no floor raise** · **no fake COMPLETE**. 3-default pins **untouched** (mom5 KEEP · mom3 PROMOTE · fund KEEP).
6. **F. projection + push** — `publish_ops_projection --apply-remote` · `ops_reeval_freshness` rc=0 · gen `projgen-2f92ebcca1f6425581739d10932d95d3` · `coverage_segments_untouched=1` · Mass **NO-GO** · origin/main push (this close).

GLM implementer only. Grok did not implement.

---

## Explicit non-declarations (held)

- READY / Mass ON / Phase7 / operational GO / GO final declare — **not**
- continuous paper arm — **UNARMED**
- human main candidate selection — **not this wave**
- sticky / peer / hyp survivors as production research_candidates — **not**
- 3 defaults retune — **forbidden / not done**
- OTC dataset COMPLETE / COMPLETE 23 invent / fake densify — **none** (Batch5 dataset **PARTIAL** held)
- master floor raise to 2008-05 invent COMPLETE — **forbidden / not done**
- Interpreting period-net DD=0 as “no risk” — **FORBIDDEN**
- S1–S5 unreject · simple_daily_sign mass · live orders — **none**
- Full catalog / hold/mom grid — **not run**

---

## Residual TOP (W101)

1. **COMPLETE 22 held** · DEFER/PARTIAL **4** (bars_am · earn_cal · master · OTC) · OTC Batch5 **4952 / 3832** · dataset **PARTIAL** · tip-wait `S260821+`
2. **equities_master** — PRE_PLAN **de-scoped** · MISDATE **21** PARTIAL until vendor Date in-window · tip continuous 2008-05→latest · this-wave re-probe **Δ COMPLETE 0**
3. **`xs_rank_ls_sticky`** — STABLE_RESEARCH_ONLY · true daily DD **material** · **not** main · **not** GO
4. **Peers** — W100 daily_path_DD cited; none promoted
5. **Hyps** — W100 pack stands **6/6/3** · W101 small pack **3/3/3** · `vol_risk_adjusted_mom` daily_path_DD **complete** · event/rate still incomplete · **not** main/GO
6. **3 defaults frozen** — mom5 KEEP · mom3 PROMOTE · fund KEEP · **not retuned** · pins_untouched **True**
7. **GO deferred** · Mass/READY/ops GO closed · continuous paper **UNARMED** · human main **NOT selected**

---

## Key metrics

| metric | BEFORE (W100) | AFTER (W101) |
|--------|----------------:|---------------------:|
| OTC COMPLETE | 4852 | **4952** (+100) |
| OTC PARTIAL | 3932 | **3832** |
| COMPLETE span | 2006-10-19…2026-08-20 | **2006-05-29…2026-08-20** |
| platform COMPLETE segs | 8241 | **8341** |
| master COMPLETE/PARTIAL | 220/21 | **220/21** (Δ0 · KEEP PARTIAL) |
| sticky daily max DD (worst window) | −0.1437 (w2017_2019) | **−0.1437** (cited) |
| peer worst daily_path_DD | −0.3734 (`xs_rank_ls_daily`) | **−0.3734** (cited; no rerun) |
| `vol_risk_adjusted_mom` daily_path_DD | unmeasured / incomplete | **complete** (worst **−23.4%**) |
| Dataset COMPLETE | 22 | **22** |
| empty COMPLETE | 0 | **0** |
| hyps | 6/6/3 (W100 stands) | **+ 3/3/3** small pack |
| Mass | NO-GO | NO-GO |
| 3-default pins | untouched | **untouched** |
| `84874fb` on origin/main | yes (already) | **yes** (already; not re-pushed as orphan) |

---

## Close checklist

| item | status |
|------|--------|
| A OTC Batch5 official +50–100 days | **yes** (+100 · 2006-10-18…2006-05-29) |
| Valid CSV only COMPLETE · 404/holiday PARTIAL | **yes** |
| Tip `S260821+` sealed only if FULL_OK | **yes** (404 wait) |
| Dataset stays PARTIAL · no fake COMPLETE | **yes** (4952/8784) |
| B peer daily_path_DD cited (no full grid) | **yes** (W100 table) |
| period-net DD=0 NOT treated as no-risk | **yes** |
| C W100 pack stands + small additional pack | **yes** (6/6/3 + 3/3/3) |
| daily_path_DD required on eval | **yes** (`vol_risk_adjusted_mom` complete) |
| Survivors not main / not GO | **yes** |
| D sticky STABLE_RESEARCH_ONLY · promote/GO=false | **yes** |
| E master MISDATE wait / re-probe · no fake COMPLETE | **yes** (Δ0) |
| 3-default pins unchanged | **yes** |
| projection FRESH | **yes** (`ops_reeval_freshness` rc=0) |
| Residual is ALL-TRACK (not TASK A only) | **yes** |
| Mass/READY/GO/live not declared | **yes** |
| must push origin/main | **yes** |
| GLM5.3 only. Grok did not implement. | **yes** |

---

## Remaining issues

1. OTC dataset still **PARTIAL** (Batch5 4952/8784) — continue planned official archive (remaining ~98 official 2006 days before `2006-05-29`, then 2005→…); tip `S260821+` 404 wait; **no invent COMPLETE**.
2. `equities_master` MISDATE **21** PARTIAL until vendor in-window Date; live listed_info probe needs client `http` wiring on next optional re-probe.
3. Period-net hyp survivors `event_post_disclosure_hold` · `rate_curve_shape_xs` still **lack daily_path_DD** (extra-dataset) — incomplete eval.
4. `vol_risk_adjusted_mom` daily_path_DD is complete but **research-only**; worst path **−23.4%** (not safer than sticky). Not catalog-promoted / not GO.
5. Contiguous 3y bars mirrors still absent (2018/2020/2022/2024) — honest shards only.
6. GO / Mass / READY / live / human main — **deferred**.

GLM implementer only. Grok did not implement.
