# W82 / w0816q — event_post PIT + paper gap + OTC residual close (Tasks A–E)

**Wave status:** **COMPLETE** — event_post PIT definition · research↔paper gap · event_post **DEMOTED** · optional xs hold=10 · OTC 4485→4499 · COMPLETE 22 health · FRESH · residual pin · push  
**Wave:** W82 / `w0816q` · event PIT + paper gap + OTC residual FULL_OK + residual FRESH / commit / push  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Live verified:** `2026-08-16T22:01:05Z` · FRESH `projgen-c231a4a021ed4449960afe59a3c20016` · coverage_segments FRESH-path untouched  
**READY 未宣言** · Mass **NO-GO** · Phase7 **OFF** · operational GO **未宣言** · densify **none** · empty COMPLETE **0** · **no invent COMPLETE 23** · **no OTC bulk densify** · **no S1–S5 un-reject** · **no simple_daily_sign mass gen** · **no live orders** · continuous paper **UNARMED** · GO **未宣言**

**GO definition (this residual):** **GO** = **pre-live-order final gate** (not operational GO declare).

---

## Success summary

| criterion | result |
|-----------|--------|
| Task A event_post PIT definition | **done** · [`w0816q_w82_event_post_pit_definition_20260817.md`](w0816q_w82_event_post_pit_definition_20260817.md) · class_signals **v5** · entry = first non-look-ahead session close · no invent DiscTime |
| Task B research↔paper gap + recompute | **done** · [`w0816q_w82_research_paper_gap_20260817.md`](w0816q_w82_research_paper_gap_20260817.md) · PIT mean net **+5.9bp** · t=**0.25** · Sharpe=**0.10** · **DEMOTE** `not_candidate` · paper limited still **−4.37%** shown honestly |
| Task C extra explore | **done** (notes in OTC proof) · multi_day **not revived** · **xs hold=10 optional KEEP** (t=**1.60** · Sharpe=**0.65** · +84.6bp) · fund discussion_only · **not Mass** |
| Task D OTC 2008+ residual | **done** · [`w0816q_w82_otc_2008plus_20260817.md`](w0816q_w82_otc_2008plus_20260817.md) · **4485 → 4499 (+14)** · span **2008-03-25…2026-08-17** · dataset **PARTIAL** · segs **7888** |
| Health + FRESH + residual | **done** · this close · GO gates update · residual TOP W82 |
| COMPLETE 22 health (local) | **pass** · COMPLETE **22** · PARTIAL **4** · fins **104** · empty **0** · OTC **4499** · bars_am **1** · segs **7888** |
| COMPLETE 22 health (remote) | **pass** · same floors after residual FRESH |
| FRESH | `projgen-c231a4a021ed4449960afe59a3c20016` · coverage_segments_untouched=1 · mass=NO-GO |
| Pytest (W82 key surface) | **57 green** · class_signals **16** · paper adapter **12** · standard_eval **17** · hyp_classes **12** |
| Standard eval wiring_only | **pass freezes** · checklist **v2** · `ready_declared=False` · mass=**NO-GO** · phase7=**OFF** · harness `research_candidate=False` · prefer liq+repo **True** |
| Mass/READY/operational GO/Phase7 | **NO-GO / 未宣言 / 未宣言 / OFF** |
| Production class_hyp candidates (default path) | **0** (event_post demoted after PIT; multi_day still demoted) |
| Optional explore candidate | **xs hold=10** `research_candidate=True` when `cross_section_hold_days=10` · default hold remains **5** (not candidate) · **≠ Mass/READY/ops GO** |
| Paper path | limited trial re-shown **−4.37%** · continuous **UNARMED** · fidelity gap irreducible under StrategySpec v2 |

**Success condition:** residual TOP = W82 landings · event_post demoted (PIT) · optional xs hold=10 · paper gap honest · OTC **4485→4499** · GO **未宣言** · COMPLETE 22 held · push past W81 tip `4143698`.

---

## Deliverables

| # | artifact | path / note |
|---|----------|-------------|
| A | event_post PIT definition + class_signals **v5** + class_hyp_eval **v5** | `class_signals.py` · `class_hyp_eval.py` · proof PIT |
| B | research↔paper gap + PIT recompute + limited paper re-trial | proof gap · logs under w82_event |
| C | extra explore (optional xs hold=10 KEEP) | notes in OTC proof · explore logs |
| D | OTC 2008+ residual FULL_OK | **4485→4499** · D1 publish · proof OTC · dataset PARTIAL |
| E | Health + FRESH + residual close | this file · GO gates · residual SoT |
| — | GO gates update | [`w0816q_w82_go_gates_20260817.md`](w0816q_w82_go_gates_20260817.md) |

---

## Research candidates remaining after merges (honest)

### Default multi-year path (`run_class_hyp_multi_year_eval` defaults)

