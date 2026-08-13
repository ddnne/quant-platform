# P0: markets_margin_interest detail_json C8 → pass + projection FRESH (2026-08-13)

**Mass / READY:** NO-GO  
**COMPLETE fabrications:** none  
**cf_premium dual-run:** **avoided** — bars + markets_breakdown executes already live (`ps`); margin `--execute` skipped (SUCCESS raw>0 already covers `2026-08-12`)  
**base SHA (PRE):** `aa43389`

## PRE snapshot (remote D1 `quant-ingest`)

| Metric | PRE |
|--------|-----|
| `markets_margin_interest.status` | **PARTIAL** |
| `observed_start` / `observed_end` | `2024-01-01` → **`2026-08-12`** |
| `detail_json` C8 | **fail** `stale: 530 day(s) > 7` |
| C8 `latest_event_time` | **`2025-02-28T00:00:00+09:00`** (cold remnant) |
| C8 `reference` / `max_days` / `days_lag` | `2026-08-12` / 7 / **530** |
| SUCCESS raw>0 receipt max `segment_end` | **`2026-08-12`** (n=22, sum_raw=144773; window `2026-05-13`…`2026-08-12`) |
| D1 hot `jquants_records` max | `2026-07-31` only (R2-only structured path residual) |
| sticky segments | COMPLETE **14** / PARTIAL **150** |
| projection | `projgen-f3dd0213…` `generated_at=2026-08-13T11:39:06Z` (wall-clock stale) |

### Root cause (honest)

- Dataset is **R2-only structured** (`write_path_config.isR2Only`). D1 hot is not SoT for latest events.
- `detail_json.checks` C8 still carried **local cold-plane** max `2025-02-28` from an older ledger refresh.
- Receipt plane already had lag **1d ≤ 7** vs `2026-08-13`, but C8 text was not re-scored → user-visible **C8 fail**.

## Code / path changes (real data only)

1. **`coverage_ledger._apply_receipt_freshness_c8`** — when SUCCESS `raw_row_count>0` `receipt_end` is fresher than hot C8, re-score C8 with `source=receipt_observed_end` (no invented dates).
2. **`ops_reeval_observed_window.py`** — remote path now rewrites `detail_json.checks` C8 + `observed_window` from the same receipt query (segments untouched; no COMPLETE claim).
3. **`BackfillPlanner` + `JQUANTS_SUBSCRIPTION_FLOOR=2006-08-13`** — never emit jobs with `requested_from` before subscription floor (fail id **2522** was `2006-08-12` → HTTP 400).

## Actions

### 1. Margin latest `--execute` — skipped (dual + evidence)

| Check | Result |
|-------|--------|
| `ps` cf_premium | **2 live** (bars mid-hole + markets_breakdown) |
| SUCCESS raw>0 max end | already **`2026-08-12`** (runs 1575/1585/2509/2519, raw=4259) |
| Decision | **no third dual execute** |

### 2. Local ledger refresh (receipt import + checks)

```bash
# upsert remote SUCCESS raw>0 Aug receipts into local collection_receipts
.venv/bin/python scripts/refresh_coverage_ledger.py \
  --db data/structured/ingestion.sqlite \
  --datasets markets_margin_interest --today 2026-08-13 --freshness-days 7
```

| Field | Local POST |
|-------|------------|
| status | **PARTIAL** (14 COMPLETE / 150 PARTIAL) |
| `observed_end` | **`2026-08-12`** |
| C8 | **pass** `1 day(s)`, `latest_event_time=2026-08-12`, `source=receipt_observed_end`, hot remnant `2025-02-28` retained in metrics |

### 3. Remote reeval (observed + detail C8)

```bash
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset markets_margin_interest --today 2026-08-13 --freshness-days 7
```

| Field | PRE | POST |
|-------|-----|------|
| `observed_end` | `2026-08-12` | **`2026-08-12`** (held) |
| `status` | PARTIAL | **PARTIAL** (unchanged; no COMPLETE) |
| detail C8 status | **fail** 530d | **pass** 1d |
| C8 `latest_event_time` | `2025-02-28…` | **`2026-08-12`** (`source=receipt_observed_end`) |
| C8 `reference` | `2026-08-12` | **`2026-08-13`** |
| `evaluated_at` | `2026-08-13T11:44:05Z` | **`2026-08-13T12:14:10.873479+00:00`** |
| segments | 14/150 | **untouched** |

### 4. Projection freshness (age=0)

```bash
.venv/bin/python scripts/ops_reeval_freshness.py
```

| Field | POST |
|-------|------|
| status | **FRESH** |
| `generated_at` | **`2026-08-13T12:14:17.185113+00:00`** |
| `age_seconds` | **0** |
| `projection_generation_id` | **`projgen-a34f7703ba9b4c7694654fb1df7aa773`** |
| `refresh_status` | `ops_reeval_freshness` |
| COMPLETE segments | **untouched** |

## POST summary

| Metric | POST |
|--------|------|
| margin status | **PARTIAL** |
| margin `observed_end` | **`2026-08-12`** |
| **detail_json C8** | **pass** lag **1** ≤ 7 |
| C8 source | `receipt_observed_end` (real SUCCESS raw>0) |
| projection | **FRESH** / **`2026-08-13T12:14:17.185113+00:00`** / age **0** |
| COMPLETE fabrication | **none** |
| Mass / READY | **NO-GO** |
| planner OOS floor | **2006-08-13** (no more 2522-class pre-floor jobs) |

## Absolute bans held

- No Mass / READY / B0 claims  
- No fabricated COMPLETE on dataset or segments  
- No concurrent third `cf_premium` while bars/breakdown execute  
- No tokens / secrets in proof  
- Worker pass ≠ Coverage COMPLETE  
- C8 pass uses **real receipt segment_end**, not invented event times  
