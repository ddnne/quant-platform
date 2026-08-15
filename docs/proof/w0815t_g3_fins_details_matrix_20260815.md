# W27-G3 / w0815t T3 — `fins_details` residual matrix (PARTIAL × CF raw) (2026-08-15)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (this-wave seals **0**; empty-raw ban held)  
**force-apply:** **not** used (fail-closed guard held; local==remote)  
**prefix:** `w0815t_g3_fins_details_*`  
**path:** PRE → **matrix all PARTIAL segs × CF raw** → seal only sealable (**0**) → pre-2018 empty shells **DEFER** evidence → issue skip → publish apply → reeval → proof → **push**  
**empty-raw ban:** held  
**empty-shell densify ban:** held — did **not** burn RPM on details `2008-01…2017-12`  
**peer kill ban:** held  

**Live verified:** 2026-08-15 (JST) / ~2026-08-15T02:41Z UTC  
**Wave start HEAD:** `306bebb2febf835032abf3bc210f755338b8caac`  
**Proof HEAD (post-push):** `766c32e312c49615969ec8347241497699a84629`  
**Projection:** **FRESH** `projgen-e16f2fda784f4e91a1ce5b6740c2e61b`  
**Artifacts:** `.glm-logs/w0815t_g3_fins_details/` (`matrix_partial_cf_raw.py`, `matrix/partial_cf_raw_matrix.json`, `matrix_summary.json`, `DEFER_pre2018_shells.json`, `FINAL_metrics.json`, publish + reeval)

## Goal

1. **Matrix every** `fins_details` **PARTIAL** segment against CF raw (`raw_retention_manifests` + R2 manifests).
2. **Seal only sealable** (nz raw ∧ params window_ok ∧ not already COMPLETE).
3. Pre-2018 empty / absent-raw shells → **DEFER** with evidence (no densify).
4. Report **closed count** (0 ok with reason).
5. `publish` + reeval + proof + **push**.

## Closed count

| metric | value |
|--------|------:|
| **closed (sealed this wave)** | **0** |
| sealable from matrix | **0** |
| reason | all **120** PARTIAL months are pre-2018 residual with **no** nz window_ok CF raw (and **zero** CF manifests with `params.from < 2018-01`) |

`0` is honest and expected under seal-first + empty-raw ban.

## PRE (remote D1 @ wave start)

| item | value |
|------|------:|
| Segment COMPLETE total | **3457** |
| Dataset COMPLETE | **11** |
| `raw_retention_manifests` | **15145** |
| `fins_details` COMPLETE | **104** |
| `fins_details` PARTIAL | **120** |
| local COMPLETE | **3457** (= remote) |

PRE SHA: `306bebb2febf835032abf3bc210f755338b8caac`  
Artifacts: `.glm-logs/w0815t_g3_fins_details/PRE_*.json`, `PRE_sha.txt`, `PRE_local.json`

### PRE island

| dataset | COMPLETE | PARTIAL | COMPLETE span | holes_in_span |
|---------|--------:|--------:|---------------|---------------|
| `fins_details` | **104** | **120** | `2018-01…2026-08` | **0** continuous |

PARTIAL residual span: **`2008-01…2017-12`** (exactly the 120-month pre-island band).

## Matrix — all PARTIAL × CF raw

### Method

1. List local/remote PARTIAL months for `fins_details` (**120**).
2. Phase1: index cached manifests under `.glm-logs/**/manifests/fins_details/` (**235** unique runs → **170** parse_ok).
3. Phase2: D1 `raw_retention_manifests` nz COMPLETE (`row_count>0`) for dataset → R2 fetch manifests (**236** d1 / **171** parse_ok; prior-cache reuse).
4. Phase2b: D1 empty COMPLETE (`row_count=0`) sample (**37** / all parse_ok) for shell evidence.
5. Classify each PARTIAL month:
   - **SEALABLE** = nz ∧ params.from/to same-month ∧ not COMPLETE
   - **DEFER_PRE2018_EMPTY** = residual pre-2018 with no nz window_ok CF raw
   - **WINDOW_BAD_NZ** / **HAS_NZ_OTHER** = would need densify/re-window (none found)

