# W81 / w0816p — stats + paper + OTC residual close (Tasks A–C + residual E/F)

**Wave status:** **COMPLETE** — stats bar re-judge · event_post only candidate · multi_day 10d demoted · paper limited trial (rehearsal) · OTC 2595→4485 · COMPLETE 22 health · FRESH · residual pin · push  
**Wave:** W81 / `w0816p` · statistical bar re-judge / paper limited trial / OTC 2008+ FULL_OK finish / residual FRESH / commit / push  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Live verified:** `2026-08-16T14:37:41Z` · FRESH `projgen-af053445fef84124939b35561ba519c0` · coverage_segments FRESH-path untouched  
**READY 未宣言** · Mass **NO-GO** · Phase7 **OFF** · operational GO **未宣言** · densify **none** · empty COMPLETE **0** · **no invent COMPLETE 23** · **no OTC bulk densify** · **no S1–S5 un-reject** · **no simple_daily_sign mass gen** · **no live orders** · continuous paper **UNARMED** · GO **未宣言**

**GO definition (this residual):** **GO** = **pre-live-order final gate** (not operational GO declare).

---

## Success summary

| criterion | result |
|-----------|--------|
| Task A stats bar re-judge | **done** · [`w0816p_w81_stats_bar_rejudge_20260816.md`](w0816p_w81_stats_bar_rejudge_20260816.md) · **event_post KEEP** (t=**2.83** · Sharpe=**1.15**) · multi_day 10d **DEMOTED** `discussion_only_noisy_stats` (t=**0.62** · Sharpe=**0.25**) |
| Task B paper limited trial | **done** · [`w0816p_w81_paper_limited_trial_20260816.md`](w0816p_w81_paper_limited_trial_20260816.md) · event_post single-shot **healthy** · limited **30d** post-cost **−4.37%** (rehearsal only · **not** edge claim) · multi_day **unarmed only** |
| Task C OTC 2008+ FULL_OK finish | **done** · [`w0816p_w81_otc_2008plus_20260816.md`](w0816p_w81_otc_2008plus_20260816.md) · **2595 → 4485 (+1890)** · span **2008-03-25…2026-08-17** · dataset **PARTIAL** · segs **7874** |
| Health + FRESH + residual | **done** · this close · GO gates update · residual TOP W81 |
| COMPLETE 22 health (local) | **pass** · COMPLETE **22** · PARTIAL **4** · fins **104** · empty **0** · OTC **4485** · bars_am **1** · segs **7874** |
| COMPLETE 22 health (remote) | **pass** · same floors after residual FRESH |
| FRESH | `projgen-af053445fef84124939b35561ba519c0` · coverage_segments_untouched=1 · mass=NO-GO |
| Pytest (W81 key surface) | **56 green** · class_signals **15** · paper adapter **12** · standard_eval **17** · hyp_classes **12** |
| Standard eval wiring_only | **pass freezes** · checklist **v2** · `ready_declared=False` · mass=**NO-GO** · phase7=**OFF** · harness `research_candidate=False` · prefer liq+repo **True** |
| Mass/READY/operational GO/Phase7 | **NO-GO / 未宣言 / 未宣言 / OFF** |
| Production class_hyp candidates | **1** (event_post only; **not** Mass/READY/ops GO) |
| Paper path | event_post limited trial done · continuous **UNARMED** · multi_day unarmed only |

**Success condition:** residual TOP = W81 landings · **event_post only research_candidate** · multi_day demoted · paper limited trial recorded (not edge) · OTC **2595→4485** · GO **未宣言** · COMPLETE 22 held · push past W80 tip `71b3466`.

---

## Deliverables

| # | artifact | path / note |
|---|----------|-------------|
| A | Stats metrics + class_signals **v4** + multi-year eval **v4** | `stats_metrics.py` · `class_signals.py` · `class_hyp_eval.py` · proof stats bar |
| B | Paper single-shot + LIMITED trial (event_post only) | proof paper trial · logs under w81_stats · multi_day unarmed |
| C | OTC 2008+ FULL_OK finish | **2595→4485** · D1 publish · proof OTC · dataset PARTIAL |
| E/F | Health + FRESH + residual close | this file · GO gates · residual SoT |
| — | GO gates update | [`w0816p_w81_go_gates_20260816.md`](w0816p_w81_go_gates_20260816.md) |

