# W0814d all-sources wave close (W4-G8 閉路) — 2026-08-14

**Mass / READY / Phase7:** **NO-GO / OFF**  
**empty COMPLETE:** **0**  
**kill acq jobs:** **none** (peers left alive: g1 bars acq / g2 fins paced / g3 deriv options seal+issue / g4 misc R2 seal / residual options weeks)  
**Forbidden held:** Mass OFF; no empty COMPLETE; no kill acq; Phase7 OFF; no large new `cf_premium` by close agent

**Session PRE (task brief):** tip `f9bf2e1`; raw **n=11713** / COMPLETE segs **2034**  
**Live PRE (this agent measure ~06:13Z):** tip `f9bf2e1`; raw **n=11714**/c **10141**; COMPLETE **2034**; empty **0**  
**Live verified POST:** **2026-08-14** (JST) / ~**2026-08-14T06:35Z** UTC

## Scope

| Step | Track | Result |
|------|-------|--------|
| 1 wait / no-kill | peer acq + seals (w0814d G1–G7) | peers **not** killed; g1 bars / g2 fins paced / g3 options / g4 misc seal continued |
| 2 issue_receipts | new raw (empty-raw ban) | margin_interest **+16**; margin_alert **+16**; short_ratio **+3**; options **+4** (G3+close `2025-01…04`); OTC **+1** (peer G7) |
| 3 freshness | `ops_reeval_freshness` | **FRESH** `projgen-05052c4e…` age≈0 (post reeval order) |
| 4 reeval | key datasets ×5 | C8 **pass** all; segs untouched by reclock |
| 5 remote measure | raw n/c + COMPLETE total + per-dataset | raw **11976**/c **10403**; COMPLETE **2074**; empty **0** |
| 6 residual SoT | `phase62_residual_status.md` | tip/raw/COMPLETE/FRESH + top datasets live-sync |
| 7 proof | this file | PRE **11713/2034** → POST **11976/2074** |

## T1 — PRE → POST global

DB: `quant-ingest` (`platform/workers/ingestion-premium/wrangler.toml`).

| Metric | PRE (brief) | POST (~06:35Z) | Δ |
|--------|------------:|---------------:|--:|
| `raw_retention_manifests` total (`raw_n`) | **11713** | **11976** | **+263** |
| raw completeness=COMPLETE (`raw_c`) | **10141** (live PRE) | **10403** | **+262** |
| `coverage_segments` COMPLETE | **2034** | **2074** | **+40** |
| empty COMPLETE (`receipt_run_id` null/0) | 0 | **0** | 0 |
| Repo tip (start) | `f9bf2e1` | *(this close push)* | — |

**Honesty:** COMPLETE climb is **peer seals (G3 options / G4 misc R2 / G7 OTC) + G8 close issue/publish** — not invented. empty-raw ban held (`issued` only when local usable raw + structured; `{"data":[]}` rejected). Worker pass ≠ Coverage COMPLETE. Large new `cf_premium` **not** launched by close agent (peers already running residual acq). Peers may still add raw/seals after this snapshot (g4 seal map **80** still in flight mid-close).

## T2 — Key dataset COMPLETE table (remote POST)

| dataset | PRE COMPLETE (2034 era) | POST COMPLETE | Δ | note |
|---------|------------------------:|--------------:|--:|------|
| `markets_calendar` | 224 | **224** | 0 | dataset COMPLETE |
| `equities_master` | 220 | **220** | 0 | residual pre-2008-05 DEFER |
| `indices_bars_daily` | 220 | **220** | 0 | held (2008-01…04 empty DEFER) |
| `indices_bars_daily_topix` | 220 | **220** | 0 | held |
| `markets_breakdown` | 137 | **137** | 0 | **W4-G5** pre-2015 DEFER held |
| `equities_bars_daily` | **118** | **118** | 0 | prior peer seals held; **W4-G1** acq still running (not killed) |
| `markets_short_ratio` | **80** | **83** | **+3** | G4 seal + G8 issue `2017-01…03` |
| `markets_margin_alert` | **66** | **82** | **+16** | G4 seal + G8 issue `2017-01…2018-04` |
| `markets_margin_interest` | **65** | **81** | **+16** | G4 seal + G8 issue `2017-01…2018-04` (incl. db-lock recover 02/03) |
| `fins_summary` | 78 | **78** | 0 | G2 fins paced cont. |
| `fins_details` | 71 | **71** | 0 | G2 fins paced cont. |
| `equities_investor_types` | 58 | **58** | 0 | G4 seal map pending beyond margin family |
| `derivatives_bars_daily_futures` | 56 | **56** | 0 | held |
| `derivatives_bars_daily_options_225` | 56 | **56** | 0 | held |
| `edinet_*` ×3 | 56 each | **56** each | 0 | held |
| `markets_short_sale_report` | 51 | **51** | 0 | G4 seal map pending |
| `fins_dividend` / `fins_earnings_date` | 50 | **50** | 0 | G2 fins paced cont. |
| `derivatives_bars_daily_options` | **14** | **18** | **+4** | **W4-G3** full-month `2025-01…04` (seal+issue; 05/06 cont.) |
| `jsda_otc_bond_reference_prices` | **17** | **18** | **+1** | **W4-G7** peer `2026-07-21` |
| `jsda_corporate_bond_transactions` | 12 | **12** | 0 | dataset COMPLETE |
| `equities_bars_daily_am` | 1 | **1** | 0 | tip-Date DEFER held |
| `equities_earnings_calendar` | 1 | **1** | 0 | tip-Date DEFER held |
| `jsda_tokyo_repo_rates` | 1 | **1** | 0 | dataset COMPLETE |

