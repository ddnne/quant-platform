# W0814 all-sources wave close — G10 (2026-08-14)

**Mass / READY / Phase7:** **NO-GO / OFF**  
**empty COMPLETE:** **0** (`receipt_run_id` null/0 = 0)  
**kill acq jobs:** **none** — peers left running (seal_from_r2 G2/G5/G6/G7, `issue_receipts` idx, opt225 one-shots)  
**Forbidden held:** Mass OFF; no empty COMPLETE; no kill acq; Phase7 OFF; no large `cf_premium` launched by G10

**Session PRE (task brief G10 閉路):** tip `cac338b`; raw **n=9687** / **c=8567**; COMPLETE segs **942**  
**Base tip at close measure:** `20a4709` (origin/main after G9 JSDA residual tip-set)  
**Live verified:** **2026-08-14** (JST) / ~**2026-08-14T01:32Z** UTC

## Scope

| Step | Track | Result |
|------|-------|--------|
| 1 wait / monitor | 他 G acq を kill しない; ~15–18 min sample | peers alive; raw climb monitored |
| 2 issue_receipts | new raw / empty-raw ban; no large cf_premium | margin dry **ready=45** (concurrent peer issue → G10 write skipped); peer seals already landed (topix/futures/JSDA) |
| 3 freshness | `ops_reeval_freshness` | **FRESH** `projgen-d28bfce…` age≈0 |
| 4 reeval | key datasets ×5 after publish | C8 **pass** all; segs untouched by reeval |
| 5 remote D1 POST | raw + COMPLETE segs + per-dataset | raw **10662**/c **9090**; COMPLETE **1106**; empty **0** |
| 6 residual live-sync | `phase62_residual_status.md` | tip/raw/COMPLETE/FRESH + top datasets |
| 7 proof | this file | PRE/POST + host RPM samples from state jsonl |

## T1 — peer monitor (no kill)

Sample window ~**2026-08-14T00:55Z → 01:10Z** (monitor `.glm-logs/w0814_all_sources_wave/monitor.log`).

Live peer roles at close (not killed):

| PID role | note |
|----------|------|
| `seal_from_r2` G2 mb / G5 fins / G6 deriv / G7 edinet | peer seals continuing |
| `issue_receipts_parallel` `indices_bars_daily` | G3 idx seal chain |
| `cf_premium_backfill` opt225 one-shots | G6 paced residual |
| prior `seal_from_r2` margin-inv | G7 residual mirror (earlier) |

**Resume policy:** fail residuals owned by live peer PIDs → **no G10 one-shot resume / no kill**.

## T2 — host RPM samples (state jsonl)

Source: `.glm-logs/cf-backfill/*_state.jsonl` → `.glm-logs/w0814_all_sources_wave/rpm_final.json`.

### w0814 multi-track (this wave)

| Track | host POST/min | n | pass/fail (state) |
|-------|--------------:|--:|-------------------|
| g1 bars | **13.74** | **200** | 124p / 76f |
| g2 mb residual | **14.38** | **120** | 48p / 72f |
| g2 mb retry | **6.09** | **43** | 43p / 0f |
| g3 topix exec | **34.74** | **142** | 81p / 61f |
| g3 idx exec | **13.22** | **80** | 13p / 67f |
| g4 master / retry | **24.28** / **21.31** | 21 / 21 | 0p / 21f ×2 (sub/429) |
| g5 fins paced | **2.39** | **34** | 32p / 2f |
| g6 deriv paced | — | **15** | 14p / 1f (serial one-shots) |
| g6 fut/opt225 first-burst | **11.47** | 12 | 0p / 12f → paced recover |
| g6 options 2026h1 | **12.64** | 13 | 0p / 13f (timeouts; DEFER) |
| g7 edinet main / retry | **7.31** / **4.26** | 36 / 36 | main 3p/33f → retry **36/36** |

### Prior-wave anchors (still in session jsonl)

| Track | host POST/min | n | note |
|-------|--------------:|--:|------|
| w0713 t7 margin_inv | **9.62** | 970 | 918p/52f + retry 52/52 |
| w0713 t3 topix | **54.56** | 192 | all pass |
| w0713 t1 bars exec/retry | **7.22** / **7.85** | 120 / 22 | |
| w0713 t4 mb residual | **10.34** | 44 | |
| t5 fins paced FINAL | **1.73** | 308 | 288p/20f |
| t5_div_pre | **4.72** | 120 | all pass |

## T3 — remote D1 raw + COMPLETE segs

DB: `quant-ingest` (`platform/workers/ingestion-premium/wrangler.toml`).

```sql
SELECT COUNT(*) n, SUM(CASE WHEN completeness='COMPLETE' THEN 1 ELSE 0 END) c
FROM raw_retention_manifests;
SELECT status, COUNT(*) n FROM coverage_segments GROUP BY status;
SELECT COUNT(*) n FROM coverage_segments
 WHERE status='COMPLETE' AND (receipt_run_id IS NULL OR receipt_run_id=0);
```

