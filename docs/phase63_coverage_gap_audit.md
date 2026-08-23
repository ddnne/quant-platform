# Phase 6.3 Lane J — remaining PARTIAL coverage gap audit

**Lane:** J (cause-classified audit only)  
**HEAD base:** `1efb405` (`origin/main`)  
**Audit date:** 2026-08-23  
**Live MCP:** `quant-mcp` (`coverage_gaps` / `dataset_coverage` / `coverage_segments` /
`raw_retention_status` / `ingestion_last_run` / `backfill_status`)  
**Projection:** `projgen-ef18b4f86ee946048161d25e2a30a2a8`  
**Dataset COMPLETE:** **22 held** · remaining PARTIAL **4** (not invented COMPLETE)  
**Mass / READY / Phase 7 / GO:** not this lane.

This note classifies why four governed datasets stay PARTIAL. It does **not**
seal segments, densify, run live backfill, shorten `history_target_start` to
erase residuals, or mark COMPLETE.

Live coverage SoT remains quant-mcp, not this prose. Residual live flags:
[`phase62_residual_status.md`](phase62_residual_status.md). Segment COMPLETE
chain: [`complete_segment_checklist.md`](complete_segment_checklist.md).

## Method

Cause classes used below:

| Class | Meaning |
|-------|---------|
| `STALE_COVERAGE_EVAL` | Ledger / projection `evaluated_at` lags live ingest |
| `VENDOR_TIP_ONLY` | Official product is recent / next-day / same-day only |
| `MISSING_COLLECTION_RECEIPT` | Required segment has no matching signed SUCCESS receipt |
| `FALSE_PARTIAL_SEGMENT_SEMANTICS` | Required inventory grain does not match event / index semantics |
| `VENDOR_MISDATE_CLAMP` | Vendor returns a later in-window `Date` for earlier requests |
| `SUBSCRIPTION_ENTITLEMENT_FLOOR` | HTTP 400 plan window; not vendor data-provision start |
| `CALENDAR_DAY_INVENTORY_OVERHANG` | Every calendar day inventoried; official index is publication days |
| `PARSER_SCHEMA_GAP` | Raw file exists; governed parser yields zero rows |
| `EMPTY_RAW_COMPLETE_BAN` | Zero structured rows must not become COMPLETE |

Evidence planes (must not be collapsed):

1. **Raw acquired** — bytes on disk / R2 with digest  
2. **Parse success** — nz source rows from the governed parser  
3. **Structured** — fact / `jquants_records` rows for the segment window  
4. **Trusted receipt** — Ed25519 SUCCESS, identity match, pagination exhausted  
5. **Segment COMPLETE** — `evaluate_segment` after (1)–(4)

Row counts, cron PASS, or raw retention **alone** are not COMPLETE.

---

## Summary

| Dataset | Live status | Required | COMPLETE / PARTIAL | Contract `history_target_start` | Change target? | Stay PARTIAL |
|---------|-------------|----------|--------------------|---------------------------------|----------------|--------------|
| `equities_bars_daily_am` | PARTIAL | 32 | 1 / 31 | 2024-01-04 | **No** | **Yes** |
| `equities_earnings_calendar` | PARTIAL | 200 | 1 / 199 | 2010-01-04 | **No** (event semantics: propose only) | **Yes** |
| `equities_master` | PARTIAL | 241 | 220 / 21 | 2006-08-13 | **No** (record official listed-info start as metadata only) | **Yes** |
| `jsda_otc_bond_reference_prices` | PARTIAL | 8784 | 5886 / 2898 | 2002-08-02 | **No** | **Yes** |

`2898 PARTIAL ≠ 2 PARSE_ZERO`. Official remaining publication days that failed
seal are **two** PARSE_ZERO files. The rest of 2898 is calendar-day inventory
without official index files.

---

## 1. `equities_bars_daily_am`

### Live snapshot (MCP 2026-08-23)

| Field | Value |
|-------|-------|
| status | PARTIAL |
| `history_target_start` | 2024-01-04 |
| observed_start / observed_end | 2026-08-01 … 2026-08-11 |
| row_count | 4444 |
| coverage_v2 | required 32 · COMPLETE **1** · PARTIAL **31** · target_end 2026-08-14 |
| `evaluated_at` | 2026-08-14T12:25:38.437817+00:00 |
| receipt window | 2026-08-01 … 2026-08-11 · receipt_raw_rows 53328 |
| PARTIAL segment reason | `missing collection receipt` (2024-01 … 2026-07; 31 months) |
| Inventory SLA | expected_after 11:30 · usable_by 12:30 · `same_trading_day_am` · TZ Asia/Tokyo |
| MCP SLA current_state | UNKNOWN (`SLA status not projected`) |
| Latest ingest run | id **14312** · 2026-08-23T18:15:01+09:00 · cron · status pass |
| Latest nz raw retention | run **14273** · 2026-08-22T05:15:12+09:00 · 4443 rows · completeness COMPLETE (raw attestation, **not** coverage COMPLETE) |
| Latest same-day retention | run **14312** · 0 rows · 88 bytes (Sunday empty envelope) |

