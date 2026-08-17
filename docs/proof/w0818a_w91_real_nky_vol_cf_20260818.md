# W91 / w0818a — Real COMPLETE-backed CF mass-eval + Nikkei vol logics

**Wave status:** **COMPLETE** — real multi-year CF path (`r2_panels`) executed · Nikkei/index vol regime logics landed · wide local real eval · 3 defaults frozen · residual TOP  
**Wave:** W91 / `w0818a` · 2026-08-18  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Logs:** [`.glm-logs/w0818a_w91_real_vol/`](../../.glm-logs/w0818a_w91_real_vol/)  
**Prior tip:** W90 `6264265` / residual pin `dbeaf6d`

---

## Goal (PRIMARY) — held

| goal | held |
|------|:----:|
| CF mass-eval quality toward **real COMPLETE-22 data** (not synthetic-as-final) | **yes** · mode **`r2_panels`** |
| Multi-year / multi-period windows (2015–2025) | **yes** · 6 periods |
| Nikkei average volatility logics (abs · term levels · ratio) | **yes** · 3 templates |
| Quality over hyp count; no grid mass | **yes** |
| Freeze 3 defaults; no GO/Mass/READY/live | **yes** |
| residual TOP=W91 · proofs · git push origin main | **yes** |

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
| **3 default-path retune** | **forbidden** · pins held |
| near-group early merge | **forbidden** |
| human main candidates this wave | **not selected** |
| Dataset COMPLETE 23 invent | **forbidden** |

### Frozen default path (not retuned)

| representative_id | pins | stance |
|-------------------|------|--------|
| `cross_section_hold_10` | hold=**10** · mom=**5** | KEEP |
| `cross_section_hold_10_mom3` | hold=**10** · mom=**3** | PROMOTE |
| `fundamentals_hold_10` | hold=**10** · mom=**10** · value_momentum_agree | KEEP |

---

## A. CF real-data path (PRIMARY)

| item | value |
|------|-------|
| **Status** | **executed on CF with real staged panels** |
| **Worker** | `quant-platform-research-mass-eval` v2 |
| **URL** | `https://quant-platform-research-mass-eval.taku-haga.workers.dev` |
| **Endpoint** | `POST /v1/mass-eval` |
| **job_id** | **`w91-real-20260817T222940Z`** |
| **mode** | **`r2_panels`** (NOT synthetic) |
| **n_logics** | **25** |
| **n_periods** | **6** |
| **n_survivors (CF)** | **6** |
| **stage n_ok** | **6 / 6** |
| **R2 bucket** | `quant-structured` |
| **R2 prefix** | `research/mass_eval/job=w91-real-20260817T222940Z/` |
| **panels prefix** | `research/mass_eval/job=w91-real-20260817T222940Z/panels/` |
| **Driver** | `scripts/run_w91_real_cf_mass_eval.py` · `research.cf_mass_eval_job` v2 |
| **Factory** | `mass-strategy-factory/v2.3` |

### Datasets used (COMPLETE-22 held)

**Primary bars for CS book:** `equities_bars_daily` (local COMPLETE-backed R2 mirrors W63 Q4 + W64 full, staged to quant-structured).

**Index vol proxy:** `indices_bars_daily_topix` (ndjson multi-year mirror) as **TOPIX realized-vol proxy** for Nikkei average vol regime. Cash Nikkei is **not** in `indices_bars_daily`; NK225F front from `derivatives_bars_daily_futures` is preferred when available (sqlite path optional / slow). NKVIF implied **not required** for term path this wave.

**Also in COMPLETE-22 inventory (not all loaded per panel):** markets_calendar, fins_*, jsda_tokyo_repo_rates, markets_margin_*, markets_short_*, indices_bars_daily, derivatives_*, edinet_*, etc.

**Permanent DEFER excluded (n=4):** equities_bars_daily_am · equities_earnings_calendar · equities_master · jsda_otc_bond_reference_prices.

### Multi-year periods (real)

| period_id | window | mirror kind |
|-----------|--------|-------------|
| `y2015_full` | 2015-01-05 → 2015-10-21 | W64 full |
| `y2017_q4` | 2017-09-01 → 2017-12-29 | W63 Q4 |
| `y2019_full` | 2019-01-04 → 2019-10-18 | W64 full |
| `y2021_full` | 2021-01-04 → 2021-10-15 | W64 full |
| `y2023_full` | 2023-01-04 → 2023-10-13 | W64 full |
| `y2025_q4` | 2025-09-01 → 2025-12-29 | W63 Q4 |

Shard policy: ≤15 codes × ≤100–120 days × 6 periods (CF wall-clock safe). Heavy multi-year deep eval remains local for promising survivors.

