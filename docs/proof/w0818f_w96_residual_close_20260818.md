# W96 / w0818f residual close

**Wave:** W96 / `w0818f` · 2026-08-18  
**Status:** **CLOSED** as residual TOP (research factory + tip data only)  
**Code tip:** `ca0a9450459d981eaeb14d5bbba026b59afd3611`  
**Prior tip:** W95 `942a43d`  
**Primary proofs:**  
- [`w0818f_w96_otc_partial_progress_20260818.md`](w0818f_w96_otc_partial_progress_20260818.md)  
- [`w0818f_w96_hyps_defaults_20260818.md`](w0818f_w96_hyps_defaults_20260818.md)  
**Logs:** [`.glm-logs/w0818f_w96_data_hyps_defaults/`](../../.glm-logs/w0818f_w96_data_hyps_defaults/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## What landed

1. **OTC tip FULL_OK advance** — S260818 + S260819 sealed · COMPLETE **4499 → 4501 (+2)** · span max **2026-08-19** · dataset **PARTIAL** held · platform segs **7888 → 7890** · COMPLETE **22** held · **no** archive densify · **no** invent 23  
2. **Failure-constrained new hyps** — `llm-hyp-generator/v1.1` hard constraints + reject gate · xAI grok-4.6 **n_proposed=8 / n_accepted=8 / n_evaluated=8 / n_survivors=5** · always via `propose_profit_hypotheses` · **do not** promote demoted/weak as main  
3. **Frozen 3-default quality** — pins **unchanged** · CF job **`w96-defaults-20260818T142144Z`** `r2_panels` · window survivors **9/9** · mild PROMOTE window notes **recorded only** · **no retune**  
4. **Freezes held** — Mass NO-GO · READY 未宣言 · Phase7 OFF · ops GO 未宣言 · continuous paper UNARMED · BaseVol canonical · ATM compare-only · spread off-mainline · no grid mass · no GO/live

---

## Explicit non-declarations (held)

- READY / Mass ON / Phase7 / operational GO / GO final declare — **not**  
- continuous paper arm — **UNARMED**  
- human main candidate selection — **not this wave**  
- factory survivors as production research_candidates — **not**  
- 3 defaults retune — **forbidden / not done**  
- OTC dataset COMPLETE / COMPLETE 23 invent / archive densify — **none**  
- smile / surface identical to BaseVol level — **forbidden / not claimed**  
- re-optimize shape/rate/flow/demoted fund — **not done**  
- S1–S5 unreject · simple_daily_sign mass · live orders — **none**

---

## Residual TOP (W96)

1. **COMPLETE 22 held** · DEFER/PARTIAL **4** (bars_am · earn_cal · master · OTC) · OTC tip **4501** (Δ+2 this wave) · tip-wait continues for further FULL_OK only  
2. **Canonical level** — **BaseVol** mainline; ATM compare-only; spread off-mainline  
3. **Shape / rate / flow / fund_slow** — prior W95 demotions held · not re-polished  
4. **New hyps** — failure-constrained xAI pack (8/8/5) · research-only · not main  
5. **3 defaults frozen** — mom5 KEEP · mom3 PROMOTE · fund KEEP · quality rechecked · contradictions recorded · **not retuned**  
6. **GO deferred** · Mass/READY/ops GO closed · continuous paper **UNARMED** · human main **NOT selected**

---

## Key jobs / artifacts

| artifact | role |
|----------|------|
| OTC tip S260818/S260819 | Track A tip FULL_OK seal |
| `hyp_summary.json` / `llm_hyp_*.json` | Track B xAI hyps + propose_profit_hypotheses |
| `w96-defaults-20260818T142144Z` | Track C CF `r2_panels` frozen defaults |
| `default_quality_table.json/md` | KEEP/PROMOTE contradiction record |
| `scripts/run_w96_hyps_and_defaults.py` | B+C recipe |

---

## Close checklist

| item | status |
|------|--------|
| OTC tip progress quantified before/after | **yes** (+2; honest tip-wait residual remains) |
| No invent / no densify / PARTIAL held | **yes** |
| New hyps with failure constraints | **yes** (8/8/5) |
| Demoted/weak not promoted as main | **yes** |
| 3 defaults quality · pins unchanged | **yes** |
| Contradictions recorded only | **yes** (mild window notes; pins held) |
| Mass/READY/GO/live closed | **yes** |
| proofs | this + OTC + hyps/defaults |
| residual TOP=W96 | **yes** |
| git push origin main | **yes** (this close) |
| GLM5.3 only. Grok did not implement. | **yes** |
