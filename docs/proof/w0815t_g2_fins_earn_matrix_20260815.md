# W27-G2 / w0815t_g2 — T2 `fins_earnings_date` residual ~100 PARTIAL×raw matrix (2026-08-15)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (this-wave seals **0**; empty-raw ban held)  
**force-apply:** **not** used (fail-closed guard held; local==remote **3457**)  
**prefix:** `w0815t_g2_fins_earn_*`  
**path:** PRE → **full PARTIAL list × CF raw matrix** → seal only **HAS_RAW_SEALABLE** (**0**) → DEFER known empty with evidence (**100**) → **no tip-densify-as-success** → issue skip → publish apply → reeval → proof → **push**  
**empty-raw ban:** held  
**empty-shell ban:** held — did **not** densify pre-2018 shells or earn `2026-01…04`  
**peer kill ban:** held

**Live verified:** 2026-08-15 (JST) / ~2026-08-15T02:43Z UTC  
**Wave start HEAD:** `306bebb2febf835032abf3bc210f755338b8caac`  
**Proof HEAD (post-push):** `dcac84932977231a136c04dbfa2dd66ac5e38971`  
**Projection:** **FRESH** `projgen-c55114231b2e4f5e9c99fb521545daac`  
**Artifacts:** `.glm-logs/w0815t_g2_fins_earn/` (`matrix/`, `pre/`, `post/`, dry plans, defer evidence, publish + reeval, `FINAL_metrics.json`)

## Goal

1. Build **full PARTIAL list × CF raw matrix** for every residual month of `fins_earnings_date`.
2. Classify each PARTIAL month: `HAS_RAW_SEALABLE` | `EMPTY_RAW_KNOWN` | `NO_RAW_FOR_MONTH`.
3. **Seal only HAS_RAW_SEALABLE** (nz COMPLETE raw with params.from/to same-month = segment).
4. Known empty (`2026-01…04`, pre-2018 shells) → **DEFER fixed with evidence**.
5. **No tip-densify-as-success** — tip residual is DEFER-only; densify execute **SKIP**.
6. Issue + fail-closed publish + reeval + proof + **push**.

## DEFER fixed (with evidence)

| island | n | segments | class | evidence |
|--------|--:|----------|-------|----------|
| pre-2018 shells | **96** | `2010-01…2017-12` | `NO_RAW_FOR_MONTH` | Among **235** CF COMPLETE nz manifests, **0** window_ok months map into residual; local structured pre-2018 rows **0**; observed_start=`2018-01-01` |
| tip known empty | **4** | `2026-01…04` | `NO_RAW_FOR_MONTH` | **0** window_ok nz for tip residual; empty-page sample run `1056` body `{"data":[]}` (params `{}`); dry tip plan_jobs=**4** only |
| **total DEFER** | **100** | | | HAS_RAW_SEALABLE=**0** |

Full matrix TSV/JSON: `.glm-logs/w0815t_g2_fins_earn/matrix/partial_raw_matrix.{json,tsv}`  
DEFER dossier: `.glm-logs/w0815t_g2_fins_earn/matrix/defer_evidence.json`

## PRE (remote D1 @ wave start)

| item | value |
|------|------:|
| Segment COMPLETE total | **3457** |
| PARTIAL total (all ds) | **9487** |
| `raw_retention_manifests` | **15145** |
| `fins_earnings_date` COMPLETE | **100** |
| `fins_earnings_date` PARTIAL | **100** |
| local COMPLETE | **3457** (= remote) |

PRE SHA: `306bebb2febf835032abf3bc210f755338b8caac`  
Artifacts: `.glm-logs/w0815t_g2_fins_earn/pre/remote_global.json`, `pre/partial_segments.json`, `pre/complete_segments.json`, `pre/tip_months.json`, `pre/raw_manifest_stats.json`, `PRE_sha.txt`

### Remote COMPLETE island (`fins_earnings_date` PRE)

| dataset | n | span | holes_in_span |
|---------|--:|------|---------------|
| `fins_earnings_date` | **100** | `2018-01…2026-08` | **4** = `2026-01…04` (**DEFER known empty**) |

Tip months `2025-12…2026-08`: COMPLETE except hole `2026-01…04`.

### CF raw_retention_manifests (`fins_earnings_date` PRE)

| completeness | n | nz (row_count>0) | zero |
|--------------|--:|-----------------:|-----:|
| COMPLETE | **259** | **235** | **24** |
| FAILED | **13** | **0** | **13** |

## Full PARTIAL × raw matrix (CF)

