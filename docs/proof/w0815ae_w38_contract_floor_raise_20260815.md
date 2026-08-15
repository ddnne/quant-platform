# W38 / w0815ae — contract floor raise + residual DEFER re-align + reeval (FINAL) (2026-08-15)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** ban held (PRE **0** → POST **0**)  
**densify:** **none** (this wave — contract floors + inventory replan only; **no tip densify as primary**)  
**DEFER densify re-run:** **not** done  
**Contract `history_target_start` raise:** **implemented** — **11** floors raised (`ba3c811`)  
**Primary metric (COMPLETE segs):** **3457 → 3457 (Δ0)**  
**Dataset COMPLETE:** **11 → 20 (+9)**  
**Secondary metric (tip raw):** **not remeasured** this wave (no tip collect; held W36 **15589**)

**Live verified:** 2026-08-15 (JST) / reeval PRE `2026-08-15T06:04:54Z` → POST `2026-08-15T06:11:48Z` UTC  
**Contract commit:** `ba3c81157c1528784e4909ca7e03e7c8076553c2`  
**Residual DEFER docs commit:** `ddbd823af28953bea659adfa970dd7301b81e3e3`  
**Proof HEAD (post-push):** `afd7189647331de2d977f3ce2018ca34135bb5c1`  
**Projection:** **FRESH** `projgen-c54a409aaeef424e9c13394b82bd720b` (fail-closed publish local=remote **3457**; mass=**NO-GO**)

**Floor catalog (evidence):** [`observed_floor_catalog_20260815.md`](observed_floor_catalog_20260815.md)  
**Residual SoT:** [`docs/phase62_residual_status.md`](../phase62_residual_status.md) §W38  
**Machine:**

| track | path |
|-------|------|
| Contract diff (T1) | [`.glm-logs/w0815ae_contract/contract_diff.json`](../../.glm-logs/w0815ae_contract/contract_diff.json) |
| Permanent DEFER (T4) | [`.glm-logs/w0815ae_defer/PERMANENT_DEFER.json`](../../.glm-logs/w0815ae_defer/PERMANENT_DEFER.json) |
| NO_DENSIFY re-align (T5) | [`.glm-logs/w0815ae_defer/NO_DENSIFY_AFTER_CONTRACT_DRAFT.json`](../../.glm-logs/w0815ae_defer/NO_DENSIFY_AFTER_CONTRACT_DRAFT.json) |
| Reeval delta (T2/T3) | [`.glm-logs/w0815ae_reeval/REEVAL_DELTA.json`](../../.glm-logs/w0815ae_reeval/REEVAL_DELTA.json) |
| PRE / POST snapshots | `.glm-logs/w0815ae_reeval/{PRE,POST}_snapshot.json` |
| Reeval summary | [`.glm-logs/w0815ae_reeval/SUMMARY.md`](../../.glm-logs/w0815ae_reeval/SUMMARY.md) |

CF-SoT held entire wave: **D1 = hot tip · R2 = history · COMPLETE = receipt-owned**.

---

## 1. Parallel agent split (W38 / w0815ae)

| lane | tasks | owner / logs | outcome |
|------|-------|--------------|---------|
| **T1 contract raises** | Raise `history_target_start` to proven observed floors (11) + aligned copies + tests | G1 · `.glm-logs/w0815ae_contract/` · commit `ba3c811` | **11** floors live; master/D4/D5 **not** raised |
| **T4 Permanent DEFER** | Inventory residual classes with no honest floor-raise cure | residual prep · `.glm-logs/w0815ae_defer/PERMANENT_DEFER.json` | **5** permanent entries formalized |
| **T5 NO_DENSIFY re-align** | Map W29 18 classes → after-raise OOS vs STILL_DEFER | residual prep · `NO_DENSIFY_AFTER_CONTRACT_DRAFT.json` | **18 → 6** active; **12** OUT_OF_SCOPE |
| **T2/T3 reeval** | PRE snapshot · inventory replan (OOS PARTIAL prune + sticky COMPLETE) · publish fail-closed · observed reeval ×11 · FRESH | `.glm-logs/w0815ae_reeval/` | Dataset COMPLETE **11→20 (+9)** · COMPLETE segs **Δ0** · empty **0** · FRESH `projgen-c54a409aaeef…` |
| **T11 contract review** | before→after table + catalog evidence | this proof §2 | matches `contract_diff.json` `count_changed=11` |
| **T10–T12 ops close** | residual POST · proof fill · push | this proof + residual SoT | POST numbers live · **POST_PUSH_SHA** · HEAD==origin |

