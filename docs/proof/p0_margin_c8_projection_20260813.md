# P0: markets_margin_interest C8 lag + projection FRESH (2026-08-13)

**Mass / READY:** NO-GO  
**COMPLETE fabrications:** none  
**cf_premium dual-run:** avoided (`ps` clear before each `--execute`; margin-only)  
**base SHA (PRE):** `9a6e930`

## PRE snapshot (remote D1 `quant-ingest`)

| Metric | PRE |
|--------|-----|
| `markets_margin_interest.status` | **PARTIAL** |
| `observed_start` / `observed_end` | `2024-01-01` → **`2026-08-12`** |
| receipt-plane C8 lag (`observed_end` vs JST/UTC day `2026-08-13`) | **1 calendar day ≤ max_days=7** → would **PASS** |
| `detail_json` C8 (cold/hot evaluation remnant) | **fail** `stale: 530 day(s) > 7`, `latest_event_time=2025-02-28T00:00:00+09:00`, `reference=2026-08-12` |
| `status_note` | `PARTIAL: segment plane + receipt observed; local C8 hot-window STALE not dataset SoT` |
| sticky segments | COMPLETE **14** / PARTIAL **150** / UNKNOWN **0** (PRE) |
| `ingestion_watermarks.last_event_date` | **`2026-08-07`** |
| `ingestion_watermarks.last_ingested_at` | `2026-08-13T20:15:42+09:00` (hourly cron) |
| ops projection | status **FRESH**, `generated_at=2026-08-13T01:01:07.627426+00:00`, stored `age_seconds=0` |
| projection **wall-clock age** at action (~11:28Z) | **~10.5 h** (still under max_age 86400; clock stale for ops) |
| active generation | `projgen-17ba75ec08a640339a7f057b7e36919d` |
| COMPLETE segments (global) | **490** |
| `collection_sla_status` | empty table (no row) |
| `ingestion_validation` latest | status **pass**, `rows_inserted=0` (hourly empty publish days) |
| raw_n (`raw_retention_manifests`) | **~3535** |

### PRE root cause (coverage vs watermark mismatch)

| Plane | Latest event | vs 2026-08-13 | C8 (max_days=7) |
|-------|--------------|---------------|-----------------|
| Cold structured remnant in `detail_json` C4/C8 | **2025-02-28** | ~530d | **fail** (stale text) |
| D1 hot `jquants_records` (window only) | **2026-07-31** (after Jul re-ingest) | ~13d | would fail if used alone |
| Watermark `last_event_date` | **2026-08-07** | **6d** | would **PASS** |
| Receipt SUCCESS `raw_row_count>0` max `segment_end` | **2026-08-12** | **1d** | would **PASS** |
| Dataset SoT status | **PARTIAL** | — | not COMPLETE; C8 cold fail **not** flipped to STALE (receipt reeval path) |

Gate note: `coverage_ledger._dataset_status` maps C8 fail → STALE when ledger is fully re-evaluated from local hot/cold facts. Remote status remains **PARTIAL** via receipt-plane reeval + honesty (segment aggregate 14/164 COMPLETE). **Do not** claim COMPLETE.

## Actions

### 1. Latest week/month `--execute` (margin only; no dual)

```bash
# ps clear each time; token from ~/.config (never logged)
.venv/bin/python scripts/ops/cf_premium_backfill.py --execute \
  --datasets markets_margin_interest --latest-only \
  --from-date 2026-07-01 --to-date 2026-08-12
# then July full month; then August re-exec for watermark restore
```

| Run | Segment | window | rowsInserted | state |
|-----|---------|--------|--------------|-------|
| latest-only | `2026-08` | `2026-08-01`→`2026-08-12` | **4259** | pass |
| month | `2026-07` | `2026-07-01`→`2026-07-31` | **21277** | pass |
| latest-only (re) | `2026-08` | `2026-08-01`→`2026-08-12` | **4259** | pass (watermark restore after Jul) |

Artifacts (gitignored `.glm-logs/cf-backfill/`):
- `margin_latest_exec_*`, `margin_jul_exec_*`, `margin_latest2_exec_*`

Worker pass ≠ Coverage COMPLETE (explicit).

### 2. `ops_reeval_observed_window` (no segment rewrite)

```bash
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset markets_margin_interest
```

| Field | PRE | POST |
|-------|-----|------|
| `observed_end` | `2026-08-12` | **`2026-08-12`** (held) |
| `observed_start` | `2024-01-01` | **`2024-01-01`** (history still DEFER) |
| `status` | PARTIAL | **PARTIAL** (no COMPLETE) |
| `evaluated_at` | `2026-08-13T01:01:09Z` | **`2026-08-13T11:30:53.009225+00:00`** |
| receipt window (raw>0) | — | `2026-05-13`…`2026-08-12`, n=**22**, sum_raw=**144773** |

### 3. C8 pass condition (honest)

| Check | Value |
|-------|-------|
| Policy | `expected_frequency=weekly`, C8 `max_days=7` |
| Receipt / `observed_end` lag | **1d ≤ 7** → **PASS** on receipt plane |
| Watermark lag (`2026-08-07`) | **6d ≤ 7** → **PASS** |
| Cold `detail_json` C8 text | still **fail** 530d / `2025-02-28` (not rewritten; not dataset SoT) |
| Dataset status | remains **PARTIAL** (segment inventory); **not** COMPLETE |

No remote `status='COMPLETE'` UPDATE. Sticky COMPLETE months untouched.

### 4. Projection re-publish (targeted freshness → age=0 FRESH)

```bash
.venv/bin/python scripts/ops_reeval_freshness.py
```

| Field | PRE | POST |
|-------|-----|------|
| status | FRESH | **FRESH** |
| `generated_at` | `2026-08-13T01:01:07.627426+00:00` | **`2026-08-13T11:31:12.718889+00:00`** |
| wall-clock age | ~10.5 h | **~0 s** |
| `age_seconds` (stored) | 0 | **0** |
| `projection_generation_id` | `projgen-17ba75ec…` | **`projgen-8811c3ea7cb746b58980a93eda7fada5`** |
| `refresh_status` | ops_reeval_freshness | `ops_reeval_freshness` |
| COMPLETE segments global | 490 | **490 untouched** |

## POST summary

| Metric | POST |
|--------|------|
| margin status | **PARTIAL** |
| margin `observed_end` / event max (receipt) | **`2026-08-12`** |
| C8 lag (receipt plane vs 2026-08-13) | **1 day ≤ 7** (PASS condition met) |
| watermark `last_event_date` | **`2026-08-07`** |
| D1 hot max `event_time` | `2026-07-31` (hot window; Aug on R2/receipt) |
| segments | COMPLETE **14** / PARTIAL **149** / UNKNOWN **1** |
| projection status / generated_at / age | **FRESH** / **`2026-08-13T11:31:12.718889+00:00`** / **0s** |
| COMPLETE fabrication | **none** |
| Mass / READY | **NO-GO** |
| cf_premium dual | **avoided** |

## Absolute bans held

- No Mass / READY / B0 claims  
- No fabricated COMPLETE on dataset or segments  
- No concurrent second `cf_premium` bars/other dual run  
- No tokens / secrets in proof or logs  
- Worker pass ≠ Coverage COMPLETE  
- Cold C8 530d text left honest (not forged to pass); receipt-plane lag is the freshness SoT for this ticket
