# W17-G2 / w0815i_g2 fins_summary residual — seal-first + tip densify (2026-08-15)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (this-wave seals emptyish check; 18 ready, all `raw_row_count>0`)  
**prefix:** `w0815i_g2_fins_summary_*`  
**path:** PRE → **seal-first all window_ok** (**0**) → densify tip-join residual (`fins-workers=2`, `fins-rpm=120`) → retry densify (`fins-workers=1`) → post-acq seal (**18**) → issue/restore/publish → reeval → proof → **push**  
**fins pool isolation:** host dispatch pool=`fins` only; **no general pool**  
**empty-raw ban:** held (`row_count>0` + usable pages only)  
**empty-shell ban:** held — did **not** burn RPM on pre-history `2008-01…06` shells  
**peer kill ban:** held (options issue peers left running)

## Goal

1. **Seal-first** all remaining `window_ok` unsealed months (no invent).
2. Densify tip-join holes only at **`fins-workers=2`, `fins-rpm=120`** (avoid 429 storm); retry at workers=1 when JQ 429 dominates.
3. Skip known empty pre-history shells (`2008-01…06`) unless nz appears.
4. Maximize COMPLETE; if 224/224 possible → dataset COMPLETE (not achieved — residual pre-history shells only).
5. `issue` + `restore` + `publish` + **push**.

## PRE (remote D1 @ wave start)

| item | value |
|------|------:|
| Segment COMPLETE total | **3409** |
| `fins_summary` COMPLETE | **200** |
| `fins_details` COMPLETE | **104** |
| `fins_dividend` COMPLETE | **163** |
| `fins_earnings_date` COMPLETE | **100** |
| `raw_retention_manifests` | **14953** |

PRE SHA: `307065e3c27c7520e78852a1e7612414ad87dc1d`

PRE tip COMPLETE islands: `2024-01…09` continuous + `2025-07` + tip `2026-05…08`

Artifacts: `.glm-logs/cf-backfill/w0815i_g2_fins_summary_PRE_*.json`, `.glm-logs/w0815i_g2_fins_summary/PRE_sha.txt`, `PRE_local.json`

## Residual dry plan (full fins pool)

```text
mode=dry-run plan_jobs=305 queued=305 executed=0
pools general=0 fins=305
by_dataset={"fins_details":120,"fins_dividend":61,"fins_earnings_date":100,"fins_summary":24}
dispatch_envelope queued_fins=305 fins_rpm=120
```

Residual islands (planner vs COMPLETE):

| dataset | residual islands | note |
|---------|------------------|------|
| `fins_summary` | pre-history `2008-01…06` (**6**) + tip-join holes (**18**) | tip-join high value; pre-history shell skip |
| `fins_details` | `2008-01…2017-12` | pre-start shell — **no RPM** (out of scope T2) |
| `fins_dividend` | `2008-01…2013-01` | pre-history only — **no RPM** (out of scope T2) |
| `fins_earnings_date` | pre-2018 + `2026-01…04` | known empty tip — **no RPM** (out of scope T2) |

Artifacts: `.glm-logs/w0815i_g2_fins_summary/plan_dry.json`, `queue_dry.json`, `dry_run.log`

## Seal-first (window_ok only)

Inventory (nz COMPLETE manifests, params.from/to same-month, unsealed locally; recent 80 sample for tip residual):

| dataset | window_ok unsealed | sealed ready | skip |
|---------|-------------------:|-------------:|-----:|
| `fins_summary` | **0** | **0** | **0** |
| **total** | **0** | **0** | **0** |

Honesty: all previously densified tip raw from W16-G3 already sealed. No invent. Pre-history `2008-01…06` had **no nz** in sample.