### Cause classes (primary → secondary)

1. **`VENDOR_TIP_ONLY` (primary, history)**  
   Official AM endpoint is **recent data only**. Spec:
   [Morning Session Stock Prices (OHLC)](https://jpx-jquants.com/en/spec/eq-bars-daily-am)
   (`/v2/equities/bars/daily/am`):
   - “Data for the day can be obtained until around 6:00 the next day.
     For historical data, please use Stock Prices (OHLC).”
   - Request parameters: `code`, `pagination_key` only — **no `date` / `from` / `to`**.
   Plan table: [data-spec](https://jpx-jquants.com/en/spec/data-spec) —
   “Morning Session Stock Prices (OHLC) … **Recent data only**”.
   Repo lock: `TIP_ONLY_POLICY` / W71 `LIVE_API_EMPTY` for all 31 PARTIAL
   months `2024-01…2026-07` (`permanent_defer.py` PD-D4-BARS-AM).
   Contract `date_mode=today` matches vendor. History months cannot be
   backfilled through this endpoint.

2. **`STALE_COVERAGE_EVAL` (primary, tip ledger)**  
   Coverage `evaluated_at` 2026-08-14 and observed_end 2026-08-11 lag live
   ingest (nz raw 2026-08-21 session in run 14273; cron still running
   2026-08-23). Refreshing `evaluated_at` / observed window is ops hygiene.
   It does **not** promote 31 history months. Re-eval stays PARTIAL (1/32).

3. **`MISSING_COLLECTION_RECEIPT`**  
   31 calendar-month segments exist as required inventory with
   `receipt_run_id=null`. Tip month is the only COMPLETE.

4. **`EMPTY_RAW_COMPLETE_BAN`**  
   Sunday 2026-08-23 0-row / 88-byte ingest is a non-session empty envelope.
   Must not be sealed COMPLETE.

### Contract change justified?

**No.** Do not shorten `history_target_start` from 2024-01-04 to the tip
month. 2024-01-04 is the first TSE session of 2024 (repo + inventory
`historical_start`); official spec does **not** publish a different AM
history start — it publishes “recent data only”. Shortening the floor would
drop 31 PARTIAL months and invent Dataset COMPLETE.

Metadata only: vendor history policy is recent-only (citation above).
`history_target_start` stays 2024-01-04.

### Human actions

| Action | Needed? |
|--------|---------|
| J-Quants credentials | **No** — live cron pass, nz AM raw on session days |
| Cloudflare Worker / cron | **No** for ingest (`15 * * * *` premium cron is live). **Yes** if ops wants SLA `current_state` projected (today UNKNOWN) |
| Coverage re-eval / projection publish | **Optional hygiene** so `evaluated_at` is not 9 days stale; will not COMPLETE the dataset |
| History backfill / densify | **Forbidden** (W71/W72 tip-only) |
| Contract data window | **Keep 2024-01-04**. Do not raise to 2026-08 |

Use `equities_bars_daily` (full-day OHLC, Premium history since 2008-05-07)
for AM **history** research. AM dataset remains same-day tip.

---

## 2. `equities_earnings_calendar`

### Live snapshot (MCP 2026-08-23)

| Field | Value |
|-------|-------|
| status | PARTIAL |
| coverage_mode / expected_frequency | `event_reconciled` / **event_driven** |
| Inventory `coverage_segment_granularity` | **calendar_month** (default) |
| `history_target_start` | 2010-01-04 |
| observed_start / observed_end | 2010-01-04 … 2026-08-14 |
| hot row_count | **333** |
| coverage_v2 | required **200** · COMPLETE **1** · PARTIAL **199** · target_end 2026-08-14 |
| receipt window | 2010-01-04 … 2026-08-12 · receipt_raw_rows **11162** |
| hot event_time (C4) | 2026-08-12 … 2026-08-14 |
| PARTIAL segment reason | `missing collection receipt` (monthly ids 2010-01 …) |
| `evaluated_at` | 2026-08-14T12:25:38.437817+00:00 |

200 months from 2010-01 through 2026-08 is the 1/200 style inventory.

### Cause classes

1. **`FALSE_PARTIAL_SEGMENT_SEMANTICS` (primary)**  
   Policy already says event feeds must not invent daily/monthly row
   expectations (`coverage.py`). `evaluate_segment` allows event-zero
   COMPLETE **when a trusted receipt exists**. Default
   `segment_granularity=calendar_month` still **plans 200 months**.
   Absent per-month receipts → 199 PARTIAL `missing collection receipt`.
   Months with no Mar/Sep FY next-day announcements are not source gaps.
   Fabricating monthly COMPLETE shells is forbidden.

2. **`VENDOR_TIP_ONLY` (primary, product)**  
   Official:
   [Earnings Calendar (March/September fiscal year-end only)](https://jpx-jquants.com/en/spec/eq-earnings-cal)
   - Returns stocks announcing **the next business day**.
   - Updated ~19:00 JST only when the JPX calendar page updates.
   - Query params: `pagination_key` only (no `from`/`to`/`date` despite
     repo contract listing them).
   Plan table: **Recent data only** (all plans),
   [data-spec](https://jpx-jquants.com/en/spec/data-spec).
   History-grade announcement dates belong on
   [`/v2/fins/earnings-date`](https://jpx-jquants.com/en/spec/fin-earnings-date)
   (Premium since **2014-09-01**), already Dataset COMPLETE after W68.

3. **`MISSING_COLLECTION_RECEIPT`**  
   199/200 months. One tip month COMPLETE. Hot D1 333 rows is the current
   snapshot; receipt_raw_rows 11162 is accumulated snapshot raw, **not**
   200 monthly trusted receipts.

4. **`STALE_COVERAGE_EVAL` (secondary)**  
   `evaluated_at` 2026-08-14. Refresh does not fill 199 months.

### Proposed event-data Coverage Contract semantics (not implemented)

Do **not** invent 199 monthly COMPLETE. Do **not** drop 199 months in this
lane to declare Dataset COMPLETE.

Proposed (human product decision, later CODE_PATCH):

| Current | Proposed for next-business-day event feeds |
|---------|--------------------------------------------|
| `segment_granularity=calendar_month` (default) | snapshot / `source_event_window` (one required segment per collection cutoff, or explicit event-id grain) |
| 200 required months 2010-01…2026-08 | required inventory = collection windows actually issued |
| missing month receipt → PARTIAL | missing **events** inside a received window → PARTIAL; no-event window with trusted empty-or-nz snapshot receipt → COMPLETE |
| `history_target_start=2010-01-04` | keep until product de-scopes history; 2010-01-04 is first TSE session of 2010, **not** vendor provision start |

`evaluate_segment` already encodes “do not treat absent events as gaps”.
The false-PARTIAL is **planning 200 months** for a next-day snapshot API.

### Contract change justified?

**`history_target_start`:** **No.** Official spec has no 2010-01-04
provision start. Shortening to the tip month invents COMPLETE.

**Granularity / event semantics:** **Yes, as a future contract change**,
not as a silent COMPLETE. Code comment only in this lane.

### Human actions

| Action | Needed? |
|--------|---------|
| Credentials | **No** for current tip collect |
| Cloudflare | Optional projection re-eval; not COMPLETE |
| Contract data window | **Keep 2010-01-04** until an explicit de-scope ADR. Do not fabricate months |
| Research history | Use `fins_earnings_date` (COMPLETE). This dataset stays tip calendar |

---

## 3. `equities_master`

### Live snapshot (MCP 2026-08-23)

| Field | Value |
|-------|-------|
| status | PARTIAL |
| coverage_mode | `scd2_event_sourcing` |
| `history_target_start` | **2006-08-13** |
| observed_start / observed_end | **2008-05-01** … 2026-08-12 |
| row_count | 8_072_621 |
| coverage_v2 | required 241 · COMPLETE **220** · PARTIAL **21** · target_end 2026-08-14 |
| surgical re-agg | 2026-08-18T22:34:04Z · prev PARTIAL 94 → PARTIAL 21 (honest re-aggregate) |
| PARTIAL segments | `2006-08` … `2008-04` (n=21) · `missing collection receipt` |
| receipt window | 2008-05-01 … 2026-08-11 · receipt_raw_rows 9_002_702 |
| `evaluated_at` | 2026-08-18T22:34:04.977436+00:00 |

PRE_PLAN `2000-07…2006-07` (73) is already OUT_OF_SCOPE via the 2006-08-13
floor (W98). Remaining required PARTIAL is **MISDATE 21 months**.

### Official listed-info / master history start

**Vendor data-provision start is 2008-05-07, not 2006-08-13.**

| Source | Start | URL |
|--------|-------|-----|
| Listed Issue Master spec | “start date of data provision **(May 7, 2008)**”; earlier dates still return **2008-05-07** | https://jpx-jquants.com/en/spec/eq-master |
| Plan data period | Listed Issue Master Premium: **Since 2008/5/7** | https://jpx-jquants.com/en/spec/data-spec |
| Repo entitlement clamp | Premium HTTP 400 originally `2006-08-13 ~`; W98 re-probe `2006-08-19 ~` | `backfill_planner.py` `JQUANTS_SUBSCRIPTION_FLOOR` |
| Repo MISDATE lock | Vendor bodies return `Date=2008-05-07` only (`window_ok=0`) | `permanent_defer.py` `MASTER_JQ_SCOPE` |

Observed_start 2008-05-01 is the first COMPLETE month of the honest island
(2008-05-07 is inside 2008-05). That is **not** a reason to treat 2006–2008
as “missing because we have not fetched yet”. Official behaviour is: those
dates are **before data provision** and the API **clamps Date to 2008-05-07**.

2006-08-13 is a **subscription entitlement floor** (plan HTTP 400), not the
listed-info provision start.

### Cause classes

1. **`VENDOR_MISDATE_CLAMP` (primary)**  
   Official spec + live MISDATE: requests in 2006-08…2008-04 return
   2008-05-07 listed info. Cannot seal those months with in-window `Date`.

2. **`SUBSCRIPTION_ENTITLEMENT_FLOOR` (distinct)**  
   2006-08-13 / live 2006-08-19 is when the Premium key accepts `date=`.
   It is **not** proof that listed-info exists those days.

3. **`MISSING_COLLECTION_RECEIPT`**  
   21 MISDATE months: no window_ok receipt.

4. Honest island `2008-05→latest` is COMPLETE (220 months) and is the
   research history floor. Ops tip collect remains allowed.

### Contract change justified?

**Do not change `history_target_start` in this lane.**  
Raising it to 2008-05-01 / 2008-05-07 would de-scope the 21 MISDATE months
and is exactly `invent_complete_via_floor_to_2008_05=FORBIDDEN`
(`permanent_defer.py`). Observed missing 2006–2008 is **not** a fetch gap
to densify, and it is **not** license to invent Dataset COMPLETE.

Official URL **does** prove 2006-08-13 is the wrong *listed-info provision*
date. This lane records that as **metadata** (citation) and leaves the
coverage floor in place until a human product ADR de-scopes MISDATE
without calling the dataset COMPLETE as a side effect.

### Human actions

| Action | Needed? |
|--------|---------|
| Credentials | **No** for 2008-05+ island (8.07M rows) |
| Cloudflare | Optional freshness; 21 MISDATE months will remain |
| Re-probe 2006-08…2008-04 | Only if vendor starts returning in-window `Date` (retry condition). No densify |
| Contract data window | **Keep 2006-08-13** until ADR. Do **not** raise to 2008-05-01 to invent COMPLETE |

---

## 4. `jsda_otc_bond_reference_prices`

### Live snapshot (MCP 2026-08-23)

| Field | Value |
|-------|-------|
| status | PARTIAL |
| coverage_mode | `official_archive_index_reconciled` |
| segment_granularity | `official_archive_day` |
| `history_target_start` | 2002-08-02 |
| observed_start / observed_end | 2002-08-06 … 2026-08-20 |
| row_count | 47_814_126 |
| coverage_v2 | required **8784** · COMPLETE **5886** · PARTIAL **2898** · target_end 2026-08-21 |
| backfill_status | remaining_segments **2898** |
| PARTIAL sample reason | `missing collection receipt` (includes 2002-08-02 … and weekend ids) |
| Official remaining 2002 | **2** PARSE_ZERO: **2002-08-02**, **2002-08-05** |
| COMPLETE span (seal log) | 2002-08-06 … 2026-08-20 · empty_otc_complete **0** |

Calendar identity: 2002-08-02 … 2026-08-19 inclusive = **8784** days =
5886 + 2898. Weekend count in that span = **2510**. Weekday count = **6274**.
`6274 − 5886 = 388` weekday PARTIAL (includes the two PARSE_ZERO days).
`2898 − 2510 = 388`. Holiday-scale remainder (~16 weekdays/year × 24 y).

### PARSE_ZERO vs remaining 2898

| Bucket | n | Raw acquired? | Parse success? | Structured? | Trusted receipt? | Segment COMPLETE? |
|--------|--:|---------------|----------------|-------------|------------------|-------------------|
| Sealed official publication days | **5886** | yes | yes (nz) | yes, raw==struct | yes | **COMPLETE** |
| Official PARSE_ZERO days `2002-08-02`, `2002-08-05` | **2** | **yes** (S020802.csv 562 202 B / S020805.csv 561 743 B; ~4200 cp932 rows) | **no** (`parse_otc_reference_csv` → 0) | no | no | **PARTIAL** (not invented COMPLETE) |
| Weekend calendar ids (no official file) | **2510** | no | n/a | n/a | missing | PARTIAL inventory |
| Weekday non-index (holidays / non-publication) | **~386** | no | n/a | n/a | missing | PARTIAL inventory |
| **Ledger PARTIAL total** | **2898** | mixed | | | | **PARTIAL** |

Seal log: `data/ops/otc_official_backfill/batch_2002_remain_20260821/otc_seal_result.json`
(`PARSE_ZERO` for those two paths; 2002-08-06 `SEALED` raw=struct=3167).

Parser cause (`packages/data_plane/ingestion/jsda/parse.py`): headerless
layout requires `_OTC_POSITIONAL_MIN_COLUMNS = 29`. 2002-08-02/05 rows have
**23** fields; 2002-08-06 already matches 29+. Files are **not** empty.
`scripts/jsda_otc_seal_official.py` maps `not parsed` → `PARSE_ZERO`.
`ingestion/jsda/archive.py` raises `official OTC archive file parsed zero rows`.
Empty-raw COMPLETE remains banned — correct, because structured is 0
**after parse**, even though bytes exist.

`plan_required_segments(..., official_archive_day)` walks **every calendar
day**. Coverage mode is `official_archive_index_reconciled` (JSDA year
index HTML, `discover_otc_reference_segments`). Non-index days should not
be required publication files. That is `CALENDAR_DAY_INVENTORY_OVERHANG`,
not 2896 additional PARSE_ZERO days.

### Cause classes

1. **`CALENDAR_DAY_INVENTORY_OVERHANG` (bulk of 2898)**  
   ~2510 weekends + ~386 non-publication weekdays. No official archive
   file → no receipt → PARTIAL. Not raw-acquired.

2. **`PARSER_SCHEMA_GAP` (official remaining = 2)**  
   Raw acquired for 2002-08-02 and 2002-08-05; parse zero under 29-col
   layout.

3. **`EMPTY_RAW_COMPLETE_BAN`**  
   Must not COMPLETE PARSE_ZERO or empty weekend ids.

4. **`MISSING_COLLECTION_RECEIPT`**  
   MCP detail for remaining ids is `missing collection receipt` —
   including the two PARSE_ZERO days (seal refused before receipt).

### Contract change justified?

**No** `history_target_start` change. 2002-08-02 **is** the first official
archive label date (file exists; JSDA contract + `docs/architecture.md`).
Do not raise the floor to 2002-08-06 to hide PARSE_ZERO. Do not COMPLETE
weekend/holiday calendar ids.

Future (not this lane): required inventory should be **official index
days**, not every calendar day. That is a planner/inventory fix, not a
floor bump, and must not mass-COMPLETE empty days.

### Human actions

| Action | Needed? |
|--------|---------|
| Credentials / Cloudflare | **No** for archive files already on disk (local JSDA lane) |
| Parser work for 2002-08-02/05 23-col layout | **Yes**, human/CODE_PATCH later; then seal only if nz parse **and** raw==struct |
| Invent COMPLETE / densify 2898 | **Forbidden** |
| Contract data window | **Keep 2002-08-02** |
| Drop weekend inventory | Product/planner ADR; not a COMPLETE shortcut |

Official index: https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/index.html

---

## What this lane did / did not do

**Did**

- Cause-classify the four PARTIAL datasets against live MCP + repo contracts
  + official J-Quants / JSDA specs.
- Record listed-info provision start **2008-05-07** as metadata (citation),
  without moving `history_target_start`.
- Comment event-feed monthly planning and OTC PARSE_ZERO / 29-col layout.

**Did not**

- Mark any dataset COMPLETE  
- Change any `history_target_start`  
- Densify, live backfill, Mass/READY/GO  
- Delete YAML / touch `research-mass-eval` Worker  
- Fabricate earnings months or weekend COMPLETE  

Dataset COMPLETE remains **22**. Residual PARTIAL remains **4**.
