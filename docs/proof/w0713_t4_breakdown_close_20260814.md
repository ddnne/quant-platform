# G4 = T4: `markets_breakdown` residual close (2026-08-14)

**Mass / READY / Phase7:** **NO-GO / OFF**  
**empty COMPLETE:** **0** (SUCCESS `raw_row_count>0` required; digest raw &lt;25MB)  
**Worker pass ≠ Coverage COMPLETE** (held)  
**kill acq jobs:** **none** — peers left running (`cf_premium_backfill` t7, `seal_from_r2` t6, other issue writers)

**Prefix:** `w0713_t4_mb_*`  
**Dataset:** `markets_breakdown`  
**Base tip at this close:** `e1a708e` (origin/main; G1 bars + G2 master proofs already on main)

## Objective

| track | action |
|-------|--------|
| **T4 / G4** | residual week-chunk backfill + R2 week-merge seal + signed receipts **+N** |

Task PRE baseline: COMPLETE **32**. Close sealable months that already hold **usable R2 raw + structured** evidence (empty-raw ban).

**Forbidden held:** no Mass; no empty COMPLETE; no invent receipt without raw; no kill of live backfill.

---

## PRE (remote D1 `quant-ingest` / task brief)

| metric | value |
|--------|------:|
| `markets_breakdown` COMPLETE segs | **32** |
| COMPLETE months (PRE tip island) | **2024-01 … 2026-08** only (32) — history PARTIAL |
| G10 interim (same day, prior close) | COMPLETE **33** (`2023-12` receipt **900768**) |
| `observed_start` / `observed_end` | **2015-03-26** / 2026-08-13 |
| dataset status | PARTIAL |
| empty COMPLETE | **0** |

API/source floor for honest non-empty history: **2015-03** (empty shells **2013-01…2015-02** DEFER).

---

## 1) Backfill residual (week-chunks) — worker pass only

```text
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets markets_breakdown \
  --execute --workers 2 --general-rpm 495 --max-jobs 0 \
  --plan-out  .glm-logs/cf-backfill/w0713_t4_mb_residual_plan.json \
  --queue-out .glm-logs/cf-backfill/w0713_t4_mb_residual_queue.json \
  --state-out .glm-logs/cf-backfill/w0713_t4_mb_residual_state.jsonl
```

| wave | state file | n | pass | fail | notes |
|------|------------|--:|-----:|-----:|-------|
| residual | `w0713_t4_mb_residual_state.jsonl` | **44** | **35** | **9** | host POST/min **~10.34** |
| retry_a | `w0713_t4_mb_retry_a_state.jsonl` | 6 | 1 | 5 | |
| retry_b | `w0713_t4_mb_retry_b_state.jsonl` | 3 | 0 | 3 | |
| retry2 | `w0713_t4_mb_retry2_state.jsonl` | 6 | 5 | 1 | |
| retry2b | `w0713_t4_mb_retry2b_state.jsonl` | 3 | 0 | 3 | |
| **combined last-per-week-job** | — | **44** | **40** | **4** | fail reason `worker_error` |

PIDs natural exit (not killed): residual **87338**, retries **2865/2867/5267/5268**.

**Worker pass only — no COMPLETE inflation at this step.**

---

## 2) R2 week-merge seal prep (usable raw only)

Helper: `.glm-logs/w0713_t4_mb/seal_from_r2.py`  
Map: `.glm-logs/w0713_t4_mb/seal_map.json` (**36** months)  
Result: `.glm-logs/w0713_t4_mb/seal_result.jsonl` — **ready=36 / 36**

| field | value |
|-------|------|
| floor / ceil | **2015-03** / **2023-12** (2024-01… tip already COMPLETE) |
| min month rows | **20000** |
| digest raw cap | **20MB** (issue `_is_usable_raw` hard **&lt;25MB**) |
| path | remote COMPLETE nz manifests → R2 pages → month combine → digest raw + `normalize_generic` + `SqliteStore.upsert` |
| empty-raw skips | **0** in ready set |

Selected segment_ids: **2015-04 … 2018-03** (36 calendar months).  
All digest files size ~19.999MB with `raw_rows` / `normalized` 59k–82k (non-empty).

---

## 3) Signed receipts + ledger (this close **+36**)

`issue_receipts_parallel --struct-hint` on this dataset stalled on full-table `EXISTS jquants_records` over a multi‑GB research mirror.  
**Targeted issue** used seal_result known raw paths + seal-prep structured counts (same empty-raw / size gates as `issue_receipts_parallel._is_usable_raw`):

```text
# local driver (not committed): .glm-logs/g1g2g4-close targeted issuer
# inputs: .glm-logs/w0713_t4_mb/seal_result.jsonl
# authority: SignedReceiptAuthority / TRUSTED_COLLECTION / dev-receipt-v1
```

