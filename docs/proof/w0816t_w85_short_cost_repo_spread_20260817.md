# W85 / w0816t — Tasks C+D: short cost = f(repo[t]) + fixed spread · light explore

**Wave status:** **Tasks C+D COMPLETE** (short cost wired · remeasure · paper SF · flow try · OTC tip) — **no commit/push**  
**Wave:** W85 / `w0816t` · 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Module:** `packages/product/research/cost_models.py` · `packages/research_runtime/core/costs.py` · `engine.py` · `class_hyp_eval.py`  
**Logs:** [`.glm-logs/w0816t_w85_short_cost/`](../../.glm-logs/w0816t_w85_short_cost/)  
**Prior cost proofs:**  
* [`w0816m_w78_repo_linked_cost_model_20260816.md`](w0816m_w78_repo_linked_cost_model_20260816.md)  
* [`w0816n_w79_liquidity_linked_cost_20260816.md`](w0816n_w79_liquidity_linked_cost_20260816.md)  
**Prior path:** W84 realign (xs hold10 mom5 · fund hold10 mom10 · paper aligned L-S residual “no borrow model”)

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| operational GO | **closed** |
| continuous paper | **UNARMED** |
| live orders | **OFF** |
| repo gap fill (ffill / invent) | **forbidden** |
| mean-bp-only promotion | **forbidden** |
| event_post look-ahead revival | **forbidden** |
| multi_day force-revive | **forbidden** |
| simple_daily_sign | **not used** |
| S1–S5 un-reject | **forbidden** |
| OTC bulk archive re-scan | **not run** (tip only) |
| commit / push | **not done** |

---

## Task C — short cost = f(repo_rate[t]) + fixed spread bp

### Approved approximation (assumptions)

```text
short_annual_bp[t] = repo_pct[t] * 100 + spread_bp
short_borrow_daily[t] = (short_annual_bp[t] / 10000) / trading_days * short_fraction
short_borrow_hold     = short_borrow_daily * hold_days   # multi-day L-S remeasure
net_L-S               = gross - amortized_one_way - short_borrow_hold
```

| sensitivity | spread_bp | note |
|-------------|----------:|------|
| **low** | **25** | liquid large-cap research band |
| **mid** (default primary) | **50** | matches prior fixed 50bp when repo≈0 |
| **high** | **150** | harder-to-borrow research band |

| assumption | held |
|------------|------|
| Prefer date-matched `jsda_tokyo_repo_rates` | **yes** |
| `short_fraction` for equal L-S books | **0.5** |
| Multi-day: continuous borrow over sticky hold (`daily * hold_days`) | **yes** (approved approx) |
| Repo gaps | **disclose only** — cost not invent-filled; tx-only net retained + flag |
| Not a broker borrow quote | **yes** |
| Research-only · not operational GO | **yes** |
| Paper DB missing repo rows | fixed **spread-only** placeholder disclosed (`rate_source=fixed_bp_placeholder`) |

### Delivered APIs

#### Research (`research.cost_models`)

| symbol | role |
|--------|------|
| `SHORT_BORROW_SPREAD_{LOW,MID,HIGH}_BP` | 25 / 50 / 150 |
| `SHORT_BORROW_SPREAD_SENSITIVITY` | band map |
| `short_borrow_daily_cost_from_repo` | daily f(repo+spread, frac) |
| `short_borrow_hold_cost_from_repo` | **W85** hold = daily × hold_days |
| `short_cost_sensitivity_bands` | L/M/H table for one repo obs |
| `resolve_short_borrow_spread_bp` | sensitivity → bp |
| `research_net_with_short_hold_cost` | gross − am_tx − short_hold |
| `remeasure_period_rows_with_short_cost` | period-row remeasure + L/M/H |
| `build_leverage_short_cost_assumption` | checklist block (repo-aware) |

#### Paper / core (`core.costs` · `core.engine` · `strategies.paper`)

