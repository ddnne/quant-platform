# Observed floor catalog — W29-G1 / w0815v (2026-08-15)

**Canonical proof** for governed-dataset **observed floors** vs coverage-contract `history_target_start`.  
**Machine twin:** [`.glm-logs/w0815v_floor/unified_floor_catalog.json`](../../.glm-logs/w0815v_floor/unified_floor_catalog.json)  
**NO_DENSIFY lock:** [`.glm-logs/w0815v_floor/NO_DENSIFY_FIXED.json`](../../.glm-logs/w0815v_floor/NO_DENSIFY_FIXED.json) · residual SoT [`docs/phase62_residual_status.md`](../phase62_residual_status.md)

| gate | status |
|------|--------|
| Mass / READY / Phase7 | **NO-GO / OFF** |
| empty-raw COMPLETE | **ban held** |
| densify (this wave) | **not executed** (floor catalog only) |
| tip densify | **secondary** — peer G7 owns T10; not this task |
| contract `history_target_start` raise | **propose only** (default; none implemented) |
| push | **not this agent** (G8 T14) |
| CF-SoT | D1 = **hot tip** · R2 = **history** · COMPLETE = **receipt-owned** |

**Live verified (peer floors):** ~2026-08-15T03:14–03:16Z UTC · remote D1 `quant-ingest` · platform COMPLETE segs **3457** · Dataset COMPLETE **11** · empty COMPLETE **0**

**Definition — observed_floor:** first calendar day/month with real non-zero in-window raw that has sealed (or can seal) COMPLETE. Empty SUCCESS shells, tip-misdated bodies, and vendor tip-only endpoints **do not** count as history floors.

**Inputs (peer floor reports):**

| task | path |
|------|------|
| T1 fins | `.glm-logs/w0815v_floor/t1_fins/floor_report.json` |
| T2 bars/master | `.glm-logs/w0815v_floor/t2_bars_master/floor_report.json` |
| T3 edinet/mb/ssr | `.glm-logs/w0815v_floor/t3_edinet_mb_ssr/floor_report.json` |
| T4 indices | `.glm-logs/w0815v_floor/t4_indices/floor_report.json` |
| residual + JSDA | `docs/phase62_residual_status.md` |

---

## 1. Unified floor table

