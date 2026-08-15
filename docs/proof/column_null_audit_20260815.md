# Column / typed NULL audit — 2026-08-15

**Waves:** w0815m / **W20-G1 Track A** (contract vs API keys) + **W20-G2 Track B** (typed NULL mapping) + **W20-G3 Track B** (JSON payload NULL)  
**Operator:** GLM 5.3 implementer  
**Authority:** CF SoT — R2 `quant-raw` + R2 `quant-structured` + remote D1 `quant-ingest` (`jquants_records.payload` / residual hot); live CF-proxy for G1 key samples. Local raw/sqlite tip is corroborative when live tip window is closed.  
**Mass / READY / Phase7:** **NO-GO**  
**Logs:** `.glm-logs/w0815m_g1_contract_api/` (G1) · `.glm-logs/w0815m_g2_typed_null/` (G2) · `.glm-logs/w0815m_g3_json_null/` (G3)

---

## Track B — specialized typed mapping (bars / master / calendar)

Scope datasets:

| dataset | specialized table (local schema) | CF hot fact plane |
|---------|----------------------------------|-------------------|
| `equities_bars_daily` | `jquants_daily_bars` (OHLC/V/Turnover/Adjustment*) | `jquants_records` where `dataset='equities_bars_daily'` (full payload JSON) |
| `equities_master` | `jquants_listed_info` | `jquants_records` / master SCD2 writer |
| `markets_calendar` | `jquants_market_calendar` | `jquants_records` |

Remote D1 does **not** materialize specialized typed tables (only `jquants_records*`). Typed-column audit is therefore: (1) keys present in CF payload/raw, (2) whether `normalize.py` / SCD2 mapper would produce NULL typed columns from those keys.

### SoT samples (non-empty)

| source | object / window | rows | empty-raw? |
|--------|-----------------|------|------------|
| R2 raw | `raw/equities_bars_daily/10718/page-000001.json` (2018-12-06..) | 3954 | no |
| R2 raw | `raw/equities_master/9962/page-000001.json` (Date=2026-08-13) | 4443 | no |
| R2 raw | `raw/markets_calendar/13253/page-000001.json` | 6 | no |
| D1 hot | bars `Date` ∈ 2026-07-01..07-31 | 97696 | n/a |
| D1 hot | master `Date` ∈ 2026-08-01..08-13 | 31115 | n/a |
| D1 hot | calendar (full hot) | 42 | n/a |
| Live proxy (W20-G1) | `/v2/equities/bars/daily`, `/v2/equities/master`, `/v2/markets/calendar` | see `w0815m_g1_contract_api/*_keys.json` | no |

---

## 1. `equities_bars_daily`

### API / payload keys (V2 short — CF SoT)

```
Code Date O H L C Vo Va UL LL
AdjFactor AdjO AdjH AdjL AdjC AdjVo
MO MH ML MC MUL MLL MVo MVa MAdjO MAdjH MAdjL MAdjC MAdjVo
AO AH AL AC AUL ALL AVo AVa AAdjO AAdjH AAdjL AAdjC AAdjVo
MktCap ExRT
```

### Specialized typed columns (`jquants_daily_bars` / `normalize_daily_bars`)

| typed column | source keys (post-fix) | D1 Jul null rate | R2 page null rate | class |
|--------------|--------------------------|------------------|-------------------|--------|
| `code` | `Code` | 0 | 0 | required identity |
| `date` | `Date` | 0 | 0 | required identity |
| `open` | `Open`/`O` | 5222/97696 (**5.34%**) | 75/2000 sample-window ≈3.8% full page | **legitimate source null** (halted / no trade) |
| `high`/`low`/`close` | `H`/`L`/`C` | same 5.34% | same | same |
| `volume`/`turnover_value` | `Vo`/`Va` | same 5.34% | same | same |
| `adjustment_*` | `AdjO`…`AdjVo` (not `AAdj*`) | same 5.34% | same | co-null with OHLC |
| (no typed col) | `AdjFactor` | **0% null** | **0%** | **discarded by design** (kept in payload/raw only) |
| (no typed col) | `UL`/`LL`, morning `M*`, afternoon `A*`, `MktCap` | partial | partial | **discarded by design** (session split / meta) |
| (no typed col) | `ExRT` | ~99.99% null | **100%** on sample pages | **source always-null-ish** (field present, value null) |

