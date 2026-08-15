# Column / NULL audit — unified (2026-08-15)

**Wave:** `w0815m` / **W20** (G1–G5 merge)  
**Operator:** GLM 5.3 implementer (W20-G5 integration)  
**Peers merged:**

| Track | Role | Log / proof |
|-------|------|-------------|
| **G1** | Contract × live API key inventory | `.glm-logs/w0815m_g1_contract_api/` |
| **G2** | Typed specialized columns (bars/master/calendar) | `.glm-logs/w0815m_g2_typed_null/` · fix `df6271d` |
| **G3** | JSON payload null (generic `jquants_records`) | `.glm-logs/w0815m_g3_json_null/` (`AUDIT_REPORT.json`, `DEEP_SAME_ROW.json`) |
| **G4** | JSDA critical (`tokyo_repo_rows=0`) + field coverage | `.glm-logs/w0815m_g4_jsda_audit/` · [`w0815m_g4_jsda_audit_20260815.md`](w0815m_g4_jsda_audit_20260815.md) · fix `4fcef08` |
| **G5** | This merge + residual + push | this file |

**Authority:** CF SoT — live proxy (G1), R2 `quant-raw` + remote D1 `quant-ingest` payload (G2/G3), local research DB for JSDA facts (G4).  
**Mass / READY / Phase7:** **NO-GO / OFF**  
**Empty-raw COMPLETE:** **forbidden** (held)  
**Destructive:** none (mapping honesty only; no re-ingest / no COMPLETE flip)

---

## Executive summary

| Area | Finding | Verdict |
|------|---------|---------|
| Generic payload path (`jquants_records`) | Same-row payload vs raw_payload keyset **100% equal** across G3 deep sample; **no field drop** | **問題なし** (mapping) |
| Typed master (`normalize` / SCD2) | V2 short keys `S17`/`S33`/`Mkt*` were 100% unmapped → always-null typed | **要修正 → FIXED** (`df6271d`) |
| Typed bars | Core OHLC maps OK; `AAdj*` was false all-day Adj alias | **要修正 → FIXED** (`df6271d`) |
| Always-null source fields | Fins forecast/unit, options EC/EH/EL/EO/SQD, ExRT, listing_date, JSDA corp schema-superset | **DEFER** (source / schema) — do not invent |
| `tokyo_repo_rows=0` vs COMPLETE | Plane split: D1 fact empty vs receipt-owned COMPLETE; local **30303** facts match receipt | **問題なし** (not data loss); honesty UI **FIXED** (`4fcef08`) |
| Tip-only endpoints | `equities_bars_daily_am`, `equities_earnings_calendar` | **DEFER** (vendor contract; D4) |

---

## 1. Dataset × key audit tables

### 1.1 Track A — contract / live API keys (G1)

Live CF-jquants-proxy probe (`live_all.json`). Storage: production ingest is **generic_payload** (`jquants_records`); bars/master/calendar also have specialized normalize paths (local typed tables may be empty while D1 holds payload).

