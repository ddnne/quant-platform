# G6 = T9 + T10 — t6_deriv_edinet seal + options_225 COMPLETE + reeval (2026-08-13)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** none (raw + structured + signed SUCCESS only)  
**cf_premium dual-run ban:** **honored** — did **not** kill live `t5_fins_paced` / `t6_options_near` / other peers  
**prefix:** `t6_deriv_edinet_*` · workers=1 · general (shared RPM)  
**base tip (residual PRE):** `e00b05f` / COMPLETE **531** / raw_n **7362**

## Goal

1. Close **G6** (T9 derivatives + T10 EDINET) circuit: backfill → R2 raw mirror → signed receipts → fail-closed publish → reeval.
2. Confirm remote COMPLETE +N already sealed; do **not** invent COMPLETE.
3. Options monthly fail / near-term week-chunks: **wave partial** close (options_near still running; not killed).

## PRE (remote D1 @ residual tip)

| Metric | PRE |
|--------|-----|
| Segment COMPLETE | **531** |
| raw_retention_manifests | **7362** |
| futures COMPLETE segs | **3** — `2026-01/02/08` (G7 residual table) |
| options COMPLETE segs | **1** — `2026-08` |
| options_225 COMPLETE segs | **1** — `2026-08` |
| edinet major COMPLETE | **4** — `2026-01/02/07/08` |
| edinet cross COMPLETE | **6** — `2026-02/03/04/06/07/08` |
| edinet large_volume COMPLETE | **8** — `2026-01…08` |

## Execute (worker pass — raw acquisition)

```bash
# main wave (finished; pid dead)
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets derivatives_bars_daily_futures,derivatives_bars_daily_options,derivatives_bars_daily_options_225,\
edinet_major_shareholders,edinet_cross_shareholdings,edinet_large_volume_shareholders \
  --execute ... \
  --plan-out .glm-logs/cf-backfill/t6_deriv_edinet_plan.json \
  --state-out .glm-logs/cf-backfill/t6_deriv_edinet_state.jsonl

# EDINET gap fill (finished)
# t6_edinet_gap_* → 6/6 pass

# options near week-chunks (still running at close; max-jobs=16 — not killed)
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets derivatives_bars_daily_options \
  --from-date 2026-06-01 --to-date 2026-07-31 \
  --execute --workers 1 --general-rpm 25 --max-jobs 16 \
  --week-chunks --chunk-days 7 \
  --plan-out .glm-logs/cf-backfill/t6_options_near_plan.json \
  --state-out .glm-logs/cf-backfill/t6_options_near_state.jsonl
```

| Field | Value |
|-------|-------|
| t6_deriv_edinet window | `2026-08-13T14:03:45Z` → `2026-08-13T14:42:05Z` (~38 min) |
| executed | **23** (plan job_count **35**; partial queue / prior coverage) |
| pass / fail | **22** / **1** |
| fail | `derivatives_bars_daily_options/2026-01` (http 0 — month job; deferred to week-chunk near wave) |
| edinet_gap | **6/6 pass** (major 03–06, cross 01/05) |
| options_near (at close) | **still_running** — state n≥3 pass week-chunks; plan 9 jobs; **not killed** |

Worker pass ≠ Coverage COMPLETE.

## Seal path (raw-required)

1. Remote `raw_retention_manifests` run_ids (non-empty pages) for each segment.
2. `wrangler r2 object get` → combined local raw under `data/raw/jquants/2026/08/13/*_from=_to=_from_r2_run*.json`.
3. Upsert structured into local `jquants_records` (row counts match raw).
4. `issue_receipts_parallel.py --struct-hint` → signed SUCCESS run_ids **900548–900565** (new seals) + re-issue of G7-era large_volume/futures for consistency.
5. Fail-closed `publish_ops_projection.py --apply-remote` (publish1 + publish2).

### New COMPLETE seals this G6 session (vs G7 POST **520**)

