# W0814b all-sources wave close (W2-G9 閉路) — 2026-08-14

**Mass / READY / Phase7:** **NO-GO / OFF**  
**empty COMPLETE:** **0**  
**kill acq jobs:** **none** (peers left alive: mb/idx/edinet/misc seals + deriv paced + residual acq)  
**Forbidden held:** Mass OFF; no empty COMPLETE; no kill acq; Phase7 OFF; no large new `cf_premium` by close agent

**Session PRE (task brief):** tip `be7ad33`; raw **n=10702** / COMPLETE segs **1376**  
**Live verified:** **2026-08-14** (JST) / ~**2026-08-14T03:29Z** UTC

## Scope

| Step | Track | Result |
|------|-------|--------|
| 1 wait / no-kill | peer acq + seals (G1–G8 w0814b) | peers **not** killed; wait ~20–40m while seals/acq ran |
| 2 issue_receipts | new raw (empty-raw ban) | margin_interest **+16**; alert **+13**; short_ratio **+16**; mb **+11** (partial); options **+1** (Mar via G5); peer seals + publish |
| 3 freshness | `ops_reeval_freshness` | **FRESH** `projgen-16cfbaa5…` age≈0 (post reeval order) |
| 4 reeval | key datasets ×5 | C8 **pass** all; segs untouched |
| 5 remote measure | raw n/c + COMPLETE total + per-dataset | raw **11242**/c **9670**; COMPLETE **1478**; empty **0** |
| 6 residual SoT | `phase62_residual_status.md` | tip/raw/COMPLETE/FRESH + top datasets live-sync |
| 7 proof | this file | PRE **10702/1376** → POST **11242/1478** |

## T1 — PRE → POST global

DB: `quant-ingest` (`platform/workers/ingestion-premium/wrangler.toml`).

| Metric | PRE (brief) | POST (~03:29Z) | Δ |
|--------|------------:|---------------:|--:|
| `raw_retention_manifests` total (`raw_n`) | **10702** | **11242** | **+540** |
| raw completeness=COMPLETE (`raw_c`) | *(session ~9129)* | **9670** | **~+541** |
| `coverage_segments` COMPLETE | **1376** | **1478** | **+102** |
| empty COMPLETE (`receipt_run_id` null/0) | 0 | **0** | 0 |
| Repo tip (start) | `be7ad33` | *(this close push)* | — |

**Honesty:** COMPLETE climb is **peer seals + G9 close issue/publish** — not invented. empty-raw ban held. Worker pass ≠ Coverage COMPLETE. Large new `cf_premium` **not** launched by close agent (peers already running residual acq).

## T2 — Key dataset COMPLETE table (remote POST)

| dataset | PRE COMPLETE (1376 era) | POST COMPLETE | Δ | note |
|---------|------------------------:|--------------:|--:|------|
| `markets_calendar` | 224 | **224** | 0 | dataset COMPLETE |
| `equities_master` | 220 | **220** | 0 | residual pre-2008-05 DEFER |
| `indices_bars_daily_topix` | 220 | **220** | 0 | held |
| `markets_breakdown` | **105** | **116** | **+11** | w0814b G2 seal+issue `2021-04…2022-04` (partial fail 2022-05…08) |
| `equities_bars_daily` | 72 | **72** | 0 | G1 acq 199p/1f; seal wave deferred |
| `markets_short_ratio` | 48 | **64** | **+16** | G7 seal + G9 issue `2014-05…2015-06` |
| `indices_bars_daily` | 33 | **61** | **+28** | G3 idx seal/issue wave |
| `fins_summary` | 54 | **54** | 0 | held |
| `markets_margin_interest` | 33 | **49** | **+16** | G7 seal + G9 issue `2014-05…2015-08` |
| `fins_details` | 47 | **47** | 0 | held |
| `markets_margin_alert` | 34 | **47** | **+13** | G7 seal + G9 issue (2014-05…2015-08 band) |
| `derivatives_bars_daily_futures` | 32 | **44** | **+12** | peer residual (pre-2024 partial) |
| `derivatives_bars_daily_options_225` | 32 | **32** | 0 | held |
| `edinet_*` ×3 | 32 each | **32** each | 0 | G6 edinet acq 36/36 pass; seal in flight |
| `equities_investor_types` | 26 | **26** | 0 | held |
| `fins_dividend` / `fins_earnings_date` | 26 | **26** | 0 | held |
| `markets_short_sale_report` | 19 | **20** | **+1** | peer |
| `jsda_corporate_bond_transactions` | 12 | **12** | 0 | dataset COMPLETE |
| `jsda_otc_bond_reference_prices` | 9 | **11** | **+2** | **W2-G8 JSDA** tip/recent |
| `derivatives_bars_daily_options` | 5 | **8** | **+3** | G5 Mar + peer weeks (Jan/Feb already; +Mar/…) |
| `jsda_tokyo_repo_rates` | 1 | **1** | 0 | dataset COMPLETE |