Sum of dataset COMPLETE rows = platform segment COMPLETE **2074**.

## T3 — Host / acq anchors (w0814d peers; natural exit only)

| Track | n / state | note |
|-------|-----------|------|
| g1 bars | max-jobs 200 in flight (`w0814d_g1_bars`) | **not** killed |
| g2 fins residual paced | serial paced residual | fins pool; **not** killed |
| g3 deriv options | full-month `2025-01…04` issued; `2025-05/06` seal cont. | **not** killed |
| g4 misc R2 seal | map **80**; margin family wave sealed+issued; alert/short mid | seal continues after G8 |
| g5 mb | residual pre-2015 probe **DEFER** (+0) | peer proof |
| g6 edinet | acq pipeline in flight | **not** killed |
| g7 JSDA | OTC **+1** → **18** | peer proof already |

## T4 — reeval + freshness (POST publish order)

Order: fail-closed `publish_ops_projection --apply-remote` (local **2074** ≥ remote **2067**) → `ops_reeval_observed_window` ×5 → `ops_reeval_freshness` (reclock after final publish).

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
| `generated_at` | **`2026-08-14T06:34:54.077494+00:00`** |
| `age_seconds` | **~0** at reclock |
| `active_generation` | **`projgen-05052c4e2af048d0a767615acab33ec8`** |
| publisher | `scripts/ops_reeval_freshness.py` |
| COMPLETE segments | **untouched by freshness reclock** |

## T5 — Issue path (empty-raw ban)

```text
# G8 close — only segments with local usable raw + structured
issue_receipts_parallel.py --datasets <ds> --segment-id <ym> --no-refresh
restore_local_complete_from_receipt.py --dataset … --segment-id …
publish_ops_projection.py --apply-remote   # fail-closed local>=remote
```

| dataset | months issued this close (G8 + concurrent peers in receipt plane ≥902424) | Δ COMPLETE (vs 2034-era) |
|---------|--------------------------------------------------------------------------|-------------------------:|
| `markets_margin_interest` | `2017-01…2018-04` (runs **902426–902441** band) | **+16** |
| `markets_margin_alert` | `2017-01…2018-04` (runs **902442+**) | **+16** |
| `markets_short_ratio` | `2017-01…03` | **+3** |
| `derivatives_bars_daily_options` | `2025-01…04` (G3 seal+issue; runs **902425/902443/…**) | **+4** |
| `jsda_otc_bond_reference_prices` | peer G7 `2026-07-21` (run **902424**) | **+1** |

Artifacts: `.glm-logs/w0814d/issue/`, `.glm-logs/w0814d/post/`, `.glm-logs/w0814d/publish1.log`, peer dirs `.glm-logs/w0814d_g*/`.

## empty COMPLETE / Mass / Phase7 / acq

| Check | Result |
|-------|--------|
| COMPLETE ∧ (`receipt_run_id` IS NULL OR =0) | **0** |
| Mass / READY / B0 | **NO-GO** |
| Phase 7 | **OFF** |
| Live acq killed? | **no** |
| Large new `cf_premium` by G8 close? | **no** (peers only) |

## Residual

`docs/phase62_residual_status.md` live-synced to this POST (COMPLETE **2074** / raw_n **11976** / FRESH `projgen-05052c4e…`).

## Top gaps remaining (honest)

- `equities_bars_daily` history densify while **W4-G1** acq runs (COMPLETE **118** held)  
- `markets_breakdown` pre-**2015-03** empty shells **DEFER** (W4-G5)  
- G4 misc remainder: short_ratio / short_sale / investor beyond issued months (seal map **80** in flight)  
- options **2025-05…06** + full **2025** continuity (paced; do not dual-storm)  
- futures/o225 pre-**2022** **DEFER**  
- `fins_*` residual months (G2 paced still running)  
- edinet pre-**2022** deep history  
- master pre-2008-05 misdated R2 pages **DEFER**  
- earn calendar / bars_daily_am history **DEFER** (tip-Date / today-mode)  
- OTC archive history **DEFER** (site timeout); tip/recent **18** held  
- Mass / READY remains **NO-GO**

## Next

- Peers may continue seal/acq; do not kill  
- After further seals: issue → publish → reeval×key → freshness  
- Mass / READY / Phase7 stay **NO-GO / OFF**
