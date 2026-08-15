# COMPLETE 21 — minimal feature catalog (2026-08-15)

**Wave:** W49 / w0815ap_g2 · T5  
**Phase:** COMPLETE 21 **usage readiness** (利用準備) — feature catalog only  
**Mass / READY / Phase7:** **not** declared · **not** enabled · densify **not** run · push **not** this task

**Sources:**

| source | path |
|--------|------|
| COMPLETE 21 list | [`coverage_baseline_21_usage_notes_20260815.md`](coverage_baseline_21_usage_notes_20260815.md) |
| CF read paths + DEFER guard | [`complete21_cf_read_paths_20260815.md`](complete21_cf_read_paths_20260815.md) |
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
| `return_1d` | `equities_bars_daily` | \((C_t - C_{t-1}) / C_{t-1}\) | implemented (v0, approved) |
| `momentum_n` | `equities_bars_daily` | N-session cumulative return | implemented (v0, approved) |
| `volatility_n` | `equities_bars_daily` | sample stdev of 1d returns · √252 | implemented (v0, approved) |
| `volume_change_1d` | `equities_bars_daily` | \((V_t - V_{t-1}) / V_{t-1}\) | **implemented** (complete21 min, candidate) |

**Not used:** `equities_bars_daily_am` (DEFER).

### 2.2 Index-relative

| feature_id | inputs (COMPLETE only) | formula (sketch) | status |
|------------|------------------------|------------------|--------|
| `topix_relative_1d` | `equities_bars_daily` + `indices_bars_daily_topix` | equity `return_1d` − TOPIX `return_1d` | **implemented** (complete21 min, candidate) |

### 2.3 Margin / short

| feature_id | inputs (COMPLETE only) | formula (sketch) | status |
|------------|------------------------|------------------|--------|
| `margin_interest_change_1d` | `markets_margin_interest` | session-over-session change in margin interest fields | catalog + **skeleton** path (guarded load) |
| (future) short_ratio_level | `markets_short_ratio` | level / change of short ratio | catalog only |
| (future) margin_alert_flag | `markets_margin_alert` | 1 if alert row visible at `as_of` | catalog only |

### 2.4 Disclosure / filings flags

| feature_id | inputs (COMPLETE only) | formula (sketch) | status |
|------------|------------------------|------------------|--------|
| `disclosure_flag_fins` | `fins_summary` | 1.0 if any PIT-visible summary row for `code` at `as_of`, else 0.0 | **implemented** (complete21 min, candidate) |
| (future) dividend_announce_flag | `fins_dividend` | announcement presence | catalog only |
| (future) edinet_major_holder_flag | `edinet_major_shareholders` | filing presence | catalog only |

**Not used:** `fins_earnings_date`, `equities_earnings_calendar` (DEFER).

### 2.5 Investor / calendar / JSDA (catalog only this wave)

| feature_id (future) | inputs | note |
|---------------------|--------|------|
| investor_flow_change | `equities_investor_types` | section × pubdate flows |
| is_trading_day | `markets_calendar` | structural / utility |
| repo_rate_level | `jsda_tokyo_repo_rates` | macro context |
| corp_bond_print_flag | `jsda_corporate_bond_transactions` | activity flag |

---

## 3. Implemented in this wave (T6)

Registered under `packages/research_runtime/features/complete21_min.py` (imported from `features` package):

| id | version | intended_role | status | required datasets |
|----|---------|---------------|--------|-------------------|
| `volume_change_1d` | 1.0.0 | signal | candidate | `equities_bars_daily` |
| `topix_relative_1d` | 1.0.0 | signal | candidate | `equities_bars_daily`, `indices_bars_daily_topix` |
| `disclosure_flag_fins` | 1.0.0 | signal | candidate | `fins_summary` |

Each compute path calls `require_feature_datasets(...)` → permanent DEFER reject **before** PIT reads.

Pipeline guard (T7): `FeatureContext.get_jquants_records` and `get_equity_master` refuse permanent DEFER ids via `require_history_eligible` / fixed reject for master.

---

## 4. Explicit non-claims

This document does **not**:

* declare Mass Autonomous Research **ON**
* declare production **READY** / B0 **GO**
* enable **Phase7**
* invent Dataset COMPLETE **22**
* re-open densify / tip densify as primary
* promote `candidate` features to strategy-default `approved` consumption
* treat local SQLite as CF SoT

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
| Prior usage readiness | [`w0815ao_w48_usage_readiness_20260815.md`](w0815ao_w48_usage_readiness_20260815.md) |
