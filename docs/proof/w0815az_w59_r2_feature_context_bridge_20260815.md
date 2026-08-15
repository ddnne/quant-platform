# W59 / w0815az_g1 — R2 structured history → FeatureContext research bridge

**Wave:** W59 / w0815az_g1 · T1–T5  
**Phase:** research-only R2→FeatureContext bridge for COMPLETE 21 history  
**Mass / READY / Phase7:** **NO-GO / not declared / OFF** (held)  
**Densify / push:** **none** (G4)  
**Local SQLite SoT:** **false** (disposable mirror only)

**Prior blocker (W58):** [`w0815ay_w58_history_window_eval_20260815.md`](w0815ay_w58_history_window_eval_20260815.md) —  
`history_expand_possible=NO` because multiday eval was **D1 tip-only**; R2 history existed but had no FeatureContext bridge.

**This wave:** implement the missing bridge so S1 signal long eval can load R2 history for at least:

* `equities_bars_daily`
* `indices_bars_daily_topix`
* `markets_calendar`

---

## Verdict

| gate | result |
|------|--------|
| **T1 R2 inventory** | **DONE** — COMPLETE 21 key patterns + DEFER exclude · [`.glm-logs/w0815az_g1_bridge/t1_r2_inventory.json`](../../.glm-logs/w0815az_g1_bridge/t1_r2_inventory.json) |
| **T2 schema mapping** | **DONE** — Code/Date/event_time/available_at → FeatureContext · `t2_schema_mapping.json` |
| **T3 research loader** | **DONE** — `packages/product/research/r2_feature_context.py` · wired `history_source="r2"\|"d1_tip"` |
| **T4 PIT** | **DONE** — `available_at` required; `available_at <= as_of`; null excluded |
| **T5 DEFER 5 hard reject** | **DONE** — `PermanentDeferHistoryError` on extract/build/mirror |
| **Unit tests** | **PASS** — `tests/test_r2_feature_context.py` (23) |
| **can_build_40d_asof** | **yes** (code path; needs R2 keys/fixtures spanning ≥40 trading days) |
| Mass / READY / densify / push | **OFF / not declared / none / none** |

---

## 0. Constraints held

| rule | status |
|------|--------|
| Mass Autonomous Research | **NO-GO** |
| READY publication | **not** declared |
| Phase7 | **OFF** |
| Densify | **none** |
| Push (G4) | **none** |
| Local SQLite as SoT | **forbidden** (mirror labeled disposable) |
| Invent COMPLETE 22 | **forbidden** |
| Permanent DEFER 5 as history | **hard reject** |

---

## 1. T1 — R2 key pattern inventory

**Sources:** code + [`complete21_cf_read_paths_20260815.md`](complete21_cf_read_paths_20260815.md) + W58 live samples (`.glm-logs/w0815ay_g1_history/`).

### 1.1 Shared patterns (`quant-structured`)

| kind | key pattern |
|------|-------------|
| Live JSONL | `structured/jsonl/{dataset}/dt=YYYY-MM-DD/{run_id}.jsonl` |
| Cold archive NDJSON | `archive/jquants_records/{dataset}/batch/{run_id}_after{rowid}.ndjson` |
| Archive meta | `…_meta.ndjson` |
| Line schema | `jquants_records/v1` |

Line envelope fields: `source`, `dataset`, `natural_key`, `event_time`, `available_at`, `ingested_at`, `payload`, `raw_payload`  
(+ optional archive `rid`).

### 1.2 S1 minimal (signal long eval)

| dataset | jsonl prefix | archive prefix | live sample (W58) |
|---------|--------------|----------------|-------------------|
| `equities_bars_daily` | `structured/jsonl/equities_bars_daily/` | `archive/jquants_records/equities_bars_daily/` | `…/dt=2008-05-07/…mmwbjs.jsonl` |
| `indices_bars_daily_topix` | `structured/jsonl/indices_bars_daily_topix/` | `archive/jquants_records/indices_bars_daily_topix/` | archive batch `…_after227044.ndjson` (2009–2011 sample span) |
| `markets_calendar` | `structured/jsonl/markets_calendar/` | `archive/jquants_records/markets_calendar/` | `…/dt=2026-08-01/…4qn6pm.jsonl` |

### 1.3 COMPLETE 21

All 21 residual COMPLETE datasets share the same JSONL/archive layout under their dataset id. Full map:  
[`.glm-logs/w0815az_g1_bridge/t1_r2_inventory.json`](../../.glm-logs/w0815az_g1_bridge/t1_r2_inventory.json)  
(also embedded as `COMPLETE_21_R2_INVENTORY` in code).

### 1.4 Permanent DEFER 5 (excluded)

| dataset | PD id |
|---------|-------|
| `equities_master` | PD-D2-MASTER |
| `equities_earnings_calendar` | PD-D4-EARN-CAL |
| `equities_bars_daily_am` | PD-D4-BARS-AM |
| `fins_earnings_date` | PD-MX-EARN-TIP |
| `jsda_otc_bond_reference_prices` | PD-D5-JSDA-OTC |

---

## 2. T2 — Schema mapping → FeatureContext

| FeatureContext resource | dataset | Code | Date | event_time | available_at |
|-------------------------|---------|------|------|------------|--------------|
| `get_equity_bars_daily` | `equities_bars_daily` | payload/nk `Code` → `row.code` | payload/nk `Date` → `row.date` | envelope | envelope (**PIT**) |
| `get_market_calendar` | `markets_calendar` | — | payload `Date` | envelope | envelope (**PIT**) |
| `get_jquants_records(dataset=…)` | e.g. `indices_bars_daily_topix` | optional | payload `Date` | envelope | envelope (**PIT**) |