**Not done:** densify · tip collect loop · empty-raw COMPLETE · Mass/READY/Phase7 · raise master/D4/D5 floors · invent COMPLETE by prune without reagg · force-apply publish.

---

## 2. T11 contract review — history_target_start (old → new + evidence)

Evidence column points at the canonical floor catalog (`observed_floor_catalog_20260815.md` §1) and residual DEFER ids. Machine twin: `.glm-logs/w0815ae_contract/contract_diff.json`.

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

## 3. PRE / POST metrics (remote D1 `quant-ingest`)

Primary = **COMPLETE segs** (must not invent). Dataset COMPLETE flips via honest floor replan + sticky COMPLETE only.

| Metric | PRE (reeval `06:04:54Z`) | POST (reeval `06:11:48Z`) | Δ | role |
|--------|-------------------------:|--------------------------:|--:|------|
| Segment COMPLETE total | **3457** | **3457** | **0** | **PRIMARY** |
| Dataset COMPLETE | **11** | **20** | **+9** | floor replan promote |
| empty COMPLETE | **0** | **0** | held | **ban held** |
| `raw_retention_manifests` | **15589** (W36 tip POST) | **not remeasured** | — | no tip collect this wave |
| densify executed | none | **false** | — | NO_DENSIFY |
| tip densify as primary | — | **false** (T7 held) | — | secondary only; not run |
| Contract floors raised | 0 (W29 propose only) | **11** | +11 | this wave |
| Active NO_DENSIFY classes | **18** | **6** | −12 | residual re-align |
| JSDA OTC COMPLETE | **72** | **72** | held | D5 |
| FRESH generation | prior W36 `projgen-cbb5d486…` | **`projgen-c54a409aaeef424e9c13394b82bd720b`** | reclocked | reeval publish |

### 3.1 Flipped to Dataset COMPLETE (+9)

OOS PARTIAL prune under new floors + sticky in-window COMPLETE → dataset reagg COMPLETE. **No new segment COMPLETE seals** (COMPLETE segs Δ0).

| dataset | old floor → new | OOS pruned (PARTIAL) | post required COMPLETE segs |
|---------|-----------------|---------------------:|----------------------------:|
| `equities_bars_daily` | 2004-01-05 → **2008-05-01** | 52 | 220 |
| `indices_bars_daily_topix` | 2008-01-01 → **2008-05-01** | 4 | 220 |
| `indices_bars_daily` | 2008-01-01 → **2008-05-01** | 4 | 220 |
| `fins_summary` | 2008-01-08 → **2008-07-01** | 6 | 218 |
| `fins_dividend` | 2008-01-08 → **2013-02-01** | 61 | 163 |
| `fins_details` | 2008-01-08 → **2018-01-01** | 120 | 104 |
| `markets_short_sale_report` | 2013-01-04 → **2013-11-01** | 10 | 154 |
| `edinet_cross_shareholdings` | 2018-01-04 → **2020-05-01** | 28 | 76 |
| `edinet_large_volume_shareholders` | 2018-01-04 → **2021-07-01** | 42 | 62 |

### 3.2 Still PARTIAL after reeval (6 datasets)

| dataset | PARTIAL segs | note |
|---------|-------------:|------|
| `equities_master` | **94** | NOT raised (D2 MISDATE / PRE_PLAN) — permanent DEFER |
| `equities_earnings_calendar` | **199** | tip-only vendor (D4) — permanent DEFER |
| `equities_bars_daily_am` | **31** | tip-only AM (D4) — permanent DEFER |
| `jsda_otc_bond_reference_prices` | **8709** | archive site (D5); tip island COMPLETE **72** |
| `fins_earnings_date` | **4** | tip holes `2026-01…04` (MX-EARN-TIP); pre-floor 96 OOS pruned |
| `markets_breakdown` | **1** | floor **2015-03-26**; residual **2015-03** thin-floor still DEFER (first full COMPLETE **2015-04**) |

### 3.3 Reeval path (no densify / no tip loop)

1. PRE remote snapshot (COMPLETE **3457** · Dataset COMPLETE **11** · empty **0**)
2. Local inventory replan from new floors: OOS PARTIAL prune + sticky COMPLETE + dataset_coverage reagg
3. `publish_ops_projection.py --apply-remote` fail-closed (local=remote **3457**; no force)
4. `ops_reeval_observed_window.py` ×11 raised datasets
5. `ops_reeval_freshness.py` → FRESH `projgen-c54a409aaeef424e9c13394b82bd720b`

---

## 4. NO_DENSIFY re-align summary

