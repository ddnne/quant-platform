# W27-G1 / w0815t_g1 T1 fins_dividend residual ~61 — mandatory matrix triage (2026-08-15)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (this-wave seals **0**; empty-raw ban held)  
**force-apply:** **not** used (fail-closed guard held; local==remote **3457**)  
**prefix:** `w0815t_g1_fins_div_*`  
**path:** PRE → **mandatory PARTIAL matrix triage** → seal only HAS_RAW_SEALABLE (**0**) → densify tip only if real (**SKIP** tip jobs **0**) → issue skip → publish apply → reeval → proof → **push**  
**fins pool isolation:** densify budget reserved `fins-workers=1`, `fins-rpm=80` (**unused**; no POSTs)  
**empty-raw ban:** held  
**empty-shell ban:** held — did **not** densify pre-`2013-02` EMPTY_SHELL island forever  
**peer kill ban:** held — concurrent `w0815t_*` peers left alone  

**Live verified:** 2026-08-15 (~2026-08-15T02:43:20Z UTC)  
**Wave start HEAD:** `306bebb2febf835032abf3bc210f755338b8caac`  
**Projection:** **FRESH** `projgen-251387b324824a1b95ad56a9b448f699`  
**Artifacts:** `.glm-logs/w0815t_g1_fins_div/` (`matrix.json`, `matrix.md`, `pre/`, `post/`, R2 manifests for residual run_ids, dry plans, publish + reeval)

## Goal

1. **Mandatory triage** every PARTIAL `segment_id` for `fins_dividend`.
2. Classify: **HAS_RAW_SEALABLE** | **EMPTY_SHELL** | **NO_RAW** | **MISDATE/TIP_DATE** from CF SoT (D1 receipts + R2 manifests).
3. HAS_RAW_SEALABLE → seal → issue → restore COMPLETE (empty-raw ban).
4. EMPTY/NO_RAW → **DEFER** with evidence if known empty island pre-`2013-02` (do **not** densify forever).
5. Tip densify only if real holes (`fins-workers=1`, `fins-rpm=80`).
6. Proof + residual + **git push**.

## Verdict (one line)

All **61** PARTIAL segs (`2008-01…2013-01`) are proven **EMPTY_SHELL** on CF: SUCCESS receipt `raw_row_count=0` + R2 `manifest.json` `row_count=0` completeness **COMPLETE** window_ok. **HAS_RAW_SEALABLE=0**. Tip island **`2013-02…2026-08` continuous COMPLETE (163)** held. **No seal / no densify / no invent.** Dataset remains **PARTIAL** with explicit DEFER + re-try condition.

## PRE (remote D1 @ wave start)

| item | value |
|------|------:|
| Segment COMPLETE total | **3457** |
| Dataset COMPLETE | **11** |
| `raw_retention_manifests` | **15145** |
| `fins_dividend` COMPLETE | **163** |
| `fins_dividend` PARTIAL | **61** |
| `dataset_coverage.status` | **PARTIAL** |
| `observed_start` | **`2013-02-01`** |
| `observed_end` | **`2026-08-14`** |
| `row_count` | **167343** |

PRE SHA: `306bebb2febf835032abf3bc210f755338b8caac`

### COMPLETE island (PRE)

| dataset | n | span | holes_in_span | tip 2026-01…08 |
|---------|--:|------|---------------|----------------|
| `fins_dividend` | **163** | `2013-02…2026-08` | **0** continuous | **all COMPLETE** |

Residual PARTIAL only: **`2008-01…2013-01` (61)**.

Artifacts: `.glm-logs/w0815t_g1_fins_div/pre/{remote_global,status_counts,dataset_coverage,partial_segments,receipts_all_residual,r2_manifest_probe}.json`

## Mandatory triage matrix

Source of truth: **remote D1** `collection_receipts` + **R2** `raw/fins_dividend/{run_id}/manifest.json` for each residual SUCCESS run_id (**61/61 fetched**).

### Class counts

| class | n | action |
|-------|--:|--------|
| `HAS_RAW_SEALABLE` | **0** | SEAL → issue → COMPLETE |
| `EMPTY_SHELL` | **61** | **DEFER** (forever densify skip) |
| `NO_RAW` | **0** | DEFER |
| `MISDATE/TIP_DATE` | **0** | INVESTIGATE |