| dataset | history_target_start | observed_floor | COMPLETE segs | PARTIAL pre-floor | PARTIAL post-floor | disposition | evidence |
|---------|---------------------:|---------------:|--------------:|------------------:|-------------------:|-------------|----------|
| `equities_bars_daily` | 2004-01-05 | **2008-05-01** | 220 (`2008-05…2026-08`) | 52 (`2004-01…2008-04`: 31 NO_RAW + 21 EMPTY) | **0** | **DEFER keep D7** / contract raise candidate → `2008-05-01` | T2 floor; D7; `w0815t_g4_bars_matrix`; `bars_p0_gap_2004_2008_reverify` |
| `equities_master` | 2000-07-13 | **2008-05-01** (sealable) | 220 (`2008-05…2026-08`) | 94 (`2000-07…2008-04`: 73 pre-plan + 21 misdate) | **0** | **DEFER keep D2** / contract raise candidate → `2008-05-01` | T2 floor; D2; `w0815b_g10_master`; harvest re-reject |
| `indices_bars_daily_topix` | 2008-01-01 | **2008-05-01** | 220 (`2008-05…2026-08`) | 4 (`2008-01…04` empty) | **0** | **DEFER keep D1** / contract raise candidate → `2008-05-01` + prune | T4 floor; D1; `w0815b_g8_topix_indices` acq 4/4 empty |
| `indices_bars_daily` | 2008-01-01 | **2008-05-01** | 220 (`2008-05…2026-08`) | 4 (`2008-01…04` empty / missing receipt) | **0** | **DEFER keep D1** / contract raise candidate → `2008-05-01` + prune | T4 floor; D1; same empty proof band |
| `fins_summary` | 2008-01-08 | **2008-07-01** | 218 (`2008-07…2026-08`) | 6 (`2008-01…06` empty shells) | **0** | **DEFER keep D10** / contract raise candidate → `2008-07-01` | T1 floor; D10; `w0815j_g1_fins_summary` |
| `fins_dividend` | 2008-01-08 | **2013-02-01** | 163 (`2013-02…2026-08`) | 61 (`2008-01…2013-01` EMPTY_SHELL) | **0** | **DEFER keep** (matrix W27-G1) / contract raise candidate → `2013-02-01` | T1 floor; `w0815t_g1_fins_div_matrix` |
| `fins_details` | 2008-01-08 | **2018-01-01** | 104 (`2018-01…2026-08`) | 120 (`2008-01…2017-12` PRE2018 empty) | **0** | **DEFER keep** (matrix W27-G3) / contract raise candidate → `2018-01-01` | T1 floor; `w0815t_g3_fins_details_matrix` |
| `fins_earnings_date` | 2010-01-04 | **2018-01-01** | 100 (`2018-01…2026-08` w/ tip holes) | 96 (`2010-01…2017-12` NO_RAW) | **4** (`2026-01…04` tip known-empty) | **DEFER keep** (matrix W27-G2 mixed) / raise candidate pre-floor only → `2018-01-01` | T1 floor; `w0815t_g2_fins_earn_matrix` |
| `markets_breakdown` | 2013-01-04 | **2015-03-26** (source; first full COMPLETE **2015-04**) | 137 (`2015-04…2026-08`) | 27 (`2013-01…2015-03` empty + thin floor month) | **0** | **DEFER keep D3** / contract raise candidate → `2015-03-26` | T3 floor; D3; `w0815b_g9_breakdown` |
| `markets_short_sale_report` | 2013-01-04 | **2013-11-01** | 154 (`2013-11…2026-08`) | 10 (`2013-01…10` empty shells) | **0** | **DEFER keep D9** / contract raise candidate → `2013-11-01` | T3 floor; D9; `w0815h_g1_short_sale` |
| `edinet_cross_shareholdings` | 2018-01-04 | **2020-05-01** | 76 (`2020-05…2026-08`) | 28 (`2018-01…2020-04` empty) | **0** | **DEFER keep D6** / contract raise candidate → `2020-05-01` | T3 floor; D6; `w0815c_g6` / `w0815r_g4` |
| `edinet_large_volume_shareholders` | 2018-01-04 | **2021-07-01** | 62 (`2021-07…2026-08`) | 42 (`2018-01…2021-06` empty) | **0** | **DEFER keep D6** / contract raise candidate → `2021-07-01` | T3 floor; D6; same EDINET proofs |
| `edinet_major_shareholders` | 2018-01-04 | **2018-01-04** | **104/104** | **0** | **0** | **DATASET COMPLETE** (floor = contract) | T3 floor; residual SoT |
| `equities_earnings_calendar` | 2010-01-04 | tip-only (**~2026-08**; no honest history floor) | **1** tip | ~199 history PARTIAL (vendor tip-date shells) | n/a (tip is the only COMPLETE) | **DEFER keep D4** — catalog history de-scope / use `fins_earnings_date` | residual D4; `w0815b_g11_earn_am` |
| `equities_bars_daily_am` | 2024-01-04 | tip-only (**~2026-08**; AM same-day) | **1** tip | ~31 history PARTIAL (`date_mode=today`) | n/a | **DEFER keep D4** — use `equities_bars_daily` OHLC for history | residual D4; same |
| `jsda_otc_bond_reference_prices` | 2002-08-02 | tip/recent island only (COMPLETE **72** segs; archive unfillable) | **72** tip/recent | archive residual **DEFER D5** (timeout/404/403) | tip advance DEFER | **DEFER keep D5** archive — **not** contract raise (site capability) | residual D5; `w0815r_g4` / `w0815n_g1` |
| `jsda_tokyo_repo_rates` | 2012-10-29 | **2012-10-29** (receipt COMPLETE 1/1; hot D1 tip plane-split) | **1/1** | **0** | **0** | **DATASET COMPLETE** | residual SoT; CF-SoT plane honesty |
| `jsda_corporate_bond_transactions` | 2015-11-04 | **2015** annual band (`2015…2026`) | **12/12** | **0** | **0** | **DATASET COMPLETE** | residual SoT |
| `markets_calendar` | 2008-01-01 | **2008-01-01** | **224/224** | **0** | **0** | **DATASET COMPLETE** | residual SoT live snapshot |
| `equities_investor_types` | 2013-01-04 | **2013-01-04** | **164/164** | **0** | **0** | **DATASET COMPLETE** | residual SoT |
| `markets_margin_interest` | 2013-01-04 | **2013-01-04** | **164/164** | **0** | **0** | **DATASET COMPLETE** | residual SoT / margin proofs |
| `markets_margin_alert` | 2013-01-04 | **2013-01-04** | **164/164** | **0** | **0** | **DATASET COMPLETE** | residual SoT |
| `markets_short_ratio` | 2013-01-04 | **2013-01-04** | **164/164** | **0** | **0** | **DATASET COMPLETE** | W12-G3 / residual SoT |
| `derivatives_bars_daily_futures` | 2013-01-04 | **2013-01-04** | **164/164** | **0** | **0** | **DATASET COMPLETE** | W13-G3; `w0815e_g3` / `w0815g_g1` |
| `derivatives_bars_daily_options_225` | 2013-01-04 | **2013-01-04** | **164/164** | **0** | **0** | **DATASET COMPLETE** | same |
| `derivatives_bars_daily_options` | 2013-01-04 | **2013-01-04** | **164/164** | **0** | **0** | **DATASET COMPLETE** | W15-G1 residual 0 |