### Mapping findings

1. **Core OHLC/V/Turnover/Adj\* mapping is correct** for V2 short names (`O`/`H`/`L`/`C`/`Vo`/`Va`/`AdjO`…). Null rates on typed metrics track the source, not a dropped-key bug.
2. **False alias removed:** `AAdjO`/`AAdjH`/`AAdjL`/`AAdjC`/`AAdjVo` were listed as fallbacks for all-day `adjustment_*`. On V2 these are **afternoon-session** adjusted series, not aliases. When all-day `Adj*` is null, afternoon must not silently fill typed all-day columns. Fix in `normalize_daily_bars`.
3. **Discarded fields (intentional for specialized table):** `AdjFactor`, limit flags, morning/afternoon split OHLCV, `MktCap`, `ExRT`. Full fidelity remains in CF `payload` / R2 raw (empty-raw ban holds). Optional follow-up: promote `adjustment_factor` (`AdjFactor`) into specialized schema if research paths need typed access without JSON extract.

### Bars null classification

| class | columns / fields |
|-------|------------------|
| Legitimate source null | OHLC / volume / turnover / Adj* when no session print (~5% Jul hot) |
| Always present non-null source | `Code`, `Date`, `AdjFactor`, `UL`/`LL` (string flags) |
| Always-null source value | `ExRT` (key present, value null almost always) |
| Mapping bug (fixed) | `AAdj*` mis-aliased to all-day adjustment |
| Discarded (not typed) | session splits, `AdjFactor`, `MktCap`, limits |

---

## 2. `equities_master`

### API / payload keys (V2 short — CF SoT)

```
Date Code CoName CoNameEn S17 S17Nm S33 S33Nm ScaleCat Mkt MktNm Mrgn MrgnNm ProdCat
```

**Not published** on `/v2/equities/master`: `ListingDate` / `ListDate`, long names (`CompanyName`, `Sector17Code`, `MarketCode`, …).

### Specialized typed columns (`jquants_listed_info` / `normalize_listed_info`)

| typed column | pre-fix aliases | V2 live key | PRE null (typed mapping) | POST null | class |
|--------------|------------------|-------------|---------------------------|-----------|--------|
| `company_name` | `CompanyName`/`CoName` | `CoName` | 0% | 0% | ok |
| `company_name_en` | …/`CoNameEn` | `CoNameEn` | 0% | 0% | ok |
| `sector_17_code` | `Sector17Code`/`Sec17Code` only | **`S17`** | **100%** | **0%** | **mapping bug → fixed** |
| `sector_17_name` | …/`Sec17CodeName` | **`S17Nm`** | **100%** | **0%** | **mapping bug → fixed** |
| `sector_33_code` | …/`Sec33Code` | **`S33`** | **100%** | **0%** | **mapping bug → fixed** |
| `sector_33_name` | … | **`S33Nm`** | **100%** | **0%** | **mapping bug → fixed** |
| `scale_category` | `ScaleCategory`/`ScaleCat` | `ScaleCat` | 0% | 0% | ok |
| `market_code` | `MarketCode`/`MktCode` only | **`Mkt`** | **100%** | **0%** | **mapping bug → fixed** |
| `market_name` | …/`MktCodeName` | **`MktNm`** | **100%** | **0%** | **mapping bug → fixed** |
| `listing_date` | `ListingDate`/`ListDate` | *(absent)* | **100%** | **100%** | **always-missing from source** (not a mapping miss) |

D1 evidence (2026-08-01..08-13, n=31115): every row has `S17`/`S33`/`Mkt` and **zero** long-name keys — pre-fix specialized mapping would have produced **31 115/31 115 null** for sector and market typed columns.

### SCD2 path (same bug class)

`platform/workers/ingestion-premium/src/master_scd2/write.ts` `payloadToMasterRecord` only read long names / missed `CoName`, `S17*`, `S33*`, `Mkt*`, `ScaleCat`. Fixed in parallel with Python normalize.

### Discarded (not in specialized schema)

| field | notes |
|-------|-------|
| `Mrgn` / `MrgnNm` | margin eligibility code/name — present 100%, kept in payload only |
| `ProdCat` | product category — present 100%, kept in payload only |