| dataset | endpoint | API keys (n) | NK (contract) | storage | dropped keys (generic) | gaps |
|---------|----------|-------------:|---------------|---------|------------------------|------|
| `equities_master` | `/v2/equities/master` | 14 | Code,Date | typed_capable + generic | none on generic; typed subset | short-name typed fix G2 |
| `equities_bars_daily` | `/v2/equities/bars/daily` | 44 | Code,Date | typed_capable + generic | none on generic | AAdj alias fix G2 |
| `equities_bars_daily_am` | `/v2/equities/bars/daily/am` | 8 | Code,Date | generic | none | **TIP_ONLY_ENDPOINT** |
| `fins_summary` | `/v2/fins/summary` | 111 | Code,DiscDate,DiscNo (+aliases) | generic | none | source always-null keys |
| `fins_details` | `/v2/fins/details` | 6 (+ nested FS) | Code,DiscDate,DiscNo | generic | none | — |
| `fins_dividend` | `/v2/fins/dividend` | 23 | Code,RefNo (+aliases) | generic | none | source always-null keys |
| `fins_earnings_date` | `/v2/fins/earnings-date` | 7 | Code,PubDate,SchDate | generic | none | — |
| `equities_earnings_calendar` | `/v2/equities/earnings-calendar` | 7 | Date,Code | generic | none | **TIP_CALENDAR_NOT_HISTORICAL_RANGE** |
| `markets_calendar` | `/v2/markets/calendar` | 2 | Date | typed_capable + generic | none | — |
| `equities_investor_types` | `/v2/equities/investor-types` | 56 | PubDate,Section | generic | none | — |
| `indices_bars_daily_topix` | `/v2/indices/bars/daily/topix` | 5 | Date | generic | none | — |
| `indices_bars_daily` | `/v2/indices/bars/daily` | 6 | Date,Code | generic | none | — |
| `derivatives_bars_daily_options_225` | `…/options/225` | 30 | Date,Code | generic | none | — |
| `derivatives_bars_daily_futures` | `…/futures` | 29 | Date,Code | generic | none | — |
| `derivatives_bars_daily_options` | `…/options` | 37 | Date,Code | generic | none | EC/EH/EL/EO/SQD always-null |
| `markets_margin_interest` | `/v2/markets/margin-interest` | 9 | Date,Code | generic | none | — |
| `markets_margin_alert` | `/v2/markets/margin-alert` | 20 | Code,PubDate,AppDate | generic | none | — |
| `markets_short_ratio` | `/v2/markets/short-ratio` | 5 | Date,S33 | generic | none | — |
| `markets_short_sale_report` | `/v2/markets/short-sale-report` | 14 | DiscDate,CalcDate,Code,DICName,FundName | generic | none | — |
| `markets_breakdown` | `/v2/markets/breakdown` | 16 | Date,Code | generic | none | — |
| `edinet_major_shareholders` | `/v2/edinet/major-shareholders` | 11 | Code,DocId | generic | none | — |
| `edinet_cross_shareholdings` | `/v2/edinet/cross-shareholdings` | 13 | Code,DocId | generic | none | — |
| `edinet_large_volume_shareholders` | `/v2/edinet/large-volume-shareholders` | 15 | Code,DocId | generic | none | — |
| JSDA OTC / corporate / tokyo_repo | JSDA site (governed) | n/a | per schema | typed fact tables | n/a | G4 plane split |

Full key lists: `.glm-logs/w0815m_g1_contract_api/*_keys.json`.

### 1.2 Track B — typed specialized (G2)

Remote D1 does **not** materialize specialized tables; typed audit = payload keys + whether `normalize.py` / SCD2 would produce NULL typed columns.

#### `equities_bars_daily`

| typed column | source keys | D1 Jul null (n=97696) | class |
|--------------|-------------|----------------------:|--------|
| code / date | Code / Date | 0% | required identity |
| open/high/low/close/volume/turnover | O H L C Vo Va | **5.34%** | legitimate source null (halt / no print) |
| adjustment_* | AdjO…AdjVo | **5.34%** | co-null with OHLC |
| (no typed) AdjFactor | AdjFactor | **0%** | discarded by design (payload only) |
| (no typed) ExRT | ExRT | **~99.99%** | source always-null-ish |
| (no typed) M*/A* session splits, MktCap, UL/LL | … | partial | discarded by design |

**Fix:** stop treating afternoon `AAdj*` as all-day `Adj*` fallbacks (`normalize_daily_bars`).

#### `equities_master`

| typed column | V2 live key | PRE typed null | POST | class |
|--------------|-------------|----------------|------|--------|
| company_name / _en | CoName / CoNameEn | 0% | 0% | ok |
| sector_17/33 code+name | **S17 / S17Nm / S33 / S33Nm** | **100%** | **0%** | **mapping bug → FIXED** |
| market_code / name | **Mkt / MktNm** | **100%** | **0%** | **mapping bug → FIXED** |
| scale_category | ScaleCat | 0% | 0% | ok |
| listing_date | *(absent on V2)* | **100%** | **100%** | always-missing source |
| Mrgn* / ProdCat | present 100% | n/a | n/a | discarded typed (payload only) |

D1 Aug window n=31115: every row has `S17`/`S33`/`Mkt`; zero long-name keys. SCD2 `write.ts` fixed in parallel.

#### `markets_calendar`

| typed | keys | null | class |
|-------|------|------|--------|
| date | Date | 0 | ok |
| holiday_division | HolDiv / HolidayDivision | 0 | ok |

### 1.3 Track C — JSON payload null (G3)

Landing path: R2 full API body; D1 `payload=stableJson(row)` + `raw_payload=JSON.stringify(row)`; **no field whitelist**; stableJson drops `undefined` only.

