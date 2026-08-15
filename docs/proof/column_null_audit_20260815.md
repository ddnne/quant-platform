# Column / typed NULL audit — 2026-08-15

**Wave:** w0815m / W20-G2 (Track B typed NULL)  
**Operator:** GLM 5.3 implementer  
**Authority:** CF SoT only — R2 `quant-raw` + remote D1 `quant-ingest` (`jquants_records.payload`). Local raw is corroborative, not authority.  
**Mass / READY / Phase7:** **NO-GO**  
**Logs:** `.glm-logs/w0815m_g2_typed_null/`

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
