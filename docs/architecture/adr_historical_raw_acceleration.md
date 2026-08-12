# ADR: Historical raw acceleration (Track A)

**Status:** accepted 2026-08-12  
**Mass research:** NO-GO  
**Local DB:** research mirror only — **not** CF control-plane SoT  
**Evidence closure:** COMPLETE only when **raw + structured** evidence exists (never fabricate)

## Context

PRE (live / research mirror snapshot, 2026-08-12):

| Metric | Approx |
|--------|--------|
| `coverage_segments` COMPLETE | ~404 |
| COMPLETE datasets | 2 (`markets_calendar`, `jsda_tokyo_repo_rates`) |
| `markets_margin_interest` | **STALE** |
| Ops projection | FRESH |
| Remote `raw_retention_manifests` | ~1488 (local mirror may be 0) |

Large history gaps remain for high-value J-Quants Premium series. Day-by-day sequential backfill under-utilizes Premium budget and CF Workers wall-clock.

## Decision

### 1. Purpose (Track A targets)

| Dataset | Acceleration focus |
|---------|-------------------|
| `equities_bars_daily` | **2004-01-05 → 2023-12-31** (history before recent FRESH window) |
| `indices_bars_daily_topix` | Full contract history from `history_target_start` (2008-01-01) |
| `markets_breakdown` | Missing calendar months vs contract |
| `fins_summary` | Missing months (event-driven; pagination-exhausted empty OK) |
| `equities_master` | Missing months / SCD2 event backfill gaps |
| `markets_margin_interest` | **Latest week/month only** for freshness; history separate; do not forge COMPLETE |

Coverage Contract (`collection_coverage.json`) remains SoT for `history_target_start` and segment identity. Drivers never hand-write history starts outside the planner/contract.

### 2. J-Quants Premium rate model

| Pool | Budget | Notes |
|------|--------|-------|
| **general** | ~**500 req/min** (driver default **480 RPM** headroom) | Bars, master, markets_*, indices_*, derivatives, edinet, calendar |
| **fins** | **Separate budget** (~500/min class; default **480 RPM**) | `fins_*` endpoints only — do **not** share the general token bucket |

Worker-side floor remains ~125 ms between upstream calls (`platform/workers/ingestion-premium` `RATE_LIMIT_INTERVAL_MS`). Client-side dual pools prevent fins backfill from starving general (and vice versa) when CF `/v1/run` is fan-out from this host.

**Do not log tokens.** Token path: `~/.config/quant-platform/ingestion_run_token` or `INGESTION_RUN_TOKEN_FILE`.

### 3. Date-range batch is standard

- Standard unit: **dataset × inclusive date range** (prefer **calendar month** aligned to Coverage V2 `segment_id=YYYY-MM`).
- CF entrypoint: `POST {premium}/v1/run?dataset=&from=&to=` (Worker expands params / pagination).
- Prefer one range call per segment over per-day loops when the endpoint accepts `from`/`to` (or Worker range expansion).
- `today`-mode catalog rows still plan as range chunks for backfill; Worker maps to daily/date params.

### 4. CF Workers / parallel fetch

```
┌─────────────┐    plan(dataset×range)    ┌──────────────────────┐
│ Backfill    │ ────────────────────────► │ RangeBatchScheduler  │
│ Planner     │                           │ dual RPM + workers   │
└─────────────┘                           └──────────┬───────────┘
                                                     │ POST /v1/run
                                                     ▼
                                          ┌──────────────────────┐
                                          │ ingestion-premium    │
                                          │ R2 raw + structured  │
                                          │ D1 control / hot     │
                                          └──────────────────────┘
```

- Parallelism **overlaps RTT**; it does not exceed RPM.
- Default: dry-run plan only; `--execute` required for live POST.
- Max parallel workers are capped per pool (defaults: general 4, fins 2).

### 5. Storage plane (unchanged)

