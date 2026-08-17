# W87 / w0816v — mass strategy generation factory + batch auto-experiment

**Wave status:** **COMPLETE** — factory lands · N≥100 generated · multi-family diversity · batch eval · auto screen · residual TOP = mass pipeline started · GO deferred · push  
**Wave:** W87 / `w0816v` · 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Logs:** [`.glm-logs/w0816v_w87_mass/`](../../.glm-logs/w0816v_w87_mass/)  
**Prior tip:** W86 `70507b1` (sign flip · paper repo financing · same-condition compare)

---

## Goal (PRIMARY) — held

Stable factory that generates **100+ diverse strategies per run** and batch-evaluates them automatically.

| goal | held |
|------|:----:|
| N≥100 generated per run | **yes** · **100** accepted |
| Multi-family diversity (not polish 3 candidates) | **yes** · **7** families |
| Batch auto-experiment (post-cost · both signs · t/Sharpe · activation) | **yes** |
| Machine-readable ranking / reject reasons / family dist | **yes** |
| Anti-bias (no single-family micro-grid flood) | **yes** · max share ≤28% |
| **Not** operational Mass / READY / GO / live | **yes** · freezes held |
| **Not** simple_daily_sign as diversity | **yes** |
| **Not** S1–S5 un-reject | **yes** |
| continuous paper UNARMED | **yes** |
| Human main candidates **not** selected this wave | **yes** |

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
| simple_daily_sign as diversity | **forbidden** |
| S1–S5 un-reject | **forbidden** |
| look-ahead | **gen-time reject** |
| mean-bp-only production promote | **forbidden** |
| human main candidates this wave | **not selected** |

**Factory “mass”** = bulk research generation + batch eval only.  
It does **not** call `agents.mass_research` / mint READY / arm live.

---

## A. Family diversity definition

| family_id | direction | param axes (multi, not mom-only) |
|-----------|-----------|----------------------------------|
| `multi_day_hold` | sticky multi-day momentum hold | hold_days · rebalance_mode |
| `event_post` | post-disclosure PIT hold | post_hold_days · entry_mode (lookahead rejected) |
| `cross_section_relative` | rank L-S sticky | hold_days · momentum_n · long_frac · short_frac |
| `macro_conditioned` | repo regime × momentum | mode · momentum_n · hold_days · high/low thresholds |
| `fundamentals_price` | PIT value × price | hold_days · momentum_n · mode |
| `flow_demand` | multi-day margin flow (not S4) | hold_days · short_confirm_mode |
| `vol_risk_adjusted` | mom gated by \|mom\|/vol | hold_days · vol_n · vol_threshold |

### Sampling rules (anti-bias)

1. Seed + N + family **ratios** → integer allocation (largest remainder + cap).  
2. **max_family_share = 0.28** — no family floods the batch.  
3. Within family: multi-axis param **slots shuffled by seed** (not sequential mom 3/4/5… microgrid as the 100).  
4. `simple_daily_sign` **excluded** from factory families.  
5. Quality filter at **eval** stage (not gen). Gen rejects only validity / PIT / datasets.

Default ratios (sum=1):

| family | ratio |
|--------|------:|
| multi_day_hold | 0.16 |
| event_post | 0.14 |
| cross_section_relative | 0.20 |
| macro_conditioned | 0.14 |
| fundamentals_price | 0.14 |
| flow_demand | 0.12 |
| vol_risk_adjusted | 0.10 |

Documented in code: `family_definitions_document()` · this proof.

---

## B. Mass generator

| item | path / behavior |
|------|-----------------|
| Module | [`packages/product/research/mass_strategy_factory.py`](../../packages/product/research/mass_strategy_factory.py) |
| CLI | [`scripts/run_mass_strategy_batch.py`](../../scripts/run_mass_strategy_batch.py) |
| Config | `MassFactoryConfig(seed, n, family_ratios, …)` |
| Stable IDs | `msf_{seed:08x}_{index:04d}_{fam}_{sha12}` — reproducible from seed+params+index |
| Gen-time reject | simple_daily_sign · look-ahead entry · missing datasets · invalid params · S1–S5 |
| Target | N≥100 accepted when datasets available |

### Observed generation (seed=870816, n=100)

| metric | value |
|--------|------:|
| n_generated_accepted | **100** |
| n_ge_100 | **True** |
| n_families_used | **7** |
| anti_bias_ok | **True** |
| multi_day_hold | 16 |
| event_post | 14 |
| cross_section_relative | 20 |
| macro_conditioned | 14 |
| fundamentals_price | 14 |
| flow_demand | 12 |
| vol_risk_adjusted | 10 |

Machine: [`.glm-logs/w0816v_w87_mass/strategies.json`](../../.glm-logs/w0816v_w87_mass/strategies.json)

---

## C. Batch auto-experiment

| step | held |
|------|:----:|
| Common evaluator (class_hyp pure bars + costs) | yes |
| Post-cost returns | yes |
| Both signs via `sign_selection` | yes |
| t / Sharpe / activation | yes |
| Fail-one-continue | yes · fail_rate **0.0** |
| Optional short paper subset only | paper_sample_k=0 · continuous **UNARMED** |
| Machine ranking + reject reasons + family dist | yes |