### Evidence rule applied

| class | rule |
|-------|------|
| HAS_RAW_SEALABLE | receipt or R2 `raw_row_count>0` **and** params/Date in segment month window |
| EMPTY_SHELL | SUCCESS receipt + R2 manifest exist with `row_count=0`, completeness COMPLETE |
| NO_RAW | no receipt and no R2 manifest for segment window |
| MISDATE/TIP_DATE | nz raw exists but params/Date outside segment month |

### Per-segment summary (all residual)

Full table: [`.glm-logs/w0815t_g1_fins_div/matrix.md`](../../.glm-logs/w0815t_g1_fins_div/matrix.md)  
Machine matrix: [`.glm-logs/w0815t_g1_fins_div/matrix.json`](../../.glm-logs/w0815t_g1_fins_div/matrix.json)

| segment span | n | receipt raw max | R2 manifest raw max | window_ok | class | action |
|--------------|--:|----------------:|--------------------:|:---------:|-------|--------|
| `2008-01…2013-01` | **61** | **0** (all SUCCESS empty) | **0** (all COMPLETE empty) | **Y** | **EMPTY_SHELL** | **DEFER** |

Sample evidence rows:

| segment_id | receipt run | receipt raw | manifest raw | completeness | params | class |
|------------|------------:|------------:|-------------:|--------------|--------|-------|
| `2008-01` | 6606 | 0 | 0 | COMPLETE | `2008-01-08…2008-01-31` | EMPTY_SHELL |
| `2010-06` | (SUCCESS empty) | 0 | 0 | COMPLETE | same-month window_ok | EMPTY_SHELL |
| `2013-01` | 6666 | 0 | 0 | COMPLETE | `2013-01-01…2013-01-31` | EMPTY_SHELL |

**any_nz_raw across residual = false.**

## Seal / issue / densify

| step | result |
|------|--------|
| HAS_RAW_SEALABLE | **[]** (**0**) |
| sealed ready | **0** |
| issue | **SKIP** (`ISSUE_SKIP`) |
| closed segs this wave | **[]** |
| tip dry (`2024-01…2026-08-14`, `fins-workers=1`, `fins-rpm=80`) | `plan_jobs=0` |
| full residual dry | `plan_jobs=61` (all DEFER EMPTY_SHELL — **not executed**) |
| densify execute | **SKIP** (`DENSIFY_SKIP`) |
| host HTTP 429 | **0** (no POSTs) |

**Closed seg list:** empty — reasons: no sealable nz raw; empty-raw ban forbids invent COMPLETE on empty shells.

## Publish + reeval

```bash
.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite --apply-remote
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset fins_dividend --today 2026-08-15 --freshness-days 7
.venv/bin/python scripts/ops_reeval_freshness.py
```

| step | result |
|------|--------|
| complete_count_guard | `ok local=3457 remote=3457 force=False` |
| remote apply | **13014** queries |
| `--force-apply-remote` | **not** used |
| reeval POST | **PARTIAL** `observed_start=2013-02-01` `observed_end=2026-08-14` C8 **pass** lag **1** |
| freshness | gen `projgen-251387b324824a1b95ad56a9b448f699`; `coverage_segments_untouched=1`; Mass **NO-GO** |

## POST (remote D1 live verify)

| item | PRE | POST | Δ |
|------|----:|-----:|--:|
| Segment COMPLETE total | **3457** | **3457** | **0** |
| `fins_dividend` COMPLETE | **163** | **163** | **0** |
| `fins_dividend` PARTIAL | **61** | **61** | **0** (honest EMPTY_SHELL residual) |
| `dataset_coverage` | PARTIAL | **PARTIAL** | held |
| `observed_start` | 2013-02-01 | **2013-02-01** | held |
| `observed_end` | 2026-08-14 | **2026-08-14** | held |
| `raw_retention_manifests` | **15145** | **15145** | **0** |
| empty COMPLETE (`fins_dividend`) | **0** | **0** | held |

### Remote COMPLETE island (POST)

