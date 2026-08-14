# W0814 all-sources **FINAL** wave sync (2026-08-14)

**Mass / READY / Phase7:** **NO-GO / OFF**  
**empty COMPLETE:** **0**  
**kill acq jobs:** **none** (natural completion only; residual opt225 one-shot may still live)  
**Forbidden held:** Mass OFF; no empty COMPLETE; no kill acq; Phase7 OFF

**Session PRE (task brief / G10 start):** tip `cac338b`; raw **n=9687** / COMPLETE segs **942**  
**Live verified:** **2026-08-14** (JST) / ~**2026-08-14T02:38Z** UTC

## Scope

| Step | Track | Result |
|------|-------|--------|
| 1 G2 close | `markets_breakdown` w0814_g2_mb | acq residual **48p/72f** + retry **80p/0f**; seal+issue **+36** → COMPLETE **69→105** |
| 2 remote measure | raw n/c + COMPLETE total + per-dataset | raw **10701**/c **9129**; COMPLETE **1376**; empty **0** |
| 3 freshness | `ops_reeval_freshness` | **FRESH** `projgen-f1d9b952…` age≈0 |
| 4 reeval | key datasets ×5 | C8 **pass** all; segs untouched |
| 5 residual SoT | `phase62_residual_status.md` | tip/raw/COMPLETE/FRESH + top datasets live-sync |
| 6 proof | this file + G2 proof | PRE **9687/942** → POST live |

## T1 — PRE → POST global

DB: `quant-ingest` (`platform/workers/ingestion-premium/wrangler.toml`).

| Metric | PRE (brief) | POST (~02:38Z) | Δ |
|--------|------------:|---------------:|--:|
| `raw_retention_manifests` total (`raw_n`) | **9687** | **10701** | **+1014** |
| raw completeness=COMPLETE (`raw_c`) | *(session)* | **9129** | — |
| `coverage_segments` COMPLETE | **942** | **1376** | **+434** |
| empty COMPLETE (`receipt_run_id` null/0) | 0 | **0** | 0 |

**Honesty:** COMPLETE climb is **peer seals + this close G2 +36** already on local/remote inventory — not invented. empty-raw ban held. Worker pass ≠ Coverage COMPLETE.

## T2 — Key dataset COMPLETE table (remote POST)

| dataset | PRE COMPLETE (session ~942 era / prior proof) | POST COMPLETE | Δ | note |
|---------|---------------------------------------------:|--------------:|--:|------|
| `markets_calendar` | 224 | **224** | 0 | dataset COMPLETE |
| `equities_master` | 220 | **220** | 0 | G4 residual 0 seals |
| `indices_bars_daily_topix` | 82 → 220 (G3) | **220** | **+138** vs session start | G3 w0814 |
| `markets_breakdown` | **69** | **105** | **+36** | **G2 w0814_g2_mb** this close |
| `equities_bars_daily` | 42 | **72** | **+30** | G1 w0814 seal |
| `fins_summary` | 42 | **54** | **+12** | G5 |
| `fins_details` | 35 | **47** | **+12** | G5 |
| `fins_dividend` | 14 | **26** | **+12** | G5 |
| `fins_earnings_date` | 14 | **26** | **+12** | G5 |
| `markets_margin_interest` | 17 | **33** | **+16** | G8 misc |
| `markets_margin_alert` | 18 | **34** | **+16** | G8 |
| `markets_short_ratio` | 32 | **48** | **+16** | G8 |
| `markets_short_sale_report` | 3 | **19** | **+16** | G8 |
| `equities_investor_types` | 10 | **26** | **+16** | G8 |
| `derivatives_bars_daily_futures` | 20 | **32** | **+12** | G6 2024 |
| `derivatives_bars_daily_options_225` | 20 | **32** | **+12** | G6 2024 |
| `derivatives_bars_daily_options` | 3 | **5** | **+2** | G6 2026-01/02 |
| `edinet_cross_shareholdings` | 20 | **32** | **+12** | G7 |
| `edinet_major_shareholders` | 20 | **32** | **+12** | G7 |
| `edinet_large_volume_shareholders` | 20 | **32** | **+12** | G7 |
| `indices_bars_daily` | 7 | **33** | **+26** | G3 idx residual |
| `jsda_corporate_bond_transactions` | 1 | **12** | **+11** | G9 dataset COMPLETE |
| `jsda_otc_bond_reference_prices` | 6 | **9** | **+3** | G9 tip |
| `jsda_tokyo_repo_rates` | 1 | **1** | 0 | dataset COMPLETE |