| field | value |
|-------|------:|
| issued | **36 / 36** |
| skipped / errors | **0 / 0** |
| receipt `run_id` | **900927 … 900962** |
| structured = raw_row_count | **yes** (script policy) |
| empty-raw skips | **0** |
| local COMPLETE after refresh | **69** (= 33 prior tip island + **36**) |

Artifact: `.glm-logs/g1g2g4-close/mb_targeted_issue.{log,json}`

### Issued segments (**+36**)

`2015-04` … `2018-03` (continuous). Remote receipt_run_id spot-check after publish includes **900928…900962** (and ledger may surface a newer SUCCESS for a given month if peers also wrote — never empty).

---

## 4) Publish (fail-closed) + reeval

```text
.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite --apply-remote
```

```text
complete_count_guard ok local=882 remote=846 force=False
remote projection applied
```

```text
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset markets_breakdown --today 2026-08-14 --freshness-days 7
.venv/bin/python scripts/ops_reeval_freshness.py
```

| field | PRE (task) | POST |
|-------|------------|------|
| **observed_start** | **2015-03-26** | **2015-03-26** |
| observed_end | 2026-08-13 | **2026-08-13** |
| status | PARTIAL | **PARTIAL** (dataset **not** COMPLETE) |
| C8 | pass | **pass** lag **1** |
| mb COMPLETE segs | **32** | **69** |
| freshness | — | **FRESH** `projgen-b8c5fbd06dd04b7e9c832bcc9b4e7ab7` age=0; `coverage_segments_untouched=1` |

---

## POST (remote D1 live verify)

| metric | PRE (task) | POST | Δ |
|--------|----------:|-----:|--:|
| **mb COMPLETE segs** | **32** | **69** | **+37** |
| this-close signed issue | — | **+36** | (G10 interim already **+1** for `2023-12`) |
| mb PARTIAL segs | 132 | **95** | −37 |
| platform COMPLETE segs | 742† / 846‡ | **882** | +36 this issue publish delta vs pre-publish 846 |
| empty COMPLETE | 0 | **0** | 0 |
| `raw_retention_manifests` total | 9455† | **9624** | peer acq Δ |

† residual SoT at G5 fins close. ‡ G1/G2 peer publishes already on remote before this MB apply.

### Remote COMPLETE inventory (mb)

- History sealed this close: **2015-04 … 2018-03** (**36**)
- Prior: **2023-12** (G10) + tip **2024-01 … 2026-08** (**32**) → total **69**
- Still PARTIAL / unsealed: **2015-03** floor month, **2018-04 … 2023-11**, etc. (need more R2 week-raw seal waves)

Dataset remains **PARTIAL** (not dataset-level COMPLETE).

---

## Backfill pass/fail summary (prefixes `w0713_t4_mb_*`)

| artifact | pass | fail |
|----------|-----:|-----:|
| residual state | 35 | 9 |
| retry waves (a/b/2/2b combined rows) | 6 | 12 |
| last-state unique week-jobs | **40** | **4** |

Worker fail residual exists; **not** one-shot re-dispatched here (honest close on sealable raw only; peers not starved).

---

## Forbidden / honesty

| Check | Result |
|-------|--------|
| Mass / READY / Phase7 | **NO-GO / OFF** |
| empty COMPLETE | **0** |
| COMPLETE without usable raw | **forbidden — held** |
| Live backfill killed? | **no** (`w0713_t7` still alive) |
| Worker pass claimed as COMPLETE? | **no** |
| `{"data":[]}` / empty digest | **banned** |

---

## Verdict

| Check | Result |
|-------|--------|
| mb COMPLETE PRE→POST | **32 → 69 (+37)** remote; this-close issue **+36** |
| raw-required seal only | **PASS** |
| empty COMPLETE | **0 PASS** |
| reeval C8 | **pass** lag 1 |
| no peer backfill kill | **PASS** |
| Overall G4/T4 breakdown close | **PASS** (sealable map closed; further history DEFER next wave) |

## Residual pointers

- Next seal map: unsealed months with remote nz COMPLETE manifests **2018-04…2023-11** (and thin **2015-03** if full-month raw appears).
- Prefer week-chunk merge + digest raw ≤20MB path; do not raise Mass.
- Optional: retry 4 failing week-jobs when general pool is quiet (not required for this close).

## Artifacts

| path | role |
|------|------|
| `.glm-logs/cf-backfill/w0713_t4_mb_residual_*` | residual backfill |
| `.glm-logs/cf-backfill/w0713_t4_mb_retry{,_a,_b,2,2b}_*` | retries |
| `.glm-logs/w0713_t4_mb/seal_from_r2.py` | R2→local seal driver |
| `.glm-logs/w0713_t4_mb/seal_{map,result,log}.*` | seal evidence |
| `.glm-logs/g1g2g4-close/mb_targeted_issue.*` | signed issue +36 |
| `.glm-logs/g1g2g4-close/publish2.log` | fail-closed publish |
| `.glm-logs/g1g2g4-close/reeval_markets_breakdown.log` | reeval |
| `.glm-logs/g1g2g4-close/freshness.log` | FRESH reclock |