- map: `.glm-logs/w0815i_g2_fins_summary/w0815i_g2_fins_summary_seal_map.json` (empty `[]` at seal-first)
- inventory: `.glm-logs/w0815i_g2_fins_summary/inventory_summary.json`
- all unsealed window_ok: `.glm-logs/w0815i_g2_fins_summary/w0815i_g2_fins_summary_all_unsealed_window_ok.json`

## Densify residual (fins pool throttled)

### Round 1 — tip-join (`--from-date 2024-10-01 --to-date 2026-04-30`, dataset `fins_summary`)

```text
--fins-workers 2 --fins-rpm 120 --sleep-on-retry 8 --execute
mode=execute plan_jobs=18 queued=18 executed=18
pools general=0 fins=18 by_dataset={"fins_summary":18}
host_dispatch_rpm requests_per_min=17.13 http_429_count=0
finished executed=18 states={'pass': 1, 'fail': 17}
```

| field | value |
|-------|------:|
| jobs | **18** |
| pass / fail | **1 / 17** |
| host HTTP 429 | **0** |
| host jpm | **17.13** |
| pass | `fins_summary/2024-10` (rowsInserted **1323**) |
| fail | **17** worker-side JQ 429 (retries exhausted) |

### Round 2 — retry remaining tip (`fins-workers=1`, `sleep-on-retry=12`)

Partial run (host timeout mid-batch) then full re-dispatch:

```text
--fins-workers 1 --fins-rpm 120 --sleep-on-retry 12 --execute
retry2: mode=execute plan_jobs=17 queued=17 executed=17
host_dispatch_rpm requests_per_min=1.77 http_429_count=0
finished executed=17 states={'pass': 17}
```

| field | value |
|-------|------:|
| retry2 jobs | **17** |
| pass / fail | **17 / 0** |
| host HTTP 429 | **0** |
| host jpm | **1.77** |

**Empty shells not executed:** summary pre-history `2008-01…06` (known empty shells).  
**Skipped COMPLETE:** `2025-07` (already COMPLETE).

### Combined tip densify result (18/18 residual tip months)

| segment | rowsInserted | densify pass |
|---------|-------------:|:------------:|
| 2024-10 | 1323 | R1 |
| 2024-11 | 3009 | R2 |
| 2024-12 | 417 | R2 |
| 2025-01 | 1176 | R2 |
| 2025-02 | 3135 | R2 |
| 2025-03 | 580 | R2 |
| 2025-04 | 1119 | R2 |
| 2025-05 | 3277 | R2 |
| 2025-06 | 425 | R2 |
| 2025-08 | 2790 | R2 |
| 2025-09 | 452 | R2 |
| 2025-10 | 1372 | R2 |
| 2025-11 | 2907 | R2 |
| 2025-12 | 410 | R2 |
| 2026-01 | 1097 | R2 |
| 2026-02 | 3023 | R2 |
| 2026-03 | 613 | R2 |
| 2026-04 | 1087 | R2 |

Artifacts: `.glm-logs/w0815i_g2_fins_summary/plan_densify.json`, `state_densify.jsonl`, `state_densify_retry.jsonl`, `state_densify_retry2.jsonl`, `execute_densify*.log`, `densify_summary.json`

## Post-densify seal (window_ok)

| dataset | window_ok new | sealed ready |
|---------|--------------:|-------------:|
| `fins_summary` | **18** | **18** (all tip residual months) |
| **total** | **18** | **18** |

`SEAL_DONE` / `seal_result.jsonl` under `.glm-logs/w0815i_g2_fins_summary/`.

Representative run_ids (R2 manifests): `2024-10`→**13320**, `2024-11`→**13338**, `2025-02`→**13363**, `2025-03`→**13364**, … (see seal maps).

### Receipts + restore