- `fins_dividend` **163**: `2013-02…2026-08` **continuous** through tip
- Residual **61** PARTIAL: `2008-01…2013-01` only — pre-`observed_start` **EMPTY_SHELL** island; **forever densify skip**

## Residual + re-try condition

Machine residual: [`docs/proof/w0815t_g1_fins_div_residual_20260815.json`](w0815t_g1_fins_div_residual_20260815.json)

```json
{
  "dataset": "fins_dividend",
  "complete": 163,
  "partial_residual": 61,
  "residual_span": "2008-01..2013-01",
  "tip_island": "2013-02..2026-08 continuous",
  "holes_in_tip_span": 0,
  "class_counts": {
    "EMPTY_SHELL": 61
  },
  "forever_densify_skip": true,
  "mass": "NO-GO"
}
```

**Re-try when:**

1. **nz raw appears** for any residual month (`manifest.row_count>0` or SUCCESS `raw_row_count>0` with Date/params in segment window) → classify HAS_RAW_SEALABLE → seal → issue → COMPLETE those segs.
2. Product policy: move `history_target_start` for `fins_dividend` from **`2008-01-08`** toward observed floor **`~2013-02-01`** (excludes empty pre-floor shells from required inventory). Not this wave.

Until then: honest **DEFER** residual empty shells; dataset stays **PARTIAL**.

## Forbidden / honesty

- Did **not** claim success from tip densify (tip densify **not executed**; tip jobs **0**).
- Did **not** launch Mass / READY / Phase7 ON.
- Did **not** invent empty COMPLETE (emptyish **0**; seal **0**).
- Did **not** densify pre-`2013-02` EMPTY_SHELL island (forever skip).
- Did **not** kill peer processes.
- `--force-apply-remote` **not** used.
- Worker pass ≠ Coverage COMPLETE (N/A — no acq).
- CF SoT: D1 hot / R2 history / receipt COMPLETE. Local not authority for triage.

## Operator artifacts

| path | role |
|------|------|
| `.glm-logs/w0815t_g1_fins_div/matrix.json` | mandatory triage matrix (machine) |
| `.glm-logs/w0815t_g1_fins_div/matrix.md` | per-seg markdown table |
| `.glm-logs/w0815t_g1_fins_div/pre/r2_manifest_probe.json` | R2 probe all 61 residual run_ids |
| `.glm-logs/w0815t_g1_fins_div/manifests/fins_dividend/*.json` | residual empty SUCCESS manifests (61) |
| `.glm-logs/w0815t_g1_fins_div/plan_tip_dry.json` | tip residual dry (**0**) |
| `.glm-logs/w0815t_g1_fins_div/plan_full_dry.json` | full residual dry (**61** DEFER) |
| `.glm-logs/w0815t_g1_fins_div/DENSIFY_SKIP.txt` | densify skip decision |
| `.glm-logs/w0815t_g1_fins_div/SEAL_SKIP.txt` | seal skip (HAS_RAW=0) |
| `.glm-logs/w0815t_g1_fins_div/publish.log` | fail-closed publish apply |
| `.glm-logs/w0815t_g1_fins_div/reeval_fins_dividend_retry.log` | observed_window reeval |
| `.glm-logs/w0815t_g1_fins_div/freshness_final.log` | FRESH + Mass NO-GO |
| `.glm-logs/w0815t_g1_fins_div/FINAL_metrics.json` | PRE/POST metrics |
| `docs/proof/w0815t_g1_fins_div_residual_20260815.json` | residual SoT snippet |
| `docs/proof/w0815t_g1_fins_div_matrix_20260815.md` | this proof |

## Report line

`COMPLETE div=163(+0) | platform 3457 | matrix EMPTY_SHELL=61 HAS_RAW=0 | seals +0 closed=[] | densify SKIP tip=0 residual=61 forever | host429=0 rpm=80 workers=1 unused | FRESH projgen-251387b3… | empty 0 | Mass NO-GO`

## Git

| ref | SHA |
|-----|-----|
| PRE (wave start) | `306bebb2febf835032abf3bc210f755338b8caac` |
| proof commit | `1f05c6bc3d5ed3b44d6796e0f6bfb79561da53f2` |
| proof content | `1f05c6bc3d5ed3b44d6796e0f6bfb79561da53f2` |
