# W22-G3 / w0815o_g3 — seal harvest with data-Date gate (2026-08-15)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (this-wave seals **0**; empty-raw ban held)  
**force-apply:** **not** used (fail-closed guard held; local==remote)  
**prefix:** `w0815o_g3_seal_*`  
**path:** PRE → **scan window_ok PARTIAL unsealed** → data-Date gate → seal/issue/restore (**0**) → tip densify non-DEFER (**0** / skip) → publish → reeval → proof → **push**  
**DEFER densify:** **not** run (policy)  
**options:** skip (already **164/164** COMPLETE)

**Live verified:** 2026-08-15 (JST) / ~2026-08-15T00:56Z UTC  
**Wave start HEAD:** `b7d0927c9fc46a6ff4041a1dfe28e5e236a768d3`  
**Base HEAD (pre-proof):** `0a8378b70d4fc22aa5729e3d40af35fd756602b4`  
**Proof HEAD (post-push):** _(filled after push)_  
**Projection:** **FRESH** `projgen-c78dbd3309f147d0b640486e3ac33796`  
**Artifacts:** `.glm-logs/w0815o_g3_seal/` (`scan_window_ok_fast.py`, `data_date_gate.py`, `inventory_window_ok.json`, `harvest_verdict.json`, `PRE_remote.json`, `POST_remote.json`, `FINAL_metrics.json`, `publish.log`, `reeval_freshness.log`, `pages/`)

## Goal

1. Scan R2/local for **window_ok** PARTIAL months not COMPLETE across JQ (options already 164 — skip if done).
2. **REJECT** tip-Date / misdated Date shells (earn tip, master `2008-05-07`).
3. Seal → issue → restore only true in-window harvest candidates (**nz raw** + **params window_ok** + **data Date in segment month**).
4. If **0**: document scan honestly.
5. `publish` + proof + **push**.

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
| fins pre-history | empty shells (summary `2008-01…06`, details/div/earn pre-island + earn tip `2026-01…04`) | keep empty |

## PRE (remote D1 @ harvest snap)

| item | value |
|------|------:|
| Segment COMPLETE total | **3442** |
| Dataset COMPLETE | **11** |
| `raw_retention_manifests` | **15037** |
| `derivatives_bars_daily_options` | **164** COMPLETE (skip) |
| `fins_summary` | **218** |
| `jsda_otc_bond_reference_prices` | **57** (peer tip; D5 archive still DEFER) |
| local COMPLETE | **3442** (= remote) |

PRE SHA (wave start): `b7d0927c9fc46a6ff4041a1dfe28e5e236a768d3`  
Artifacts: `.glm-logs/w0815o_g3_seal/PRE_remote.json`, `PRE_sha.txt`, `PRE_partial_segments.json`

### PARTIAL residual inventory (JQ; non-JSDA)

| dataset | PARTIAL | COMPLETE | note |
|---------|--------:|---------:|------|
| `edinet_cross_shareholdings` | 28 | 76 | D6 empty residual |
| `edinet_large_volume_shareholders` | 42 | 62 | D6 empty residual |
| `equities_bars_daily` | 52 | 220 | D7 pre-2008-05 |
| `equities_bars_daily_am` | 31 | 1 | D4 tip-only |
| `equities_earnings_calendar` | 199 | 1 | D4 tip-dated |
| `equities_master` | 94 | 220 | D2 misdate + pre-plan |
| `fins_details` | 120 | 104 | pre-history empty shells |
| `fins_dividend` | 61 | 163 | pre-history empty shells |
| `fins_earnings_date` | 100 | 100 | pre-history + tip `2026-01…04` |
| `fins_summary` | 6 | 218 | `2008-01…06` empty |
| `indices_bars_daily` | 4 | 220 | D1 `2008-01…04` |
| `indices_bars_daily_topix` | 4 | 220 | D1 `2008-01…04` |
| `markets_breakdown` | 27 | 137 | D3 pre-2015 |
| `markets_short_sale_report` | 10 | 154 | D9 `2013-01…10` |

## Scan — window_ok PARTIAL unsealed

### Method

1. Cache-first index of `.glm-logs/**/manifests/<dataset>/*.json` (**6768** unique run files → **5560** parse_ok nz → **2825** best params-window_ok segments across care datasets).
2. Targeted R2 fetch for PARTIAL months missing cache window_ok (phase2: ~**1013** manifest fetches across 13 datasets with missing wok; **new_wok unsealed keys = 0** for residual PARTIAL months).
3. **Data-Date gate** (stricter than params.from/to): reject tip-misdated / misdated payload.

### Params-level window_ok unsealed (before data gate)

| dataset | unsealed | non_defer | defer | note |
|---------|--------:|----------:|------:|------|
| `equities_earnings_calendar` | **199** | 0 | **199** | params month OK; **data Date=tip** |
| `equities_master` | **20** | 0 | **20** | params month OK; **data Date=2008-05-07** |
| all other PARTIAL families | **0** | 0 | 0 | no nz same-month raw for residual months |
| **total** | **219** | **0** | **219** | |