| segment | receipt_run_id | raw | structured | ledger |
|---------|---------------:|----:|-----------:|--------|
| `fins_summary/2024-10` | **903820** | 1323 | 1323 | → **COMPLETE** |
| `fins_summary/2024-11` | **903822** | 3009 | 3009 | → **COMPLETE** |
| `fins_summary/2024-12` | **903841** | 417 | 417 | → **COMPLETE** |
| `fins_summary/2025-01` | **903840** | 1176 | 1176 | → **COMPLETE** |
| `fins_summary/2025-02` | **903842** | 3135 | 3135 | → **COMPLETE** |
| `fins_summary/2025-03` | **903843** | 580 | 580 | → **COMPLETE** |
| `fins_summary/2025-04` | **903823** | 1119 | 1119 | → **COMPLETE** |
| `fins_summary/2025-05` | **903824** | 3277 | 3277 | → **COMPLETE** |
| `fins_summary/2025-06` | **903825** | 425 | 425 | → **COMPLETE** |
| `fins_summary/2025-08` | **903831** | 2790 | 2790 | → **COMPLETE** |
| `fins_summary/2025-09` | **903839** | 452 | 452 | → **COMPLETE** |
| `fins_summary/2025-10` | **903838** | 1372 | 1372 | → **COMPLETE** |
| `fins_summary/2025-11` | **903837** | 2907 | 2907 | → **COMPLETE** |
| `fins_summary/2025-12` | **903836** | 410 | 410 | → **COMPLETE** |
| `fins_summary/2026-01` | **903832** | 1097 | 1097 | → **COMPLETE** |
| `fins_summary/2026-02` | **903833** | 3023 | 3023 | → **COMPLETE** |
| `fins_summary/2026-03` | **903834** | 613 | 613 | → **COMPLETE** |
| `fins_summary/2026-04` | **903835** | 1087 | 1087 | → **COMPLETE** |

```bash
.venv/bin/python scripts/issue_receipts_parallel.py \
  --datasets fins_summary --segment-id YYYY-MM --workers 1 --no-refresh
.venv/bin/python scripts/restore_local_complete_from_receipt.py \
  --dataset fins_summary --segment-id YYYY-MM
```

emptyish **0**.

Publish (fail-closed), final apply:

```text
complete_count_guard ok local=3434 remote=3426 force=False
remote projection applied (13014 queries)
```

## FINAL reeval (`ops_reeval_observed_window` + freshness)

```bash
for ds in fins_summary fins_details fins_dividend fins_earnings_date; do
  .venv/bin/python scripts/ops_reeval_observed_window.py \
    --dataset "$ds" --today 2026-08-15 --freshness-days 7
done
.venv/bin/python scripts/ops_reeval_freshness.py
```

| dataset | status | observed_start | observed_end | C8 |
|---------|--------|----------------|--------------|----|
| `fins_summary` | **PARTIAL** | **`2008-07-01`** | **`2026-08-14`** | **pass** lag **1** |
| `fins_details` | **PARTIAL** | **`2018-01-01`** | **`2026-08-14`** | **pass** lag **1** |
| `fins_dividend` | **PARTIAL** | **`2013-02-01`** | **`2026-08-14`** | **pass** lag **1** |
| `fins_earnings_date` | **PARTIAL** | **`2018-01-01`** | **`2026-12-11`** (future-dated events) | **pass** lag **1** |

Freshness: `projgen-0472c6020f4143d49638f75e435fbb8d` reeval path; **FRESH**; `coverage_segments_untouched=1`; Mass **NO-GO**.

## POST (remote D1 live verify)

| item | PRE (wave) | POST | Δ |
|------|----------:|-----:|--:|
| Segment COMPLETE total | **3409** | **3434** | **+25** (this-wave seals **+18** + concurrent peer seals published) |
| `fins_summary` COMPLETE | **200** | **218** | **+18** |
| `fins_details` COMPLETE | **104** | **104** | **+0** |
| `fins_dividend` COMPLETE | **163** | **163** | **+0** |
| `fins_earnings_date` COMPLETE | **100** | **100** | **+0** |
| `raw_retention_manifests` | **14953** | **14997** | **+44** |
| empty COMPLETE (this-wave seals) | — | **0** | |

