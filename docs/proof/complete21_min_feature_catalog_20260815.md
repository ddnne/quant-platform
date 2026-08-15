# COMPLETE 21 — minimal feature catalog (2026-08-15)

**Wave:** W52 / w0815as_g1 · T1–T4 (extends W51 / w0815ar_g2 · W50 / w0815aq_g2 · W49 / w0815ap_g2)  
**Phase:** COMPLETE 21 **usage readiness** (利用準備) — feature catalog + min implementations + quality gates  
**Mass / READY / Phase7:** **not** declared · **not** enabled · densify **not** run · push **not** this task  
**Promotion (W52):** **2** approved — `is_trading_day` · `volume_change_1d` (version pin **1.0.0**); remaining **8** stay `candidate`  
**Promotion eval proof:** [`w0815as_w52_feature_promotion_eval_20260815.md`](w0815as_w52_feature_promotion_eval_20260815.md)  
**Candidate → approved criteria:** [`complete21_feature_candidate_to_approved_criteria_20260815.md`](complete21_feature_candidate_to_approved_criteria_20260815.md)

**Sources:**

| source | path |
|--------|------|
| COMPLETE 21 list | [`coverage_baseline_21_usage_notes_20260815.md`](coverage_baseline_21_usage_notes_20260815.md) |
| CF read paths + DEFER guard | [`complete21_cf_read_paths_20260815.md`](complete21_cf_read_paths_20260815.md) |
| Candidate → approved criteria | [`complete21_feature_candidate_to_approved_criteria_20260815.md`](complete21_feature_candidate_to_approved_criteria_20260815.md) |
| Residual SoT | [`../phase62_residual_status.md`](../phase62_residual_status.md) |
| Permanent DEFER lock | [`w0815ak_w44_defer_lock_20260815.md`](w0815ak_w44_defer_lock_20260815.md) |
| Features contract | [`../features.md`](../features.md) |
| Guard + min features (code) | `packages/research_runtime/features/` |

---

## 0. Scope and hard rules

This catalog lists **minimal research features computable only from Dataset COMPLETE 21** facts.

| rule | guidance |
|------|----------|
| **Inputs** | History fact loads **must** come from the **21 COMPLETE** datasets only. |
| **Exclude** | Permanent **DEFER 5** are **never** feature inputs for full-history / research compute. |
| **PIT** | Every value is gated by `available_at <= as_of` via the features runtime + PIT API. |
| **CF-SoT** | D1 = hot tip · R2 = history · COMPLETE = receipt-owned. Local SQLite is **not** SoT. |
| **READY** | **Not claimed.** Catalog + skeletons only; no production READY / Mass / Phase7 GO. |

### Permanent DEFER 5 — **excluded from all catalog inputs**

| dataset | PD id | why excluded |
|---------|-------|--------------|
| `equities_master` | PD-D2-MASTER | MISDATE + PRE_PLAN residual; not Dataset COMPLETE |
| `equities_earnings_calendar` | PD-D4-EARN-CAL | vendor tip-only history |
| `equities_bars_daily_am` | PD-D4-BARS-AM | tip-only AM bars |
| `fins_earnings_date` | PD-MX-EARN-TIP | tip holes `2026-01…04` |
| `jsda_otc_bond_reference_prices` | PD-D5-JSDA-OTC | archive long-tail; tip island only |

Code path: `data_contracts.permanent_defer` (`filter_permanent_defer` / `require_history_eligible` / `reject_permanent_defer_for_history`).  
Feature pipeline: `features.dataset_guard` + `FeatureContext` fail-closed on DEFER ids (see T7).

---

## 1. COMPLETE 21 input surface (allowed)

| # | dataset | typical feature use |
|--:|---------|---------------------|
| 1 | `equities_bars_daily` | returns, volume change, volatility, momentum |
| 2 | `indices_bars_daily_topix` | TOPIX absolute / relative returns |
| 3 | `indices_bars_daily` | other index relatives |
| 4 | `markets_calendar` | trading-day alignment |
| 5 | `markets_margin_interest` | margin balance / change |
| 6 | `markets_margin_alert` | margin alert flags |
| 7 | `markets_short_ratio` | short interest / ratio signals |
| 8 | `markets_short_sale_report` | short-sale disclosure flags |
| 9 | `markets_breakdown` | sector/market breakdown context |
| 10 | `equities_investor_types` | investor-type flow / change |
| 11 | `fins_summary` | disclosure presence / earnings flags |
| 12 | `fins_details` | richer FS flags (heavier) |
| 13 | `fins_dividend` | dividend announcement flags |
| 14–16 | `edinet_*` (3) | major / cross / large-volume holder flags |
| 17–19 | `derivatives_bars_daily_*` (3) | futures/options state (optional later) |
| 20–21 | `jsda_tokyo_repo_rates`, `jsda_corporate_bond_transactions` | rates / credit context (macro-ish) |