Sum of dataset COMPLETE rows = platform segment COMPLETE **1478**.

## T3 — Host / acq anchors (w0814b peers; natural exit only)

| Track | n | pass/fail | note |
|-------|--:|-----------|------|
| g1 bars | **200** | **199p / 1f** | max-jobs 200; not killed |
| g2 mb residual | **100** | **100p / 0f** | week-chunks residual |
| g3 idx exec | **100** | **100p / 0f** | indices residual |
| g6 edinet | **36** | **36p / 0f** | 2023 residual |
| g5 options paced | ongoing | Mar sealed+published; Apr seal in flight | dual-storm avoided |
| g7 misc seal | R2 | margin/alert/short_ratio ready months | issue by G9 close |
| g8 JSDA | OTC | **+2** → COMPLETE **11** | peer proof residual tip |

## T4 — reeval + freshness (POST publish order)

Order: fail-closed `publish_ops_projection --apply-remote` → `ops_reeval_observed_window` ×5 → `ops_reeval_freshness`.

### `ops_reeval_observed_window` (×5)

No segment rewrite / no COMPLETE claim. `--today 2026-08-14 --freshness-days 7`.

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
| `generated_at` | **`2026-08-14T03:28:34.989621+00:00`** |
| `age_seconds` | **~0** at reclock |
| `active_generation` | **`projgen-16cfbaa5dfb643c9867b5aaa3b4f905a`** |
| publisher | `scripts/ops_reeval_freshness.py` |
| COMPLETE segments | **untouched by freshness reclock** |

## T5 — Issue path (empty-raw ban)

```text
# G9 close — only segments with local usable raw + structured
issue_receipts_parallel.py --segment-id <ym> --no-refresh
restore_local_complete_from_receipt.py --dataset … --segment-id …
publish_ops_projection.py --apply-remote   # fail-closed local>=remote
```

| dataset | months issued this close | Δ COMPLETE |
|---------|--------------------------|-----------:|
| `markets_margin_interest` | 2014-05…2015-08 | **+16** |
| `markets_margin_alert` | 2014-05…2015-08 band (13 ready) | **+13** |
| `markets_short_ratio` | 2014-05…2015-06 | **+16** |
| `markets_breakdown` | 2021-04…2022-04 (subset; 2022-05…08 fail issued=0) | **+11** |
| `derivatives_bars_daily_options` | 2026-03 (G5 peer) + prior | **+3** vs 5 |

Artifacts: `.glm-logs/w0814b/issue_margin/`, `.glm-logs/w0814b/issue_misc/`, `.glm-logs/w0814b/POST_metrics.json`.

## empty COMPLETE / Mass / Phase7 / acq

| Check | Result |
|-------|--------|
| COMPLETE ∧ (`receipt_run_id` IS NULL OR =0) | **0** |
| Mass / READY / B0 | **NO-GO** |
| Phase 7 | **OFF** |
| Live acq killed? | **no** |
| Large new `cf_premium` by G9 close? | **no** (peers only) |

## Residual

`docs/phase62_residual_status.md` live-synced to this POST (COMPLETE **1478** / raw_n **11242** / FRESH `projgen-16cfbaa5…`).

## Top gaps remaining (honest)

- `markets_breakdown` **`2022-05…2023-11`** seal/issue when usable raw ready  
- `equities_bars_daily` history after **2010-10**  
- options **2026-04…05** + **2025** full months (paced; do not dual-storm)  
- master pre-2008-05 misdated R2 pages **DEFER**  
- fins residual months / edinet pre-2024 deep history  
- OTC archive history **DEFER** (site timeout)  
- Mass / READY remains **NO-GO**

## Next

- Peers may continue seal/acq; do not kill  
- After further seals: issue → publish → reeval×key → freshness  
- Mass / READY / Phase7 stay **NO-GO / OFF**
