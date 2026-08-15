# W24-G5 / w0815q_g5 — T7–T11 coverage tip only (2026-08-15)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (this-wave seals **0**; empty-raw ban held)  
**force-apply:** **not** used (fail-closed guard held; local==remote)  
**prefix:** `w0815q_g5_tip_*`  
**path:** PRE → tip-hole scan → **T7–T9 fins tip skip** (no holes) → **T10 bars tip densify** (week-chunks, w=8, rpm**495**) → **T11 EDINET nz residual scan only** → seal/issue (**0**) → publish → reeval → proof → **push**  
**DEFER densify:** **not** run (fins empty shells 61/120/6, bars pre-2008 **52**, edinet empty, earn history, master misdate, topix empty 4)  
**peers not killed:** `w0815q_g6_ops` ops_loop left running; G1 audit peer left alone

**Live verified:** 2026-08-15 (JST) / ~2026-08-15T01:40Z UTC  
**Wave start HEAD:** `5966aa08ba09c55a321d686040202831d9ca50e0`  
**Proof HEAD (post-push):** `PLACEHOLDER`  
**Projection:** **FRESH** `projgen-432e34acc37e49e3be496d5e379ff8a2`  
**Artifacts:** `.glm-logs/w0815q_g5_tip/` (`dry_*`, `exec_bars_tip_*`, `scan_residual_nz*`, `FINAL_metrics.json`, `pre/`, `post/`, publish + reeval logs)

## Goal

1. **T7–T9** — densify fins tip **only if tip holes** on summary/div/details (not DEFER pre-history shells or earn empty shells).
2. **T10** — bars tip densify only near general **495 RPM** (week-chunks; no pre-2008 residual).
3. **T11** — EDINET residual **nz scan only**; seal only if residual month has COMPLETE∧`row_count>0` raw; never empty densify.
4. Seal → issue any **new** window_ok tip months → fail-closed publish → reeval → proof → **push**.

## DEFER densify skip (honored)

| family | scope | DEFER |
|--------|-------|-------|
| fins empty shells | summary **6** (`2008-01…06`) / dividend **61** / details **120** | D10 + keep empty |
| bars | pre-**2008-05** PARTIAL **52** | D7 |
| EDINET cross/large | empty residual islands (28+42) | D6 |
| earn history | `fins_earnings_date` `2026-01…04` empty shells + earn_calendar tip-only | D4-adjacent / prior |
| master misdate | `2006-08…2008-04` + pre-plan | D2 |
| topix / idx | `2008-01…04` empty **4+4** | D1 |

Dry-only DEFER inventory (`--to-date 2015-03-31 --latest-only`, `--db /nonexistent`) queued **4** jobs (bars+3 fins) — **not executed**.

## PRE (remote D1)

| item | value |
|------|------:|
| Segment COMPLETE total | **3457** |
| Dataset COMPLETE | **11** |
| `raw_retention_manifests` | **15100** |
| local COMPLETE | **3457** (= remote) |
| empty COMPLETE probe | **0** |

PRE SHA: `5966aa08ba09c55a321d686040202831d9ca50e0`  
Artifacts: `.glm-logs/w0815q_g5_tip/pre/remote_global.json`, `pre/remote_tip_months.json`, `pre/tip_partial_scan.json`, `PRE_sha.txt`

### Tip months already COMPLETE (owned)

| dataset | `2026-07` | `2026-08` |
|---------|-----------|-----------|
| `equities_bars_daily` | COMPLETE | COMPLETE |
| `fins_summary` | COMPLETE | COMPLETE |
| `fins_dividend` | COMPLETE | COMPLETE |
| `fins_details` | COMPLETE | COMPLETE |
| `edinet_major_shareholders` | COMPLETE | COMPLETE |
| `edinet_cross_shareholdings` | COMPLETE | COMPLETE |
| `edinet_large_volume_shareholders` | COMPLETE | COMPLETE |

Non-DEFER densifiable tip PARTIAL `>=2026-01` for bars/summary/div/details = **0**.  
Only tip-band PARTIAL in scan: `fins_earnings_date` **`2026-01…04`** (DEFER empty shells — densify **skipped**).

## T7–T9 — fins tip only if tip holes

| check | result |
|-------|--------|
| summary/div/details tip `2026-07`/`2026-08` | **all COMPLETE** |
| tip holes (summary/div/details) | **[]** |
| residual PARTIAL (history DEFER) | div **61** / details **120** / summary **6** |
| earn tip PARTIAL `2026-01…04` | **DEFER** empty shells — **not densified** |
| **decision** | **SKIP** fins tip densify |

Dry inventory only (not executed): fins `--latest-only` plan **3** jobs (summary/div/details `2026-08`) at fins pool rpm**100** w=2.

Artifact: `t7t9_fins_tip_decision.txt`, `dry_fins_tip_*.json`

## T10 — bars tip densify only

```text
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --db /nonexistent \
  --datasets equities_bars_daily \
  --from-date 2026-08-01 \
  --week-chunks --chunk-days 7 \
  --execute --workers 8 --general-rpm 495 --fins-workers 0 --fins-rpm 1 \
  --sleep-on-retry 3.0
```

