# T5/T9/T10 — MB reeval + 2015-dir week batch + EDINET monthly +4 (2026-08-13)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**bars/fins:** not killed (bars solo still live on general; fins paced finished on its own)  
**cf_premium:** MB week-chunks (low RPM) + EDINET H1 month batch only

## Summary

| Item | Result |
|------|--------|
| Segment COMPLETE (remote) | **506 → 510** (**+4** EDINET) |
| `markets_breakdown.observed_start` | reeval restore **`2015-03-26`** (post-publish was 2024-01-01; prior residual 2015-04-01) |
| MB solo (pre-this-pass) | **409/409 pass** (2016-03→2023-12 week-chunks) — finished before this pass |
| MB this pass | 2015-dir week-chunks (low RPM vs bars): **pass 26 / fail 5**, sum_rows≈211k; stuck→stopped (not bars) |
| JSDA OTC | **+0** — official site connect timeout; no new local/R2 raw beyond existing 5 COMPLETE days |
| EDINET | **+4 COMPLETE** months sealed (monthly expand from Jul/Aug only) |

## 1) markets_breakdown (T5)

### PRE
- MB solo already finished: `p0_mb_solo` executed=409 states `pass:409` (2016-03…2023-12).
- Full publish had regressed remote `observed_start` to **`2024-01-01`**.
- Receipt plane dry-run: n_receipts **608**, window start **`2015-04-01`**, sum_raw≈10.6M.

### Actions
1. `ops_reeval_observed_window.py --dataset markets_breakdown` → restored **`2015-04-01`**.
2. One week-chunk batch toward 2015 frontier (solo already closed 2016+):
   - range `2015-01-01`…`2016-02-29`, `--week-chunks --chunk-days 7`
   - wave A: workers=1 `general-rpm=80` max-jobs=52 → 429 contention with bars@495
   - wave B: restart `general-rpm=40` max-jobs=30 sleep-on-retry=8
3. Post-publish reeval again (full publish reset observed to 2024-01-01).

### POST
| metric | value |
|--------|------:|
| `observed_start` | **`2015-03-26`** |
| `observed_end` | `2026-08-12` |
| status | PARTIAL |
| week pass/fail this pass | **26 / 5** |
| segments touched | 2015-01…2015-05 |

Worker pass ≠ Coverage COMPLETE. No dataset COMPLETE claim for breakdown.

## 2) JSDA OTC (T9)

| check | result |
|-------|--------|
| Local COMPLETE days | 5 (`2026-08-06/07/10/12/13`) — unchanged |
| Official CSV probe (earlier) | HTTP 200 for S260805/04/03/731 |
| Fetch this pass | **connect timeout** to `market.jsda.or.jp:443` |
| R2 probe unsealed days | miss |
| issue_receipts dry | raw_index 0 for OTC path / no_struct recent calendar |

**OTC +0.** Honest DEFER until raw bytes available (official or R2).

## 3) EDINET monthly expand (T10)

### Backfill (worker pass)
`cf_premium_backfill` H1 months `2026-01`…`2026-06`, workers=1 `general-rpm=30` max-jobs=12:

| dataset | segment | rowsInserted |
|---------|---------|-------------:|
| `edinet_major_shareholders` | 2026-01 | 71 |
| `edinet_cross_shareholdings` | 2026-02 | 68 |
| `edinet_cross_shareholdings` | 2026-03 | 542 |
| `edinet_cross_shareholdings` | 2026-04 | 68 |

(Further jobs stalled under general RPM share with bars; process stopped — not bars/fins.)

### Seal path (raw-required)
1. Remote `raw_retention_manifests` run_ids 4744 / 4757 / 4765 / 4779 (row_count>0).
2. `wrangler r2 object get` non-empty pages → combined local raw under `data/raw/jquants/2026/08/13/` with `from=`/`to=` names.
3. Upsert structured into local `jquants_records` (window counts match).
4. `issue_receipts_parallel.py --struct-hint` → signed SUCCESS run_ids **900526–900529**.
5. Fail-closed `publish_ops_projection.py --apply-remote` (retry after wrangler import flake).

### Segments sealed (+4)

| dataset | segment_id | structured | receipt run_id | R2 run |
|---------|------------|----------:|---------------:|-------:|
| `edinet_major_shareholders` | 2026-01 | 71 | 900526 | 4744 |
| `edinet_cross_shareholdings` | 2026-02 | 68 | 900529 | 4757 |
| `edinet_cross_shareholdings` | 2026-03 | 542 | 900528 | 4765 |
| `edinet_cross_shareholdings` | 2026-04 | 68 | 900527 | 4779 |

Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`.  
Empty-raw ban held (only non-empty R2 pages combined).

### Remote POST edinet COMPLETE months
- major: **2026-01**, 2026-07, 2026-08 (was 07+08 only)
- cross: **2026-02/03/04**, 2026-07, 2026-08
- large_volume: 2026-07, 2026-08 (no new seal this pass)

## Publish / freshness

| step | result |
|------|--------|
| complete_count_guard | local=510 remote=506 → apply → **remote=510** |
| post reeval freshness | `projgen-e730b97119c6407aac3f17e2f8d50982` FRESH age=0 |
| breakdown observed after reeval | **`2015-03-26`** |

## Explicit non-claims / DEFER

| Item | Status |
|------|--------|
| COMPLETE without raw | **Forbidden** |
| OTC +N this pass | **+0** (no raw) |
| Full EDINET history | **DEFER** (only +4 months) |
| large_volume H1 months | **DEFER** (backfill incomplete under RPM) |
| MB dataset COMPLETE | **not claimed** |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| bars solo process | **left running** |

## Operator notes
- Full publish still resets breakdown `observed_*` toward hot facts; always re-run `ops_reeval_observed_window.py --dataset markets_breakdown` after full apply.
- Sharing general with bars@495 requires ≤40 RPM + single worker or wait for bars idle.