### Master null classification

| class | columns |
|-------|---------|
| Mapping bug (fixed) | sector_17/33 code+name, market code+name under V2 short keys |
| Always-missing source | `listing_date` (ListingDate never on V2 master) |
| Legitimate non-null source | CoName*, ScaleCat, S*, Mkt*, Mrgn*, ProdCat on live window |
| Discarded typed | Mrgn*, ProdCat |

---

## 3. `markets_calendar`

### API keys

```
Date HolDiv
```

### Typed columns

| typed column | keys | D1 hot null | R2 null | class |
|--------------|------|-------------|---------|--------|
| `date` | `Date` | 0/42 | 0/6 | ok |
| `holiday_division` | `HolidayDivision`/`HolDiv` | 0/42 | 0/6 | ok |

No discarded fields. No mapping bug. No always-null typed column.

---

## Fixes shipped (this ticket)

| file | change |
|------|--------|
| `packages/data_plane/ingestion/jquants/normalize.py` | Master: add `S17`/`S17Nm`/`S33`/`S33Nm`/`Mkt`/`MktNm`. Bars: stop treating `AAdj*` as all-day Adj aliases. |
| `platform/workers/ingestion-premium/src/master_scd2/write.ts` | Same V2 short-key coverage for SCD2 `MasterRecord`. |
| `tests/test_jquants_normalize.py` | `test_listed_info_v2_live_short_names`, `test_bars_aadj_is_not_all_day_adjustment_alias`. |

**Tests:** `python3 -m pytest tests/test_jquants_normalize.py -q` → **16 passed**.

**Not done (explicit non-claims):**

- No re-ingest / D1 rewrite of historical specialized rows (CF hot is generic payload — already complete).
- No schema expansion for `AdjFactor` / `Mrgn` / session split columns.
- No Mass ON / READY / Phase7 / empty-raw accept.

---

## Evidence paths

```
.glm-logs/w0815m_g2_typed_null/
  r2_bars_page.json
  r2_master_page.json
  r2_calendar_page.json
  d1_bars_jul2026.json
  d1_master_aug2026.json
  audit_summary.json
  pytest_normalize.log
```

Cross-check live key inventory: `.glm-logs/w0815m_g1_contract_api/{equities_bars_daily,equities_master,markets_calendar}_keys.json`.

---

## Verdict (Track B)

| dataset | always-null typed (pre) | root cause | status |
|---------|-------------------------|------------|--------|
| equities_bars_daily OHLC/V/Adj* | no (≈5% source null) | n/a | **PASS** mapping; Adj false-alias hardened |
| equities_master sector/market | **yes (100%)** | missing V2 short aliases | **FIXED** |
| equities_master listing_date | yes (100%) | source never sends field | **classified — no code fix** |
| markets_calendar | no | n/a | **PASS** |

**Track B GO for mapping correctness after fix.** Storage plane remains generic-payload SoT; specialized tables only used on local Python paths / SCD2 attrs.

---

## Track A — contract vs live API key inventory (W20-G1)

**Wave:** w0815m / W20-G1  
**Scope:** all 23 datasets in `packages/data_plane/data_contracts/jquants_premium_core.json`  
**Transport:** CF secret-proxy (`cf-jquants-proxy`), ~1–few day windows; fins after general; rate ~≤500/min  
**Artifacts (key lists only, no secrets / no full payloads):** `.glm-logs/w0815m_g1_contract_api/`  
**Mass / READY / Phase7:** **NO-GO**

### Method

1. Live `JQuantsClient.fetch_dataset` via CF proxy for each Premium path (params corrected per vendor 400 messages: derivatives need `date`; indices need `date|code`; short-ratio needs `date|s33`; dividend needs `date|code` not bare from/to).
2. When live empty (AM tip expired after ~06:00 next day on weekend; sparse EDINET days), corroborate keys from non-empty tip `jquants_records.payload` / retained raw (same key surface).
3. Diff contract `natural_key_fields` + `field_aliases` + path against sampled keys; smoke `identity.natural_key` on live rows.
4. Classify storage: specialized typed normalize vs catalog `normalize_generic` → `jquants_records` payload/raw_payload.

### Storage classification (production)