OHLCV aliases for bars: `O/H/L/C/Vo` (+ Adj* / A* forms via tip normalizers).  
TOPIX close: `C` / `Close`. Calendar holiday: `HolDiv` / `HolidayDivision`.

PIT rule (held): **`available_at` required** and **`available_at <= as_of`**; null/empty excluded on load and in the FeatureContext reader.

Detail: [`.glm-logs/w0815az_g1_bridge/t2_schema_mapping.json`](../../.glm-logs/w0815az_g1_bridge/t2_schema_mapping.json).

---

## 3. T3 — Research loader

### 3.1 Module

**Path:** [`packages/product/research/r2_feature_context.py`](../../packages/product/research/r2_feature_context.py)

| API | role |
|-----|------|
| `parse_r2_structured_line` / `parse_r2_structured_bytes` | JSONL/NDJSON → envelope |
| `normalize_r2_history_row` | envelope → tip-compatible FeatureContext row |
| `extract_r2_history_feature_rows` | COMPLETE-21 extract (keys / local paths / raw lines) |
| `build_r2_feature_context` | PIT FeatureContext (`plane=R2_history`) |
| `materialize_disposable_sqlite_mirror` | optional temp SQLite for pit smokes — **not SoT** |
| `default_r2_get_object` | wrangler remote get (injectable in tests) |
| `r2_inventory_document` / `write_r2_inventory_json` | T1 export |
| `can_build_40d_asof` | capability report |

Input channels (at least one per dataset):

1. `object_keys_by_dataset` + `r2_get` (or wrangler default)  
2. `local_paths_by_dataset` (disposable mirror files)  
3. `raw_lines_by_dataset` (in-memory / unit fixtures)

### 3.2 Wire into eval / single-shot

| entry | param |
|-------|--------|
| `execute_multiday_signal_eval` | `history_source="d1_tip"` (**default**) \| `"r2"` |
| `execute_multiday_nextday_return_eval` | same |
| `eval_harness.run_multiday_signal_eval` | same |
| `eval_harness.run_nextday_return_eval` | same |

When `history_source="r2"`, also accept:

* `r2_object_keys_by_dataset`
* `r2_local_paths_by_dataset`
* `r2_raw_lines_by_dataset`
* `r2_get`
* `r2_bucket` (default `quant-structured`)

Default tip path is **unchanged** (`d1_tip`).

`build_tip_feature_context` gained optional `plane` / `source` / `table_prefix` so R2 and tip share one PIT reader implementation.

### 3.3 Disposable SQLite mirror

`materialize_disposable_sqlite_mirror` writes `jquants_records` (+ curated bar/calendar tables) to a temp file for callers that must exercise stock `pit.*` / `features.compute(db_path=…)`.  
Documented as **disposable mirror, never SoT**. Preferred research path remains in-memory FeatureContext.

---

## 4. T4 — PIT (no look-ahead)

| check | behavior |
|-------|----------|
| Null/empty `available_at` on load | dropped in `filter_history_rows` |
| FeatureContext reader | `_available_at_ok(row.available_at, as_of)` — false → skip |
| Future `available_at` relative to as_of | excluded (T+1 bar not visible at T close) |
| Next-day return path | unchanged W55 policy (`NEXTDAY_LOOKAHEAD_POLICY`) |

Unit coverage: `test_t4_pit_excludes_future_available_at`, `test_t4_null_available_at_excluded_on_load_and_context`.

---

## 5. T5 — DEFER 5 hard reject

`extract_r2_history_feature_rows` / `build_r2_feature_context` / `materialize_disposable_sqlite_mirror` call:

* `require_complete_21_only` (non-COMPLETE + DEFER)
* `reject_permanent_defer_for_history` (belt-and-suspenders)

Raises `PermanentDeferHistoryError` before parse/write.  
Unit coverage: parametrized over all 5 DEFER ids.

---

## 6. Tests

```text
uv run pytest tests/test_r2_feature_context.py -q
# 23 passed
```

Covers schema parse (string payload), window/code filter, FeatureContext candidate features (volume / topix relative / trading day), PIT, DEFER, inventory export, multiday `history_source="r2"` dry-run batch, 40d capability.

---

## 7. can_build_40d_asof

| mode | result |
|------|--------|
| Code path (bridge present) | **yes** |
| Live without keys | requires `object_keys` (artifacts-join-plan) or fixtures spanning ≥40 trading days |
| D1 tip alone | still ~28 trading days (hot cutoff `2026-07-01`) — unchanged |

Honest note: this wave **implements the bridge** and proves it with fixtures. A live 40–60 day CF eval is now **code-possible** once R2 keys for the window are listed/fetched; it is not auto-run here (no densify / no Mass / no push).

---

## 8. Explicit non-claims

This proof does **not**:

* declare Mass GO or Phase7 ON  
* declare READY / B0 GO  
* claim edge / statistical significance  
* invent Dataset COMPLETE 22  
* treat local SQLite as CF SoT  
* push remote artifacts as an authority claim for this wave  

---

## 9. Deliverable summary

| item | value |
|------|-------|
| **module path** | `packages/product/research/r2_feature_context.py` |
| **datasets supported** | all COMPLETE 21 (inventory + load path); S1 MVP = `equities_bars_daily` + `indices_bars_daily_topix` + `markets_calendar` |
| **can_build_40d_asof** | **yes** |
| **history_source default** | `d1_tip` (backward compatible) |
| **tests** | `tests/test_r2_feature_context.py` |
| **inventory log** | `.glm-logs/w0815az_g1_bridge/t1_r2_inventory.json` |