**Row count:** 26 governed datasets (all `collection_coverage.json` entries). Residual-bearing: **15** · COMPLETE short rows: **11**.

---

## 2. Contract change proposals (T6) — **propose only; not implemented**

Rule applied: propose when `observed_floor > history_target_start` **and** all pre-floor residuals are proven empty / NO_RAW / MISDATE (not sealable).  
**Implement** only if always-empty is proven **and** product policy allows **and** change is a one-line safe contract update with tests.  
**This wave default:** **no contract file change**.

| dataset | current `history_target_start` | proposed | pre-floor residual proven empty? | implement this wave? | reason |
|---------|-------------------------------:|---------:|----------------------------------:|----------------------|--------|
| `indices_bars_daily_topix` | 2008-01-01 | **2008-05-01** | **yes** (4 empty shells; acq 4/4 `rows=0`) | **NO** | human-gate + PARTIAL prune SQL required; residual D1 already documents path |
| `indices_bars_daily` | 2008-01-01 | **2008-05-01** | **yes** (4 empty / missing receipt) | **NO** | same human-gate as topix |
| `fins_summary` | 2008-01-08 | **2008-07-01** | **yes** (6 empty R2 shells) | **NO** | D10 re-try already lists policy move; surgical COMPLETE not rule-legal without inventory reagg |
| `fins_dividend` | 2008-01-08 | **2013-02-01** | **yes** (61 EMPTY_SHELL matrix) | **NO** | matrix DEFER only; no ADR/ops path intending raise this wave |
| `fins_details` | 2008-01-08 | **2018-01-01** | **yes** (120 PRE2018 empty) | **NO** | same |
| `fins_earnings_date` | 2010-01-04 | **2018-01-01** | **yes** pre-floor (96); tip **4** remain | **NO** | raise alone does not clear tip DEFER holes |
| `equities_bars_daily` | 2004-01-05 | **2008-05-01** | **yes** (52 NO_RAW/EMPTY) | **NO** | D7; subscription/history policy decision; no one-line safe update |
| `equities_master` | 2000-07-13 | **2008-05-01** | **yes** sealable (73+21 misdate) | **NO** | D2 misdate band needs product policy; not always-empty API |
| `markets_breakdown` | 2013-01-04 | **2015-03-26** | **yes** empty shells + thin floor month | **NO** | D3; source-floor policy gate |
| `markets_short_sale_report` | 2013-01-04 | **2013-11-01** | **yes** (10 empty shells) | **NO** | D9 lists floor move as re-try option only |
| `edinet_cross_shareholdings` | 2018-01-04 | **2020-05-01** | **yes** (28 empty) | **NO** | D6 keep empty; no ADR intending raise |
| `edinet_large_volume_shareholders` | 2018-01-04 | **2021-07-01** | **yes** (42 empty) | **NO** | D6 same |
| `edinet_major_shareholders` | 2018-01-04 | — | n/a COMPLETE | **NO** | floor already equals contract |
| COMPLETE datasets (margin/short_ratio/deriv/investor/calendar/JSDA corp/repo) | = floor | — | n/a | **NO** | already aligned |
| `jsda_otc_bond_reference_prices` | 2002-08-02 | **do not raise to tip** | archive is site-fail, not “always empty product window” | **NO** | D5 archive capability; tip 72 is operational island only |
| D4 earn_calendar / bars_am | 2010-01-04 / 2024-01-04 | catalog **de-scope history** (not floor raise) | tip-only vendor | **NO** | product/catalog change, not `history_target_start` floor bump |