| Layer | Role |
|-------|------|
| **D1 `quant-ingest`** | Control/evidence + **hot** window only |
| **R2 `quant-raw`** | Raw evidence SoT |
| **R2 `quant-structured`** | Long structured history SoT |
| Local sqlite | Research/sync mirror — **never** CF SoT |

High-volume writers must not refill D1 full history (see `cf_native_storage_plane.md`, `write_routing_rules.md`).

### 6. Evidence closure rules

1. **COMPLETE** requires raw retention + structured reconciliation + eligible receipt (Coverage V2).
2. **Never** mark COMPLETE without raw.
3. **Never** Mass ON / READY from this track.
4. Worker `summary.status=pass` ≠ Coverage COMPLETE (planner `expected_evidence` is honest).
5. STALE stays STALE until C8 freshness + segment inventory actually clear — report honestly.

### 7. Daily visualization metrics (throughput report)

Script: `scripts/report_raw_throughput.py`

| Metric | Definition |
|--------|------------|
| `raw_manifests_total` | `COUNT(*)` of `raw_retention_manifests` |
| `raw_manifests_complete` | completeness=`COMPLETE` |
| `raw_manifests_by_dataset` | per-dataset counts / row_count / raw_bytes |
| `jquants_records_by_dataset` | rows + min/max `event_time` (local or synced mirror) |
| `complete_segments` | `coverage_segments.status='COMPLETE'` count |
| `complete_datasets` | `dataset_coverage.status='COMPLETE'` count |
| `stale_datasets` | status=`STALE` list |
| `partial_segments` | PARTIAL count |
| `track_a_focus` | per Track A dataset: complete segs / total segs / records span |
| `projection_status` | from `data/ops/projection_meta.json` if present |
| `pre_post_delta` | optional baseline JSON compare |

Outputs: JSON (machine) + Markdown (human). Tag snapshots PRE/POST around acceleration windows.

### 8. Throughput design numbers (planning envelope)

Assumptions (conservative, not a SLA):

| Parameter | Value |
|-----------|--------|
| General RPM cap | 480 |
| Fins RPM cap | 480 (isolated) |
| Parallel general workers | 4 |
| Parallel fins workers | 2 |
| Month segment / job | 1 CF `/v1/run` (range) |
| Upstream pages / month (bars, all codes) | highly variable (10²–10⁴); wall-clock dominated by pagination inside Worker |
| Planner jobs Track A @ full history (empty COMPLETE) | O(10²–10³) month segments |
| Host-side job dispatch rate | ≤ min(workers, RPM) — typically **≪** upstream page rate |

**Implication:** acceleration wins by (1) range jobs instead of day loops, (2) dual pools, (3) parallel dispatch of independent segments, (4) CF-side raw→R2 without re-hosting API keys. Closing COMPLETE still requires receipt seal after raw+structured — out of band from this scheduler.

### 9. Implementation anchors

| Component | Path |
|-----------|------|
| Planner | `packages/data_plane/ops/backfill_planner.py` |
| Range batch scheduler | `packages/data_plane/ops/range_batch_scheduler.py` |
| CF driver | `scripts/ops/cf_premium_backfill.py` |
| Local hist driver | `scripts/run_historical_backfill.py` |
| Throughput report | `scripts/report_raw_throughput.py` |
| Premium catalog | `packages/data_plane/data_contracts/jquants_premium_core.json` |
| Coverage contract | `packages/data_plane/data_contracts/collection_coverage.json` |

### 10. Non-goals / absolute bans

- Mass research ON / READY publication
- COMPLETE without raw
- Treating local sqlite as CF SoT
- Committing secrets, tokens, or sqlite DB blobs
- Large B1 import-path rewrites

## Consequences

- Operators dry-run plans by default; execute only when write path is R2-safe and D1 headroom is OK.
- Margin interest latest-only execute is allowed; residual STALE must be reported honestly until C8 + history close.
- Progress is measured by raw manifests + records span + honest segment states — not by green-washing COMPLETE counts.
