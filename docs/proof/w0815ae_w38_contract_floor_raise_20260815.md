# W38 / w0815ae — contract floor raise + residual DEFER re-align (T11 draft) (2026-08-15)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** ban held  
**densify:** **none** (this wave — residual SoT + contract review only)  
**DEFER densify re-run:** **not** done  
**Contract `history_target_start` raise:** **implemented** — **11** floors raised (`ba3c811`)  
**Primary metric (COMPLETE segs):** **pending reeval** (peer T2 / G5 fill POST)  
**Secondary metric (tip raw):** **pending reeval**

**Live verified (contract):** 2026-08-15 (JST) — floors live in `collection_coverage.json` after `ba3c811`  
**Contract commit:** `ba3c81157c1528784e4909ca7e03e7c8076553c2`  
**Floor catalog (evidence):** [`observed_floor_catalog_20260815.md`](observed_floor_catalog_20260815.md)  
**Residual SoT:** [`docs/phase62_residual_status.md`](../phase62_residual_status.md) §W38  
**Machine:** [`.glm-logs/w0815ae_contract/contract_diff.json`](../../.glm-logs/w0815ae_contract/contract_diff.json) · [`.glm-logs/w0815ae_defer/PERMANENT_DEFER.json`](../../.glm-logs/w0815ae_defer/PERMANENT_DEFER.json) · [`.glm-logs/w0815ae_defer/NO_DENSIFY_AFTER_CONTRACT_DRAFT.json`](../../.glm-logs/w0815ae_defer/NO_DENSIFY_AFTER_CONTRACT_DRAFT.json)

CF-SoT held: **D1 = hot tip · R2 = history · COMPLETE = receipt-owned**.

---

## 1. Scope

| lane | owner | outcome |
|------|-------|---------|
| **T1 contract raises** | G1 | **11** `history_target_start` raises to proven observed floors |
| **T4 Permanent DEFER** | residual prep | **5** permanent entries (D2 / D4×2 / D5 / MX-EARN-TIP) |
| **T5 NO_DENSIFY re-align** | residual prep | **18 → 6** active; **12** OUT_OF_SCOPE |
| **T11 contract review** | this proof (draft) | before→after table + catalog evidence links |
| **T2 reeval / G5 metrics** | peer | COMPLETE/raw/FRESH **pending reeval** — G5 fills final POST |

**Not done:** densify · empty-raw COMPLETE · Mass/READY/Phase7 · raise master/D4/D5 floors · invent COMPLETE by prune without reagg.

---

## 2. T11 contract review table (before → after)

Evidence column points at the canonical floor catalog (`observed_floor_catalog_20260815.md` §1) and residual DEFER ids. Machine twin of raises: `.glm-logs/w0815ae_contract/contract_diff.json`.

### 2.1 Raised (11)

