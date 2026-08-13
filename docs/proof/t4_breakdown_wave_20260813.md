# T4 / G3 — markets_breakdown week-chunk hole fill (2026-08-13)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** none claimed  
**bars / master / misc:** not killed (peer general jobs left running)

## Scope

| item | value |
|------|------:|
| dataset | `markets_breakdown` |
| prior | MB solo **409/409** week-chunks (2016-03→2023-12); `observed_start` already **`2015-03-26`** |
| this pass | receipt-plane gap scan + week-chunk fill wave `t4b_mb_*` |
| workers / RPM | **2** / `--general-rpm 495` (shared general with peers) |
| log prefix | `.glm-logs/cf-backfill/t4b_mb_*` |

## PRE — remote receipt gap scan (SUCCESS + `raw_row_count>0`)

Calendar union of nz SUCCESS receipts for `markets_breakdown`:

| window | result |
|--------|--------|
| **2015-03-26 → 2023-12-31** | continuous **except** **2019-04-30 → 2019-05-05** (6 calendar days) |
| **2024-01-02 → 2026-05-12** | no week-level nz receipts (segments **2024-01…2026-04** already **COMPLETE** — planner skips) |
| zero-nz months (2015–2023) | **2015-01**, **2015-02** only (pre-source empty shells; do not move `observed_*`) |

Planner dry-run (`--week-chunks`, 2015-03-26…2023-12-31, empty db so no COMPLETE skip): **458** week jobs; only **2** windows had any missing covered days — both inside the 2019-04/05 hole.

## Execute — wave `t4b_mb_midhole`

```text
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets markets_breakdown \
  --from-date 2019-04-01 --to-date 2019-05-31 \
  --week-chunks --chunk-days 7 \
  --execute --workers 2 --general-rpm 495 --max-jobs 0 \
  --sleep-on-retry 3 \
  --plan-out .glm-logs/cf-backfill/t4b_mb_midhole_plan.json \
  --queue-out .glm-logs/cf-backfill/t4b_mb_midhole_queue.json \
  --state-out .glm-logs/cf-backfill/t4b_mb_midhole_state.jsonl
```

| field | value |
|-------|------:|
| plan / executed | **9 / 9** |
| **pass** | **9** |
| **fail** | **0** |
| http_429 | **0** |
| host POST/min | **8.97** (window ≈53.5s) |
| rowsInserted sum | **149_398** |
| hole week `2019-04-29→2019-05-05` | pass, **`rowsInserted=0`** (API empty) |

### Golden Week 2019 note

2019-04-27…2019-05-06 was the extended imperial-transition holiday window (almost no TSE sessions). Empty `data[]` / `rowsInserted=0` on the hole week is **expected** — not a missing raw failure. Neighbor weeks inserted ~19k rows each.

Artifacts (local, not committed): `t4b_mb_midhole_{plan,queue,state,run}.log` under `.glm-logs/cf-backfill/`.

## Coverage reeval (required after wave)

```text
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset markets_breakdown
```

| metric | PRE | POST |
|--------|----:|-----:|
| status | PARTIAL | **PARTIAL** |
| **observed_start** | **2015-03-26** | **`2015-03-26`** |
| **observed_end** | 2026-08-12 | **2026-08-12** |
| nz SUCCESS receipts | — | n=**631**, sum_raw=**10_966_392** |
| C8 | pass lag 1d | **pass** lag **1**d (`receipt_observed_end`) |
| coverage_segments | — | **untouched** (no COMPLETE invent) |

Log: `.glm-logs/cf-backfill/t4b_mb_reeval.log`.

## POST residual shape

| item | result |
|------|--------|
| trading-day raw continuity 2015-03-26…2023-12 | **held** (only GW empty calendar hole) |
| 2015-01/02 empty shells | unchanged (no `observed_*` move) |
| 2024-01…2026-04 | still **COMPLETE** segments (planner skip; not re-opened) |
| dataset COMPLETE | **not claimed** |
| worker pass ≠ Coverage COMPLETE | **held** |

## Explicit non-claims / bans held

- **No** Mass / READY / Phase7 ON  
- **No** empty-raw COMPLETE seal  
- **No** kill of master / misc / bars / other peer drivers  
- **No** secrets logged  
- Segment COMPLETE inventory for 2013–2023 remains PARTIAL (honest; seal only with raw+structured+signed receipt)

## Ops notes

- Prefer `--week-chunks --chunk-days 7` for `markets_breakdown` dense months (full-month → HTTP 503).  
- After every full publish, re-run `ops_reeval_observed_window.py --dataset markets_breakdown` (publish can reset `observed_*` toward hot facts).  
- Calendar gaps that are all TSE holidays (e.g. GW 2019) show as empty week jobs — do not treat as hard fail.
