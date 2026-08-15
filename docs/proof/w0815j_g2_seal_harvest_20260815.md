# W18-G2 / w0815j_g2 — seal harvest window_ok unsealed (JQ, no DEFER densify) (2026-08-15)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (this-wave seals **0**; empty-raw ban held)  
**force-apply:** **not** used (fail-closed guard held; local==remote)  
**prefix:** `w0815j_g2_seal_harvest_*`  
**path:** PRE → **scan window_ok PARTIAL unsealed** → data-Date gate → seal/issue/restore (**0**) → tip densify non-DEFER (**0** / skip) → publish → reeval → proof → **push**  
**DEFER densify:** **not** run (policy)  
**options:** skip (already **164/164** COMPLETE)

**Live verified:** 2026-08-15 (JST) / ~2026-08-15T00:19Z UTC  
**Base HEAD (pre-proof):** `2d7dfc15ba354ee52fd429faf60abdfcacc3e3a3`  
**Projection:** **FRESH** (reeval `projgen-215d88a429154d7db9b6e6ebd8798d1d`; meta active `projgen-fd51fc6b29e34c0badf7e56fe880b46e`; remote ACTIVE concurrent peers may rotate)  
**Artifacts:** `.glm-logs/w0815j_g2_seal_harvest/` (`scan_window_ok_fast.py`, `inventory_window_ok.json`, `harvest_verdict.json`, `PRE_remote.json`, `POST_remote.json`, `FINAL_metrics.json`, `publish.log`, `reeval_freshness_retry.log`)

## Goal

1. Scan R2/local for **window_ok** PARTIAL months not COMPLETE across JQ (options already 164 — skip if done).
2. Seal → issue → restore any true harvest candidates.
3. Optional tip densify only for **non-DEFER** tip holes (`general-rpm **400**`, workers **4**).
4. `publish` + proof + **push**.

## DEFER densify skip (honored)

| family | scope | DEFER |
|--------|-------|-------|
| topix / idx | `2008-01…04` | D1 |
| master | misdate `2006-08…2008-04` + pre-plan | D2 |
| breakdown | pre-2015 `2013-01…2015-03` | D3 |
| earn_calendar / bars_am | tip-only history | D4 |
| short_sale | `2013-01…10` empty pre-history | D9 |
| EDINET cross/large | empty residual islands | D6 |
| bars | pre-2008-05 | D7 |
| fins pre-history | empty shells (summary `2008-01…06`, details/div/earn pre-island) | keep empty |

## PRE (remote D1 @ formal harvest snap)

| item | value |
|------|------:|
| Segment COMPLETE total | **3440** |
| Dataset COMPLETE | **11** |
| `raw_retention_manifests` | **15020** |
| `derivatives_bars_daily_options` | **164** COMPLETE (skip) |
| `fins_summary` | **218** |
| `jsda_otc_bond_reference_prices` | **55** (peer tip progress vs W17 **49**) |
| local COMPLETE | **3440** (= remote) |

PRE SHA: `2d7dfc15ba354ee52fd429faf60abdfcacc3e3a3`  
Artifacts: `.glm-logs/w0815j_g2_seal_harvest/PRE_remote.json`, `PRE_sha.txt`, `PRE_partial_segments.json`

### Residual dry plan context (`w0815j_all`)

```text
mode=dry-run plan_jobs=674 queued=674 executed=0
pools general=387 fins=287
by_dataset all DEFER-class residuals only
  topix/idx 4+4, bars pre-floor 21, master 21, earn 199, am 31,
  fins shells 6+120+61+100, short_sale 10, breakdown 27, edinet 28+42
```

**No non-DEFER densify jobs** in planner residual.

## Scan — window_ok PARTIAL unsealed

### Method

1. Cache-first index of `.glm-logs/**/manifests/<dataset>/*.json` (**4626** files → **1791** best params-window_ok segments across PARTIAL JQ datasets).
2. Targeted R2 fetch for PARTIAL months missing cache window_ok (phase2 sample on DEFER families → **0** new true windows).
3. **Data-Date gate** (stricter than params.from/to): reject tip-misdated / misdated payload.