| dataset | before | after | pre-floor residual (catalog) | observed_floor | defer / class | evidence |
|---------|-------:|------:|------------------------------|---------------:|---------------|----------|
| `equities_bars_daily` | 2004-01-05 | **2008-05-01** | 52 segs `2004-01…2008-04` (31 NO_RAW + 21 EMPTY) | **2008-05-01** | D7 | [catalog §1](observed_floor_catalog_20260815.md) equities_bars_daily · D7 · `bars_p0_gap_2004_2008_reverify` |
| `indices_bars_daily_topix` | 2008-01-01 | **2008-05-01** | 4 months `2008-01…04` empty shells; acq 4/4 rows=0 | **2008-05-01** | D1 EMPTY_SHELL | [catalog §1](observed_floor_catalog_20260815.md) indices_bars_daily_topix · D1 · `w0815b_g8_topix_indices` |
| `indices_bars_daily` | 2008-01-01 | **2008-05-01** | 4 months `2008-01…04` empty / missing receipt | **2008-05-01** | D1 | [catalog §1](observed_floor_catalog_20260815.md) indices_bars_daily · D1 |
| `fins_summary` | 2008-01-08 | **2008-07-01** | 6 empty shells `2008-01…06` | **2008-07-01** | D10 | [catalog §1](observed_floor_catalog_20260815.md) fins_summary · D10 · `w0815j_g1_fins_summary` |
| `fins_dividend` | 2008-01-08 | **2013-02-01** | 61 EMPTY_SHELL `2008-01…2013-01` | **2013-02-01** | MX-DIV | [catalog §1](observed_floor_catalog_20260815.md) fins_dividend · `w0815t_g1_fins_div_matrix` |
| `fins_details` | 2008-01-08 | **2018-01-01** | 120 PRE2018 empty `2008-01…2017-12` | **2018-01-01** | MX-DET | [catalog §1](observed_floor_catalog_20260815.md) fins_details · `w0815t_g3_fins_details_matrix` |
| `fins_earnings_date` | 2010-01-04 | **2018-01-01** | 96 NO_RAW `2010-01…2017-12`; tip **4** remain DEFER | **2018-01-01** | MX-EARN-PRE OOS · **MX-EARN-TIP** survives | [catalog §1](observed_floor_catalog_20260815.md) fins_earnings_date · `w0815t_g2_fins_earn_matrix` |
| `markets_breakdown` | 2013-01-04 | **2015-03-26** | 27 segs `2013-01…2015-03` empty + thin floor month | **2015-03-26** | D3 | [catalog §1](observed_floor_catalog_20260815.md) markets_breakdown · D3 · `w0815b_g9_breakdown` |
| `markets_short_sale_report` | 2013-01-04 | **2013-11-01** | 10 empty shells `2013-01…10` | **2013-11-01** | D9 | [catalog §1](observed_floor_catalog_20260815.md) markets_short_sale_report · D9 · `w0815h_g1_short_sale` |
| `edinet_cross_shareholdings` | 2018-01-04 | **2020-05-01** | 28 empty `2018-01…2020-04` | **2020-05-01** | D6 | [catalog §1](observed_floor_catalog_20260815.md) edinet_cross · D6 · `w0815r_g4_edinet_otc` |
| `edinet_large_volume_shareholders` | 2018-01-04 | **2021-07-01** | 42 empty `2018-01…2021-06` | **2021-07-01** | D6 | [catalog §1](observed_floor_catalog_20260815.md) edinet_large · D6 |

**Count raised:** **11** (matches `contract_diff.json` `count_changed`).

### 2.2 Not raised (4) — permanent / capability residual

| dataset | history_target_start (held) | why not raised | permanent ref | evidence |
|---------|----------------------------:|----------------|---------------|----------|
| `equities_master` | 2000-07-13 | MISDATE band not pure always-empty; tip-dated bodies; product gate | PD-D2-MASTER | [catalog §1](observed_floor_catalog_20260815.md) equities_master · D2 · `w0815b_g10_master` / harvest re-reject |
| `equities_earnings_calendar` | 2010-01-04 | tip-only vendor; de-scope ≠ floor raise | PD-D4-EARN-CAL | [catalog §1](observed_floor_catalog_20260815.md) D4 · `w0815b_g11_earn_am` |
| `equities_bars_daily_am` | 2024-01-04 | today-mode AM tip-only | PD-D4-BARS-AM | [catalog §1](observed_floor_catalog_20260815.md) equities_bars_daily_am |
| `jsda_otc_bond_reference_prices` | 2002-08-02 | archive site fail; do **not** raise to tip island (COMPLETE 72) | PD-D5-JSDA-OTC | [catalog §1](observed_floor_catalog_20260815.md) jsda_otc · D5 · `w0815r_g4` / `w0815n_g1` |

W29 catalog §2 had **12** raise candidates including master → `2008-05-01`. W38 implements **11** proven always-empty floors only; **master withheld** as Permanent DEFER.

### 2.3 Aligned copies / tests

| path | role |
|------|------|
| `packages/data_plane/data_contracts/collection_coverage.json` | SoT `history_target_start` |
| `packages/data_plane/data_contracts/canonical_datasets.json` | `historical_start` aligned |
| `packages/edge/cf_platform/ingest_premium/coverage.py` | `EXPECTED_START` aligned |
| `packages/data_plane/ops/range_batch_scheduler.py` | `TRACK_A_FOCUS_RANGES` aligned |
| `packages/data_plane/data_contracts/jsda_governed.json` | **unchanged** |
| tests: `test_phase35_coverage_matrix` · `test_backfill_planner` · `test_range_batch_scheduler` · `test_phase6_snapshot_publication` | updated with raise set |

---

## 3. NO_DENSIFY re-align summary

| metric | W29 (pre) | W38 (post) |
|--------|----------:|-----------:|
| NO_DENSIFY classes | **18** | **6** active |
| OUT_OF_SCOPE after raise | 0 | **12** |
| Permanent DEFER entries | (implicit in 18) | **5** formalized |
| densify executed | none (lock) | **none** |