**Implemented contract changes this wave:** **none**  
**Before/after:** n/a  
**Files touched for contract:** none (`packages/data_plane/data_contracts/collection_coverage.json` **unchanged**)

---

## 3. NO_DENSIFY_FIXED (summary)

Every residual segment class below is **locked — never re-densify** unless the formal DEFER re-try condition is met (vendor nz or human-gate contract+prune). Empty-raw COMPLETE remains **forbidden**. Tip densify for **non-DEFER** tip holes remains secondary (peer-owned).

| DEFER id | dataset(s) | residual class / span | n segs | never densify reason |
|----------|------------|----------------------|-------:|----------------------|
| **D1** | `indices_bars_daily_topix` | PARTIAL `2008-01…04` empty shells | 4 | API empty; acq proven 0-row |
| **D1** | `indices_bars_daily` | PARTIAL `2008-01…04` empty / missing receipt | 4 | same band |
| **D2** | `equities_master` | pre-plan `2000-07…2006-07` | 73 | below subscription / no sealable raw |
| **D2** | `equities_master` | misdate `2006-08…2008-04` | 21 | R2 Date stuck tip; window_ok=0 |
| **D3** | `markets_breakdown` | PARTIAL `2013-01…2015-03` | 27 | source floor 2015-03-26; empty/thin |
| **D4** | `equities_earnings_calendar` | history residual tip-dated shells | ~199 | vendor next-bday only |
| **D4** | `equities_bars_daily_am` | history residual today-mode | ~31 | vendor same-day AM only |
| **D5** | `jsda_otc_bond_reference_prices` | archive beyond tip COMPLETE 72 | archive | site timeout/404/403 |
| **D6** | `edinet_cross_shareholdings` | pre-island `2018-01…2020-04` | 28 | empty-raw residual |
| **D6** | `edinet_large_volume_shareholders` | pre-island `2018-01…2021-06` | 42 | empty-raw residual |
| **D7** | `equities_bars_daily` | NO_RAW `2004-01…2006-07` | 31 | OOS / entitlement |
| **D7** | `equities_bars_daily` | EMPTY `2006-08…2008-04` | 21 | empty API under subscription |
| **D9** | `markets_short_sale_report` | PARTIAL `2013-01…10` | 10 | empty pre-history shells |
| **D10** | `fins_summary` | PARTIAL `2008-01…06` | 6 | empty pre-history shells |
| **MX-DIV** | `fins_dividend` | EMPTY_SHELL `2008-01…2013-01` | 61 | W27-G1 matrix forever-skip |
| **MX-DET** | `fins_details` | DEFER_PRE2018 `2008-01…2017-12` | 120 | W27-G3 matrix forever-skip |
| **MX-EARN-PRE** | `fins_earnings_date` | NO_RAW pre-floor `2010-01…2017-12` | 96 | W27-G2 matrix |
| **MX-EARN-TIP** | `fins_earnings_date` | tip known-empty `2026-01…04` | 4 | W27-G2 tip DEFER (not densify-as-success) |

**NO_DENSIFY class count:** **18** (formal D1–D7,D9,D10 segment classes + 4 matrix-fixed classes).  
**D8** (Batch Z / Mass·READY·Phase7) remains policy OFF — not a segment densify class.

Full machine list: `.glm-logs/w0815v_floor/NO_DENSIFY_FIXED.json`.

---

## 4. Ops policy lock (W29-G1)

1. **Floors locked** — observed floors above are the sealable history anchors; do not densify pre-floor shells.
2. **Tip densify secondary** — only non-DEFER tip holes; peer G7 / continuous collect; this task did not tip-densify.
3. **No invent COMPLETE** by pruning PARTIAL without human-gate contract floor move + reagg policy.
4. **CF-SoT held:** D1 hot tip · R2 history · receipt-owned COMPLETE.
5. **empty-raw COMPLETE ban held.**

---

## 5. Artifact index

| artifact | path |
|----------|------|
| This proof | `docs/proof/observed_floor_catalog_20260815.md` |
| Unified JSON | `.glm-logs/w0815v_floor/unified_floor_catalog.json` |
| NO_DENSIFY JSON | `.glm-logs/w0815v_floor/NO_DENSIFY_FIXED.json` |
| T1–T4 peer floors | `.glm-logs/w0815v_floor/t{1,2,3,4}_*/floor_report.json` |
| Residual SoT | `docs/phase62_residual_status.md` |
| Coverage contract (unchanged) | `packages/data_plane/data_contracts/collection_coverage.json` |