| field | value |
|------:|
| plan / queued / executed | **2 / 2 / 2** |
| pass / fail | **2 / 0** |
| HTTP 429 | **0** |
| host POST/min | **9.88** (window 6.1s; host dispatch only; n=2) |
| configured general-rpm | **495** (workers **8**) |
| `rowsInserted` sum | **40_001** |

| window | rowsInserted |
|--------|-------------:|
| `2026-08-01…07` | 22227 |
| `2026-08-08…14` | 17774 |

State: `.glm-logs/w0815q_g5_tip/exec_bars_tip_state.jsonl`  
Log: `exec_bars_tip.log`

**NOTE:** worker pass ≠ Coverage COMPLETE. Tip months were already COMPLETE; densify refreshes raw only. Pre-2008 DEFER **52** **not** densified.

## T11 — EDINET residual nz scan only

Driver: `.glm-logs/w0815q_g5_tip/scan_residual_nz.py` (adapted from W19-G5)

| dataset | COMPLETE | residual | nz COMPLETE manifests | sealable residual nz |
|---------|--------:|---------:|----------------------:|---------------------:|
| `edinet_major_shareholders` | **104**/104 | **0** | — | skip (verify only) |
| `edinet_cross_shareholdings` | **76** | **28** (`2018-01…2020-04`) | **114** | **0** |
| `edinet_large_volume_shareholders` | **62** | **42** (`2018-01…2021-06`) | **143** | **0** |

- zero-row residual months sampled: cross **28/28**, large **42/42**  
- residual without nz/zero sample: **[]**  
- **No densify. No seal.** empty-raw ban held.

One-line residual condition (`defer_condition.txt`):

```text
DEFER_EMPTY_API: re-try seal when raw_retention_manifests COMPLETE∧row_count>0 appears for residual months cross=2018-01…2020-04 (n=28) large=2018-01…2021-06 (n=42); do not re-densify all empty months forever; major COMPLETE 104/104 skip; sealable_nz=0 this wave.
```

## Seal / issue

| check | result |
|-------|--------|
| non-DEFER owned tip PARTIAL `>=2026-01` | **0** |
| new window_ok unsealed tip months | **[]** |
| EDINET sealable residual nz | **[]** |
| seal | **0** |
| issue | **0** (nothing to issue; dual-issue peer `w0815q_g6_ops` ops_loop alive anyway) |
| empty-raw ban | held |

## Publish + freshness + observed

```text
publish_ops_projection --apply-remote
  complete_count_guard ok local=3457 remote=3457 force=False
  remote projection applied

ops_reeval_freshness
  OK gen=projgen-432e34acc37e49e3be496d5e379ff8a2
  coverage_segments_untouched=1 mass=NO-GO
```

Observed-window reeval (receipt plane; no segment rewrite) — C8 **pass** all owned:

| dataset | observed_end | C8 |
|---------|--------------|-----|
| `equities_bars_daily` | `2026-08-14` | **pass** lag **1** |
| `fins_summary` | `2026-08-14` | **pass** lag **1** |
| `fins_dividend` | `2026-08-14` | **pass** lag **1** |
| `fins_details` | `2026-08-14` | **pass** lag **1** |
| `edinet_cross_shareholdings` | `2026-08-14` | **pass** lag **1** |
| `edinet_large_volume_shareholders` | `2026-08-14` | **pass** lag **1** |
| `edinet_major_shareholders` | `2026-08-14` | **pass** lag **1** (dataset COMPLETE held) |

Fail-closed: **no** `--force-apply-remote`.

## POST (remote D1)

| Metric | PRE | POST | Δ |
|--------|----:|-----:|--:|
| Segment COMPLETE | **3457** | **3457** | **0** |
| Dataset COMPLETE | **11** | **11** | 0 |
| raw manifests | **15100** | **15102** | **+2** (bars tip densify ≠ COMPLETE) |
| empty COMPLETE (this wave) | **0** | **0** | held |
| G5 owned seal/issue | — | **0** | tip COMPLETE + edinet sealable 0 |
| bars acq | — | **2p/0f** | 0×429 |
| fins tip densify | — | **SKIP** | no tip holes |
| edinet densify | — | **SKIP** | scan only; sealable **0** |

## Residual SoT note

- T7–T9: fins tip holes **0** → densify **skipped** (pool 100 policy held for when holes appear).
- T10: bars tip raw refresh at general **495 RPM / w=8** week-chunks **2p/0f** rows **40001**; pre-2008 DEFER **held**.
- T11: EDINET residual nz scan **sealable=0** → DEFER_EMPTY_API held; major **104/104** verify skip.
- COMPLETE segs held **3457**; Dataset COMPLETE **11**; empty COMPLETE **0**.
- Peer ops loop / G1 audit not killed.

## Summary line

`T7–T9 fins tip SKIP (holes 0) | T10 bars tip 2p/0f @495rpm w8 rows=40001 | T11 edinet nz scan sealable=0 | seal/issue 0 | COMPLETE 3457→3457 | raw 15100→15102 (+2) | Dataset COMPLETE 11 | FRESH projgen-432e34ac… | C8 pass bars/fins/edinet | empty 0 | DEFER densify ban held | push`