| symbol | role |
|--------|------|
| `ShortFinancingModel` | daily cash charge on short MV |
| `short_financing(...)` | factory (sensitivity / series / fallback) |
| `run_backtest(..., short_financing=)` | engine daily accrual |
| `PaperRunConfig.short_financing_enabled` | default **False** (legacy numerics) |
| `PaperRunConfig.short_financing_sensitivity` | low\|mid\|high |
| `PaperRunConfig.short_financing_repo_rates` | date→repo_pct (optional) |
| `PaperRunConfig.short_financing_fallback_repo_annual_bp` | when no series |

Paper formula (same family):

```text
daily_cost = |short_notional| * (repo_pct/100 + spread_bp/10000) / trading_days
```

Gap day with series present → charge **0** that day (no invent) + gap count in metadata.

### Wiring paths

| path | change |
|------|--------|
| `class_hyp_eval.run_class_hyp_multi_year_eval` | `apply_short_cost_remeasure=True` (default) on **macro / CS / fund L-S**; primary net = **mid**; L/M/H kept under `short_cost_sensitivity` |
| cost assumptions for L-S | `build_leverage_short_cost_assumption(..., repo_rate_series=..., short_borrow_sensitivity=mid)` |
| paper runner | optional short financing via `PaperRunConfig` → `run_backtest` |
| unit tests | `tests/test_cost_models_short_cost_w85.py` |

### Research remeasure numbers (W80/W81 windows · 30 large-cap · liq 10bp)

#### Primary mid vs tx-only (default candidates)

| block | tx-only mean | **short mid mean** | t | Sharpe | win | hard RC |
|-------|-------------:|-------------------:|--:|-------:|----:|:-------:|
| **cross_section_hold_10** mom=5 | **+84.6bp** | **+83.4bp** | 1.59 | 0.65 | 0.67 | **True** |
| **fundamentals_hold_10** mom=10 | **+45.9bp** | **+44.8bp** | 1.78 | 0.73 | 0.67 | **True** |

Short hold cost (mid, hold=10, frac=0.5) ≈ **1.17bp** mean — does **not** flip hard RC.

#### Sensitivity table (mean net bp · period nets)

| block | low (25) | **mid (50)** | high (150) | mean short_hold mid |
|-------|---------:|-------------:|-----------:|--------------------:|
| cross_section_hold_10 | +83.9 | **+83.4** | +81.4 | 1.17bp |
| fundamentals_hold_10 | +45.3 | **+44.8** | +42.7 | 1.17bp |
| fundamentals hold=20 primary | +69.6 | +68.6 | +64.5 | 2.33bp |
| cross_section hold=5 | −11.2 | −11.4 | −12.5 | 0.58bp |
| macro_conditioned | −24.4 | −24.7 | −25.7 | 0.58bp |

Logs: `remeasure_default_path_short_cost.json` · `remeasure_tx_only.json` · `results_table.json`.

### Paper limited trial (aligned CS L-S · short financing)

DB: W83 offline seed · window **2023-08-31 … 2023-10-13** (30d · same as W84 limited) · cost 10bp · continuous **UNARMED**.  
Paper DB `jsda_repo_rates` empty → **fixed mid 50bp** placeholder (disclosed).

| trial | post-cost | maxDD | trades | short_fin cost |
|-------|----------:|------:|-------:|---------------:|
| W84 aligned (no SF) | **+1.5416%** | −1.23% | 60 | 0 |
| **W85 + short fin mid** | **+1.5121%** | −1.23% | 60 | **¥292.4** (~29 days) |
| **Δ** | **−2.96bp** | — | — | — |

Not alpha / significance / edge claim. Live OFF.

Live-repo API smoke (ingestion.sqlite · sample 2026-08-14 repo≈1.0%):

