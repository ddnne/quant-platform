# W86 / w0816u — Task C: same-condition comparison table (chosen_sign only)

**Wave status:** **Task C COMPLETE** (same-condition table · proof · machine JSON)  
**Wave:** W86 / `w0816u` · 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Logs:** [`.glm-logs/w0816u_w86_go_pre/`](../../.glm-logs/w0816u_w86_go_pre/)  
**Prior:**  
* [`w0816u_w86_sign_flip_nonzero_20260817.md`](w0816u_w86_sign_flip_nonzero_20260817.md) — Task A sign flip · all three `chosen_sign=+1`  
* [`w0816u_w86_paper_repo_financing_20260817.md`](w0816u_w86_paper_repo_financing_20260817.md) — Task B paper daily repo financing · multi-window remeasure  

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| operational GO | **未宣言** |
| continuous paper | **UNARMED** |
| live orders | **OFF** |
| mean-bp-only promotion | **forbidden** |
| hide paper negatives | **forbidden** |
| Mass/READY/ops GO from compare table | **forbidden** |
| COMPLETE 23 invent | **forbidden** |

**GO gate (explicit):** **repo + same-condition compare table required before GO consideration** — table **ready** this task; GO **not** declared.

---

## Same conditions (held)

| dimension | value |
|-----------|-------|
| Research windows | same multi-year period nets (W84 class_hyp / explore; **6** periods) |
| Paper windows | same **10-window** W85 multi-window calendar |
| Research cost | tx + liquidity preferred + repo-linked **short mid** (spread 50 bp) where remeasured |
| Paper cost | 10 bp one-way tx + liquidity high + **short mid** + **daily repo series** + leverage repo-only |
| Sign | **`chosen_sign` only** (research primary) |
| Gap policy | disclose only · **no ffill / invent** |

---

## Comparison table (chosen_sign only)

Machine: [`.glm-logs/w0816u_w86_go_pre/same_condition_compare.json`](../../.glm-logs/w0816u_w86_go_pre/same_condition_compare.json) · [`.glm-logs/w0816u_w86_go_pre/same_condition_compare.md`](../../.glm-logs/w0816u_w86_go_pre/same_condition_compare.md)

| strategy | sign | mean net (bp) | t | Sharpe | paper multi-window mean % (repo financing) | paper pos/neg | role |
|----------|-----:|--------------:|--:|-------:|-------------------------------------------:|:-------------:|------|
| **xs_hold10_mom5** | **+1** | **83.4** | **1.59** | **0.65** | **−0.5515** | 5/5 | KEEP default |
| **xs_hold10_mom3** | **+1** | **120.0** | **3.04** | **1.24** | **+0.6036** | 6/4 | PROMOTE→default (W85) |
| **fund_hold10_mom10** | **+1** | **44.8** | **1.77** | **0.72** | **−1.8280** | 3/7 | KEEP default |

### Columns (contract)

| column | source |
|--------|--------|
| strategy | default-path key |
| sign | research `chosen_sign` after Task A (both-sides after cost) |
| mean net | research multi-year mean net **bp** under short-mid surface when available |
| t | research multi-year t-stat (same surface) |
| Sharpe | research multi-year Sharpe (same surface) |
| paper multi-window mean | Task B after short mid + daily repo + leverage (10 windows) |

### Cost surface notes

| strategy | research cost surface | paper financing |
|----------|----------------------|-----------------|
| xs_hold10_mom5 | tx+liquidity+repo+**short_mid** (W85 remeasure) | short mid + daily repo + leverage repo-only |
| xs_hold10_mom3 | tx amortized multi-year (**short_mid remeasure not re-run**; disclose) | short mid + daily repo + leverage repo-only |
| fund_hold10_mom10 | tx+liquidity+repo+**short_mid** (W85 remeasure) | short mid + daily repo + leverage repo-only |

mom3 research short-mid remeasure was **not** re-run this wave. Table uses multi-year tx-amortized nets for mom3; expected class Δ ~1 bp from xs/fund short-mid drag is **disclosed, not invented**. Paper column for mom3 **does** include full repo financing.

---

## Reading (honest, not hidden)

1. **All three defaults keep `chosen_sign=+1`** (original). Fund paper flip was evaluated and is **weak** (+0.19% · t=0.13) — research stays **+1**.  
2. **mom3 and mom5 both kept** as parallel defaults (no merge / no over-invest).  
3. Paper multi-window means are **after** Task B financing. Drag vs W85 tx-only paper ≈ **−6 bp** on mean for all three.  
4. Paper PnL is **not** alpha / significance / edge claim (positive or negative). Continuous **UNARMED**.  
5. Fund multi-window paper remains **weak** (3/7 · −1.83%) — **not auto-reject** KEEP (W85 policy held).  
6. xs mom5 paper mixed 5/5 · −0.55% — keep_default held.  
7. xs mom3 paper still positive (+0.60%) after financing — promote_default research+paper stance held.  

---

## Default representatives after W86 A+B+C

| # | representative | params | chosen_sign | research mean bp / t / Sh | paper MW mean % (repo fin) | default-wired |
|---|----------------|--------|:-----------:|--------------------------:|---------------------------:|:-------------:|
| 1 | **cross_section_hold_10** | hold=10 · **mom=5** · frac=0.3 | **+1** | **+83.4** / **1.59** / **0.65** | **−0.55** | **yes** |
| 2 | **cross_section_hold_10_mom3** | hold=10 · **mom=3** | **+1** | **+120.0** / **3.04** / **1.24** | **+0.60** | **yes** |
| 3 | **fundamentals_hold_10** | hold=10 · **mom=10** | **+1** | **+44.8** / **1.77** / **0.72** | **−1.83** | **yes** |

**n_default = 3.** Mass / READY / operational GO / live: still closed.

---

## Artifacts

| path | role |
|------|------|
| `.glm-logs/w0816u_w86_go_pre/same_condition_compare.json` | machine table |
| `.glm-logs/w0816u_w86_go_pre/same_condition_compare.md` | human table |
| `.glm-logs/w0816u_w86_go_pre/sign_flip_selection.json` | Task A both-sides |
| `.glm-logs/w0816u_w86_go_pre/paper_summaries.json` | Task B aggregates |
| `.glm-logs/w0816t_w85_short_cost/results_table.json` | short-mid research remeasure (mom5/fund) |

---

## Exit criteria

| criterion | status |
|-----------|:------:|
| Same multi-year windows | **yes** |
| Same tx + liquidity + repo + short mid (disclosed surfaces) | **yes** |
| chosen_sign only | **yes** |
| Columns: strategy, sign, mean net, t, Sharpe, paper MW mean | **yes** |
| Paper mean with repo financing | **yes** (Task B) |
| Machine JSON under go_pre | **yes** |
| Proof written | **yes** |
| GO not declared | **held** |
| Mass/READY/live OFF | **held** |

**Bottom line:** Same-condition comparison table is **ready**. **repo + compare table required before GO consideration** — prerequisite held for residual inventory; **operational GO still 未宣言**.