### PARTIAL months with no params window_ok nz (honest counts)

| dataset | missing wok | sample residual months |
|---------|------------:|------------------------|
| `edinet_cross_shareholdings` | 28 | `2018-01…` |
| `edinet_large_volume_shareholders` | 42 | `2018-01…` |
| `equities_bars_daily` | 52 | `2004-01…` pre-floor |
| `equities_bars_daily_am` | 31 | `2024-01…` tip shells |
| `equities_master` | 74 | pre-plan `2000-07…` (misdate band has params wok, not data wok) |
| `fins_details` | 120 | `2008-01…` empty shells |
| `fins_dividend` | 61 | `2008-01…` empty shells |
| `fins_earnings_date` | 100 | pre-island + tip empty |
| `fins_summary` | 6 | `2008-01…06` |
| `indices_bars_daily` | 4 | `2008-01…04` |
| `indices_bars_daily_topix` | 4 | `2008-01…04` |
| `markets_breakdown` | 27 | `2013-01…2015-03` |
| `markets_short_sale_report` | 10 | `2013-01…10` |

Phase2 note: all residual PARTIAL families returned **new_wok=0** for unsealed residual months (any tip-month window_ok hits already COMPLETE, e.g. `fins_details` `2026-08`).

### Data-Date gate samples (reject)

| dataset | segment sample | params window | payload Date | verdict |
|---------|----------------|---------------|--------------|---------|
| `equities_earnings_calendar` | `2017-08` run **7205** page-000001 | `2017-08-01…31` | **all `2026-08-14`** (196/196) | **REJECT** tip-dated; DEFER D4 |
| `equities_earnings_calendar` | `2026-07` run **7354** page-000001 | `2026-07-01…31` | **all `2026-08-14`** (196/196) | **REJECT** tip-dated; DEFER D4 |
| `equities_master` | `2006-09` run **11713** page-000001 | `2006-09-01…30` | **all `2008-05-07`** (2494/2494) | **REJECT** misdate; DEFER D2 |

### True seal-harvest candidates

| result | n |
|--------|--:|
| window_ok ∧ nz ∧ in-scope Date ∧ not COMPLETE | **0** |
| issue | **0** |
| restore | **0** |

**options:** already **164/164** COMPLETE — skip.  
**empty-raw ban:** held (no seal of `row_count=0` / tip-misdated payloads as COMPLETE).

Artifacts:
- `.glm-logs/w0815o_g3_seal/inventory_window_ok.json`
- `.glm-logs/w0815o_g3_seal/seal_map_all_window_ok.json` (params-level; **not** seal input)
- `.glm-logs/w0815o_g3_seal/seal_map_non_defer.json` (**[]**)
- `.glm-logs/w0815o_g3_seal/harvest_verdict.json`
- `.glm-logs/w0815o_g3_seal/pages/` (data-Date gate samples)

## Tip densify (optional, non-DEFER only)

| check | result |
|-------|--------|
| PARTIAL segments `>=2024-01` | only **earn** (**31**), **am** (**31**), **fins_earnings_date `2026-01…04`** (**4**) — all DEFER / known-empty |
| non-DEFER tip holes | **[]** |
| densify launch | **not launched** (nothing in scope) |
| DEFER densify | **SKIP** (policy) |

## Publish + freshness

```text
publish_ops_projection --apply-remote
  complete_count_guard ok local=3442 remote=3442 force=False
  remote projection applied

ops_reeval_freshness
  OK gen=projgen-c78dbd3309f147d0b640486e3ac33796
  coverage_segments_untouched=1 mass=NO-GO
```

Fail-closed: **no** `--force-apply-remote`.

## POST (remote D1)

| Metric | PRE | POST | Δ |
|--------|----:|-----:|--:|
| Segment COMPLETE | **3442** | **3442** | **0** |
| Dataset COMPLETE | **11** | **11** | 0 |
| raw manifests | **15037** | **15057** | **+20** (peer worker pass ≠ COMPLETE; concurrent W22-G2 tip densify) |
| options segs | **164** | **164** | 0 |
| OTC COMPLETE | **57** | **57** | 0 |
| empty COMPLETE (this wave) | **0** | **0** | held |
| G3 owned seal/issue | — | **0** | honest +0 |

## Residual SoT note

All remaining JQ PARTIAL residuals remain **DEFER-class** (D1–D7, D9 + fins pre-history empty shells). No new sealable window_ok island discovered vs W21-G2 harvest. Peer raw +20 during wave (worker/tip densify pass only). Re-confirm: params-level false positives (earn **199** + master **20**) still fail data-Date gate (tip `2026-08-14` / master shell `2008-05-07`).

## Summary line

`seal_harvest=0 (params_wok_false_positive earn199+master20 data-Date REJECT) | densify_skip DEFER+no_tip_holes | options 164 skip | COMPLETE 3442→3442 | raw 15037→15057 | Dataset COMPLETE 11 | FRESH projgen-c78dbd… | empty 0 | DEFER densify ban held | push`