---

## Smoke results (machine)

### D1 / local OTC COMPLETE snapshot (finalize)

| source | OTC COMPLETE | span | platform COMPLETE segs | notes |
|--------|-------------:|------|-----------------------:|-------|
| local (W81 pin) | **4485** | 2008-03-25…2026-08-17 | **7874** | +1890 from W80 2595 |
| remote AFTER residual FRESH | **4485** | 2008-03-25…2026-08-17 | **7874** | health remote pass |

Logs: `.glm-logs/w0816p_w81_stats/otc_after.json` · `otc_d1_after_*.json` · `health_*_residual.log`

### COMPLETE 22 health

| source | all_checks_pass | COMPLETE | PARTIAL | fins | empty | OTC | bars_am | segs |
|--------|-----------------|----------|---------|------|-------|-----|---------|------|
| local SQLite | **true** | 22 | 4 | 104 | 0 | **4485** | 1 | **7874** |
| remote D1 | **true** | 22 | 4 | 104 | 0 | **4485** | 1 | **7874** |

Note: OTC **dataset** status remains **PARTIAL**. Platform COMPLETE datasets stay **22**.  
pre-2008 OTC is **not** a main claim (2008+ FULL_OK only).

Log: `.glm-logs/w0816p_w81_stats/health_local_residual.log` · `health_remote_residual.log`

### FRESH

| field | value |
|-------|-------|
| gen | `projgen-af053445fef84124939b35561ba519c0` |
| now | `2026-08-16T14:37:41.435438+00:00` |
| coverage_segments_untouched | **1** |
| mass | **NO-GO** |

Log: `.glm-logs/w0816p_w81_stats/reeval_freshness_residual.log`

### Standard research eval (wiring_only · dry_run)

| field | value |
|-------|-------|
| checklist_version | `standard-research-eval-checklist/v2` |
| mode | `wiring_only` |
| dry_run | `true` |
| ready_declared | **False** |
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| operational_go | **False** |
| research_candidate (harness) | **False** |
| research_candidate_allowed | **False** |
| prefer_repo_linked | **True** |
| prefer_liquidity_linked | **True** |
| gate_pass_implies_* | all **False** |

Log: `.glm-logs/w0816p_w81_stats/standard_eval_wiring.log`

### Pytest counts (green)

| suite | n |
|-------|--:|
| `tests/test_class_signals.py` | 15 |
| `tests/test_paper_candidate_adapter.py` | 12 |
| `tests/test_standard_research_eval.py` | 17 |
| `tests/test_hypothesis_classes.py` | 12 |
| **total** | **56** |

Log: `.glm-logs/w0816p_w81_stats/pytest_w81_residual.log`

### Stats bar honesty (class_hyp production bar)

| hyp / variant | gate | econ | occ | stats | research_candidate | decision |
|---------------|------|------|-----|-------|--------------------|----------|
| multi_day_hold 5d | FAIL | no | yes | no | **False** | not_candidate |
| multi_day_hold **10d** | PASS | yes **+21.1bp** | act 0.090 | **no** t=**0.62** Sharpe=**0.25** | **False** | **demote** `discussion_only_noisy_stats` |
| **event_post** | PASS | yes **+53.0bp** | ~3.61/code-yr | **yes** t=**2.83** Sharpe=**1.15** | **True** | **keep** |
| macro_conditioned | PASS | weak − | yes | no | **False** | not_candidate |
| flow_demand | FAIL | mixed | yes | no | **False** | not_candidate |
| fundamentals_price | PASS | yes | rate fail | no | **False** | discussion_only |
| cross_section | FAIL | no | yes | no | **False** | not_candidate |

**Production research candidates after W81: event_post only.**  
**Mass / READY / operational GO: still closed.**

### Paper limited trial honesty

| step | result |
|------|--------|
| event_post single-shot (5d Draft) | **healthy** · post-cost **+1.38%** |
| event_post LIMITED (30d Paper) | **ok** · post-cost **−4.37%** · maxDD **−9.81%** · **rehearsal only · not edge claim** |
| multi_day_hold 10d trial | **not armed** (demoted) · unarmed receptacle only |
| continuous paper scheduler | **OFF** |
| live orders | **OFF** |

Fidelity note: StrategySpec v2 uses `disclosure_flag_fins` threshold proxy — not full surprise sticky hold. Limited-window PnL does **not** revoke multi-year KEEP and does **not** authorize live/continuous arm.