| hyp / variant | mean net | t | Sharpe | win-rate | research_candidate | decision |
|---------------|---------:|--:|-------:|---------:|--------------------|----------|
| multi_day_hold 5d | +0.4bp | 0.03 | 0.01 | 0.50 | **False** | not_candidate |
| multi_day_hold **10d** | **+21.1bp** | **0.62** | **0.25** | 0.67 | **False** | **demote held** `discussion_only_noisy_stats` |
| **event_post** (PIT v5) | **+5.9bp** | **0.25** | **0.10** | 0.67 | **False** | **DEMOTE** `not_candidate_economic_net_not_meaningful` |
| macro_conditioned | −24.1bp | −3.16 | −1.29 | 0.00 | **False** | not_candidate |
| cross_section default hold=5 | −10.9bp | −0.44 | −0.18 | 0.50 | **False** | not_candidate |
| flow_demand | mixed | — | — | — | **False** | not_candidate |
| fundamentals_price | discussion | — | — | — | **False** | discussion_only |

**Default production research_candidates after W82: 0.**  
W81 event_post KEEP (**+53.0bp** · t=**2.83** · Sharpe=**1.15**) was **look-ahead contaminated** (same-day close for after-hours DiscTime). PIT-safe entry collapses residual to noise.

### Optional explore (Task C · not default-wired)

| variant | mean net | t | Sharpe | win-rate | research_candidate | note |
|---------|---------:|--:|-------:|---------:|--------------------|------|
| **cross_section sticky hold=10** | **+84.6bp** | **1.60** | **0.65** | **0.67** | **True** | KEEP research only · `cross_section_hold_days=10` param · **not Mass** |
| fund hold=10 | +47.5bp | 1.28 | 0.52 | 0.67 | **False** | discussion_only_stats_bar (t&lt;1.5) |
| multi_day hold=20 | +18.5bp | 0.20 | 0.08 | 0.83 | **False** | **not revived** |

Code default remains `cross_section_hold_days=5`. Optional KEEP is **evaluable** via param; it is **not** auto-promoted to default path or Mass/READY.

Logs: `.glm-logs/w0816q_w82_event/candidate_summary.json` · `explore_xs_hold10.json` · `task_c_candidate_summary.json`

---

## Smoke results (machine)

### D1 / local OTC COMPLETE snapshot (finalize)

| source | OTC COMPLETE | span | platform COMPLETE segs | notes |
|--------|-------------:|------|-----------------------:|-------|
| local (W82 pin) | **4499** | 2008-03-25…2026-08-17 | **7888** | +14 from W81 4485 |
| remote AFTER residual FRESH | **4499** | 2008-03-25…2026-08-17 | **7888** | health remote pass |

Logs: `.glm-logs/w0816q_w82_event/otc_after.json` · `otc_d1_after_complete.json` · `health_w82_*.log`

### COMPLETE 22 health

| source | all_checks_pass | COMPLETE | PARTIAL | fins | empty | OTC | bars_am | segs |
|--------|-----------------|----------|---------|------|-------|-----|---------|------|
| local SQLite | **true** | 22 | 4 | 104 | 0 | **4499** | 1 | **7888** |
| remote D1 | **true** | 22 | 4 | 104 | 0 | **4499** | 1 | **7888** |

Note: OTC **dataset** status remains **PARTIAL**. Platform COMPLETE datasets stay **22**.  
pre-2008 OTC is **not** a main claim (2008+ FULL_OK only).

Log: `.glm-logs/w0816q_w82_event/health_w82_residual.log` · `health_w82_postfresh.log`

### FRESH

| field | value |
|-------|-------|
| gen | `projgen-c231a4a021ed4449960afe59a3c20016` |
| now | `2026-08-16T22:01:05.870600+00:00` |
| coverage_segments_untouched | **1** |
| mass | **NO-GO** |

Log: `.glm-logs/w0816q_w82_event/reeval_freshness_residual.log`

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

Log: `.glm-logs/w0816q_w82_event/standard_eval_wiring.log`

### Pytest counts (green)

| suite | n |
|-------|--:|
| `tests/test_class_signals.py` | 16 (+ PIT entry test) |
| `tests/test_paper_candidate_adapter.py` | 12 |
| `tests/test_standard_research_eval.py` | 17 |
| `tests/test_hypothesis_classes.py` | 12 |
| **total** | **57** |

Log: `.glm-logs/w0816q_w82_event/pytest_w82_residual.log`

### Paper limited trial honesty (re-shown)

| step | result |
|------|--------|
| event_post single-shot (5d Draft) | **healthy** · post-cost **+1.38%** |
| event_post LIMITED (30d Paper) | **ok** · post-cost **−4.37%** · maxDD **−9.81%** · **rehearsal only · not edge claim** |
| continuous paper scheduler | **OFF** |
| live orders | **OFF** |

Fidelity note: StrategySpec v2 uses `disclosure_flag_fins` threshold proxy — not signed surprise sticky hold. Gap is **irreducible** under v2 schema. Limited-window PnL is **not** alpha evidence and is consistent with research demotion after PIT.

### OTC / platform numbers