Sum of dataset COMPLETE rows = platform segment COMPLETE **1376** (calendar 224 + all partial-dataset seals).

## T3 — Host POST/min anchors (w0814 multi-track)

| Track | host POST/min | n | pass/fail |
|-------|--------------:|--:|-----------|
| g1 bars | **13.74** | **200** | 124p / 76f |
| g2 mb residual | **14.26** | **120** | 48p / 72f |
| g2 mb retry | **5.07** | **80** | 80p / 0f |
| g3 topix | **34.74** | **142** | 81p / 61f |
| g5 fins paced | **2.0** | **48** | 48p / 0f |
| g7 edinet retry | **4.26** | **36** | 36/36 |

## T4 — reeval + freshness (FINAL)

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
| `generated_at` | **`2026-08-14T02:37:22.769338+00:00`** |
| `age_seconds` | **0** |
| `active_generation` | **`projgen-f1d9b9524bf74bbca1e239b9bc26f230`** |
| publisher | `scripts/ops_reeval_freshness.py` |
| COMPLETE segments | **untouched by freshness reclock** |

## T5 — Peer / G-track close index

| G | proof | headline |
|---|-------|----------|
| G1 | [`w0814_g1_bars_acq_20260814.md`](w0814_g1_bars_acq_20260814.md) | bars COMPLETE **42→72** |
| G2 | [`w0814_g2_breakdown_20260814.md`](w0814_g2_breakdown_20260814.md) | breakdown **69→105 (+36)** |
| G3 | [`w0814_g3_indices_20260814.md`](w0814_g3_indices_20260814.md) | topix **82→220**, idx **7→33** |
| G4 | [`w0814_g4_master_residual_20260814.md`](w0814_g4_master_residual_20260814.md) | master **220→220 (+0)** DEFER |
| G5 | [`w0814_g5_fins_residual_20260814.md`](w0814_g5_fins_residual_20260814.md) | fins **54/47/26/26** |
| G6 | [`w0814_g6_deriv_20260814.md`](w0814_g6_deriv_20260814.md) | futures/o225/options **+26** |
| G7 | [`w0814_g7_edinet_20260814.md`](w0814_g7_edinet_20260814.md) | edinet×3 **+36** |
| G8 | [`w0814_g8_misc_20260814.md`](w0814_g8_misc_20260814.md) | margin family **+80** |
| G9 | [`w0814_g9_jsda_20260814.md`](w0814_g9_jsda_20260814.md) | corp COMPLETE 12; OTC +3 |
| G10 mid | [`w0814_all_sources_wave_20260814.md`](w0814_all_sources_wave_20260814.md) | mid close raw 10662 / COMPLETE 1106 |
| **FINAL** | **this file** | **raw 10701 / COMPLETE 1376** |

## empty COMPLETE / Mass / Phase7 / acq

| Check | Result |
|-------|--------|
| COMPLETE ∧ (`receipt_run_id` IS NULL OR =0) | **0** |
| Mass / READY / B0 | **NO-GO** |
| Phase 7 | **OFF** |
| Live acq killed? | **no** |
| Large new `cf_premium` by FINAL? | **no** (G2 already sealed; measure + reeval only) |

## Residual

`docs/phase62_residual_status.md` live-synced to this POST (COMPLETE **1376** / raw_n **10701** / mb **105** / FRESH `projgen-f1d9b952…`).

## Next (honest)

- breakdown **`2021-04…2023-11`** seal when raw ready  
- bars history after 2010-10 / fins remaining months  
- options residual weeks (paced; do not dual-storm general pool)  
- Mass / READY remains **NO-GO** until inventory policy says otherwise