**Active STILL_DEFER (6):** D2 PRE_PLAN · D2 MISDATE · D4 earn_cal · D4 bars_am · D5 OTC archive · MX-EARN-TIP `2026-01…04`.

**OUT_OF_SCOPE (12):** D1×2 · D3 · D6×2 · D7×2 · D9 · D10 · MX-DIV · MX-DET · MX-EARN-PRE.

Full mapping: residual SoT §W38 · `.glm-logs/w0815ae_defer/NO_DENSIFY_AFTER_CONTRACT_DRAFT.json`.

---

## 4. Permanent DEFER (reasons)

| id | dataset(s) | why | retry |
|----|------------|-----|-------|
| **PD-D2-MASTER** | `equities_master` | tip-misdated Date; not always-empty | in-scope Date + window_ok seal |
| **PD-D4-EARN-CAL** | `equities_earnings_calendar` | tip-only vendor | historical API or catalog de-scope |
| **PD-D4-BARS-AM** | `equities_bars_daily_am` | `date_mode=today` AM | historical AM API or use daily OHLC |
| **PD-D5-JSDA-OTC** | `jsda_otc_bond_reference_prices` | site capability; tip 72 island | HTTP 200 + R2 raw day-by-day |
| **PD-MX-EARN-TIP** | `fins_earnings_date` `2026-01…04` | tip holes survive floor raise | vendor nz for tip months |

Detail: [`.glm-logs/w0815ae_defer/PERMANENT_DEFER.json`](../../.glm-logs/w0815ae_defer/PERMANENT_DEFER.json).

---

## 5. PRE / POST metrics — **pending reeval**

| Metric | PRE (W36 baseline) | POST (W38) | role |
|--------|-------------------:|-----------:|------|
| Segment COMPLETE total | **3457** (`596e721` / W36) | **pending reeval** | PRIMARY — G5 fill |
| `raw_retention_manifests` | **15589** (W36 tip POST) | **pending reeval** | secondary |
| Dataset COMPLETE | **11** | **pending reeval** | held unless reeval says otherwise |
| empty COMPLETE | **0** | **0** expected (ban held) | ban |
| densify executed | none | **false** | NO_DENSIFY |
| Contract floors raised | 0 (W29 propose only) | **11** | this wave |
| Active NO_DENSIFY classes | **18** | **6** | residual re-align |
| JSDA OTC COMPLETE | **72** | **72** expected (D5 held) | D5 |
| FRESH generation | `projgen-cbb5d486…` (W36) | **pending reeval** | G5 fill |

**NOTE:** Contract raise alone does not invent COMPLETE segs. OOS pre-floor PARTIALs may remain in inventory until human-gate prune/reagg — densify still forbidden. Peer T2 reeval / G5 ops close owns final POST numbers.

---

## 6. Policy holds

| gate | status |
|------|--------|
| empty-raw COMPLETE | **forbidden** |
| tip densify | secondary — non-DEFER tip holes only |
| permanent DEFER densify | **forbidden** |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| CF-SoT | D1 hot tip · R2 history · receipt-owned COMPLETE |
| force-apply publish | fail-closed when local COMPLETE < remote |

---

## 7. G5 fill checklist (placeholder)

- [ ] Remote D1 COMPLETE segs POST
- [ ] Dataset COMPLETE count POST
- [ ] raw_retention_manifests POST
- [ ] FRESH `projgen-*` after any reeval/publish
- [ ] Confirm HAS_RAW_SEALABLE still **0** / post_floor sealable **0**
- [ ] Confirm MX-EARN-TIP still DEFER (4 tip months)
- [ ] Push SHA (if G5 pushes all)

---

## 8. Related proofs

| doc | role |
|-----|------|
| [`observed_floor_catalog_20260815.md`](observed_floor_catalog_20260815.md) | W29 observed floors + raise candidates |
| [`w0815v_w29_floor_contract_ops_20260815.md`](w0815v_w29_floor_contract_ops_20260815.md) | W29 floor lock (raises **not** implemented then) |
| [`docs/phase62_residual_status.md`](../phase62_residual_status.md) §W38 | residual DEFER + NO_DENSIFY SoT after raise |
| `.glm-logs/w0815ae_contract/contract_diff.json` | machine before/after |
| `.glm-logs/w0815ae_defer/*` | Permanent DEFER + NO_DENSIFY mapping drafts |