### Remote COMPLETE segment islands (fins_summary)

- `fins_summary` **218**: `2008-07…2024-03` continuous + tip **`2024-01…2026-08` continuous** (joined all tip residual this wave)
- residual pre-history shells only: **`2008-01…06`** (not densified; known empty; no nz)
- tip-join residual: **0** (closed)

Dataset remains **PARTIAL** (not dataset-level COMPLETE; 224/224 not reached — pre-history shells **6** remain without real raw).

Remote targets (this-wave, sample):
- `fins_summary/2024-10` = **COMPLETE** `receipt_run_id=903820`
- `fins_summary/2025-02` = **COMPLETE** `receipt_run_id=903842`
- `fins_summary/2025-03` = **COMPLETE** `receipt_run_id=903843`
- … all 18 tip residual months COMPLETE (see receipt table)

## Forbidden / honesty

- Did **not** launch Mass / READY / Phase7 ON.
- Did **not** invent empty COMPLETE (emptyish **0** / 18; seal-first raw inventory **0**).
- Did **not** kill peer processes (options issue peers held under DB contention).
- Did **not** burn RPM on summary pre-history `2008-01…06`.
- Densify honesty: R1 **1/18** pass at `fins-workers=2` / `fins-rpm=120` (worker JQ 429); R2 **17/17** pass at `fins-workers=1` / `fins-rpm=120`; host 429 count **0** both rounds.
- Worker pass ≠ Coverage COMPLETE; COMPLETE path is **seal+receipt+restore**, not acq alone.
- Platform COMPLETE Δ includes concurrent peer seals (POST total **3434** vs this-wave fins **+18**).

## Residual pointers

- Planner residual after this wave (approx): summary **~6** (pre-history `2008-01…06` only).
- Tip continuous block: **`2024-01…2026-08`** fully continuous (was holes at `2024-10…2025-06`, `2025-08…2026-04`).
- Next: only pre-history shells remain; densify **only if nz raw appears** (empty-shell ban). Dataset COMPLETE (224/224) blocked until those 6 have real raw + seal path, or policy excludes them.
- Lesson: `fins-workers=1` + `sleep-on-retry≥12` dramatically improves tip densify yield under JQ 429 vs workers=2.

## Operator artifacts

| path | role |
|------|------|
| `.glm-logs/w0815i_g2_fins_summary/plan_dry.json` | full residual dry (**305**, summary **24**) |
| `.glm-logs/w0815i_g2_fins_summary/w0815i_g2_fins_summary_seal_map.json` | seal1 window_ok map (**0**) |
| `.glm-logs/w0815i_g2_fins_summary/seal_from_r2.py` | R2 page→local seal |
| `.glm-logs/w0815i_g2_fins_summary/SEAL_DONE` | seal readiness |
| `.glm-logs/w0815i_g2_fins_summary/seal_result.jsonl` | per-month seal results (**18** ready) |
| `.glm-logs/w0815i_g2_fins_summary/state_densify.jsonl` | densify R1 18 job states |
| `.glm-logs/w0815i_g2_fins_summary/state_densify_retry2.jsonl` | densify R2 17 job states (all pass) |
| `.glm-logs/w0815i_g2_fins_summary/densify_summary.json` | densify aggregate |
| `.glm-logs/cf-backfill/w0815i_g2_fins_summary_receipt_issue.json` | issue (**18**) |
| `.glm-logs/cf-backfill/w0815i_g2_fins_summary_publish_final.log` | publish apply |
| `.glm-logs/cf-backfill/w0815i_g2_fins_summary_POST_*.json` | remote POST inventory |
| `.glm-logs/cf-backfill/w0815i_g2_fins_summary_empty_check.json` | emptyish **0** |
| `docs/proof/w0815i_g2_fins_summary_20260815.md` | this proof |