| class | datasets | notes |
|-------|----------|-------|
| **typed_capable__generic_production** | `equities_bars_daily`, `equities_master`, `markets_calendar` | `normalize_daily_bars` / `normalize_listed_info` / `normalize_market_calendar` exist; catalog ingest always uses `normalize_generic`. Local specialized tables currently **0** rows; CF hot is **generic payload**. |
| **generic_payload** | remaining **20** Premium datasets | `normalize_generic` → `jquants_records.payload` + `raw_payload` (full row retained; no key drop). |

### Contract vs API — summary table

| dataset | endpoint | API keys sample (n) | contract NK / aliases | storage | dropped keys? | gaps |
|---------|----------|---------------------|----------------------|---------|---------------|------|
| `equities_master` | `/v2/equities/master` | 14: `Code,Date,CoName,CoNameEn,S17,S17Nm,S33,S33Nm,ScaleCat,Mkt,MktNm,Mrgn,MrgnNm,ProdCat` | NK=`Code,Date` | typed_capable / generic prod | specialized: `Mrgn*`/`ProdCat` payload-only (intentional); long names absent on V2 | — (short aliases **FIXED** W20-G2) |
| `equities_bars_daily` | `/v2/equities/bars/daily` | 44 short OHLCV + Adj/M/A splits + `MktCap,ExRT,AdjFactor` | NK=`Code,Date` | typed_capable / generic prod | specialized maps all-day O/H/L/C/Vo/Va/Adj*; session splits / AdjFactor / limits payload-only | — |
| `equities_bars_daily_am` | `/v2/equities/bars/daily/am` | 8: `Code,Date,MO,MH,ML,MC,MVo,MVa` | NK=`Code,Date` | generic | none | **TIP_ONLY** (no historical `date`; empty after tip window) |
| `fins_summary` | `/v2/fins/summary` | 111 incl. `Code,DiscDate,DiscNo,DiscTime` | NK=`Code,DiscDate,DiscNo` aliases Disc*↔Disclosed* | generic | none | — (live uses short `Disc*`) |
| `fins_details` | `/v2/fins/details` | 6: `Code,DiscDate,DiscNo,DiscTime,DocType,FS` | same Disc aliases | generic | none | — |
| `fins_dividend` | `/v2/fins/dividend` | 23 incl. `CARefNo` (not `RefNo`) | NK=`Code,RefNo` aliases `CARefNo` | generic | none | — NK resolves via alias |
| `fins_earnings_date` | `/v2/fins/earnings-date` | 7: `Code,PubDate,SchDate,CoName,CoNameEn,FQName,FYE` | NK=`Code,PubDate,SchDate` | generic | none | — |
| `equities_earnings_calendar` | `/v2/equities/earnings-calendar` | 7: `Date,Code,CoName,FQ,FY,Section,SectorNm` | NK=`Date,Code` | generic | none | **TIP_CALENDAR** (not historical range) |
| `markets_calendar` | `/v2/markets/calendar` | 2: `Date,HolDiv` | NK=`Date` | typed_capable / generic prod | HolDiv mapped | — |
| `equities_investor_types` | `/v2/equities/investor-types` | 56 incl. `PubDate,Section,EnDate` | NK=`PubDate,Section` | generic | none | — |
| `indices_bars_daily_topix` | `/v2/indices/bars/daily/topix` | 5: `Date,O,H,L,C` | NK=`Date` | generic | none | — |
| `indices_bars_daily` | `/v2/indices/bars/daily` | 6: `Date,Code,O,H,L,C` | NK=`Date,Code` | generic | none | — (API requires `date` or `code`) |
| `derivatives_bars_daily_options_225` | `/v2/derivatives/bars/daily/options/225` | 30 | NK=`Date,Code` | generic | none | — (API requires `date`) |
| `derivatives_bars_daily_futures` | `/v2/derivatives/bars/daily/futures` | 29 | NK=`Date,Code` | generic | none | — (API requires `date`) |
| `derivatives_bars_daily_options` | `/v2/derivatives/bars/daily/options` | 37 | NK=`Date,Code` | generic | none | — (API requires `date`) |
| `markets_margin_interest` | `/v2/markets/margin-interest` | 9 | NK=`Date,Code` | generic | none | — |
| `markets_margin_alert` | `/v2/markets/margin-alert` | 20 incl. `Code,PubDate,AppDate` | NK=`Code,PubDate,AppDate` | generic | none | — |
| `markets_short_ratio` | `/v2/markets/short-ratio` | 5: `Date,S33,SellExShortVa,ShrtNoResVa,ShrtWithResVa` | NK=`Date,S33` | generic | none | — (API requires `date` or `s33`) |
| `markets_short_sale_report` | `/v2/markets/short-sale-report` | 14 incl. `DiscDate,CalcDate,Code,DICName,FundName` | NK=5-field composite | generic | none | — |
| `markets_breakdown` | `/v2/markets/breakdown` | 16 | NK=`Date,Code` | generic | none | — |
| `edinet_major_shareholders` | `/v2/edinet/major-shareholders` | 11 incl. `Code,DocId,SubDate,SubTime` | NK=`Code,DocId` | generic | none | sparse days (sampled historical date) |
| `edinet_cross_shareholdings` | `/v2/edinet/cross-shareholdings` | 13 | NK=`Code,DocId` | generic | none | sparse days |
| `edinet_large_volume_shareholders` | `/v2/edinet/large-volume-shareholders` | 15 | NK=`Code,DocId` | generic | none | — |

