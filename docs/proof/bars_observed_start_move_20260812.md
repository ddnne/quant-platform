# Proof: equities_bars_daily observed_start moved before 2024

**Date:** 2026-08-12  
**P0:** Move `dataset_coverage.observed_start` for `equities_bars_daily` earlier than 2024-01-01 using real SUCCESS receipts (`raw_row_count > 0`).  
**Code SHA (fix):** `22a9d56` — `fix(coverage): union receipt plane into observed_start/end`  
**No Mass / READY / Phase7 / synthetic COMPLETE.**  
**cf_premium_backfill:** concurrent week-chunk job (pid 9623, 2008-05-01→2023-12-31) was left running; **no second execute started**. Job exited by proof time (`state.jsonl` ~40 lines).

## Root cause

Premium R2-only structured path keeps D1 `jquants_records` as a **hot window**. Coverage C4 therefore reported `event_time_min ≈ 2024-01-04` even after historical raw + SUCCESS receipts landed for 2008+.

## Fix

`packages/data_plane/storage/coverage_ledger.py`:

| Helper | Role |
|--------|------|
| `_date_prefix` | Normalize ISO / calendar to `YYYY-MM-DD` for ordering |
| `_receipt_observed_window` | Min/max segment bounds over **SUCCESS** receipts with **`raw_row_count > 0`** only (empty SUCCESS shells ignored) |
| `_merge_observed_window` | Union hot C4 window with receipt plane; preserve full hot timestamp when same calendar day wins |

`refresh_coverage_ledger` merges receipt evidence into `observed_start` / `observed_end` and records `detail_json.observed_window` (`source=receipt_union_hot` when receipts contribute).

**Unit tests** (`tests/test_phase61_coverage_v2.py`):

- `test_receipt_observed_window_ignores_empty_success_shells` — empty SUCCESS + FAILED ignored; early raw SUCCESS advances start
- `test_merge_observed_window_preserves_hot_timestamp_when_same_day` — same-day hot ISO kept; receipt-only; empty receipt no-op

```text
.venv/bin/python -m pytest \
  tests/test_phase61_coverage_v2.py::test_receipt_observed_window_ignores_empty_success_shells \
  tests/test_phase61_coverage_v2.py::test_merge_observed_window_preserves_hot_timestamp_when_same_day -q
# ..  (pass)
```

## PRE (session start, live remote + local)

| Field | Local research DB | Remote D1 `quant-ingest` |
|-------|-------------------|--------------------------|
| `observed_start` | `2024-01-04T15:00:00+09:00` | `2024-01-04T15:00:00+09:00` |
| `observed_end` | `2026-08-10T15:30:00+09:00` | `2026-08-10T15:30:00+09:00` |
| `status` | PARTIAL | PARTIAL |
| `row_count` (hot) | 803862 | 803862 |
| bars COMPLETE segs | 12 | 12 |

Session-start remote receipts (SUCCESS + `raw_row_count>0`): **n=123**, min `2008-05-01`, max `2026-08-10`, **n_pre2024=104**, sum_raw≈2.8e6.

## Local refresh

```text
.venv/bin/python -u scripts/refresh_coverage_ledger.py \
  --db data/structured/ingestion.sqlite --datasets equities_bars_daily
```

| Field | POST local |
|-------|------------|
| `observed_start` | **`2008-05-01`** |
| `observed_end` | `2026-08-11` |
| `status` | PARTIAL |
| `row_count` | 803862 |
| `evaluated_at` | `2026-08-12T14:28:47.035017+00:00` |
| `detail_json.observed_window` | `receipt_start=2008-05-01`, `receipt_end=2026-08-11`, `receipt_raw_rows=2932972`, `source=receipt_union_hot` |
| SUCCESS receipts raw>0 | n=75, span 2008-05-01…2026-08-11, sum_raw=2932972 |
| bars COMPLETE segs | **11** (`2024-01`…`2024-03`, `2025-04`, `2026-01`…`2026-07`) — sticky `2026-08` demoted on local re-eval (receipt identity / inventory); **not projected remote** |

## Remote update path

**Full `publish_ops_projection --apply-remote` skipped on purpose:** local bars COMPLETE (11) < remote (12); total COMPLETE was local 480 ≥ remote 479 (guard GO) but applying would demote remote sticky `2026-08` COMPLETE. Out of P0 scope.

Remote `observed_start` was updated surgically (receipt-plane evidence already on D1; no synthetic receipts). At proof verification:

| Field | POST remote |
|-------|-------------|
| `observed_start` | **`2008-05-01`** (< 2024-01-01 ✓) |
| `observed_end` | `2026-08-10T15:30:00+09:00` |
| `status` | PARTIAL |
| `row_count` | 803862 |
| `evaluated_at` | `2026-08-12T14:27:44.364605+00:00` |
| SUCCESS receipts raw>0 | n=**150**, span 2008-05-01…2026-08-10, sum_raw=**3048527** |
| `raw_retention_manifests` (dataset) | **443** (growing under backfill; earlier session ~389) |
| bars COMPLETE segs | **12** — `2024-01`, `2024-02`, `2024-03`, `2025-04`, `2026-01`…`2026-08` (sticky inventory preserved) |

Ops helper (committed with this proof): `scripts/ops_reeval_observed_window.py` — remote D1 UPDATE of `observed_*` only from SUCCESS+raw>0 receipts; does **not** rewrite `coverage_segments` or claim COMPLETE.

## Acceptance

| Gate | Result |
|------|--------|
| Code unions SUCCESS raw>0 receipts into observed window | **PASS** (`22a9d56`) |
| Empty SUCCESS shells do not extend window | **PASS** (unit test) |
| Local `observed_start` < 2024-01-01 | **PASS** (`2008-05-01`) |
| Remote `observed_start` < 2024-01-01 | **PASS** (`2008-05-01`) |
| Evidence = real raw_row_count>0 receipts (not Mass/捏造) | **PASS** |
| No dual cf_premium_backfill execute | **PASS** |
| No COMPLETE promotion claimed | **PASS** (dataset remains PARTIAL) |

## Honest limits

- Dataset status remains **PARTIAL** — historical months are not all TRUSTED-COMPLETE; only the **observed calendar span** advanced.
- Hot D1 `row_count` still ~804k (hot window); historical structured lives on R2.
- Local sticky `2026-08` demotion during refresh was **not** pushed to remote.
- Backfill continues to add raw manifests / receipts; later refreshes may widen `observed_end` further under the same union rule.
- Contract history floor for bars remains planner range ~2006-08-12+; earliest **receipt-backed** observed_start today is **2008-05-01** (honest min of SUCCESS+raw>0).

## Commands (reproducible)

```bash
# unit
.venv/bin/python -m pytest tests/test_phase61_coverage_v2.py -k receipt_observed_window -q

# local refresh
.venv/bin/python -u scripts/refresh_coverage_ledger.py \
  --db data/structured/ingestion.sqlite --datasets equities_bars_daily

# remote dry-run re-eval (no segment rewrite)
.venv/bin/python -u scripts/ops_reeval_observed_window.py \
  --dataset equities_bars_daily --dry-run
```
