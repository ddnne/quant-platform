# W87 / w0816v — residual FRESH close (mass strategy factory)

**Wave status:** **COMPLETE** — mass factory · N≥100 · batch auto-eval · screen · residual TOP updated · push  
**Wave:** W87 / `w0816v` · residual close 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Logs:** [`.glm-logs/w0816v_w87_mass/`](../../.glm-logs/w0816v_w87_mass/)  
**Proof:** [`w0816v_w87_mass_strategy_factory_20260817.md`](w0816v_w87_mass_strategy_factory_20260817.md)  
**Prior tip:** W86 `70507b1`  
**This feature tip:** `470971e`

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** |
| **Mass** (operational) | **NO-GO** |
| **Phase7** | **OFF** |
| operational GO | **未宣言 / deferred** |
| continuous paper | **UNARMED** |
| live orders | **OFF** |
| simple_daily_sign diversity | **forbidden** |
| S1–S5 un-reject | **forbidden** |
| look-ahead | **forbidden** |
| human main candidates this wave | **not selected** |

---

## Success condition (wave)

| condition | result |
|-----------|:------:|
| Mass pipeline started (factory + batch) | **yes** |
| N≥100 diverse strategies / run | **yes** · **100** |
| Multi-family anti-bias sampling | **yes** · 7 families |
| Batch auto eval + screen | **yes** · fail_rate 0 · ~8.8s |
| GO judgment deferred | **yes** |
| residual TOP updated | **yes** · live SoT [`docs/phase62_residual_status.md`](../phase62_residual_status.md) leads with W87 · this close |
| Commit + push past W86 tip `70507b1` | **yes** · feature `470971e` · residual SoT fix follow-up |

---

## Task landings

| task | result | proof / log |
|------|--------|-------------|
| A family diversity definition | **done** · 7 families · multi-axis · ratios · anti-bias 28% cap | factory proof |
| B mass generator | **done** · seed/N/ratios · stable IDs · gen-time reject | `mass_strategy_factory.py` |
| C batch auto experiment | **done** · post-cost · both signs · t/Sharpe · fail-one-continue | run logs |
| D auto screening | **done** · near-zero / both-sign / data · survivors by family | `screens.json` |
| E stability | **done** · re-run recipe · N≥100 · wall ~8.8s · paper UNARMED | SUMMARY.md |
| F residual TOP + proof + push | **done** · this close | this file |

---

## Run report (seed=870816, n=100, real mirrors)

| field | value |
|-------|------:|
| n_generated_accepted | **100** |
| n_ge_100 | **True** |
| n_families_used | **7** |
| anti_bias_ok | **True** |
| n_survivors | **79** |
| fail_rate | **0.0** |
| wall_time_sec | **~8.805** |
| continuous_paper | **UNARMED** |
| human_main_candidates_selected | **False** |
| mass_research | **NO-GO** |
| reject_reason_histogram | both_signs_near_zero_or_nonpositive **21** · near_zero_after_cost **7** |

### Family distribution (generated)

| family | n |
|--------|--:|
| multi_day_hold | 16 |
| event_post | 14 |
| cross_section_relative | 20 |
| macro_conditioned | 14 |
| fundamentals_price | 14 |
| flow_demand | 12 |
| vol_risk_adjusted | 10 |

### Survivor family distribution

| family | survivors |
|--------|----------:|
| multi_day_hold | 16 |
| event_post | 14 |
| cross_section_relative | 19 |
| flow_demand | 12 |
| vol_risk_adjusted | 9 |
| fundamentals_price | 8 |
| macro_conditioned | 1 |

Machine: `.glm-logs/w0816v_w87_mass/{factory_run,strategies,ranking,screens,results_compact,SUMMARY}.json|md`

---

## Residual TOP (after W87)

| # | residual | status |
|---|----------|--------|
| **R0** | **Mass strategy pipeline started** (factory generate + batch eval + screen) | **TOP · held** |
| R1 | Operational GO / Mass ON / READY declare | **deferred** · not this wave |
| R2 | Deeper class_hyp multi-year + short-cost mid re-eval of factory survivors | next research |
| R3 | Optional short paper sample top-k (continuous remains UNARMED) | next optional |
| R4 | Human main candidate selection from survivors | **not this wave** |
| R5 | W86 defaults (xs mom5/mom3 · fund mom10) + same-condition compare | held underneath |

**GO judgment: deferred.**  
Factory survivors ≠ production `research_candidate` ≠ READY ≠ Mass ≠ ops GO.

---

## Pytest

| surface | result |
|---------|--------|
| `tests/test_mass_strategy_factory.py` | green |
| `tests/test_hypothesis_classes.py` | green |
| `tests/test_sign_selection.py` | green |

Log: `.glm-logs/w0816v_w87_mass/pytest_factory.log`

---

## Re-run recipe (short)

```bash
.venv/bin/python scripts/run_mass_strategy_batch.py \
  --seed 870816 --n 100 \
  --out-dir .glm-logs/w0816v_w87_mass/
```

---

## Close statement

W87 residual TOP is **mass strategy pipeline started**.  
Generation factory + batch auto-experiment operational for research.  
Live residual SoT [`docs/phase62_residual_status.md`](../phase62_residual_status.md) **TOP leads with W87** (mass factory).  
**GO / Mass / READY / live remain closed.** continuous paper **UNARMED**.  
Human main candidates **not** selected. Feature tip `470971e` · residual SoT fix on main.