### Eval tradeoffs (documented)

Lite multi-year for wall-time at N≥100:

* **Q4 windows** (6 periods) preferred over full-year  
* **max_codes=20** · **max_days=80**  
* Survivors are **factory screen only** — need deeper `class_hyp` re-eval before any production `research_candidate` promotion  
* Not production SoT; not human main candidates

### Observed batch (real mirrors + sqlite)

| metric | value |
|--------|------:|
| n_strategies_evaluated | **100** |
| fail_rate | **0.0** |
| wall_time_sec | **~8.8** |
| n_survivors | **79** |
| n_screen_rejected | **21** |

Reject reason histogram:

| reason | count |
|--------|------:|
| both_signs_near_zero_or_nonpositive | 21 |
| near_zero_after_cost | 7 |

(Some rows carry both reasons.)

Survivor family distribution:

| family | survivors |
|--------|----------:|
| multi_day_hold | 16 |
| event_post | 14 |
| cross_section_relative | 19 |
| flow_demand | 12 |
| vol_risk_adjusted | 9 |
| fundamentals_price | 8 |
| macro_conditioned | 1 |

---

## D. Screening (auto)

Auto-reject:

* near-zero after cost  
* both signs fail non-zero / non-positive  
* data missing / no ok periods  
* post-cost collapse  
* eval error (when no ok periods)  
* low activation (soft floor)

**Survivors summarized by family (top few)** — see `family_top_survivors` in screens JSON.  
**Do NOT pick human main candidates this wave** — `human_main_candidates_selected=False`.  
Existing W86 defaults may be re-scored as part of factory later; **not the goal** of this wave.

### Research ranking top 5 (not human mains · lite eval only)

| rank | family | mean_net (approx bp) | t | chosen_sign |
|-----:|--------|---------------------:|--:|:-----------:|
| 1 | cross_section_relative | ~208 | 3.42 | +1 |
| 2 | cross_section_relative | ~35 | 2.53 | −1 |
| 3 | cross_section_relative | ~85 | 2.07 | −1 |
| 4 | vol_risk_adjusted | ~34 | 1.94 | −1 |
| 5 | cross_section_relative | ~31 | 1.81 | −1 |

IDs in [`.glm-logs/w0816v_w87_mass/ranking.json`](../../.glm-logs/w0816v_w87_mass/ranking.json).  
**Honesty:** lite Q4+subsample ranking ≠ W81 production stats bar. Deeper multi-year full-code re-eval required before KEEP/PROMOTE language.

---

## E. Stability

### Short re-run recipe

```bash
# from repo root (project venv)
.venv/bin/python scripts/run_mass_strategy_batch.py \
  --seed 870816 --n 100 \
  --out-dir .glm-logs/w0816v_w87_mass/

# synthetic smoke (no mirrors)
.venv/bin/python scripts/run_mass_strategy_batch.py \
  --synthetic --n 100 --out-dir /tmp/msf_syn
```

| report field | value |
|--------------|------:|
| fail_rate | **0.0** |
| wall_time_sec | **~8.8** |
| N≥100 achieved | **yes** |
| continuous paper | **UNARMED** |

Tests: `tests/test_mass_strategy_factory.py` — diversity · ID stability · gen-time reject · fail-one-continue · freezes.

---

## F. Implementation landings

| item | path |
|------|------|
| Factory core | `packages/product/research/mass_strategy_factory.py` |
| Public exports | `packages/product/research/__init__.py` |
| CLI | `scripts/run_mass_strategy_batch.py` |
| Tests | `tests/test_mass_strategy_factory.py` |
| Run logs | `.glm-logs/w0816v_w87_mass/` |
| This proof | `docs/proof/w0816v_w87_mass_strategy_factory_20260817.md` |
| Residual close | `docs/proof/w0816v_w87_residual_close_20260817.md` |

Reused assets (not reimplemented):

* `hypothesis_classes` · `class_signals` · `class_hyp_eval`  
* `cost_models` · `sign_selection` · `stats_metrics`  
* checklist v2 remains separate (no auto research_candidate from factory survivors)

---

## Residual TOP after W87

| priority | residual |
|----------|----------|
| **TOP** | **Mass strategy pipeline started** (factory + batch). Operational GO / Mass / READY **deferred**. |
| next | Deeper class_hyp re-eval on factory survivors (full multi-year · short-cost mid · production bar) |
| next | Optional short paper sample on top-k (still continuous UNARMED) |
| not this wave | Human main candidate pick · operational GO · live · Mass ON |

---

## Forbidden checklist (held)

| forbidden | held |
|-----------|:----:|
| look-ahead | gen-time reject |
| simple_daily_sign mass as diversity | excluded |
| S1–S5 un-reject | freezes |
| Mass/READY/ops GO/live declare | freezes |
| mom grid only as the 100 | multi-family multi-axis |
| Finish without push | residual close + push |

---

## Close

W87 lands a **stable research mass factory**: seed-reproducible N≥100 multi-family generation, batch post-cost / both-sign eval, auto screen, machine-readable ranking.  
**GO judgment deferred.** continuous paper **UNARMED**. No human main candidates selected.