Script: `.glm-logs/w0815t_g3_fins_details/matrix_partial_cf_raw.py`  
Full matrix: `.glm-logs/w0815t_g3_fins_details/matrix/partial_cf_raw_matrix.json`  
Summary: `.glm-logs/w0815t_g3_fins_details/matrix_summary.json`

### CF raw aggregate (`fins_details`)

| CF raw | n |
|--------|--:|
| total manifests | **287** |
| nz COMPLETE | **236** (unique window_ok segs → **104** = full COMPLETE island) |
| empty COMPLETE | **27** (+ empty FAILED **10** in kind split) |
| FAILED | **24** (10 empty + 14 nz) |

### Classification (120/120 PARTIAL)

| classification | n | note |
|----------------|--:|------|
| **DEFER_PRE2018_EMPTY** | **120** | all residual months |
| SEALABLE | **0** | nothing to seal |
| WINDOW_BAD_NZ | **0** | — |
| HAS_NZ_OTHER | **0** | — |

### Key evidence

| check | result |
|-------|--------|
| COMPLETE island months with nz window_ok CF raw | **104 / 104** |
| PARTIAL months with nz window_ok CF raw | **0 / 120** |
| CF manifests with `params.from < 2018-01` (any rc) | **0** |
| empty COMPLETE manifests mapped months | post-2017 only (`2020-11`, `2021-01…08`, `2022-05`) — already COMPLETE via better nz runs |
| local `jquants_records` pre-2018 | **0** (minmax event_time `2018-01-04…2026-08-10`; n=135323) |
| planner residual dry | **120** jobs all `fins_details` (`2008-01…2017-12`) |
| tip residual dry (`2024-01…2026-08-14`) | **0** |

Empty-shell evidence artifact: `.glm-logs/w0815t_g3_fins_details/matrix/empty_shell_evidence.json`  
DEFER record: `.glm-logs/w0815t_g3_fins_details/DEFER_pre2018_shells.json`

```json
{
  "dataset": "fins_details",
  "status": "DEFER",
  "n_shells": 120,
  "span": "2008-01..2017-12",
  "reason": "pre-history residual before observed_start 2018-01-01; matrix found zero nz window_ok CF raw and zero manifests with from<2018-01; local pre-2018 rows=0; sealable=0"
}
```

## Seal only sealable

| step | n |
|------|--:|
| sealable candidates | **0** |
| sealed / ready | **0** |
| issue | **0** (skip) |
| restore | **0** |

- `seal_map.json` / `all_unsealed_window_ok.json` → `[]`
- `READY_COUNT` / `SEAL_DONE` → **0**
- `SEAL_SKIP.txt` / `ISSUE_SKIP.txt`

No invent. Empty-raw ban held (would not seal `row_count=0` even if empty pre-2018 runs existed).

## Densify