| metric | W81 | W82 | Δ |
|--------|----:|----:|--:|
| OTC COMPLETE segs | 4485 | **4499** | +14 |
| OTC COMPLETE span start | 2008-03-25 | **2008-03-25** | held |
| OTC dataset status | PARTIAL | **PARTIAL** | held |
| platform COMPLETE segs | 7874 | **7888** | +14 |
| platform COMPLETE datasets | 22 | **22** | held |
| empty COMPLETE | 0 | **0** | held |
| pre-2008 densify | not run | **not run** | out of scope |

---

## Explicit non-declarations (held)

- **READY** — not declared  
- **Mass** — **NO-GO / OFF**  
- **Phase7** — **OFF**  
- **operational GO** — **未宣言**  
- **Dataset COMPLETE 23** — not invented  
- **OTC dataset COMPLETE** — not forced (segment COMPLETE 4499 only; dataset PARTIAL)  
- **empty COMPLETE** — not minted (0 held)  
- **research_candidate → Mass/READY/ops GO** — never auto-connects  
- **paper continuous / unlimited arm** — **False**  
- **live orders** — **forbidden** this residual  
- **S1–S5 un-reject** — not done  
- **simple_daily_sign mass generation** — **forbidden** (default OFF)  
- **OTC bulk densify** — not run (FULL_OK residual only)  
- **pre-2008 OTC as main claim** — **forbidden**  
- **limited paper PnL as edge / significance** — **not claimed**  
- **multi_day_hold 10d production candidate** — **still demoted** (noisy stats; not revived)  
- **event_post production candidate** — **demoted after PIT** (W81 KEEP look-ahead contaminated)  
- **mean-bp-only promotion** — **forbidden** (stats bar required)  
- **xs hold=10 default wire / Mass** — optional research KEEP only; default hold stays 5  

---

## Residual TOP (W82)

1. **event_post PIT-safe entry** — class_signals **v5** · DiscDate+DiscTime SoT · no invent · after-close/missing time → next session  
2. **event_post DEMOTED** — mean net **+5.9bp** · t=**0.25** · Sharpe=**0.10** · win-rate **0.67** · `not_candidate_economic_net_not_meaningful` · W81 KEEP look-ahead contaminated  
3. **Paper gap honest** — StrategySpec v2 proxy irreducible · limited trial still **−4.37%** post-cost · continuous **UNARMED**  
4. **Optional xs sticky hold=10 KEEP** — t=**1.60** · Sharpe=**0.65** · +84.6bp · research only · **not** default-wired · **not Mass**  
5. **multi_day_hold 10d not revived** — t=**0.62** · Sharpe=**0.25** · still `discussion_only_noisy_stats`  
6. **OTC 4485→4499 (+14)** — 2008-03-25…2026-08-17 · dataset still **PARTIAL** · segs **7888** · pre-2008 not claimed  
7. **Default production research_candidates: 0** · harness wiring still `research_candidate=False`  
8. **GO 未宣言** — pre-live-order residual only · Mass **NO-GO** · READY **未宣言** · operational GO **未宣言**  
9. **COMPLETE 22 held** · empty **0** · no invent 23 · costs v2 held · research entry linked · FRESH residual  

See also: [`w0816q_w82_go_gates_20260817.md`](w0816q_w82_go_gates_20260817.md)

---

## Prior tip / push

| item | value |
|------|-------|
| W81 tip (start) | `4143698` — docs pin after stats+paper+OTC close |
| W81 feature tip | `726d245` — stats bar + event_post only + paper trial + OTC 2595→4485 |
| W82 feature tip | `e7d73fb` — event_post PIT demote + paper gap + OTC 4485→4499 + FRESH close |
| This wave | commit + push on `main` past `4143698` |

---

## Related proofs

| doc | role |
|-----|------|
| A event_post PIT definition | [`w0816q_w82_event_post_pit_definition_20260817.md`](w0816q_w82_event_post_pit_definition_20260817.md) |
| B research↔paper gap | [`w0816q_w82_research_paper_gap_20260817.md`](w0816q_w82_research_paper_gap_20260817.md) |
| C+D OTC residual + explore | [`w0816q_w82_otc_2008plus_20260817.md`](w0816q_w82_otc_2008plus_20260817.md) |
| GO gates | [`w0816q_w82_go_gates_20260817.md`](w0816q_w82_go_gates_20260817.md) |
| Residual SoT | [`docs/phase62_residual_status.md`](../phase62_residual_status.md) |
| W81 close | [`w0816p_w81_stats_paper_otc_close_20260816.md`](w0816p_w81_stats_paper_otc_close_20260816.md) |

---

## Logs index

```text
.glm-logs/w0816q_w82_event/
  candidate_summary.json
  class_hyp_multi_year_bundle.json
  entry_split.json
  explore_xs_hold10.json
  task_c_candidate_summary.json
  paper_results.json / paper_limited_trial/
  otc_after.json / otc_return.json
  health_w82_residual.log / health_w82_postfresh.log
  reeval_freshness_residual.log
  standard_eval_wiring.log
  pytest_w82_residual.log
```