Per-dataset key JSON: `.glm-logs/w0815m_g1_contract_api/{dataset_id}_keys.json` + `audit_full.json` + `table.md`.

### Natural-key smoke (live rows → `identity.natural_key`)

| dataset | result |
|---------|--------|
| `fins_summary` | `{"Code",DiscDate,DiscNo}` — no hash fallback |
| `fins_dividend` | `RefNo` filled from live `CARefNo` via contract alias |
| `equities_master` | `{"Code","Date"}` |
| `markets_calendar` | `{"Date"}` |
| `markets_short_ratio` | `{"Date","S33"}` |
| `markets_short_sale_report` | 5-field composite OK |

**No NK_MISSING across Premium 23.** Contract paths all match live `/v2/...` surfaces.

### Residual non-mapping gaps (product / vendor — not normalize bugs)

| flag | datasets | disposition |
|------|----------|-------------|
| `TIP_ONLY_ENDPOINT` | `equities_bars_daily_am` | Vendor same-day AM only until ~06:00 next day; contract lists `params:["code","date"]` but historical date is not supported. History DEFER (see `w0815b_g11_earn_am`). Keys from tip structured store when live window closed. |
| `TIP_CALENDAR_NOT_HISTORICAL_RANGE` | `equities_earnings_calendar` | Next-business-day tip calendar; range params ignored by vendor. History DEFER. |

No empty-raw accept. No invented fields. No Mass ON.

### Track A code changes

None required beyond W20-G2 (`df6271d`) master short-key + bars `AAdj*` fix already on `main`. Catalog path remains generic for all Premium datasets; empty-raw ban held.

### JSDA governed (brief, out of JQ Premium sample)

From `packages/data_plane/data_contracts/jsda_governed.json` (schema v1):

| dataset_id | product | natural_key_fields | history_target_start |
|------------|---------|--------------------|----------------------|
| `jsda_otc_bond_reference_prices` | 公社債店頭売買参考統計値 | source, publication_label_date, security_code, bond_name | 2002-08-02 |
| `jsda_tokyo_repo_rates` | 東京レポ・レート | source, as_of_date, tenor, rate_type | 2012-10-29 |
| `jsda_corporate_bond_transactions` | 社債の取引情報 | source, publication_label_date, trade_date, security_code, source_record_id | 2015-11-04 |

JSDA is archive/file ingest (CSV/XLS), not J-Quants REST; storage via JSDA-specific tables / normalize — not `jquants_records`.

### Verdict (Track A)

| check | status |
|-------|--------|
| All 23 Premium paths sampled (live and/or non-empty SoT payload) | **PASS** |
| Contract NK present (direct or alias) on live shape | **PASS** |
| Generic path retains full keys | **PASS** |
| Typed path mapping bugs for master/bars | **FIXED** (W20-G2) |
| AM / earnings calendar historical capability | **DEFER** (vendor tip-only — documented) |
| Mass / READY | **NO-GO** |

---

## Track B — JSON payload NULL audit (W20-G3)

