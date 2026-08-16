# W71 / w0816e — bars_am historical months LIVE API probe (2026-08-16)

**Wave:** W71 / `w0816e`  
**Task A:** LIVE API probe for `equities_bars_daily_am` PARTIAL history months `2024-01…2026-07` + seal **only if** nz window_ok  
**Task B:** aggregate sync after any seal (N/A — zero seals)  
**As of (live D1 AFTER restore):** `2026-08-16T02:00:06Z`  
**Mass / READY / Phase7:** **OFF / not declared / OFF**  
**Commit/push:** **not done** (D agent)

---

## Policy held

| gate | value |
|------|-------|
| empty-raw COMPLETE | **FORBIDDEN** · **held** (0 seals) |
| invent COMPLETE | **FORBIDDEN** · **held** |
| fins 104/104 | **held** (must not roll back) |
| Dataset COMPLETE 22 | **held** (→23 only if bars_am 32/32 honest) |
| Mass / READY | **OFF** |
| rate limit | general pool · `--workers 1` · `--general-rpm 60` |
| PD-D4-BARS-AM | prior permanent DEFER (tip-only vendor); **THIS WAVE re-probes live API** like W68 fins tip4 |

Prior residual label **PD-D4-BARS-AM** remains valid for research history loads. This wave **explicitly re-probed** live `/v1/run` for all 31 PARTIAL months. Vendor returned **empty** shells for every history window → **no seal**.

---

## 1. BEFORE — remote D1

| item | value |
|------|------:|
| `equities_bars_daily_am` COMPLETE segs | **1** (`2026-08` tip) |
| `equities_bars_daily_am` PARTIAL segs | **31** (`2024-01`…`2026-07`) |
| complete_segments ratio | **1/32** |
| Dataset COMPLETE (seg-derived) | **22** |
| Platform COMPLETE segs | **3482** |
| `fins_earnings_date` COMPLETE | **104/104** |
| empty COMPLETE | **0** |

### PARTIAL segment list (n=31)

`2024-01` `2024-02` `2024-03` `2024-04` `2024-05` `2024-06` `2024-07` `2024-08` `2024-09` `2024-10` `2024-11` `2024-12` `2025-01` `2025-02` `2025-03` `2025-04` `2025-05` `2025-06` `2025-07` `2025-08` `2025-09` `2025-10` `2025-11` `2025-12` `2026-01` `2026-02` `2026-03` `2026-04` `2026-05` `2026-06` `2026-07`

Artifacts: [`.glm-logs/w0816e_w71_bars_am/BEFORE_snapshot.json`](../../.glm-logs/w0816e_w71_bars_am/BEFORE_snapshot.json) · `BEFORE_bars_am_status.json` · `BEFORE_partial_list.json`

---

## 2. Catalog / vendor constraint (re-stated)

| field | value |
|-------|-------|
| `dataset_id` | `equities_bars_daily_am` |
| `path` | `/v2/equities/bars/daily/am` |
| `date_mode` | **`today`** (worker expands `from`/`to` → per-day `date=` queries) |
| `params` | `code`, `date` |
| vendor docs | same-day AM only until ~06:00 next day; historical OHLC → full-day bars API |

Permanent DEFER id: **PD-D4-BARS-AM** (still active for research history loads).

---

## 3. LIVE API probe (must prove API hit — not inventory-only)

**Path:** `scripts/ops/cf_premium_backfill.py --execute`  
**Endpoint:** `POST …/v1/run?dataset=equities_bars_daily_am&from=…&to=…`  
**Worker:** `quant-platform-ingestion-premium.taku-haga.workers.dev`  
**Pool:** general · `--workers 1` · `--general-rpm 60`

Dry-run first (sample month `2026-07`): `mode=dry-run plan_jobs=1 queued=1 executed=0`.

Then **per-month live execute** for all 31 PARTIAL months (HTTP 200, worker `pass`, `rowsInserted=0` every month).

### Per-month results

