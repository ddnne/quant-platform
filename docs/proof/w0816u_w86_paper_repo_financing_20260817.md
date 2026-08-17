# W86 / w0816u — Task B: connect daily repo financing into paper engine

**Wave status:** **Task B COMPLETE** (paper path wired · KEEP remeasure · tests · no invent) — closed with residual W86  
**Wave:** W86 / `w0816u` · 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Modules:**  
* `packages/research_runtime/core/costs.py` — `ShortFinancingModel` + **`LeverageFinancingModel`**  
* `packages/research_runtime/core/repo_rates.py` — **PIT load helper** for paper (tip visibility default)  
* `packages/research_runtime/core/engine.py` — daily short + leverage accrual (`0.6.2`)  
* `packages/research_runtime/strategies/paper/{types,runner}.py` — `PaperRunConfig` + auto-load (`0.7.0`)  
* `packages/product/research/cost_models.py` — wave tip pin  
**Logs:** [`.glm-logs/w0816u_w86_go_pre/`](../../.glm-logs/w0816u_w86_go_pre/)  
**Prior:**  
* [`w0816t_w85_short_cost_repo_spread_20260817.md`](w0816t_w85_short_cost_repo_spread_20260817.md) — short cost model + engine SF  
* [`w0816t_w85_multi_window_paper_20260817.md`](w0816t_w85_multi_window_paper_20260817.md) — KEEP multi-window (tx-only residual)

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
| short-spread on leverage leg | **forbidden** (no double-count) |
| mean-bp-only promotion | **forbidden** |
| commit / push | residual W86 |

---

## Problem (W85 residual)

W85 multi-window paper seeded `jsda_repo_rates` into the paper DB for **disclosure**, but the paper engine path still ran:

```text
fixed one-way CostModel only
short_financing = null
```

W85 short-cost work added `ShortFinancingModel` + `PaperRunConfig` knobs, but multi-window KEEP runs never enabled them / never auto-loaded the daily series.

---

## Task B — what was wired

### 1. Daily repo series → paper path

| piece | behaviour |
|-------|-----------|
| `PaperRunConfig.short_financing_enabled` | still **default False** (legacy numerics) |
| `short_financing_sensitivity` | default **`mid`** (50 bp spread) |
| `short_financing_auto_load_repo` | default **True** when enabled |
| `load_repo_rates_by_date_for_paper` | core helper via `pit.get_jsda_repo_rates` (strategies never import `pit`) |
| tenor preference | `overnight/翌日物/T+0` → T+1 → `隔日物` → first |
| visibility default | **`tip`** — research paper seeds often stamp `available_at` at extract time; tip load admits date-matched rows **without inventing** missing dates. Optional `visibility="period_end"` for strict PIT |

### 2. Short + leverage financing (no double-count)

| book | formula | spread |
|------|---------|--------|
| **Short** | `daily = \|short_mv\| × (repo_pct/100 + spread_bp/10000) / 245` | mid 50 (L/M/H) |
| **Leverage** | `daily = max(gross_nv − equity, 0) × (repo_pct/100) / 245` | **none** (repo only) |

CS L-S books with long_frac=short_frac=0.3 have gross ≈ 0.6 → leverage cost ≈ 0 (any residual is mark/cash drift, disclosed).

### 3. Gap policy

With series present, missing `as_of_date` → charge **0** that day + gap count. **No ffill / invent.**

---

## Remeasure — KEEP / default candidates

**DB:** `.glm-logs/w0816t_w85_paper/paper_db/w85_multi_window_paper.sqlite` (W85 multi-window seed)  
**Cost:** 10 bp one-way (liquidity high / mult=1.0)  
**Financing after:** short mid + auto-load repo + leverage on  
**Before:** W85 multi-window paper (`short_financing` off)  
**Windows:** full 10-window W85 calendar (incl. limited continuity)

### Aggregate before / after (mean post-cost % over 10 windows)

| candidate | role | before mean % | **after mean %** | **Δ mean (bp)** | mean SF cost ¥ | mean lev ¥ | pos/neg |
|-----------|------|--------------:|-----------------:|----------------:|---------------:|-----------:|:-------:|
| **xs_hold10_mom5** | KEEP default | −0.4925 | **−0.5515** | **−5.90** | 583.3 | 0.99 | 5/5 |
| **fund_hold10_mom10** | KEEP default | −1.7683 | **−1.8280** | **−5.97** | 600.0 | 0.20 | 3/7 |
| **xs_hold10_mom3** | PROMOTE→default | +0.6635 | **+0.6036** | **−5.99** | 589.8 | 0.40 | 6/4 |

All 30 runs: `rate_source=repo_plus_borrow_spread`, `has_repo_series=True`, `n_short_financing_gaps=0`.

### Limited continuity window (2023-08-31 … 2023-10-13)

Repo overnight ≈ −0.15% → short annual ≈ mid 50 − 15 ≈ **35 bp** (vs W85 fixed-placeholder 50 bp).

| candidate | before post % | **after post %** | **Δ bp** | SF cost ¥ |
|-----------|--------------:|-----------------:|---------:|----------:|
| xs_hold10_mom5 | +1.5416 | **+1.5205** | **−2.12** | 209.9 |
| fund_hold10_mom10 | +4.7197 | **+4.6987** | **−2.10** | 211.7 |
| xs_hold10_mom3 | +2.0107 | **+1.9895** | **−2.12** | 209.8 |

