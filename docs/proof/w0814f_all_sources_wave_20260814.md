# W0814f all-sources wave close (W6-G7 閉路) — 2026-08-14

**Mass / READY / Phase7:** **NO-GO / OFF**  
**empty COMPLETE:** **0**  
**kill acq jobs:** **none** (peers left alive: g1 bars acq+seal / g2 fins paced done natural / g3 deriv options paced / g4 misc R2 seal cont. / g5 edinet seal / g6 JSDA already published)  
**Forbidden held:** Mass OFF; no empty COMPLETE; no kill acq; Phase7 OFF; no large new `cf_premium` by close agent

**Session PRE (task brief):** tip `1f4320d`; raw **n=12481** / COMPLETE segs **2446**  
**Live PRE (this agent measure):** tip `1f4320d`; raw **n=12481**/c **10906**; COMPLETE **2446**; empty **0**  
**Live verified POST:** **2026-08-14** (JST) / ~**2026-08-14T11:20Z** UTC

## Scope

| Step | Track | Result |
|------|-------|--------|
| 1 wait / no-kill | peer acq + seals (w0814f G1–G6) | peers **not** killed; g1 bars / g3 options / g4 misc seal / g5 edinet continued; g2 fins natural DONE 47/47; g6 OTC published pre-close |
| 2 issue_receipts | new raw (empty-raw ban) | margin_interest **+16**; margin_alert **+16**; short_ratio **+3**; bars **+7**; edinet_major **+5**; OTC **+6** (peer G6) |
| 3 freshness | `ops_reeval_freshness` | **FRESH** `projgen-83bd002e…` age≈0 (post reeval order) |
| 4 reeval | key datasets ×5 | C8 **pass** all; segs untouched by reclock |
| 5 remote measure | raw n/c + COMPLETE total + per-dataset | raw **12791**/c **11216**; COMPLETE **2499**; empty **0** |
| 6 residual SoT | `phase62_residual_status.md` | tip/raw/COMPLETE/FRESH + top datasets live-sync |
| 7 proof | this file | PRE **12481/2446** → POST **12791/2499** |

## T1 — PRE → POST global

DB: `quant-ingest` (`platform/workers/ingestion-premium/wrangler.toml`).

| Metric | PRE (brief) | POST (~11:20Z) | Δ |
|--------|------------:|---------------:|--:|
| `raw_retention_manifests` total (`raw_n`) | **12481** | **12791** | **+310** |
| raw completeness=COMPLETE (`raw_c`) | **10906** (live PRE) | **11216** | **+310** |
| `coverage_segments` COMPLETE | **2446** | **2499** | **+53** |
| empty COMPLETE (`receipt_run_id` null/0) | 0 | **0** | 0 |
| Repo tip (start) | `1f4320d` | *(this close push)* | — |

**Honesty:** COMPLETE climb is **peer G6 OTC seal +6** + **G7 close issue/publish of G4/G1/G5 ready months (+47)** — not invented. empty-raw ban held (`issued` only when local usable raw + structured; no invent). Worker pass ≠ Coverage COMPLETE. Large new `cf_premium` **not** launched by close agent (peers already running residual acq). Peers may still add raw/seals after this snapshot (g4 seal map **80** mid-wave ~39 ready; g1 bars acq ~181/200; g3 options weeks; g5 edinet seal cont.).

## T2 — Key dataset COMPLETE table (remote POST)

| dataset | PRE COMPLETE (2446 era) | POST COMPLETE | Δ | note |
|---------|------------------------:|--------------:|--:|------|
| `markets_calendar` | 224 | **224** | 0 | dataset COMPLETE |
| `equities_master` | 220 | **220** | 0 | residual pre-2008-05 DEFER |
| `indices_bars_daily` | 220 | **220** | 0 | held |
| `indices_bars_daily_topix` | 220 | **220** | 0 | held |
| `equities_bars_daily` | **163** | **170** | **+7** | G1 seal+G7 issue `2020-12…2021-06` |
| `markets_breakdown` | 137 | **137** | 0 | pre-2015 DEFER held |
| `markets_short_ratio` | **112** | **115** | **+3** | G4 seal + G7 issue `2019-09…11` |
| `markets_margin_alert` | **98** | **114** | **+16** | G4 seal + G7 issue `2019-09…2020-12` |
| `markets_margin_interest` | **97** | **113** | **+16** | G4 seal + G7 issue `2019-09…2020-12` |
| `fins_summary` | 102 | **102** | 0 | G2 fins paced DONE (seals may follow) |
| `fins_details` | 93 | **93** | 0 | G2 fins paced DONE |
| `equities_investor_types` | 90 | **90** | 0 | G4 seal map pending beyond margin family |
| `edinet_major_shareholders` | **80** | **85** | **+5** | G5 seal + G7 issue `2019-01…05` |
| `markets_short_sale_report` | 83 | **83** | 0 | G4 seal map pending |
| `derivatives_bars_daily_futures` | 80 | **80** | 0 | held |
| `derivatives_bars_daily_options_225` | 80 | **80** | 0 | held |
| `edinet_cross_shareholdings` | 76 | **76** | 0 | G5 seal cont. |
| `fins_dividend` / `fins_earnings_date` | 74 | **74** | 0 | G2 fins paced DONE |
| `edinet_large_volume_shareholders` | 62 | **62** | 0 | G5 seal cont. |
| `derivatives_bars_daily_options` | 26 | **26** | 0 | G3 options weeks acq cont. |
| `jsda_otc_bond_reference_prices` | **20** | **26** | **+6** | **W6-G6** peer `2026-07-08…15` |
| `jsda_corporate_bond_transactions` | 12 | **12** | 0 | dataset COMPLETE |
| `equities_bars_daily_am` | 1 | **1** | 0 | tip-Date DEFER held |
| `equities_earnings_calendar` | 1 | **1** | 0 | tip-Date DEFER held |
| `jsda_tokyo_repo_rates` | 1 | **1** | 0 | dataset COMPLETE |