### Method

1. Load **all** remote PARTIAL segments for `fins_earnings_date` (**100**).
2. Fetch/load all COMPLETE nz (**235**) + zero (**24**) manifests from R2 (cache-first; prior-wave seed **235**).
3. Map window_ok = `params.from[:7] == params.to[:7]`; segment = `from[:7]`.
4. Best nz / zero run per segment month.
5. Classify each PARTIAL:
   - **HAS_RAW_SEALABLE** — window_ok nz exists for residual month
   - **EMPTY_RAW_KNOWN** — window_ok zero-row COMPLETE exists for residual month
   - **NO_RAW_FOR_MONTH** — neither (this wave: all 100)

Script: `.glm-logs/w0815t_g2_fins_earn/build_partial_raw_matrix.py`

### Matrix class counts

| class | n | action |
|-------|--:|--------|
| `HAS_RAW_SEALABLE` | **0** | would SEAL |
| `EMPTY_RAW_KNOWN` | **0** | DEFER (window_ok zero mapped) |
| `NO_RAW_FOR_MONTH` | **100** | DEFER fixed |
| **total PARTIAL** | **100** | |

### Window-ok nz coverage (context)

| field | value |
|-------|------:|
| window_ok nz months | **100** (`2018-01…2026-08`) |
| of which already COMPLETE | **100** |
| of which on PARTIAL residual | **0** |
| complete island missing nz | **0** |
| manifest src | cache=**235**, r2 zero-fetch=**24**, fail=**0** |

Note: 24 zero-row COMPLETE manifests have `params={}` (unparametrized tip-style runs) → cannot map to a residual segment month → counted under `NO_RAW_FOR_MONTH` for residual, not `EMPTY_RAW_KNOWN`. Empty body evidence retained: run `1056` page `{"data":[]}`.

### Class by year (PARTIAL residual)

| year | NO_RAW_FOR_MONTH |
|------|-----------------:|
| 2010–2017 | **12** each (**96**) |
| 2026 (Jan–Apr only) | **4** |

## Residual dry plan (planner; not executed)

Full residual (`--to-date 2026-08-14`):

```text
mode=dry-run plan_jobs=100 queued=100 executed=0
pools general=0 fins=100
by_dataset={"fins_earnings_date":100}
dispatch_envelope queued_fins=100 fins_rpm=80
```

Tip residual (`--from-date 2026-01-01`):

```text
mode=dry-run plan_jobs=4 queued=4
by_dataset={"fins_earnings_date":4}   # 2026-01..04 DEFER only
```

Artifacts: `plan_full_dry.json`, `queue_full_dry.json`, `plan_tip_dry.json`, `queue_tip_dry.json`, `dry_full.log`, `dry_tip.log`

## Seal only HAS_RAW_SEALABLE

| field | value |
|-------|------:|
| HAS_RAW_SEALABLE | **0** |
| sealed ready | **0** |
| issue | **skip** (`ISSUE_SKIP n=0`) |
| empty COMPLETE invented | **0** |

Honesty: residual PARTIAL months have **no** nz window_ok CF raw. Main island already sealed. No invent.

- seal map: `.glm-logs/w0815t_g2_fins_earn/seal_map.json` (`[]`)
- `SEAL_DONE` / `READY_COUNT` = **0**

## Tip densify — SKIP (no tip-densify-as-success)

**Decision: SKIP densify execute.**

| field | value |
|-------|------:|
| tip dry jobs | **4** (`2026-01…04` only) |
| tip non-DEFER holes | **0** |
| HAS_RAW_SEALABLE after matrix | **0** |
| executed | **0** |
| pass / fail | **0 / 0** |
| host HTTP 429 | **0** (no POSTs) |

Local structured may hold SchDate-keyed rows in `2026-01…04` from prior tip-date densify (e.g. PubDate≠segment month). **Without window_ok segment raw these are not HAS_RAW_SEALABLE** — empty-raw ban / no invent COMPLETE. Densify-as-success explicitly refused.

Artifacts: `DENSEIFY_SKIP.txt`, `densify_summary.json`, `matrix/defer_evidence.json`

## Issue + publish

Issue: **skip** (`ISSUE_SKIP n=0 seal_ready=0 HAS_RAW_SEALABLE=0`).

Publish (fail-closed, `--apply-remote`):

```text
complete_count_guard ok local=3457 remote=3457 force=False
remote projection applied (13014 queries)
```

## FINAL reeval (`ops_reeval_observed_window` + freshness)