**SKIP** (not this wave's scope; residual is DEFER-only).

| field | value |
|-------|------:|
| tip residual | **0** |
| sealable unsealed | **0** |
| residual shells | **120** DEFER pre-2018 |
| executed | **0** |
| host HTTP 429 | **0** (no POSTs) |

Artifacts: `DENSEIFY_SKIP.txt`, `densify_summary.json`

## Issue + publish

Issue: **skip** (`ISSUE_SKIP n=0 seal_ready=0`).

Publish (fail-closed, `--apply-remote`):

```text
complete_count_guard ok local=3457 remote=3457 force=False
remote projection applied
```

## FINAL reeval

```bash
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset fins_details --today 2026-08-15 --freshness-days 7
.venv/bin/python scripts/ops_reeval_freshness.py
```

| dataset | status | observed_start | observed_end | C8 |
|---------|--------|----------------|--------------|----|
| `fins_details` | **PARTIAL** | **`2018-01-01`** | **`2026-08-14`** | **pass** lag **1** |

Freshness: `projgen-e16f2fda784f4e91a1ce5b6740c2e61b` **OK**; `coverage_segments_untouched=1`; Mass **NO-GO**.

## POST (remote D1)

| item | PRE | POST | Δ |
|------|----:|-----:|--:|
| Segment COMPLETE total | **3457** | **3457** | **+0** |
| Dataset COMPLETE | **11** | **11** | **0** |
| `raw_retention_manifests` | **15145** | **15145** | **+0** |
| `fins_details` COMPLETE | **104** | **104** | **+0** |
| `fins_details` PARTIAL | **120** | **120** | **0** |
| empty COMPLETE (this-wave seals) | — | **0** | held |
| closed / seals | — | **0** | honest |

### Remote COMPLETE island (POST)

- `fins_details` **104**: `2018-01…2026-08` **continuous** (holes_in_span **0**)

Dataset remains **PARTIAL** at coverage level. Residual is honestly **DEFER-only** pre-history; no tip-join sealable remaining.

## Forbidden / honesty

- Did **not** launch Mass / READY / Phase7 ON.
- Did **not** invent empty COMPLETE (matrix sealable **0**; densify **0**).
- Did **not** densify DEFER pre-2018 shells (`2008-01…2017-12` × **120**).
- Did **not** kill peer processes.
- Did **not** use `--force-apply-remote`.
- Matrix honesty: every PARTIAL month checked against CF raw; closed **0** with explicit reason.
- Worker pass ≠ Coverage COMPLETE; COMPLETE path remains **seal+receipt+restore**.

## Residual pointers

| residual | n | condition to resume |
|----------|--:|---------------------|
| `fins_details` `2008-01…2017-12` | **120** | vendor/JQuants returns **nz** history for those months **and** CF raw lands with params window_ok → re-run matrix → seal-first only |

Do **not** densify empty/absent shells hoping for COMPLETE. Main island stays continuous through tip.

## Operator artifacts

| path | role |
|------|------|
| `.glm-logs/w0815t_g3_fins_details/matrix_partial_cf_raw.py` | PARTIAL×CF matrix runner |
| `.glm-logs/w0815t_g3_fins_details/matrix/partial_cf_raw_matrix.json` | full 120-row matrix |
| `.glm-logs/w0815t_g3_fins_details/matrix/empty_shell_evidence.json` | empty CF raw mapping |
| `.glm-logs/w0815t_g3_fins_details/matrix_summary.json` | compact matrix summary |
| `.glm-logs/w0815t_g3_fins_details/DEFER_pre2018_shells.json` | DEFER evidence pack |
| `.glm-logs/w0815t_g3_fins_details/seal_map.json` | seal candidates (**[]**) |
| `.glm-logs/w0815t_g3_fins_details/plan_dry.json` | residual dry **120** |
| `.glm-logs/w0815t_g3_fins_details/plan_tip_dry.json` | tip dry **0** |
| `.glm-logs/w0815t_g3_fins_details/FINAL_metrics.json` | wave metrics |
| `.glm-logs/w0815t_g3_fins_details/publish.log` | publish apply |
| `.glm-logs/w0815t_g3_fins_details/reeval_fins_details.log` | observed_window reeval |
| `.glm-logs/w0815t_g3_fins_details/reeval_freshness.log` | FRESH reclock |

## Report line

`T3 fins_details matrix PARTIAL×CF: sealable=0 closed=0 | DEFER pre-2018 shells 120 (no CF raw from<2018-01) | COMPLETE 104 island 2018-01…2026-08 continuous | platform 3457→3457 | raw 15145 | FRESH projgen-e16f2fda… C8 pass lag1 | empty 0 | empty-raw ban held | push`