| month | from → to | HTTP | state | rowsInserted | R2 run_id | pages | rawBytes | window_ok | empty vs nz | reason |
|-------|-----------|-----:|-------|-------------:|----------:|------:|---------:|:---------:|:-----------:|--------|
| `2024-01` | 2024-01-04 → 2024-01-31 | **200** | pass | **0** | **14099** | 28 | 2464 | no | **empty** | LIVE_API_EMPTY |
| `2024-02` | 2024-02-01 → 2024-02-29 | **200** | pass | **0** | **14110** | 29 | 2552 | no | **empty** | LIVE_API_EMPTY |
| `2024-03` | 2024-03-01 → 2024-03-31 | **200** | pass | **0** | **14111** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2024-04` | 2024-04-01 → 2024-04-30 | **200** | pass | **0** | **14112** | 30 | 2640 | no | **empty** | LIVE_API_EMPTY |
| `2024-05` | 2024-05-01 → 2024-05-31 | **200** | pass | **0** | **14113** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2024-06` | 2024-06-01 → 2024-06-30 | **200** | pass | **0** | **14114** | 30 | 2640 | no | **empty** | LIVE_API_EMPTY |
| `2024-07` | 2024-07-01 → 2024-07-31 | **200** | pass | **0** | **14115** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2024-08` | 2024-08-01 → 2024-08-31 | **200** | pass | **0** | **14100** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2024-09` | 2024-09-01 → 2024-09-30 | **200** | pass | **0** | **14101** | 30 | 2640 | no | **empty** | LIVE_API_EMPTY |
| `2024-10` | 2024-10-01 → 2024-10-31 | **200** | pass | **0** | **14102** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2024-11` | 2024-11-01 → 2024-11-30 | **200** | pass | **0** | **14103** | 30 | 2640 | no | **empty** | LIVE_API_EMPTY |
| `2024-12` | 2024-12-01 → 2024-12-31 | **200** | pass | **0** | **14104** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2025-01` | 2025-01-01 → 2025-01-31 | **200** | pass | **0** | **14105** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2025-02` | 2025-02-01 → 2025-02-28 | **200** | pass | **0** | **14106** | 28 | 2464 | no | **empty** | LIVE_API_EMPTY |
| `2025-03` | 2025-03-01 → 2025-03-31 | **200** | pass | **0** | **14107** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2025-04` | 2025-04-01 → 2025-04-30 | **200** | pass | **0** | **14108** | 30 | 2640 | no | **empty** | LIVE_API_EMPTY |
| `2025-05` | 2025-05-01 → 2025-05-31 | **200** | pass | **0** | **14116** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2025-06` | 2025-06-01 → 2025-06-30 | **200** | pass | **0** | **14117** | 30 | 2640 | no | **empty** | LIVE_API_EMPTY |
| `2025-07` | 2025-07-01 → 2025-07-31 | **200** | pass | **0** | **14118** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2025-08` | 2025-08-01 → 2025-08-31 | **200** | pass | **0** | **14119** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2025-09` | 2025-09-01 → 2025-09-30 | **200** | pass | **0** | **14120** | 30 | 2640 | no | **empty** | LIVE_API_EMPTY |
| `2025-10` | 2025-10-01 → 2025-10-31 | **200** | pass | **0** | **14121** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2025-11` | 2025-11-01 → 2025-11-30 | **200** | pass | **0** | **14122** | 30 | 2640 | no | **empty** | LIVE_API_EMPTY |
| `2025-12` | 2025-12-01 → 2025-12-31 | **200** | pass | **0** | **14123** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2026-01` | 2026-01-01 → 2026-01-31 | **200** | pass | **0** | **14124** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2026-02` | 2026-02-01 → 2026-02-28 | **200** | pass | **0** | **14125** | 28 | 2464 | no | **empty** | LIVE_API_EMPTY |
| `2026-03` | 2026-03-01 → 2026-03-31 | **200** | pass | **0** | **14126** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2026-04` | 2026-04-01 → 2026-04-30 | **200** | pass | **0** | **14127** | 30 | 2640 | no | **empty** | LIVE_API_EMPTY |
| `2026-05` | 2026-05-01 → 2026-05-31 | **200** | pass | **0** | **14128** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |
| `2026-06` | 2026-06-01 → 2026-06-30 | **200** | pass | **0** | **14129** | 30 | 2640 | no | **empty** | LIVE_API_EMPTY |
| `2026-07` | 2026-07-01 → 2026-07-31 | **200** | pass | **0** | **14098** | 31 | 2728 | no | **empty** | LIVE_API_EMPTY |

**LIVE_API_EMPTY:** **true** (all 31 months `rowsInserted=0` / R2 `row_count=0`).

Notes:

- `2024-01` clipped to `history_target_start=2024-01-04` → 28 query-days (planner contract).
- R2 raw shell ≈ **88 bytes/day** (empty page); month `raw_bytes` ≈ `88 × page_count`.
- Sample manifest (`run_id=14129`, month `2026-06`): `params.from/to` correct window, `row_count=0`, per-page `rows=0`.
- Worker `pass` ≠ Coverage COMPLETE. Empty raw must not invent COMPLETE.

Logs: [`.glm-logs/w0816e_w71_bars_am/live_api_results.json`](../../.glm-logs/w0816e_w71_bars_am/live_api_results.json) · `run_manifest_map.json` · `manifests/` · `live_*_state.jsonl` · `live_*_run.log`

---

## 4. Seal decision

| check | result |
|-------|--------|
| any month nz window_ok raw? | **No** (0/31) |
| empty-raw COMPLETE allowed? | **FORBIDDEN** |
| seal action | **NO_SEAL** (all months left PARTIAL) |
| sealed this wave | **0** |
| densify executed | **0** |

### Worker side-effect + restore

During live `/v1/run`, worker `writeRequiredCoverageSegment` rewrote each planned history segment to **`status=UNKNOWN`** (ON CONFLICT forces UNKNOWN + clears receipt). Tip `2026-08` sticky COMPLETE was **not** demoted.

Per wave policy (“empty months: leave PARTIAL”), restored after probe:

```sql
UPDATE coverage_segments
SET status='PARTIAL',
    detail_json=json_set(..., '$.wave_w71', 'LIVE_API_EMPTY', ...),
    evaluated_at=...