### Params-level window_ok unsealed (before data gate)

| dataset | unsealed | non_defer | defer | note |
|---------|--------:|----------:|------:|------|
| `equities_earnings_calendar` | **199** | 0 | **199** | params month OK; **data Date=tip** |
| `equities_master` | **20** | 0 | **20** | params month OK; **data Date=2008-05-07** |
| all other PARTIAL families | **0** | 0 | 0 | no nz same-month raw for residual months |
| **total** | **219** | **0** | **219** | |

### Data-Date gate samples (reject)

| dataset | segment sample | params window | payload Date | verdict |
|---------|----------------|---------------|--------------|---------|
| `equities_earnings_calendar` | `2017-08` (local raw run7205) | `2017-08-01…31` | **all `2026-08-14`** (196/196) | **REJECT** tip-dated; DEFER D4 |
| `equities_master` | `2006-09` run **11713** page-000001 | `2006-09-01…30` | **all `2008-05-07`** (2494/2494) | **REJECT** misdate; DEFER D2 |
| `equities_master` | local `2006-09` run6958 | same | **all `2008-05-07`** | **REJECT** |

### True seal-harvest candidates

| result | n |
|--------|--:|
| window_ok ∧ nz ∧ in-scope Date ∧ not COMPLETE | **0** |
| issue | **0** |
| restore | **0** |

**options:** already **164/164** COMPLETE — skip.  
**empty-raw ban:** held (no seal of `row_count=0` / tip-misdated payloads as COMPLETE).

Artifacts:
- `.glm-logs/w0815j_g2_seal_harvest/inventory_window_ok.json`
- `.glm-logs/w0815j_g2_seal_harvest/seal_map_all_window_ok.json` (params-level; **not** seal input)
- `.glm-logs/w0815j_g2_seal_harvest/seal_map_non_defer.json` (**[]**)
- `.glm-logs/w0815j_g2_seal_harvest/harvest_verdict.json`
- `.glm-logs/w0815j_g2_seal_harvest/master_sample_page.json`

## Tip densify (optional, non-DEFER only)

| check | result |
|-------|--------|
| PARTIAL segments `>=2024-01` | only **earn** / **am** / **fins_earnings_date `2026-01…04`** (all DEFER / known-empty) |
| planner non-DEFER tip holes | **[]** |
| `cf_premium_backfill` general-rpm **400** w=4 | **not launched** (nothing in scope) |
| DEFER densify | **SKIP** (policy) |

## Publish + freshness

```text
publish_ops_projection --apply-remote
  complete_count_guard ok local=3440 remote=3440 force=False
  remote projection applied

ops_reeval_freshness
  first attempt: D1 long-running import busy (post-publish) → retry
  retry OK gen=projgen-215d88a429154d7db9b6e6ebd8798d1d
  coverage_segments_untouched=1 mass=NO-GO
```

Fail-closed: **no** `--force-apply-remote`.

## POST (remote D1)

| Metric | PRE | POST | Δ |
|--------|----:|-----:|--:|
| Segment COMPLETE | **3440** | **3440** | **0** |
| Dataset COMPLETE | **11** | **11** | 0 |
| raw manifests | **15020** | **15020** | 0 |
| options segs | **164** | **164** | 0 |
| OTC COMPLETE | **55** | **55** | 0 (peer-held vs W17 49) |
| empty COMPLETE (this wave) | **0** | **0** | held |
| G2 owned seal/issue | — | **0** | honest +0 |

## Residual SoT note

All remaining JQ PARTIAL residuals remain **DEFER-class** (D1–D7, D9 + fins pre-history empty shells). No new sealable window_ok island discovered. Peer OTC tip progress (**49→55**) observed outside this G2 lane.

## Summary line

`seal_harvest=0 (params_wok_false_positive earn199+master20 data-Date REJECT) | densify_skip DEFER+no_tip_holes | options 164 skip | COMPLETE 3440→3440 | raw 15020 | Dataset COMPLETE 11 | FRESH reclock | empty 0 | DEFER densify ban held | push`