W85 fixed-mid SF trial on same xs window was +1.5121% (Δ −2.96 bp vs tx-only). **Repo-linked mid is slightly cheaper** here because Tokyo repo was **negative** in late 2023.

### xs_hold10_mom5 multi-window detail

| window | before % | after % | Δ bp | SF ¥ | note |
|--------|---------:|--------:|-----:|-----:|------|
| w2015_spring | +1.01 | +0.94 | −6.9 | 678 | mid-cycle |
| w2015_summer | −3.45 | −3.52 | −6.9 | 691 | China-scare |
| w2017_q4 | +7.65 | +7.60 | −5.4 | 522 | late bull |
| w2019_spring | +7.64 | +7.59 | −5.1 | 497 | rebound |
| w2019_summer | −6.50 | −6.55 | −4.9 | 506 | trade-war |
| w2021_spring | −1.58 | −1.63 | −5.1 | 515 | reopening |
| w2021_summer | +1.82 | +1.77 | −5.3 | 518 | mixed |
| w2023_spring | −11.74 | −11.78 | −4.3 | 445 | beta rally L-S hurt |
| w2023_h2_limited | +1.54 | +1.52 | −2.1 | 210 | continuity |
| **w2025_q4** | −1.32 | **−1.45** | **−12.9** | **1251** | tip era · repo ~1% |

2025 Q4 shows the **repo-linked** difference clearly (higher overnight rates → larger short financing drag).

### Verdict impact

| candidate | paper multi-window after financing | change vs W85 KEEP/PROMOTE |
|-----------|------------------------------------|----------------------------|
| xs mom5 | still 5/5 pos/neg · mean mildly more negative | **keep_default** held (policy: no auto-reject for financing drag alone) |
| fund mom10 | still 3/7 · mean slightly worse | **keep_default** held |
| xs mom3 | still 6/4 · mean still positive | **promote_default** research+paper stance held |

Not alpha / significance / edge claim. Continuous **UNARMED**. Live **OFF**.

---

## Unit / integration tests

```text
.venv/bin/python -m pytest \
  tests/test_paper_repo_financing_w86.py \
  tests/test_cost_models_short_cost_w85.py \
  tests/test_cost_models_repo_linked.py \
  tests/test_cost_models_liquidity_linked.py \
  tests/test_core_engine.py \
  tests/test_paper_pipeline.py \
  tests/test_paper_store.py \
  tests/test_core_data_boundary.py \
  tests/test_strategies_static_boundaries.py -q
# → 110 passed
```

Locks in `tests/test_paper_repo_financing_w86.py`:

* mid default + repo series when present  
* leverage = repo only (no short-spread double-count)  
* gap day charge 0  
* tip vs period_end visibility  
* auto-load via paper runner  
* financing-off legacy path unchanged  

Log: `.glm-logs/w0816u_w86_go_pre/pytest_key.log`

---

## Artifacts

| path | role |
|------|------|
| `.glm-logs/w0816u_w86_go_pre/run_w86_paper_repo_financing.py` | remeasure entry |
| `.glm-logs/w0816u_w86_go_pre/run_all.log` | full run log |
| `.glm-logs/w0816u_w86_go_pre/paper_meta.json` | config pin |
| `.glm-logs/w0816u_w86_go_pre/paper_results_after.json` | 30 after-runs |
| `.glm-logs/w0816u_w86_go_pre/paper_comparison.json` | before/after table |
| `.glm-logs/w0816u_w86_go_pre/paper_summaries.json` | aggregate |
| `.glm-logs/w0816u_w86_go_pre/paper_*.json` | per window compact |
| `.glm-logs/w0816u_w86_go_pre/paper_limited_window_detail.json` | limited window |
| `.glm-logs/w0816u_w86_go_pre/paper_runs/` | JsonPaperStore outputs |

---

## Design notes / gaps disclosed

1. **Tip visibility for financing load** — W85 paper DB stamps `available_at=2026-08-11` on all repo rows (extract time). Strict period-end PIT would return 0 rows for every historical window and force fixed-placeholder. Default tip load is **date-matched only** (no invent of missing dates). Documented in `repo_financing_load` metadata (`visibility=tip`).
2. **Leverage residual** — equal-weight CS L-S is not cash-borrow levered; mean lev cost ≪ short cost. Non-zero micro amounts come from mark/cash gross drift, not intentional leverage.
3. **Enablement remains opt-in** — `short_financing_enabled=False` by default so legacy paper numerics and long-only paths stay bit-stable until a trial opts in.
4. **Not operational GO** — research/paper cost honesty only.

---

## Versions

| component | version |
|-----------|---------|
| `CORE_ENGINE_VERSION` | **0.6.2** |
| `PAPER_RUNNER_VERSION` | **0.7.0** |
| `COST_MODELS_WAVE` | **W86 / w0816u** |
| `COST_MODELS_PROOF` | this file |

---

## Exit criteria

| criterion | status |
|-----------|:------:|
| Daily repo series wired into paper path | **yes** |
| Defaults mid short spread + repo when series present | **yes** |
| No double-count with short spread on leverage | **yes** |
| Gap disclose / no invent | **yes** |
| KEEP/default remeasure multi-window | **yes** (3 × 10) |
| Unit/integration tests | **yes** (110) |
| Proof + logs | **yes** |
| Continuous UNARMED / live OFF | **held** |
| No invent / no Mass/READY/GO | **held** |
