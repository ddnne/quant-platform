# fins_summary history → observed_start < 2024 (2026-08-13)

**Mass / READY / raw無し COMPLETE: NO-GO**  
**Worker pass ≠ Coverage COMPLETE** (no fins_summary COMPLETE seal claimed)

## Contract / planner notes

| item | value |
|------|------:|
| Coverage Contract `history_target_start` | **2008-01-08** |
| Date mode | `today` (month chunks; paced serial after 429) |
| Track A focus range | 2008-01-08 → 2099-12-31 |
| This wave span | **2014-01-01 → 2015-12-31** (24 month jobs) |

Empty API shells (`rowsInserted=0`) do **not** extend `observed_*` (receipt filter `raw_row_count > 0`).

## PRE (remote D1 `quant-ingest`)

| metric | value |
|--------|------:|
| `dataset_coverage.observed_start` | **2024-01-01** |
| `dataset_coverage.observed_end` | 2026-08-11 |
| `dataset_coverage.status` | PARTIAL |
| `dataset_coverage.row_count` | 6121 (hot residual; not full R2 history) |
| SUCCESS receipts `raw_row_count>0` | n≈**31**, window **2026-05-13 → 2026-08-12** (hot only) |
| `raw_retention_manifests` (dataset) | **62** (complete 55) |

No secrets logged. Dual `cf_premium_backfill` gate: `ps` checked before each wave; **single fins driver only** (no concurrent bars/breakdown).

## Execute waves

### Wave 0 — planner dry-run

```text
.venv/bin/python scripts/ops/cf_premium_backfill.py \
  --datasets fins_summary \
  --from-date 2008-01-08 --to-date 2023-12-31 \
  --plan-out .glm-logs/cf-backfill/fins_hist_plan.json \
  --queue-out .glm-logs/cf-backfill/fins_hist_queue.json
```

| field | value |
|-------|------:|
| plan_jobs | **192** (month segments 2008-01 → 2023-12) |
| pool | fins (isolated) |

### Wave 1 — host parallel (fail: 429)

```text
.venv/bin/python scripts/ops/cf_premium_backfill.py \
  --datasets fins_summary \
  --from-date 2008-01-08 --to-date 2023-12-31 \
  --execute --max-jobs 48 --fins-workers 2 \
  --plan-out .glm-logs/cf-backfill/fins_hist_plan.json \
  --queue-out .glm-logs/cf-backfill/fins_hist_queue.json \
  --state-out .glm-logs/cf-backfill/fins_hist_state.jsonl
```

| field | value |
|-------|------:|
| executed | **48** |
| pass | **2** (2008-01, 2008-02 empty shells, `rowsInserted=0`) |
| fail | **46** (transient HTTP **429** retries exhausted) |

Rapid dual-worker dispatch burned upstream fins budget; host RPM alone does not pace Worker-internal pagination.

### Wave 2 — serial + low host RPM (still 429 cascade)

```text
.venv/bin/python scripts/ops/cf_premium_backfill.py \
  --datasets fins_summary \
  --from-date 2008-01-08 --to-date 2023-12-31 \
  --execute --max-jobs 36 --fins-workers 1 --workers 1 --fins-rpm 60 \
  --plan-out .glm-logs/cf-backfill/fins_hist_w2_plan.json \
  --queue-out .glm-logs/cf-backfill/fins_hist_w2_queue.json \
  --state-out .glm-logs/cf-backfill/fins_hist_w2_state.jsonl
```

| field | value |
|-------|------:|
| pass | **2** |
| fail | **34** (429 cascade: fail-fast jobs re-hammer the pool) |

### Probe (cooldown 90s) — month OK with real rows

| range | status | rowsInserted |
|-------|--------|-------------:|
| 2015-06-01..30 | pass | **419** |
| 2020-03-01..07 | pass | **82** |

### Wave 3 — paced serial month loop (SUCCESS + raw) — **primary**

Single process, sleep 12s after pass / 45s + 1 retry after fail. **max-jobs=48** requested; process delivered **24** consecutive months (2014-01 → 2015-12) all final-pass before host exit (no COMPLETE claim).

```text
# month ranges from contract-dense window 2014-01 → 2023-12
# paced curl POST /v1/run?dataset=fins_summary&from=&to=
# logs: .glm-logs/cf-backfill/fins_hist_paced.log
# state: .glm-logs/cf-backfill/fins_hist_paced_state.tsv
```

| field | value |
|-------|------:|
| months final-pass | **24 / 24** |
| first-attempt fail then retry pass | **14** |
| still fail after retry | **0** |
| rowsInserted sum | **39_364** |
| rawBytes sum (final) | **~76.6 MB** |
| span | **2014-01-01 → 2015-12-31** |

Artifacts: `.glm-logs/cf-backfill/fins_hist_paced*` (local; not committed).

## Coverage reeval (remote receipt union)

```text
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset fins_summary
```

Receipt window used: SUCCESS + `raw_row_count>0` → min **2014-01-01**, max **2026-08-12**, n=**58**, sum_raw=**51_322**.

`coverage_segments` **not** rewritten. No COMPLETE / Mass / READY claim.

## POST (remote D1)

| metric | PRE | POST | Δ |
|--------|----:|-----:|--:|
| **observed_start** | **2024-01-01** | **2014-01-01** | moved **&lt; 2024-01-01** ✓ |
| observed_end | 2026-08-11 | 2026-08-12 | advanced |
| status | PARTIAL | PARTIAL | (no COMPLETE claim) |
| nz SUCCESS receipts | ~31 (hot) | **58** | **+27** history |
| nz receipt min start | 2026-05-13 | **2014-01-01** | history |
| raw_manifests (dataset) | 62 | **187** | **+125** |
| raw COMPLETE (dataset) | 55 | 86 | +31 |
| raw sum row_count | 11_668 | 66_108 | +54_440 |

### Success criteria

1. **remote `observed_start` < 2024-01-01** → **PASS** (`2014-01-01`)
2. **SUCCESS + raw receipts** (no raw無し COMPLETE; empty shells ignored) → **PASS**
3. **max-jobs ≥ 24** real-data month execute → **PASS** (24/24 paced)
4. **cf_premium dual ban** (ps gate; single fins process) → **PASS**
5. docs/proof + git commit push → (see SHA after push)

### Explicit non-claims

- **No** fins_summary dataset COMPLETE
- **No** Mass / READY
- **No** seal of 2008 empty shells as history (`rowsInserted=0` ignored by reeval)
- Residual month jobs for **2016-01 → 2023-12** (and 2008–2013) still pending vs 192-plan
- D1 `jquants_records` / coverage `row_count=6121` remains hot residual; long history is R2 raw + receipts
- Worker pass ≠ Coverage COMPLETE

## Ops note

Prefer **paced serial** (`fins-workers=1` + inter-job sleep ≥12s, retry+45s on fail) for `fins_summary` month ranges. Dual-worker / fail-fast 429 cascades do not recover without cooldown. After each real-data wave re-run `scripts/ops_reeval_observed_window.py --dataset fins_summary`. Empty SUCCESS (`raw_row_count=0`) never moves `observed_start`.