Sum of dataset COMPLETE rows = platform segment COMPLETE **2499**.

## T3 — Host / acq anchors (w0814f peers; natural exit only)

| Track | n / state | note |
|-------|-----------|------|
| g1 bars | max-jobs 200 in flight (`w0814f_g1_bars`); state ~**181**/200 mid-close; seal weeks → **+7** issued | **not** killed |
| g2 fins residual paced | serial paced **47/47** pass natural DONE | fins pool; natural exit; seals may continue |
| g3 deriv options | week-chunks 2024-01+ paced rpm45 (~8 events mid-close) | **not** killed |
| g4 misc R2 seal | map **80**; margin family sealing mid-wave; G7 issued **35** margin-family months from ready set | seal continues after G7 |
| g5 edinet | 2019 residual seal in flight; G7 issued **+5** major ready | **not** killed |
| g6 JSDA | OTC **+6** → **26** (published pre-close; proof `w0814f_g6_jsda`) | peer proof already |

## T4 — reeval + freshness (POST publish order)

Order: fail-closed `publish_ops_projection --apply-remote` (local **2499** ≥ remote **2452**) → `ops_reeval_observed_window` ×5 → `ops_reeval_freshness` (reclock after final publish).

### `ops_reeval_observed_window` (×5)

No segment rewrite / no COMPLETE claim. `--today 2026-08-14 --freshness-days 7`.

| dataset | status | observed_start | observed_end | C8 |
|---------|--------|----------------|--------------|----|
| `equities_bars_daily` | **PARTIAL** | **`2008-05-01`** | **`2026-08-13`** | **pass** lag **1** |
| `equities_master` | **PARTIAL** | **`2006-08-13`** | **`2026-08-13`** | **pass** lag **1** |
| `indices_bars_daily_topix` | **PARTIAL** | **`2008-01-01`** | **`2026-08-14`** | **pass** lag **0** |
| `markets_breakdown` | **PARTIAL** | **`2015-03-26`** | **`2026-08-13`** | **pass** lag **1** |
| `markets_margin_interest` | **PARTIAL** | **`2013-01-04`** | **`2026-08-13`** | **pass** lag **2** (**held**) |

### `ops_reeval_freshness` → FRESH age≈0

| Field | POST |
|-------|------|
| status | **FRESH** |
| `generated_at` | **`2026-08-14T11:20:07.474563+00:00`** |
| `age_seconds` | **~0** at reclock |
| `active_generation` | **`projgen-83bd002e526c4bb8987184e207a12cb4`** |
| publisher | `scripts/ops_reeval_freshness.py` |
| COMPLETE segments | **untouched by freshness reclock** |

## T5 — Issue path (empty-raw ban)

```text
# G7 close — only segments with local usable raw + structured (G4/G1/G5 seal ready)
issue_receipts_parallel.py --dataset <ds> --segment-id <ym> --no-refresh
restore_local_complete_from_receipt.py --dataset … --segment-id …
publish_ops_projection.py --apply-remote   # fail-closed local>=remote
```

| dataset | months issued this close (G7 + peer G6 OTC) | Δ COMPLETE (vs 2446-era) |
|---------|---------------------------------------------|-------------------------:|
| `markets_margin_interest` | `2019-09…2020-12` | **+16** |
| `markets_margin_alert` | `2019-09…2020-12` | **+16** |
| `markets_short_ratio` | `2019-09…11` | **+3** |
| `equities_bars_daily` | `2020-12…2021-06` | **+7** |
| `edinet_major_shareholders` | `2019-01…05` | **+5** |
| `jsda_otc_bond_reference_prices` | peer G6 `2026-07-08…15` (runs **902837–902842**) | **+6** |

Artifacts: `.glm-logs/w0814f/issue/`, `.glm-logs/w0814f/post/`, peer dirs `.glm-logs/w0814f*/`.

## empty COMPLETE / Mass / Phase7 / acq

| Check | Result |
|-------|--------|
| COMPLETE ∧ (`receipt_run_id` IS NULL OR =0) | **0** |
| Mass / READY / B0 | **NO-GO** |
| Phase 7 | **OFF** |
| Live acq killed? | **no** |
| Large new `cf_premium` by G7 close? | **no** (peers only) |

## Residual

`docs/phase62_residual_status.md` live-synced to this POST (COMPLETE **2499** / raw_n **12791** / FRESH `projgen-83bd002e…`).

## Top gaps remaining (honest)

- `equities_bars_daily` history densify while **W6-G1** acq runs (COMPLETE **170**; further seals pending)  
- `markets_breakdown` pre-**2015-03** empty shells **DEFER**  
- G4 misc remainder: short_sale / investor / further margin months (seal map **80** in flight)  
- options **2024** continuity (g3 paced; do not dual-storm)  
- futures/o225 pre-**2020** residual **DEFER** band  
- `fins_*` residual seal after G2 paced DONE 47/47  
- edinet pre-**2020** deep history (G5 cont.; major **+5** only this close)  
- master pre-2008-05 misdated R2 pages **DEFER**  
- earn calendar / bars_daily_am history **DEFER** (tip-Date / today-mode)  
- OTC archive history **DEFER** (site timeout after tip/recent **26** held)  
- Mass / READY remains **NO-GO**

## Next

- Peers may continue seal/acq; do not kill  
- After further seals: issue → publish → reeval×key → freshness  
- Mass / READY / Phase7 stay **NO-GO / OFF**