**Count:** **21**. Do **not** invent Dataset COMPLETE **22**.

---

## 2. Minimal feature catalog

Status legend: **catalog** = documented here; **implemented** = registered feature (may be `candidate` skeleton).  
None of these declare READY.

### 2.1 Price / volume (bars only)

| feature_id | inputs (COMPLETE only) | formula (sketch) | status |
|------------|------------------------|------------------|--------|
| `return_1d` | `equities_bars_daily` | \((C_t - C_{t-1}) / C_{t-1}\) | implemented (v0, **approved**) · DEFER-guarded via `get_equity_bars_daily` |
| `return_1d_c21` | `equities_bars_daily` | same formula; complete21 path + `require_feature_datasets` | **implemented** (complete21 min, **candidate**) · W51 export · does **not** replace v0 |
| `momentum_n` | `equities_bars_daily` | N-session cumulative return | implemented (v0, approved) |
| `volatility_n` | `equities_bars_daily` | sample stdev of 1d returns · √252 | implemented (v0, approved) |
| `volume_change_1d` | `equities_bars_daily` | \((V_t - V_{t-1}) / V_{t-1}\) | **implemented** (complete21 min, **approved** · v1.0.0 · W52) |

**Not used:** `equities_bars_daily_am` (DEFER).

### 2.2 Index-relative

| feature_id | inputs (COMPLETE only) | formula (sketch) | status |
|------------|------------------------|------------------|--------|
| `topix_relative_1d` | `equities_bars_daily` + `indices_bars_daily_topix` | equity `return_1d` − TOPIX `return_1d` | **implemented** (complete21 min, candidate) |

### 2.3 Margin / short

| feature_id | inputs (COMPLETE only) | formula (sketch) | status |
|------------|------------------------|------------------|--------|
| `margin_interest_change_1d` | `markets_margin_interest` | \((M_t - M_{t-1}) / M_{t-1}\) with \(M =\) LongVol + ShrtVol | **implemented** (complete21 min, candidate) |
| `short_ratio_level` | `markets_short_ratio` | \((\)ShrtWithResVa + ShrtNoResVa\() / \)SellExShortVa for S33 section | **implemented** (complete21 min, candidate) |
| `margin_alert_flag` | `markets_margin_alert` | 1.0 if any PIT-visible alert row for `code` at `as_of`, else 0.0 | **implemented** (complete21 min, candidate) · W51 |

### 2.4 Disclosure / filings flags

| feature_id | inputs (COMPLETE only) | formula (sketch) | status |
|------------|------------------------|------------------|--------|
| `disclosure_flag_fins` | `fins_summary` | 1.0 if any PIT-visible summary row for `code` at `as_of`, else 0.0 | **implemented** (complete21 min, candidate) |
| (future) dividend_announce_flag | `fins_dividend` | announcement presence | catalog only |
| (future) edinet_major_holder_flag | `edinet_major_shareholders` | filing presence | catalog only |

**Not used:** `fins_earnings_date`, `equities_earnings_calendar` (DEFER).

### 2.5 Investor / calendar / JSDA

| feature_id | inputs | formula (sketch) | status |
|------------|--------|------------------|--------|
| (future) investor_flow_change | `equities_investor_types` | section × pubdate flows | catalog only |
| `is_trading_day` | `markets_calendar` | 1.0 if `holiday_division=="1"` for date (default = as_of day) | **implemented** (complete21 min, **approved** · v1.0.0 · W52 · utility) |
| `repo_rate_level` | `jsda_tokyo_repo_rates` | latest PIT-visible `rate` (optional tenor / rate_type) | **implemented** (complete21 min, candidate) |
| (future) corp_bond_print_flag | `jsda_corporate_bond_transactions` | activity flag | catalog only |

### 2.6 Derivatives (futures / options)