| metric | W29 (pre) | W38 (post) |
|--------|----------:|-----------:|
| NO_DENSIFY classes | **18** | **6** active |
| OUT_OF_SCOPE after raise | 0 | **12** |
| Permanent DEFER entries | (implicit in 18) | **5** formalized |
| densify executed | none (lock) | **none** |

**Active STILL_DEFER (6):** D2 PRE_PLAN · D2 MISDATE · D4 earn_cal · D4 bars_am · D5 OTC archive · MX-EARN-TIP `2026-01…04`.

**OUT_OF_SCOPE (12):** D1×2 · D3 · D6×2 · D7×2 · D9 · D10 · MX-DIV · MX-DET · MX-EARN-PRE.

Full mapping: residual SoT §W38 · `.glm-logs/w0815ae_defer/NO_DENSIFY_AFTER_CONTRACT_DRAFT.json`.

**Tip densify:** **not primary** this wave (T7 held). No tip collect loop. Secondary tip densify only applies to non-DEFER tip holes in collect waves — W38 is contract/reeval only.

---

## 5. Permanent DEFER list

| id | dataset(s) | class / span | why permanent | retry |
|----|------------|--------------|---------------|-------|
| **PD-D2-MASTER** | `equities_master` | MISDATE `2006-08…2008-04` (n=21) + PRE_PLAN `2000-07…2006-07` (n=73) | tip-misdated Date; not always-empty | in-scope Date + window_ok seal |
| **PD-D4-EARN-CAL** | `equities_earnings_calendar` | TIP_ONLY history (~199) | tip-only vendor | historical API or catalog de-scope |
| **PD-D4-BARS-AM** | `equities_bars_daily_am` | TIP_ONLY history (~31) | `date_mode=today` AM | historical AM API or use daily OHLC |
| **PD-D5-JSDA-OTC** | `jsda_otc_bond_reference_prices` | ARCHIVE beyond tip **72** | site capability | HTTP 200 + R2 raw day-by-day |
| **PD-MX-EARN-TIP** | `fins_earnings_date` | tip holes `2026-01…04` (n=4) | tip holes survive floor raise | vendor nz for tip months |

Detail: [`.glm-logs/w0815ae_defer/PERMANENT_DEFER.json`](../../.glm-logs/w0815ae_defer/PERMANENT_DEFER.json).

**Optional residual note:** `markets_breakdown` **2015-03** (1 month) remains PARTIAL under floor `2015-03-26` — thin-floor first partial month; densify **forbidden**; treat as DEFER thin-floor (not a Permanent DEFER id; first full COMPLETE is **2015-04**).

---

## 6. Policy holds

| gate | status |
|------|--------|
| empty-raw COMPLETE | **forbidden** — PRE/POST **0** |
| tip densify as primary | **not** (T7 held) |
| permanent DEFER densify | **forbidden** |
| densify this wave | **none** |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| CF-SoT | D1 hot tip · R2 history · receipt-owned COMPLETE |
| force-apply publish | fail-closed when local COMPLETE < remote (held; equal **3457**) |
| invent COMPLETE | **none** — sticky COMPLETE only; OOS PARTIAL prune does not mint segs |

---

## 7. Push / SHA lock

| item | value |
|------|------:|
| Contract | `ba3c81157c1528784e4909ca7e03e7c8076553c2` |
| Residual DEFER docs | `ddbd823af28953bea659adfa970dd7301b81e3e3` |
| Proof finalize | `afd7189647331de2d977f3ce2018ca34135bb5c1` |
| **POST_PUSH_SHA** | `afd7189647331de2d977f3ce2018ca34135bb5c1` |
| origin/main after push | equals HEAD after SHA-fill push |

---

## 8. Related proofs

| doc | role |
|-----|------|
| [`observed_floor_catalog_20260815.md`](observed_floor_catalog_20260815.md) | W29 observed floors + raise candidates |
| [`w0815v_w29_floor_contract_ops_20260815.md`](w0815v_w29_floor_contract_ops_20260815.md) | W29 floor lock (raises **not** implemented then) |
| [`docs/phase62_residual_status.md`](../phase62_residual_status.md) §W38 | residual DEFER + NO_DENSIFY SoT + live POST metrics |
| `.glm-logs/w0815ae_contract/contract_diff.json` | machine before/after |
| `.glm-logs/w0815ae_defer/*` | Permanent DEFER + NO_DENSIFY mapping |
| `.glm-logs/w0815ae_reeval/REEVAL_DELTA.json` | PRE/POST machine metrics |