### Modes (worker)

| mode | role |
|------|------|
| **`r2_panels`** | **W91 default / final path** — staged COMPLETE-backed real bars |
| `d1_bars` | D1 tip extract only (hot window; **not** multi-year) |
| `synthetic` | smoke residual only — **forbidden as final success** |
| `nets_only` | pre-baked nets |

---

## B. Nikkei volatility logics (definitions)

**Family:** `index_vol_regime` (class-signals **v8** · W91)  
**Distinction vs per-name:** `vol_risk_adjusted_mom` / `vol_breakout_expand` gate **single-name** realized vol on mom. `nky_vol_*` apply **index-level** RV regime once, then risk-adjust the **CS book**.

| logic_id | thesis | signal_definition | position_rule | datasets_used |
|----------|--------|-------------------|---------------|---------------|
| `nky_vol_abs_level` | Absolute Nikkei/TOPIX RV level is a risk-appetite factor: low → risk-on keep CS; high → risk-off reverse; mid → flat | CS rank(mom) L-S risk-adjusted by abs short-window ann. RV | sticky fixed_horizon balanced L/S after abs-vol transform | equities_bars_daily · markets_calendar · indices_bars_daily(_topix) · derivatives_bars_daily_futures |
| `nky_vol_term_levels` | Joint short+long absolute RV levels (agreement): both calm → risk-on; both stressed → risk-off; disagree → flat | CS rank mom L-S; regime requires short **and** long abs levels to agree | sticky fixed_horizon balanced L/S | same |
| `nky_vol_term_ratio` | Index RV term structure (short/long): compressing → risk-on; expanding → risk-off; mid → no trade | ratio=RV_short/RV_long; expand/compress thresholds | sticky fixed_horizon balanced L/S | same |

**Defaults:** short_n=10 · long_n=60 · high=0.20 · low=0.10 ann. · expand=1.20 · compress=0.80 · hold=10 · mom=5 · L/S frac=0.3.

**Near-groups (parallel, not merged):** `index_vol_regime_family` · `vol_family_name_vs_index`.

---

## C. Results

### Wide local (real mirrors)

| item | value |
|------|-------|
| data_path | **real_mirrors** |
| catalog after_dedup | **25** templates (v2.3) |
| evaluated | **25** |
| survivors | **22** |
| fail_rate | ~0.12 |
| nky all 3 | **survived** |

| nky logic | mean_net | t_stat | sharpe_period | chosen_sign | survived |
|-----------|----------|--------|---------------|-------------|----------|
| `nky_vol_abs_level` | ≈0.00355 | ≈0.40 | ≈0.16 | +1 | **yes** |
| `nky_vol_term_ratio` | ≈0.00400 | ≈0.72 | ≈−0.31 | −1 | **yes** |
| `nky_vol_term_levels` | ≈0.01307 | ≈0.93 | ≈0.66 | +1 | **yes** |

### CF multi-logic multi-period (real r2_panels)

| item | value |
|------|-------|
| job_id | **`w91-real-20260817T222940Z`** |
| mode | **r2_panels** |
| status | **ok** |
| n_logics × n_periods | 25 × 6 |
| n_survivors | **6** |
| nky CF | abs/levels weak-t reject · **term_ratio survived** |

Machine packs: [`.glm-logs/w0818a_w91_real_vol/`](../../.glm-logs/w0818a_w91_real_vol/) · `w91_summary.json` · `wide_eval.json` · `cf_mass_eval_job.json` · `cf_nky_results.json`.

---

## D. Remaining synthetic / unconnected (honest)

| item | status |
|------|--------|
| CF final path | **real r2_panels** (not synthetic) |
| D1 multi-year history | **not connected** (tip-only; use r2_panels) |
| Cash Nikkei code in indices_bars_daily | **absent** — TOPIX / NK225F proxy |
| NKVIF implied vol path | **catalogued, not required** this wave |
| rate/mf full factor legs on pure-TS CF | **fallback mdh** or local factory |
| CF 200/500 queue fan-out | **not yet** |
| LLM hyp mass flood | **not this wave** (optional small quality batch only) |

---

## E. Freezes restated

Mass **NO-GO** · READY **未宣言** · Phase7 **OFF** · ops GO **未宣言** · continuous paper **UNARMED** · 3 defaults **frozen** · no invent COMPLETE 23 · no S1–S5 unreject · no simple_daily_sign mass · no hold/mom/frac grid.

---

## F. Proofs / residual

- Residual close: [`w0818a_w91_residual_close_20260818.md`](w0818a_w91_residual_close_20260818.md)
- Residual SoT: [`docs/phase62_residual_status.md`](../phase62_residual_status.md) TOP=**W91**