**Deep same-row (D1):** for all 16 audited datasets, `payload` vs `raw_payload` **keyset_equal_rate=1.0**, `mapping_drop=false`, `value_mismatches={}`.

| dataset | payload keys | always-null/empty (deep) | sparse (&lt;5%) | verdict (mapping) |
|---------|-------------:|--------------------------|----------------|-------------------|
| `fins_summary` | 111 | 11 (see list) | many forecast/2Q fields | **問題なし** (source nulls; false MAPPING_BUG on cross-sample) |
| `fins_details` | 6 + nested FS | 0 top-level | rare FS labels | **問題なし** |
| `fins_dividend` | 23 | 5 | — | **問題なし** (source) |
| `fins_earnings_date` | 7 | 0 | — | **問題なし** |
| `markets_margin_interest` | 9 | 0 | — | **問題なし** |
| `markets_margin_alert` | 20 | 0 | — | **問題なし** |
| `markets_short_ratio` | 5 | 0 | — | **問題なし** |
| `markets_short_sale_report` | 14 | 0 | — | **問題なし** |
| `markets_breakdown` | 16 | 0 | — | **問題なし** |
| `derivatives_bars_daily_futures` | 29 | 0 | — | **問題なし** |
| `derivatives_bars_daily_options` | 37 | 5 (EC/EH/EL/EO/SQD) | — | **問題なし** (source) |
| `derivatives_bars_daily_options_225` | 30 | 0 | — | **問題なし** |
| `edinet_*` (3) | 11–15 | 0 | — | **問題なし** |
| `equities_investor_types` | 56 | 0 | — | **問題なし** |

Note: initial G3 `AUDIT_REPORT` labeled `fins_summary` **MAPPING_BUG** by comparing raw page (n=414) vs D1 sample (n=200) always-null sets. Deep same-row on D1 n=300 shows **no drop** — sparse keys (`Div3Q`, `NxFNCEPS2Q`, …) appear at ~0.3–1% when sampled sufficiently. **Reclassified to SOURCE_NULLS / sparse.**

### 1.4 Track D — JSDA typed facts (G4)

Local `data/structured/ingestion.sqlite`:

| fact table | rows | coverage status | key null findings |
|------------|-----:|-----------------|-------------------|
| `jsda_otc_bond_reference_prices` | **702451** | PARTIAL | coupon_rate ~0.5%; avg yield ~0.35%; individual_investor_flag ~3.5%; identity/PIT 0% |
| `jsda_corporate_bond_transactions` | **156079** | COMPLETE | **always-empty schema-superset:** isin, buyer/seller counterparty, face/trade amount (100%); execution_price ~20% null; identity 0% |
| `jsda_repo_rates` (dataset `jsda_tokyo_repo_rates`) | **30303** | COMPLETE | rate/tenor/rate_type/raw_payload/available_at **0% null** |

---

## 2. Always-null / always-missing inventory + cause class

| dataset | field(s) | plane | cause class | action |
|---------|----------|-------|-------------|--------|
| `equities_master` | `listing_date` (ListingDate) | typed | **SOURCE_ALWAYS_MISSING** (V2 never sends) | DEFER — no invent |
| `equities_master` | sector/market typed (pre-fix) | typed | **MAPPING_BUG** (missed S17/Mkt short keys) | **FIXED** G2 |
| `equities_bars_daily` | `ExRT` | payload | **SOURCE_ALWAYS_NULL** (~100%) | DEFER observe |
| `equities_bars_daily` | OHLC ~5% | payload/typed | **LEGITIMATE_SOURCE_NULL** | ok |
| `equities_bars_daily` | `AAdj*` → all-day Adj (pre-fix) | typed | **MAPPING_BUG** (false alias) | **FIXED** G2 |
| `fins_summary` | DivUnit, FDiv1Q, FDivTotalAnn, FDivUnit, FPayoutRatioAnn, MatChgSub, NCROE, NxFDiv1Q, NxFDiv3Q, NxFDivUnit, NxFNCOP2Q | payload | **SOURCE_ALWAYS_NULL** (vendor leaves empty) | DEFER |
| `fins_summary` | Div3Q, NxFNCEPS2Q, NxFNCNP2Q, NxFNCOdP2Q, NxFNCSales2Q, … | payload | **SPARSE_SOURCE** (&lt;5% non-empty) | ok — not mapping |
| `fins_dividend` | DeemCapGains, DeemDiv, DistAmt, NetAssetDecRatio, RetEarn | payload | **SOURCE_ALWAYS_NULL** | DEFER |
| `derivatives_bars_daily_options` | EC, EH, EL, EO, SQD | payload | **SOURCE_ALWAYS_NULL** (evening/SQ empty on sample) | DEFER |
| `jsda_corporate_bond_transactions` | isin, buyer/seller_counterparty_type, face_value_mil_jpy, trade_amount_mil_jpy | typed | **SCHEMA_SUPERSET / SOURCE_EMPTY** | DEFER — do not invent |
| `jsda_tokyo_repo_rates` on D1 | whole fact table | D1 fact | **PLANE_SPLIT** (coverage projected; full history not on D1) | honesty FIXED G4; **hot tip** D1 **252** rows published 2026-08-15 (`publish_jsda_hot_to_d1.py`); not local loss |
| `equities_bars_daily_am` / `equities_earnings_calendar` | history | product | **TIP_ONLY / NO_HISTORICAL_RANGE** | DEFER D4 |

