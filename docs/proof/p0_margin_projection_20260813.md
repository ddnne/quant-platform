# P0 margin + projection (2026-08-13 JST / 2026-08-12 UTC)

**Mass / READY:** NO-GO  
**COMPLETE fabrications:** none  
**cf_premium dual-run:** bars gap chain already `EXECUTE_DONE` (no concurrent bars); margin-only `--execute`  
**base SHA (PRE):** `43dd2350548ecd05ef513bc6b8cb50375b8976d3`

## PRE snapshot (remote D1)

| Metric | PRE |
|--------|-----|
| `markets_margin_interest.status` | **PARTIAL** |
| `observed_start` / `observed_end` | `2024-01-12T00:00:00+09:00` → **`2026-08-11`** |
| C8 lag (`observed_end` vs today JST `2026-08-13`) | **2 calendar days ≤ max_days=7** → would PASS |
| `detail_json` C8 (stale cold-plane remnant) | still cites `latest_event_time=2025-02-28` / 530d fail text (not rewritten) |
| sticky segments | COMPLETE **14** / PARTIAL **150** |
| `ingestion_watermarks.last_event_date` | `2026-08-07` |
| ops projection | status **FRESH**, `generated_at=2026-08-12T14:31:19Z`, stored `age_seconds=0` |
| projection real age at action | **~28769 s (~8.0 h)** vs max_age 86400 |
| active generation | `projgen-3c7840ac7f2f4607a73fb480886555d7` |
| COMPLETE segments (global) | local **482** = remote **482** (publish guard would GO) |

## Actions

### 1. Lag confirmation (observed_end vs today, C8)

- Policy: `expected_frequency=weekly`, C8 `max_days=7`.
- PRE: `observed_end=2026-08-11` vs `2026-08-13` JST → lag **2d** ≤ 7.
- POST: `observed_end=2026-08-12` → lag **1d** ≤ 7 → **C8 would PASS** on receipt plane.
- Did **not** flip status to COMPLETE. Did **not** fabricate Mass/READY.
- Note: `detail_json.checks` still holds legacy cold-plane C8 fail text; status plane remains **PARTIAL** (segment aggregate + honesty).

### 2. Latest week/month `--execute` (margin only)

| Run | Segment | window | rowsInserted | state |
|-----|---------|--------|--------------|-------|
| latest-only | `2026-08` | `2026-08-01`→`2026-08-12` | **4259** | pass |
| month | `2026-07` | `2026-07-01`→`2026-07-31` | **21277** | pass |
| latest-only (re) | `2026-08` | `2026-08-01`→`2026-08-12` | **4259** | pass (watermark restore after Jul overwrite) |

Artifacts (gitignored `.glm-logs/`):
- `margin_latest_20260813_*`, `margin_jul_20260813_*`, `margin_latest2_20260813_*`

Receipt plane after execute: SUCCESS `raw_row_count>0` max `segment_end` = **`2026-08-12`** (run_id 1575+).  
D1 hot `jquants_records` remains July window only (`2026-07-03`…`2026-07-31`, n=21277) — R2/receipt truth for August weekly batch; not used to claim COMPLETE.

### 3. reeval + status (PARTIAL only)

```bash
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset markets_margin_interest
```

| Field | PRE | POST |
|-------|-----|------|
| `observed_end` | `2026-08-11` | **`2026-08-12`** |
| `observed_start` | `2024-01-12T00:00:00+09:00` | unchanged |
| `status` | PARTIAL | **PARTIAL** (unchanged; no COMPLETE) |
| `evaluated_at` | `2026-08-12T14:34:28Z` | `2026-08-12T22:30:26Z` |
| receipt window | — | `2026-05-13`…`2026-08-12`, n=18, sum_raw≈110719 |

Segment inventory (no rewrite by reeval script): COMPLETE **14** sticky / PARTIAL **149** / UNKNOWN **1**.  
**No** remote `status='COMPLETE'` UPDATE. Sticky COMPLETE months untouched.

### 4. Projection re-publish (fail-closed age → FRESH)

Used **targeted** path (no segment rewrite, COMPLETE-safe):

```bash
.venv/bin/python scripts/ops_reeval_freshness.py
```

| Field | PRE | POST |
|-------|-----|------|
| status | FRESH | **FRESH** |
| `generated_at` | `2026-08-12T14:31:19.203190+00:00` | **`2026-08-12T22:30:48.706767+00:00`** |
| real age | ~28769 s | **0 s** (clock reset) |
| `age_seconds` (stored) | 0 | **0** |
| `projection_generation_id` | `projgen-3c7840ac…` | **`projgen-a101ed0a8bea4edebd6bcbfc29755ffc`** |
| `refresh_status` | (prior full publish) | `ops_reeval_freshness` |
| COMPLETE segments | 482 | **482 untouched** |

Full `publish_ops_projection --apply-remote` not required: local COMPLETE == remote COMPLETE (482), but targeted freshness is sufficient and avoids full SQL export risk. Mass NO-GO held.

## POST summary

| Metric | POST |
|--------|------|
| margin status | **PARTIAL** |
| margin `observed_end` | **2026-08-12** |
| C8 lag vs 2026-08-13 JST | **1 day ≤ 7** (would PASS) |
| watermark `last_event_date` | **2026-08-07** (restored after Jul then Aug re-exec) |
| projection status / age | **FRESH / 0s** |
| COMPLETE fabrication | **none** |
| Mass / READY | **NO-GO** |
| cf_premium dual | **avoided** (bars idle) |

## Absolute bans held

- No Mass / READY / B0 claims  
- No fabricated COMPLETE on dataset or segments  
- No second concurrent `cf_premium` bars run  
- No tokens / secrets in proof  
- Worker pass ≠ Coverage COMPLETE (explicit)