| sens | spread | daily cost on ¥1e6 short | daily bp on book |
|------|-------:|-------------------------:|-----------------:|
| low | 25 | ¥51.02 | 0.51bp |
| mid | 50 | ¥61.22 | 0.61bp |
| high | 150 | ¥102.04 | 1.02bp |

---

## Task D — light explore

### Policy (held)

| rule | held |
|------|------|
| PIT-safe only; no look-ahead event revival | **yes** |
| No multi_day force-revive | **yes** |
| No simple_daily_sign | **yes** |
| Stats always shown; no mean-bp-only | **yes** |
| OTC tip-wait only | **yes** |

### Flow near-miss (cheap try)

| variant | mean | t | Sharpe | win | occ | stats | hard RC | holistic |
|---------|-----:|--:|-------:|----:|:---:|:-----:|:------:|----------|
| hold=5 hard short_confirm (W84) | +123.0bp | 1.54 | 0.63 | 0.67 | ✗ | ✓ | False | **conditional_near_miss** (held) |
| hold=5 **soft** (gap+conflict→margin) | +117.9bp | 0.76 | 0.31 | 0.33 | ✓ | ✗ | False | **reject** — collapses to bare |
| hold=5 bare (no confirm) | +117.9bp | 0.76 | 0.31 | 0.33 | ✓ | ✗ | False | **reject** |

**Conclusion:** Soft confirm that keeps margin on short conflict recovers occurrence but **destroys** the stats lift from hard confirm. No free improve. **Hard short_confirm remains discussion-only near-miss** (not default-wired). API `short_confirm_mode=off|hard|soft` kept for research.

### OTC tip-wait

| metric | value |
|--------|------:|
| dataset | `jsda_otc_bond_reference_prices` |
| dataset status | **PARTIAL** |
| COMPLETE segments | **4499** |
| PARTIAL segments | 4282 |
| span | **2008-03-25 … 2026-08-17** |
| W83/W84 pin | 4499 |
| **4499 → ?** | **4499 → 4499 (Δ0)** |
| bulk archive re-scan | **not run** |

Log: `.glm-logs/w0816t_w85_short_cost/otc_tip_full_ok.json`

---

## Unit tests

```text
.venv/bin/python -m pytest \
  tests/test_cost_models_short_cost_w85.py \
  tests/test_cost_models_repo_linked.py \
  tests/test_cost_models_liquidity_linked.py \
  tests/test_core_engine.py -q
# all passed
```

---

## Log index

| file | content |
|------|---------|
| `.glm-logs/w0816t_w85_short_cost/run_w85_short_cost_explore.py` | remeasure + explore runner |
| `.glm-logs/w0816t_w85_short_cost/run_all.log` | stdout (partial; OTC fixed post-run) |
| `.glm-logs/w0816t_w85_short_cost/remeasure_default_path_short_cost.json` | L-S remeasure mid + L/M/H |
| `.glm-logs/w0816t_w85_short_cost/remeasure_tx_only.json` | tx-only baseline |
| `.glm-logs/w0816t_w85_short_cost/results_table.json` | compact table |
| `.glm-logs/w0816t_w85_short_cost/explore_flow_soft.json` | flow soft vs bare |
| `.glm-logs/w0816t_w85_short_cost/paper_short_financing.json` | API + trial |
| `.glm-logs/w0816t_w85_short_cost/paper_short_financing_trial.json` | limited paper SF |
| `.glm-logs/w0816t_w85_short_cost/otc_tip_full_ok.json` | 4499→4499 |
| `tests/test_cost_models_short_cost_w85.py` | unit tests |

---

## Explicit non-declarations (held)

- **READY / Mass / Phase7 / operational GO / live orders** — closed  
- **continuous paper arm** — **False**  
- **short cost is research approximation** — not broker HTB quote  
- **paper SF with empty repo table** — fixed spread placeholder only  
- **flow soft** — not a production candidate  
- **default path** still xs hold10 mom5 · fund hold10 mom10 (still hard RC after short mid)  
- **commit / push** — not this task  