| feature_id | inputs (COMPLETE only) | formula (sketch) | status |
|------------|------------------------|------------------|--------|
| `futures_activity_proxy` | `derivatives_bars_daily_futures` | sum of `Volume` on latest PIT-visible date (optional contract `code`) | **implemented** (complete21 min, candidate) · W51 |
| (future) options_activity_proxy | `derivatives_bars_daily_options` / `_options_225` | analogous volume proxy | catalog only |

---

## 3. Implemented (T5–T6)

Registered under `packages/research_runtime/features/complete21_min.py` (imported from `features` package):

| id | version | intended_role | status | required datasets | wave |
|----|---------|---------------|--------|-------------------|------|
| `volume_change_1d` | **1.0.0** (pin) | signal | **approved** | `equities_bars_daily` | W49 → **W52 promote** |
| `topix_relative_1d` | 1.0.0 | signal | candidate | `equities_bars_daily`, `indices_bars_daily_topix` | W49 |
| `disclosure_flag_fins` | 1.0.0 | signal | candidate | `fins_summary` | W49 |
| `margin_interest_change_1d` | 1.0.0 | signal | candidate | `markets_margin_interest` | W50 |
| `short_ratio_level` | 1.0.0 | signal | candidate | `markets_short_ratio` | W50 |
| `is_trading_day` | **1.0.0** (pin) | utility | **approved** | `markets_calendar` | W50 → **W52 promote** |
| `repo_rate_level` | 1.0.0 | state | candidate | `jsda_tokyo_repo_rates` | W50 |
| `return_1d_c21` | 1.0.0 | signal | candidate | `equities_bars_daily` | **W51** |
| `margin_alert_flag` | 1.0.0 | signal | candidate | `markets_margin_alert` | **W51** |
| `futures_activity_proxy` | 1.0.0 | state | candidate | `derivatives_bars_daily_futures` | **W51** |

**Count:** **10** complete21 min features (**2** approved · **8** candidate) (+ 3 approved v0 bars features outside this module).

Each compute path calls `require_feature_datasets(...)` → permanent DEFER reject **before** PIT reads.

Pipeline guard: `FeatureContext.get_jquants_records`, `get_equity_master`, `get_market_calendar`, `get_equity_bars_daily`, and `get_jsda_repo_rates` refuse permanent DEFER ids via `require_history_eligible` / fixed reject for master.

**W52 promotion notes:**

* Promoted (max 2): `is_trading_day` · `volume_change_1d` — version pin **1.0.0**; proof [`w0815as_w52_feature_promotion_eval_20260815.md`](w0815as_w52_feature_promotion_eval_20260815.md).
* `is_trading_day` remains `intended_role=utility` — `get_for_strategy` requires explicit `allowed_roles` override (not a default strategy signal).
* `volume_change_1d` is `intended_role=signal` + `approved` → admitted by default `get_for_strategy`.
* Consumers must pin `(id, version="1.0.0")`; major bump if meaning changes.

**W51 notes (held):**

* `return_1d_c21` is a **candidate export** of the 1d simple-return formula on the complete21 path (`require_feature_datasets` + tags). It does **not** replace approved v0 `return_1d` and was **not** promoted (W52).
* Test strengthen (T5): missing required inputs, `as_of` required, PIT `available_at` gates, DEFER poison on all declared dataset groups.

---

## 4. Explicit non-claims

This document does **not**:

* declare Mass Autonomous Research **ON**
* declare production **READY** / B0 **GO**
* enable **Phase7**
* invent Dataset COMPLETE **22**
* re-open densify / tip densify as primary
* promote more than the W52 set of **2** features (remaining 8 stay candidate)
* merge `return_1d_c21` into approved v0 `return_1d`
* treat local SQLite as CF SoT
* declare Mass / READY / Phase7 from feature promotion alone

Live residual remains: Mass **NO-GO** · READY **not** declared · Phase7 **OFF**.

---

## 5. Related

| artifact | path |
|----------|------|
| DEFER guard module | `packages/data_plane/data_contracts/permanent_defer.py` |
| Feature dataset guard | `packages/research_runtime/features/dataset_guard.py` |
| Feature runtime | `packages/research_runtime/features/runtime.py` |
| Min features | `packages/research_runtime/features/complete21_min.py` |
| Guard / feature tests | `tests/test_complete21_min_features.py` |
| Candidate → approved criteria | [`complete21_feature_candidate_to_approved_criteria_20260815.md`](complete21_feature_candidate_to_approved_criteria_20260815.md) |
| Prior usage readiness | [`w0815ao_w48_usage_readiness_20260815.md`](w0815ao_w48_usage_readiness_20260815.md) |