**Wave:** w0815m / **W20-G3**  
**Scope:** generic `jquants_records` **payload / raw_payload** for priority datasets (fins / markets / derivatives / edinet / investor_types)  
**SoT:** CF R2 raw pages + R2 structured JSONL + D1 residual hot rows  
**Empty-raw ban:** only COMPLETE manifests with `row_count > 0`  
**Mass / READY / Phase7:** **NO-GO**  
**Artifacts:** `.glm-logs/w0815m_g3_json_null/` (`AUDIT_REPORT.json`, `DEEP_SAME_ROW.json`, `R2_STRUCTURED_SAMPLE.json`, `FINAL_VERDICT.json`, raw/structured samples)

### 1. How records land in `jquants_records` (and R2 structured)

Premium-core ingest is CF-native (`platform/workers/ingestion-premium`):

| stage | what is written |
|-------|-----------------|
| API page | `parsed.data[]` rows — **no field whitelist / no drop** |
| R2 raw | full response body → `quant-raw/raw/{dataset}/{run_id}/page-*.json` + manifest |
| structured record | `payload = stableJson(row)` (sorted keys; **undefined only** stripped); `raw_payload = JSON.stringify(row)` |
| write path | Premium core → **R2-only** structured JSONL (`structured/jsonl/{dataset}/dt=…/{runId}.jsonl`); D1 `jquants_records` is residual hot / legacy tip, not full history |

```ts
// platform/workers/ingestion-premium/src/index.ts — upsertRecords
const payload = stableJson(row);
// ...
rawPayload: JSON.stringify(row),
```

```ts
// platform/workers/ingestion-premium/src/identity.ts — stableJson
// undefined keys dropped; null / "" preserved as JSON null / empty string
```

**Implication:** any always-null value in payload is either (a) present empty from the API, or (b) a same-row drop vs `raw_payload`. There is no intermediate typed flatten for these generic datasets.

### 2. Method

1. For each priority dataset, pick a non-empty COMPLETE `raw_retention_manifests` row; download R2 raw page(s); compute key presence / null-or-empty rates on API `data[]`.
2. Sample D1 `jquants_records` residual rows (`payload`, `raw_payload`); **same-row** compare keysets + values.
3. Resolve R2 structured keys via `ingestion_change_log` (`jquants_records_r2` summaries); download JSONL; re-check payload≡raw_payload.
4. Classify always-null keys: **SOURCE** (empty in raw API) vs **MAPPING** (raw has value, payload lost it).

### 3. Dataset results (same-row integrity)

| dataset | raw sample n | D1 compared | R2 JSONL sample | payload≡raw keyset (D1) | value mismatches | always-null keys (D1 hot) | class |
|---------|-------------:|------------:|----------------:|------------------------:|-----------------:|---------------------------:|-------|
| `fins_summary` | 414 | 300 | 200 | **1.0** | 0 | 11 | **SOURCE** |
| `fins_details` | 402 | 266 | 200 | **1.0** | 0 | 0 top-level | OK (nested `FS`) |
| `fins_dividend` | 460 | 300 | 200 | **1.0** | 0 | 5 | **SOURCE** |
| `fins_earnings_date` | 18 | 300 | 5 | **1.0** | 0 | 0 | OK |
| `markets_margin_interest` | 500 | 300 | 200 | **1.0** | 0 | 0 | OK |
| `markets_margin_alert` | 219 | 300 | 200 | **1.0** | 0 | 0 | OK |
| `markets_short_ratio` | 34 | 300 | 34 | **1.0** | 0 | 0 | OK |
| `markets_short_sale_report` | 500 | 300 | 200 | **1.0** | 0 | 0 | OK |
| `markets_breakdown` | 500 | 300 | 200 | **1.0** | 0 | 0 | OK |
| `derivatives_bars_daily_futures` | 126 | 126 | 126 | **1.0** | 0 | 0 | OK |
| `derivatives_bars_daily_options` | 500 | 300 | 200 | **1.0** | 0 | 5 | **SOURCE** |
| `derivatives_bars_daily_options_225` | 500 | 300 | 200 | **1.0** | 0 | 0 | OK |
| `edinet_major_shareholders` | 2 | 57 | 2 | **1.0** | 0 | 0 | OK |
| `edinet_cross_shareholdings` | 2 | 51 | 2 | **1.0** | 0 | 0 (D1) | OK (R2 tip-day sparse) |
| `edinet_large_volume_shareholders` | 41 | 300 | 23 | **1.0** | 0 | 0 | OK |
| `equities_investor_types` | 25 | 20 | 4 | **1.0** | 0 | 0 | OK |