---

## 3. `tokyo_repo_rows=0` explanation (mandatory)

### Question

Why can `storage_plane_status.jsda.tokyo_repo_rows` be **0** while `jsda_tokyo_repo_rates` is dataset **COMPLETE**?

### Answer (root cause)

Two **independent** aggregates:

| Signal | Meaning | Owner |
|--------|---------|-------|
| `tokyo_repo_rows` | `COUNT(*)` on fact table **`jsda_repo_rates` on the DB plane queried** | `OpsCurrentReadService.storage_plane_status` / MCP `domain.js` |
| Dataset **COMPLETE** | Signed receipt + `coverage_segments` → `dataset_coverage.status` | `coverage_ledger` + ops projection |

Ops projection publishes **coverage ledgers**, not full JSDA fact backfill to D1. Architecture: D1 = control/hot tip; full structured history SoT = local research DB / R2 structured. High-volume history **must not** refill D1.

### Evidence

| Plane | `jsda_repo_rates` rows | `dataset_coverage` | Receipt |
|-------|----------------------:|--------------------|---------|
| **Local** research sqlite | **30303** | COMPLETE, row_count **30303** | run **83**, raw=structured=**30303**, TRUSTED, `2012-10-29`→`2026-08-10` |
| **D1** remote (prior quality scan) | **0** | COMPLETE (projected) | receipt-owned segment `jsda-era-timeseries` |

→ **`tokyo_repo_rows=0` on D1 is expected plane-split, not data loss and not receipt fraud.** Local facts match the sealed receipt.

Additional: `r2_parse` discover layout looks for `jsda_tokyo_repo_rates/` dataset dirs; production seal used date-stamped `data/raw/jsda/YYYY/MM/DD/` via `repo_archive` — discoverer can show 0 artifacts while governed seal already succeeded.

### Fix applied (G4, honesty only)

`storage_plane_status` now exposes:

- `jsda.coverage` (status, coverage_row_count, observed window)
- `jsda.coverage_vs_fact_divergence` (`COMPLETE_WITHOUT_LOCAL_FACTS` / count mismatch)
- `jsda.definition` (plane semantics for `tokyo_repo_rows`)

No re-ingest, no COMPLETE rewrite, no Mass change.

---

## 4. Summary per dataset — 問題なし / 要修正 / DEFER