| Metric | PRE (brief) | POST (~01:32Z) | Δ |
|--------|------------:|---------------:|--:|
| `raw_retention_manifests` total (`raw_n`) | **9687** | **10662** | **+975** |
| raw completeness=COMPLETE (`raw_c`) | **8567** | **9090** | **+523** |
| `coverage_segments` COMPLETE | **942** | **1106** | **+164** |
| empty COMPLETE (`receipt_run_id` null/0) | 0 | **0** | 0 |

**Honesty:** G10 this pass = **monitor + measure + reeval + freshness + publish apply** (local **1106** ≥ remote **1068** fail-closed).  
COMPLETE climb is from **peer seals** already on local/remote (topix/futures/JSDA/G9) — **not** invented; empty-raw ban held.  
G10 margin dry found **ready=45** but **concurrent** peer `issue_receipts` → **write skipped** (二重禁止).

### Top datasets COMPLETE (POST)

| dataset | PRE COMPLETE | POST COMPLETE | Δ | note |
|---------|-------------:|--------------:|--:|------|
| `markets_calendar` | 224 | **224** | 0 | dataset COMPLETE |
| `equities_master` | 220 | **220** | 0 | G4 residual acq 0 seals |
| `indices_bars_daily_topix` | **82** | **220** | **+138** | G3 w0814 seal wave |
| `markets_breakdown` | 69 | **69** | 0 | G2 acq continuing; seal DEFER mid |
| `equities_bars_daily` | 42 | **42** | 0 | G1 acq 124p/76f; seals next wave |
| `fins_summary` | 42 | **42** | 0 | G5 residual acq/seal in flight |
| `derivatives_bars_daily_futures` | **20** | **32** | **+12** | G6 2024 futures paced |
| `jsda_corporate_bond_transactions` | 1 | **12** | **+11** | **G9** dataset COMPLETE |
| `jsda_otc_bond_reference_prices` | 6 | **9** | **+3** | **G9** tip days |
| `markets_margin_interest` | 17 | **17** | 0 | dry ready=45 deferred (peer concurrent) |

## T4 — reeval + freshness

### `ops_reeval_observed_window` (×5 after publish)

No segment rewrite / no COMPLETE claim. `--today 2026-08-14 --freshness-days 7`.  
Artifacts: `.glm-logs/w0814_all_sources_wave/reeval2_*.log`

| dataset | status | observed_start | observed_end | C8 |
|---------|--------|----------------|--------------|----|
| `equities_bars_daily` | **PARTIAL** | **`2008-05-01`** | **`2026-08-13`** | **pass** lag **1** |
| `equities_master` | **PARTIAL** | **`2006-08-13`** | **`2026-08-13`** | **pass** lag **1** |
| `indices_bars_daily_topix` | **PARTIAL** | **`2008-01-01`** | **`2026-08-14`** | **pass** lag **0** |
| `markets_breakdown` | **PARTIAL** | **`2015-03-26`** | **`2026-08-13`** | **pass** lag **1** |
| `markets_margin_interest` | **PARTIAL** | **`2013-01-04`** | **`2026-08-13`** | **pass** lag **2** |

### `ops_reeval_freshness` → FRESH age≈0

| Field | POST |
|-------|------|
| status | **FRESH** |
| `generated_at` | **`2026-08-14T01:31:56.282878+00:00`** |
| `age_seconds` | **0** (local meta) / **~15** (remote age query immediately after) |
| `active_generation` | **`projgen-d28bfce700ad4452ac85b404961504f2`** |
| publisher | `scripts/ops_reeval_freshness.py` |
| COMPLETE segments | **untouched by freshness reclock** |

Prior: full `publish_ops_projection.py --apply-remote` (`complete_count_guard ok local=1106 remote=1068`).

## empty COMPLETE / Mass / Phase7 / acq

| Check | Result |
|-------|--------|
| COMPLETE ∧ (`receipt_run_id` IS NULL OR =0) | **0** |
| Mass / READY / B0 | **NO-GO** |
| Phase 7 | **OFF** |
| Live acq killed? | **no** |
| Large cf_premium by G10? | **no** |

## Artifacts (local, gitignored logs)

- `.glm-logs/w0814_all_sources_wave/monitor.log` — 6 samples ~18 min  
- `.glm-logs/w0814_all_sources_wave/rpm_final.json` / `rpm_final.txt`  
- `.glm-logs/w0814_all_sources_wave/issue_dry_margin.log` — ready=45  
- `.glm-logs/w0814_all_sources_wave/publish.log` — fail-closed apply  
- `.glm-logs/w0814_all_sources_wave/freshness2.log` / `reeval2_*.log`  
- `.glm-logs/w0814_all_sources_wave/final_*.json` — remote POST measures  

## Residual

`docs/phase62_residual_status.md` live-synced to this POST (COMPLETE **1106** / raw_n **10662** / topix **220** / futures **32** / FRESH `projgen-d28bfce…`).