### OTC / platform numbers

| metric | W80 phase A | W81 | Δ |
|--------|------------:|----:|--:|
| OTC COMPLETE segs | 2595 | **4485** | +1890 |
| OTC COMPLETE span start | 2016-01-04 | **2008-03-25** | archive extend 2008+ |
| OTC dataset status | PARTIAL | **PARTIAL** | held |
| platform COMPLETE segs | 5984 | **7874** | +1890 |
| platform COMPLETE datasets | 22 | **22** | held |
| empty COMPLETE | 0 | **0** | held |
| pre-2008 densify | — | **not run** (out of scope) |

---

## Explicit non-declarations (held)

- **READY** — not declared  
- **Mass** — **NO-GO / OFF**  
- **Phase7** — **OFF**  
- **operational GO** — **未宣言**  
- **Dataset COMPLETE 23** — not invented  
- **OTC dataset COMPLETE** — not forced (segment COMPLETE 4485 only; dataset PARTIAL)  
- **empty COMPLETE** — not minted (0 held)  
- **research_candidate → Mass/READY/ops GO** — never auto-connects  
- **paper continuous / unlimited arm** — **False**  
- **live orders** — **forbidden** this residual  
- **S1–S5 un-reject** — not done  
- **simple_daily_sign mass generation** — **forbidden** (default OFF)  
- **OTC bulk densify** — not run (FULL_OK official 2008+ only)  
- **pre-2008 OTC as main claim** — **forbidden**  
- **limited paper PnL as edge / significance** — **not claimed**  
- **multi_day_hold 10d production candidate** — **demoted** (noisy stats)

---

## Residual TOP (W81)

1. **Stats bar raised** — period |t|≥1.5 · Sharpe≥0.50 · win-rate≥0.60 · ≥4 pos years · class_signals **v4** · stats_metrics **v1**  
2. **event_post only research_candidate** — t=**2.83** · Sharpe=**1.15** · mean net **+53.0bp** · **not Mass**  
3. **multi_day_hold 10d DEMOTED** — t=**0.62** · Sharpe=**0.25** · `discussion_only_noisy_stats`  
4. **Paper limited trial** — event_post single-shot healthy · 30d post-cost **−4.37%** rehearsal only · multi_day unarmed · continuous **OFF**  
5. **OTC 2595→4485 (+1890)** — 2008-03-25…2026-08-17 · dataset still **PARTIAL** · segs **7874** · pre-2008 not claimed  
6. **GO 未宣言** — pre-live-order residual only · Mass **NO-GO** · READY **未宣言** · operational GO **未宣言**  
7. **COMPLETE 22 held** · empty **0** · no invent 23 · costs v2 held · research entry linked  
8. **W80 underneath** — prior 2 candidates / OTC 2595 / paper UNARMED adapter superseded by W81 stats + paper trial + OTC 4485  

See also: [`w0816p_w81_go_gates_20260816.md`](w0816p_w81_go_gates_20260816.md)

---

## Prior tip / push

| item | value |
|------|-------|
| W80 tip (start) | `71b3466` — docs pin after candidate residual close |
| W80 feature tip | `e7b2cf5` — production candidates + OTC 639→2595 + paper UNARMED |
| W81 feature tip | `726d245` — stats bar + event_post only + paper trial + OTC 2595→4485 + FRESH close |
| This wave | commit + push on `main` past `71b3466` |

---

## Related proofs

| doc | role |
|-----|------|
| A stats bar re-judge | [`w0816p_w81_stats_bar_rejudge_20260816.md`](w0816p_w81_stats_bar_rejudge_20260816.md) |
| B paper limited trial | [`w0816p_w81_paper_limited_trial_20260816.md`](w0816p_w81_paper_limited_trial_20260816.md) |
| C OTC 2008+ | [`w0816p_w81_otc_2008plus_20260816.md`](w0816p_w81_otc_2008plus_20260816.md) |
| GO gates | [`w0816p_w81_go_gates_20260816.md`](w0816p_w81_go_gates_20260816.md) |
| Residual SoT | [`docs/phase62_residual_status.md`](../phase62_residual_status.md) |
| W80 close | [`w0816o_w80_candidate_close_20260816.md`](w0816o_w80_candidate_close_20260816.md) |