WHERE dataset='equities_bars_daily_am'
  AND status='UNKNOWN'
  AND segment_id BETWEEN '2024-01' AND '2026-07';
-- changes=31
```

Tip COMPLETE `2026-08` / receipt `900297` untouched.

---

## 5. AFTER — remote D1 recount

| item | before | after | Δ |
|------|-------:|------:|--:|
| bars_am COMPLETE segs | **1** | **1** | **0** |
| bars_am PARTIAL segs | **31** | **31** | **0** |
| complete_segments ratio | **1/32** | **1/32** | **0** |
| Dataset COMPLETE | **22** | **22** | **0** |
| Platform COMPLETE segs | **3482** | **3482** | **0** |
| `fins_earnings_date` COMPLETE | **104** | **104** | **0** |
| empty COMPLETE | **0** | **0** | held |
| sealed this wave | — | **0** | |
| densify executed | — | **0** | |

### Tip segment AFTER

| segment_id | status | receipt_run_id |
|------------|--------|---------------:|
| `2026-08` | **COMPLETE** | 900297 |

### History residual AFTER

| span | status | n |
|------|--------|--:|
| `2024-01`…`2026-07` | **PARTIAL** | **31** |

---

## 6. Task B — aggregate sync

| step | result |
|------|--------|
| any seal? | **No** |
| `sync_dataset_coverage_from_segments.py` | **SKIPPED** (no segment COMPLETE flip) |
| `publish_ops_projection.py` | **SKIPPED** (no seal) |
| remote `dataset_coverage.equities_bars_daily_am.status` | **PARTIAL** |
| segment SoT vs ops | **match** local+remote: COMPLETE **1** / PARTIAL **31** |

No dishonest Dataset COMPLETE promote. bars_am remains out of the 22 Dataset COMPLETE set (needs honest 32/32).

---

## 7. Honesty explicit

- **Live API attempted** for all 31 PARTIAL months (HTTP 200 ×31, R2 run_ids **14098…14129** with gap at 14109) — not inventory-only
- **All months LIVE_API_EMPTY** (`rowsInserted=0`, `row_count=0`)
- **No seal** — empty-raw COMPLETE forbidden
- **No invent COMPLETE** — Dataset COMPLETE held **22**
- **fins 104/104** held
- **empty COMPLETE = 0** held
- Worker UNKNOWN side-effect **restored to PARTIAL**
- Did **not** Mass / READY
- Did **not** commit/push

**Vendor conclusion (re-confirmed live):** AM endpoint remains tip-only. Historical month windows return empty shells. Honest history densify still unavailable on this path; residual stays PD-D4-BARS-AM for research history until a true historical AM API or alternate (full-day bars morning fields) is used.

---

## Wave result

### **wave A COMPLETE for LIVE probe evidence (no seal)**

| field | value |
|-------|-------|
| outcome | **LIVE_API_EMPTY** all 31 history months |
| complete_segments | **1/32 → 1/32** |
| Dataset COMPLETE | **22 → 22** |
| sealed_n | **0** |
| API returned nz data | **no** |

---

## Machine logs (gitignored OK)

Prefix: [`.glm-logs/w0816e_w71_bars_am/`](../../.glm-logs/w0816e_w71_bars_am/)

| artifact | purpose |
|----------|---------|
| `d1q.py` | remote D1 helper |
| `BEFORE_snapshot.json` / `BEFORE_*.json` | before counts + partial list |
| `dry_2026-07_*` | dry-run plan sample |
| `live_2026-07_*` / `live_all_partial_*` / `live_remaining_*` / `live_????-??_*` | per-month live API |
| `live_api_results.json` | full month table machine form |
| `run_manifest_map.json` / `wave_monthly_manifests.json` | R2 run_id ↔ month |
| `manifests/manifest_*.json` | R2 raw manifests (empty shells) |
| `restore_partial.log` | UNKNOWN → PARTIAL restore |
| `AFTER_*.json` / `AFTER_restore_*.json` | after D1 recount |
| `segment_sot_verify.json` | local vs remote segment match |
| `FINAL_metrics.json` | machine metrics |

---

## Exact numbers (return)

```text
BEFORE: bars_am complete_segments=1/32  PARTIAL=31  dataset_complete=22  platform_complete_segs=3482  fins=104/104  empty_complete=0
LIVE API: probed=31  nz=0  empty=31  fail=0  run_ids=14098..14129 (gap 14109)  LIVE_API_EMPTY=true
SEAL: sealed_n=0  densify_executed=0
AFTER:  bars_am complete_segments=1/32  PARTIAL=31  dataset_complete=22  platform_complete_segs=3482  fins=104/104  empty_complete=0
DELTA:  complete_segments=+0  dataset_complete=+0  sealed_n=0
SIDE-EFFECT: worker UNKNOWN rewrite on plan → restored PARTIAL×31 (tip COMPLETE held)
AGGREGATE SYNC: skipped (no seals); ops dataset_coverage PARTIAL matches segment SoT 1/31
WAVE A: LIVE probe complete; no history seal possible (vendor tip-only AM reconfirmed)
```
