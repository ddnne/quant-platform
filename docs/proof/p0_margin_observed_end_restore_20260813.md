# P0: `markets_margin_interest` observed_end restore (2026-08-13)

**Mass / READY:** NO-GO  
**COMPLETE fabrications:** none  
**cf_premium --execute:** **skipped** (SUCCESS receipts already cover `2026-08-12`; dual/double backfill ban)  
**base SHA (PRE):** `0ce3d32` / tip `da3f076`

## Incident

Live remote `dataset_coverage.observed_end` for `markets_margin_interest` **regressed** to **`2026-08-04`** after prior P0 had advanced it to **`2026-08-12`** (see [`p0_margin_c8_projection_20260813.md`](p0_margin_c8_projection_20260813.md)).

With today JST **2026-08-13**:

| plane | end | lag vs today | C8 (`max_days=7`) |
|-------|-----|--------------|-------------------|
| PRE `observed_end` | **2026-08-04** | **9d** | **FAIL** (would risk STALE if ledger re-eval used this as SoT) |
| POST `observed_end` (receipt union) | **2026-08-12** | **1d** | **PASS** |
| SUCCESS receipt max `segment_end` | **2026-08-12** | 1d | PASS (evidence already present) |
| watermark `last_event_date` | **2026-08-07** | 6d | PASS |
| D1 hot `jquants_records` | (not re-queried as SoT) | — | not used for this ticket |

## PRE snapshot (remote D1 `quant-ingest`, wrangler `--remote`)

| Metric | PRE |
|--------|-----|
| `status` | **PARTIAL** |
| `observed_start` | `2024-01-01` |
| `observed_end` | **`2026-08-04`** |
| `row_count` | 251470 |
| `evaluated_at` | `2026-08-12T22:53:50.795533+00:00` |
| sticky segments | COMPLETE **14** / PARTIAL **150** |
| `ingestion_watermarks.last_event_date` | `2026-08-07` |
| `ingestion_watermarks.last_ingested_at` | `2026-08-13T20:30:33+09:00` |
| SUCCESS raw>0 receipt window | `2026-05-13` … **`2026-08-12`**, n=**22**, sum_raw=**144773** |
| Aug non-empty receipts (examples) | run_id **2512/2509/1585/1575** `segment_end=2026-08-12` raw=4259 |
| active projection | `projgen-f3dd02137343411286b39646f06deeea` `generated_at=2026-08-13T11:39:06.776341+00:00` |

### Root cause (honest)

- **Receipt plane was not missing Aug data.** Max SUCCESS `segment_end` with `raw_row_count>0` remained **`2026-08-12`**.
- **Coverage row regressed:** `observed_end` was rewritten to **`2026-08-04`** (weekly run 172 window) while later monthly/latest receipts still pointed at 2026-08-11/12.
- Likely path: a coverage refresh / projection republish that re-derived `observed_*` from a non-max plane (or partial receipt sample) rather than `MAX(segment_end)` over SUCCESS raw>0. **Not** investigated to a single cron job id in this ticket.
- **No re-ingest required** to fix lag; reeval alone restores the receipt-truth window.

## Actions

### 1. PRE wrangler (numeric confirmation)

```bash
wrangler d1 execute quant-ingest --remote --config=platform/workers/ingestion-premium/wrangler.toml \
  --command="SELECT dataset, status, observed_start, observed_end, evaluated_at FROM dataset_coverage WHERE dataset='markets_margin_interest';"
# observed_end PRE = 2026-08-04
```

### 2. Aug latest `--execute` — **skipped**

| Check | Result |
|-------|--------|
| `ps` for `cf_premium` | clear |
| SUCCESS raw>0 max end | already **2026-08-12** |
| Decision | **no `--execute`** (二重 backfill 禁止) |

### 3. `ops_reeval_observed_window`

```bash
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset markets_margin_interest
```

| Field | PRE | POST |
|-------|-----|------|
| `observed_end` | **`2026-08-04`** | **`2026-08-12`** |
| `observed_start` | `2024-01-01` | `2024-01-01` (history still DEFER) |
| `status` | PARTIAL | **PARTIAL** (no COMPLETE) |
| `evaluated_at` | `2026-08-12T22:53:50Z` | **`2026-08-13T11:44:05.090165+00:00`** |
| receipt window | — | `2026-05-13`…`2026-08-12`, n=22, sum_raw=144773 |

Segment inventory **untouched** by reeval: COMPLETE **14** sticky / PARTIAL **150**.  
**No** remote `status='COMPLETE'` UPDATE.

### 4. `ops_reeval_freshness` — **skipped**

| Check | Value |
|-------|-------|
| active generation | `projgen-f3dd02137343411286b39646f06deeea` |
| `generated_at` | `2026-08-13T11:39:06.776341+00:00` |
| wall-clock age at POST (~11:44Z) | **~5 min** ≪ max_age 86400 |
| Decision | already **FRESH**; no reclock required |

## POST C8 judgment (receipt plane = SoT for this ticket)

| Check | Value |
|-------|-------|
| Policy | `expected_frequency=weekly`, C8 `max_days=7` |
| today JST | **2026-08-13** |
| POST `observed_end` | **2026-08-12** |
| lag | **1 calendar day ≤ 7** → **PASS** |
| PRE lag (for contrast) | **9d > 7** → **FAIL** |
| Dataset status | remains **PARTIAL** (segment inventory 14/164); **not** COMPLETE |
| Mass / READY | **NO-GO** |

## Absolute bans held

- No Mass / READY / B0 claims  
- No fabricated COMPLETE on dataset or segments  
- No `cf_premium` dual-run / no re-execute of already-covered Aug window  
- No tokens / secrets in proof  
- Worker pass ≠ Coverage COMPLETE  
- COMPLETE count not claimed changed by this ticket  
