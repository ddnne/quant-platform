# W78 / w0816m — GO remaining gates (short checklist)

**Wave:** W78 / `w0816m` · 2026-08-16  
**Purpose:** Honest inventory of what still blocks **operational GO** / Mass / READY.  
**Status:** **operational GO 未宣言** · Mass **NO-GO** · READY **未宣言** · Phase7 **OFF**  
**Not this document:** any declare of GO / Mass ON / READY / COMPLETE 23 invent.

---

## Held this wave (inputs, not GO)

| landing | result | proof |
|---------|--------|-------|
| Repo-linked cost models v2 | `prefer_repo_linked` · gaps disclosed · no ffill invent | [`w0816m_w78_repo_linked_cost_model_20260816.md`](w0816m_w78_repo_linked_cost_model_20260816.md) |
| OTC archive staged FULL_OK | **93 → 163 (+70)** · dataset still **PARTIAL** | [`w0816m_w78_otc_archive_stage_20260816.md`](w0816m_w78_otc_archive_stage_20260816.md) |
| Class hyp impl + multi-year eval | multi_day_hold / macro_conditioned (+ optional CS) · **not auto-candidate** | [`w0816m_w78_hyp_impl_eval_20260816.md`](w0816m_w78_hyp_impl_eval_20260816.md) |
| COMPLETE 22 health | local+remote **pass** · OTC floor ≥93 (now **163**) · segs **3552** | close + health JSON |
| FRESH | `projgen-65c5af3769194269a9027ba4d013561e` · segs untouched · mass=NO-GO | reeval log |

---

## GO remaining gates (short checklist)

Use this as the operational gate list. **All must be true** before any operational GO discussion. **None** of these auto-declare Mass or READY.

| # | gate | current (W78 close) | needed for GO discussion |
|---|------|---------------------|---------------------------|
| G1 | **Eval v2 candidate exists** | Checklist v2 **wired** · multi-year class-hyp eval **ran** · primary multi_day_hold **FAIL** · macro **discussion-only weak −** · harness `research_candidate=False` always | At least one hyp with **honest** multi-year cost-aware pass **and** human promotion path (still ≠ Mass/READY) |
| G2 | **Repo-linked costs** | **Landed** (`research-cost-models/v2` · prefer date-matched `jsda_tokyo_repo_rates`) · wiring complete | Hold in any candidate package; no fixed-bp-only silent path for levered/short research |
| G3 | **OTC / repo thickness** | Repo tip **30330** / end **2026-08-14** held · OTC segment COMPLETE **163** (was 93) · OTC **dataset still PARTIAL** (163/8781) · corp **12/12** | Thickness adequate for the *specific* hyp data plane; **never** force OTC dataset COMPLETE; further FULL_OK only staged |
| G4 | **Orders separate** | Order intents / live routing **not** in research path · paper/selection remain fail-closed | Orders remain a **separate** gate after research candidate + human review; research print ≠ order authority |
| G5 | **Mass / READY / operational GO** | Mass **NO-GO** · READY **未宣言** · operational GO **未宣言** · Phase7 **OFF** | Explicit human declare only; **never** auto from gate pass |
| G6 | **COMPLETE floor** | Dataset COMPLETE **22** · empty **0** · DEFER **4** · no invent 23 | Held; COMPLETE expand = tip-wait / FULL_OK only |
| G7 | **S1–S5 / simple_daily_sign** | S1–S5 **research_baseline_rejected** untouched · `simple_daily_sign` default **OFF** | Must stay; no mass gen / un-reject as GO path |

### Gate interpretation rules (held)

1. **Gate pass ≠ research_candidate ≠ READY ≠ Mass ≠ operational GO ≠ orders.**  
2. Incomplete checklist v2 → `research_candidate_allowed=False`.  
3. Complete checklist + weak negative print → may be **discussion only**; harness keeps `research_candidate=False` unless a separate promotion API is used (none this wave).  
4. OTC segment COMPLETE growth does **not** mint dataset COMPLETE or COMPLETE 23.  
5. Repo gap policy: disclose · **no ffill invent**.

---

## What would still be required (non-exhaustive, non-promise)

- A **real** research candidate under checklist v2 (multi-year · costs · risk scenarios · gap disclosure) with human review  
- StrategySpec / paper path coherence for that candidate (separate from this wave)  
- Order path still gated (G4)  
- Mass arm only after READY + explicit ops policy (not W78)

---

## Explicit non-declarations

- **operational GO** — **未宣言**  
- **Mass** — **NO-GO**  
- **READY** — **未宣言**  
- **Phase7** — **OFF**  
- **COMPLETE 23** — not invented  
- **OTC dataset COMPLETE** — still PARTIAL  
- **S1–S5 un-reject** / **simple_daily_sign mass gen** — forbidden  

---

## Related

| doc | role |
|-----|------|
| Residual SoT | [`docs/phase62_residual_status.md`](../phase62_residual_status.md) |
| Wave close | [`w0816m_w78_go_build_close_20260816.md`](w0816m_w78_go_build_close_20260816.md) |
| Research entry | [`w0816h_w74_research_entry_complete22_20260816.md`](w0816h_w74_research_entry_complete22_20260816.md) |
| W77 redesign / checklist v2 | [`w0816k_w77_hypothesis_eval_jsda_close_20260816.md`](w0816k_w77_hypothesis_eval_jsda_close_20260816.md) |