| dataset | mapping / column health | residual coverage (separate) | column-audit verdict |
|---------|-------------------------|------------------------------|----------------------|
| `equities_master` | typed short keys **FIXED**; listing_date missing | PARTIAL (misdate DEFER D2) | **要修正→済** + listing **DEFER** |
| `equities_bars_daily` | OHLC OK; AAdj **FIXED**; ExRT source-null | PARTIAL (pre-2008-05 D7) | **要修正→済** + ExRT **DEFER** |
| `equities_bars_daily_am` | keys OK | tip-only COMPLETE 1 | **DEFER** tip product |
| `markets_calendar` | clean | COMPLETE | **問題なし** |
| `fins_summary` | no payload drop; source always-null keys | PARTIAL residual | **問題なし** (source DEFER fields) |
| `fins_details` | clean (nested FS sparse OK) | PARTIAL | **問題なし** |
| `fins_dividend` | source always-null 5 keys | PARTIAL | **問題なし** + fields **DEFER** |
| `fins_earnings_date` | clean | PARTIAL | **問題なし** |
| `equities_earnings_calendar` | clean keys | tip-only | **DEFER** tip product |
| `equities_investor_types` | clean | COMPLETE | **問題なし** |
| `indices_bars_daily(_topix)` | clean keys | PARTIAL empty pre-2008-05 D1 | **問題なし** (coverage DEFER) |
| `markets_margin_interest` | clean | COMPLETE | **問題なし** |
| `markets_margin_alert` | clean | COMPLETE | **問題なし** |
| `markets_short_ratio` | clean | COMPLETE | **問題なし** |
| `markets_short_sale_report` | clean | PARTIAL pre-hist D9 | **問題なし** |
| `markets_breakdown` | clean | PARTIAL pre-2015 D3 | **問題なし** |
| `derivatives_bars_daily_futures` | clean | COMPLETE | **問題なし** |
| `derivatives_bars_daily_options` | EC/EH/EL/EO/SQD source-null | COMPLETE | **問題なし** + fields **DEFER** |
| `derivatives_bars_daily_options_225` | clean | COMPLETE | **問題なし** |
| `edinet_major_shareholders` | clean | COMPLETE | **問題なし** |
| `edinet_cross_shareholdings` | clean | PARTIAL empty pre-island D6 | **問題なし** |
| `edinet_large_volume_shareholders` | clean | PARTIAL empty pre-island D6 | **問題なし** |
| `jsda_tokyo_repo_rates` | facts full local; D1 count plane-split | COMPLETE | **問題なし** (honesty **FIXED**) |
| `jsda_corporate_bond_transactions` | schema-superset always-empty cols | COMPLETE | **問題なし** + cols **DEFER** |
| `jsda_otc_bond_reference_prices` | sparse legitimate nulls | PARTIAL archive D5 | **問題なし** (coverage DEFER) |

---

## 5. Fixes applied this wave (code)

| Commit | Change |
|--------|--------|
| `df6271d` | `normalize.py` master V2 short aliases + bars AAdj not all-day; SCD2 `write.ts` same; tests; Track B proof section |
| `4fcef08` | `storage_plane_status` JSDA coverage + divergence honesty (Python + MCP); G4 proof |

**Tests:** `pytest tests/test_jquants_normalize.py` → **16 passed**.

**Not done:** historical specialized re-materialize; D1 JSDA fact backfill; schema expansion for AdjFactor/Mrgn/session splits; Mass/READY/Phase7.

---

## 6. Leak-check

| Gate | Status |
|------|--------|
| Empty-raw COMPLETE ban | **held** |
| Mass / READY / B0 | **NO-GO** |
| Phase 7 | **OFF** |
| Destructive DROP/rewrite | **none** |
| Dual-issue / peer kill | **n/a** (docs+mapping only) |

---

## 7. Evidence index

```
.glm-logs/w0815m_g1_contract_api/   live_all.json, *_keys.json, audit_full.json, table.md
.glm-logs/w0815m_g2_typed_null/     r2_*.json, d1_*.json, audit_summary.json
.glm-logs/w0815m_g3_json_null/      AUDIT_REPORT.json, DEEP_SAME_ROW.json, samples/, d1/
.glm-logs/w0815m_g4_jsda_audit/     audit_local.json, residual.md
docs/proof/w0815m_g4_jsda_audit_20260815.md
docs/proof/data_quality_scan_20260812.md   # prior D1 jsda_repo_rates=0
```

---

## 8. Orchestrator report (W20-G5)

1. **commits (wave):** `df6271d` (G2 typed), `4fcef08` (+ lock `07e6a67`), `5b5c146` (G1 docs), `2210813` (G3 docs), `f818d3f` (G5 unify)
2. **push SHA:** `f818d3f30b2ee10bf6606e591c3cd05dff6e68fa`
3. **audit summary table:** §4
4. **always-null list:** §2
5. **fixes applied:** master short keys, bars AAdj, tokyo_repo honesty (§5)
6. **remaining issues:** source always-null fields; tip-only am/earn calendar; JSDA corp schema-superset empties; D1 fact plane empty by design; coverage DEFERs D1–D9 unchanged