| dataset | segment_ids | structured (ex.) | receipt run_ids | +N |
|---------|-------------|-----------------:|-----------------|--:|
| `derivatives_bars_daily_futures` | **2026-03…07** | 2352…2772 | **900548–900552** | **+5** |
| `edinet_major_shareholders` | **2026-03…06** | 73…2402 | **900553–900556** | **+4** |
| `edinet_cross_shareholdings` | **2026-01**, **2026-05** | 68 / 214 | **900557**, **900558** | **+2** |
| `derivatives_bars_daily_options_225` | **2026-01…07** | 145292…232474 | **900559–900565** | **+7** |
| **session total** | | | | **+18** |

Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`.  
Empty-raw ban held. Re-issues of already-COMPLETE large_volume 01–06 / futures 01–02 (G7 T12) do **not** inflate +N.

### Publish guards

```text
publish1: complete_count_guard ok local=531 remote=520 force=False → remote=531
publish2: complete_count_guard ok local=538 remote=531 force=False → remote=538
```

Residual tip **531** already absorbed publish1 (+11 from G7 520). This closeout confirms publish2 **+7** (options_225).

## POST (remote D1 — verified live)

| Metric | POST |
|--------|-----:|
| Segment COMPLETE | **538** (**+7** vs residual tip 531; **+18** vs G7 520) |
| Dataset COMPLETE | **2** (calendar + tokyo_repo; unchanged) |
| raw_retention_manifests | **7389** (peer acq continuing: options_near + fins) |
| Projection | **FRESH** `projgen-b758a387a7a440639ea4619eb7bad6ad` age=0 |

### COMPLETE months (remote)

| dataset | COMPLETE segment_ids | n |
|---------|----------------------|--:|
| `derivatives_bars_daily_futures` | **2026-01…08** | **8** |
| `derivatives_bars_daily_options` | 2026-08 only | 1 |
| `derivatives_bars_daily_options_225` | **2026-01…08** | **8** |
| `edinet_major_shareholders` | **2026-01…08** | **8** |
| `edinet_cross_shareholdings` | **2026-01…08** | **8** |
| `edinet_large_volume_shareholders` | 2026-01…08 (unchanged) | 8 |

## Reeval

```bash
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset derivatives_bars_daily_futures --today 2026-08-13
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset derivatives_bars_daily_options --today 2026-08-13
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset derivatives_bars_daily_options_225 --today 2026-08-13
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset edinet_major_shareholders --today 2026-08-13
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset edinet_cross_shareholdings --today 2026-08-13
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset edinet_large_volume_shareholders --today 2026-08-13
.venv/bin/python scripts/ops_reeval_freshness.py
```

| dataset | status | observed_start → end | C8 |
|---------|--------|----------------------|-----|
| futures | **PARTIAL** | `2026-01-01` → `2026-08-12` | **pass** lag 1 |
| options | **PARTIAL** | **`2026-06-01`** → `2026-08-12` (was 2026-08-01) | **pass** lag 1 |
| options_225 | **PARTIAL** | `2026-01-01` → `2026-08-12` | **pass** lag 1 |
| edinet major | **PARTIAL** | `2026-01-01` → `2026-08-13` | **pass** lag 3 |
| edinet cross | **PARTIAL** | `2026-01-01` → `2026-08-13` | **pass** lag 3 |
| edinet large_volume | **PARTIAL** | `2026-01-01` → `2026-08-13` | **pass** lag 1 |

No segment rewrite. No COMPLETE / Mass / READY claim from reeval. Datasets remain **PARTIAL** honest (catalog months remain open beyond 2026 H1).

## Wave partial / still_running

| job | status | note |
|-----|--------|------|
| `t6_deriv_edinet` main | **done** | 22p/1f; seals published |
| `t6_edinet_gap` | **done** | 6/6 pass |
| `t6_options_near` | **still_running** | max-jobs **16** (not 40); week-chunks Jun–Jul options; **not killed** |
| `t5_fins_paced` | **still_running** | peer; **not killed** |

Options full-month COMPLETE still **DEFER** until week-chunks finish + R2 seal path. Close circuit on sealed +18 / remote **538**.

## Forbidden held

- empty COMPLETE — none
- Mass / READY / Phase7 ON — **NO-GO / OFF**
- kill other jobs — none

## Report line

`SHA=<post-push> COMPLETE=538 (+7 tip / +18 vs G7) pass=22 fail=1 still_running=t6_options_near,t5_fins_paced`