**Fields dropped before payload:** **none** (0 mapping drops across all 16).

Example R2 structured objects:

- `structured/jsonl/fins_summary/dt=2026-08-14/r2-fins_summary-1786752949387-8jal91.jsonl`
- `structured/jsonl/markets_margin_interest/dt=2026-05-01/r2-markets_margin_interest-1786721754020-7jc1fo.jsonl`
- `structured/jsonl/derivatives_bars_daily_options/dt=2026-08-14/r2-derivatives_bars_daily_options-1786752970381-kfd8j8.jsonl`

Note: latest hourly raw for `markets_margin_interest` is often `row_count=0` (empty-raw ban → not used); audit used non-empty COMPLETE run with 4253 rows.

### 4. Always-null key catalog (source API empty strings)

Same-row: if payload is always empty for a key, `raw_payload` is always empty for that key too (no mapping nullify).

| dataset | always-null / empty keys (D1 residual sample) | interpretation |
|---------|-----------------------------------------------|----------------|
| `fins_summary` | `DivUnit`, `FDiv1Q`, `FDivTotalAnn`, `FDivUnit`, `FPayoutRatioAnn`, `MatChgSub`, `NCROE`, `NxFDiv1Q`, `NxFDiv3Q`, `NxFDivUnit`, `NxFNCOP2Q` | REIT unit fields + rarely-used forecast / non-consolidated series; API returns `""`. `MatChgSub` superseded by `SigChgInC` after 2024-07-22 vendor change (key may still appear empty). Spec: [fins/summary](https://jpx-jquants.com/en/spec/fin-summary). |
| `fins_dividend` | `DeemCapGains`, `DeemDiv`, `DistAmt`, `NetAssetDecRatio`, `RetEarn` | REIT / deemed-dividend fields empty on common equity cash-dividend rows in sample. |
| `derivatives_bars_daily_options` | `EO`, `EH`, `EL`, `EC`, `SQD` | Emergency-margin OHLC + special quotation date; empty when emergency margin not triggered (typical `EmMrgnTrgDiv=002`). |

R2 structured tip windows can show a **superset** of empty forecast keys for `fins_summary` (e.g. all `FNC*` / `FNCOP*` empty on a single disclosure day) — still source-empty, not dropped.

### 5. Special cases

#### `fins_details` nested `FS`

Top-level keys are only **6**: `Code`, `DiscDate`, `DiscNo`, `DiscTime`, `DocType`, `FS`.  
BS/PL/CF line items live **inside** the `FS` object (vendor shape). Payload stores the whole object; nothing is flattened away. This is **not** a field-drop bug.

#### No specialized typed mapping for this set

These datasets are **generic_payload** only (see Track A). W20-G2 typed fixes (bars `AAdj*`, master `S17`/`Mkt`…) do not apply. Nulls here are JSON-value nulls, not typed-column mapping.

### 6. Code fix

**None required.** No pre-payload field drop; no `stableJson` loss of present keys; payload ≡ raw_payload on same rows for D1 residual and R2 structured.

Optional follow-ups (out of scope / non-claims):

- Document expected always-empty REIT/emergency fields in consumer docs.
- Nested `FS` key cardinality variance (XBRL label surface differs by DocType) — research consumers should treat `FS` as open map.
- No Mass ON / re-ingest / empty-raw accept.

### 7. Verdict (W20-G3)

| check | status |
|-------|--------|
| Landing path traced (raw + structured) | **PASS** |
| R2 raw + R2 structured + D1 residual sampled for 16 priority datasets | **PASS** |
| payload keyset ≡ raw_payload same-row | **PASS (100%)** |
| Always-null keys classified source vs mapping | **PASS — all SOURCE** |
| Fields dropped before payload | **NONE** |
| Code fix | **not needed** |
| Empty-raw ban | **held** |
| Mass / READY / Phase7 | **NO-GO** |

**Track B JSON payload integrity: GO (no mapping defects).** Residual nulls are vendor empty values retained faithfully.