```bash
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset fins_earnings_date --today 2026-08-15 --freshness-days 7
.venv/bin/python scripts/ops_reeval_freshness.py
```

| dataset | status | observed_start | observed_end | C8 |
|---------|--------|----------------|--------------|----|
| `fins_earnings_date` | **PARTIAL** | **`2018-01-01`** | **`2026-12-11`** (future-dated SchDate events) | **pass** lag **1** (receipt_observed_end=`2026-08-14`) |

Freshness: `projgen-c55114231b2e4f5e9c99fb521545daac` **OK**; `coverage_segments_untouched=1`; Mass **NO-GO**.

## POST (remote D1 live verify)

| item | PRE (wave) | POST | Δ |
|------|----------:|-----:|--:|
| Segment COMPLETE total | **3457** | **3457** | **+0** |
| `fins_earnings_date` COMPLETE | **100** | **100** | **+0** |
| `fins_earnings_date` PARTIAL | **100** | **100** | **0** |
| `raw_retention_manifests` | **15145** | **15145** | **+0** |
| empty COMPLETE (this-wave seals) | — | **0** | held |
| seal / issue / densify | — | **0 / 0 / 0** | matrix sealable=0 |

### Remote COMPLETE island (POST)

- `fins_earnings_date` **100**: `2018-01…2025-12` continuous + `2026-05…08` (hole **2026-01…04** DEFER known empty — not burned)

Dataset remains **PARTIAL** at coverage level. Residual is honestly DEFER-only (pre-history shells + known empty tip). No tip-join sealable remaining for T2.

## Forbidden / honesty

- Did **not** launch Mass / READY / Phase7 ON.
- Did **not** invent empty COMPLETE (HAS_RAW_SEALABLE **0**; densify executed **0**).
- Did **not** seal without window_ok nz CF raw.
- Did **not** densify DEFER empty shells (pre-2018 **96** + tip `2026-01…04` **4**).
- Did **not** claim tip densify as success.
- Did **not** kill peer processes.
- Worker pass ≠ Coverage COMPLETE; COMPLETE path remains **seal+receipt+restore**.
- Platform COMPLETE Δ (**+0** this-wave T2).

## Residual pointers

| residual | n | resume condition |
|----------|--:|------------------|
| pre-2018 shells `2010-01…2017-12` | **96** | vendor returns **nz** COMPLETE raw with params window for those months → re-run matrix → seal HAS_RAW_SEALABLE only |
| tip `2026-01…04` | **4** | vendor returns **nz** window_ok raw for those months (not tip-date densify alone) → re-matrix → seal |

## Operator artifacts

| path | role |
|------|------|
| `.glm-logs/w0815t_g2_fins_earn/build_partial_raw_matrix.py` | PARTIAL×raw matrix builder |
| `.glm-logs/w0815t_g2_fins_earn/matrix/partial_raw_matrix.json` | full 100-row matrix |
| `.glm-logs/w0815t_g2_fins_earn/matrix/partial_raw_matrix.tsv` | matrix TSV |
| `.glm-logs/w0815t_g2_fins_earn/matrix/matrix_summary.json` | class counts + defer buckets |
| `.glm-logs/w0815t_g2_fins_earn/matrix/has_raw_sealable.json` | seal candidates (**[]**) |
| `.glm-logs/w0815t_g2_fins_earn/matrix/defer_fixed.json` | DEFER rows (**100**) |
| `.glm-logs/w0815t_g2_fins_earn/matrix/defer_evidence.json` | DEFER evidence dossier |
| `.glm-logs/w0815t_g2_fins_earn/plan_full_dry.json` | planner residual **100** |
| `.glm-logs/w0815t_g2_fins_earn/plan_tip_dry.json` | tip residual **4** |
| `.glm-logs/w0815t_g2_fins_earn/pages/empty_sample_1056.json` | empty raw body evidence |
| `.glm-logs/w0815t_g2_fins_earn/publish.log` | publish apply |
| `.glm-logs/w0815t_g2_fins_earn/reeval_*.log` | reeval + freshness |
| `.glm-logs/w0815t_g2_fins_earn/FINAL_metrics.json` | wave metrics |

## Report line

`T2 earn matrix PARTIAL=100 → HAS_RAW_SEALABLE=0 DEFER=100 (pre2018=96 tip=4) | seal/issue/densify 0 | COMPLETE 3457→3457 earn 100 held | raw 15145 | FRESH projgen-c5511423… | C8 pass | empty 0 | no tip-densify-as-success | Mass NO-GO | push`
