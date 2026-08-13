# Phase 6.2 / 6.3 residual status

**Live residual SoT** (agents: prefer this file over any `phase62*_status` / final_report).  
**Live verified:** 2026-08-14 (JST) / ~2026-08-13T23:20Z UTC (remote D1; COMPLETE segs **729**; raw_n **9387**; G10 stagnant-4 seals + peers; FRESH age=0; empty COMPLETE **0**; Phase7 **OFF**)  
**Repo tip:** `100be1c` (pre-push; set to push SHA after G10 land) — COMPLETE **729** / raw_n **9387** / stagnant-4 Δ / Phase7 **OFF**

## Live snapshot (remote D1 `quant-ingest`)

| Item | Value |
|------|--------|
| Dataset COMPLETE | **2** — `markets_calendar` (224/224 segs), `jsda_tokyo_repo_rates` (1/1) |
| Dataset STALE | **0** (margin PARTIAL via receipt reeval; not STALE) |
| Segment COMPLETE total | **729** (remote; G10 publish local=729; G9 **677** + stagnant-4 + peer master/topix inventory; **no** empty COMPLETE) |
| Segment other | PARTIAL / UNKNOWN (remainder; not mass-READY) |
| calendar segments | **224 COMPLETE / 0 PARTIAL** |
| JSDA OTC COMPLETE segs | **6** — `2026-08-06`…`13` + **`2026-08-14`** (dataset still PARTIAL; G8 T11 **+1** via CF R2 XLS; further days **DEFER** site timeout / R2 MISS) |
| JSDA corporate COMPLETE segs | **1** — year `2026` only (prior years **DEFER** — no raw) |
| A3 sealed (partial datasets) | prior + G9 T13 + **G10 stagnant-4** (bars **+1** / master **+** / topix **+** / breakdown **+1** incl peer inventory) → COMPLETE **729** |
| Remote `raw_retention_manifests` | **9387** total (session PRE **7917** → POST **9387**; worker pass ≠ COMPLETE) |
| Track A + P0 execute | **w0713 multi-track live** (t1 bars / t2 master / t3 topix / t4 mb / t6 deriv / t7 margin) + G10 wave close — peers not killed; **Worker pass ≠ COMPLETE** |
| master | `scd2_event_sourcing` / D1 hot |
| projection | **FRESH** — `projgen-7b6c973445c74bd384ac7c960b622259` age=0 (G10 T17 `ops_reeval_freshness`; segs untouched by reclock) |
| sticky COMPLETE | **fixed** segment_id fallback + post-sticky dataset aggregate + COMPLETE inventory retain past UTC target_end (`coverage_ledger.py`) |
| Full publish guard | `scripts/publish_ops_projection.py` fail-closed |
| Targeted freshness | `scripts/ops_reeval_freshness.py` (no segment rewrite) |
| Observed window re-eval | `scripts/ops_reeval_observed_window.py` (SUCCESS receipts `raw_row_count>0`; no segment rewrite / no COMPLETE claim) |
| Layout migration | **DONE** — libraries under `packages/{edge,data_plane,research_runtime,product}`; import leaf names unchanged |
| Track A (historical raw accel) | **EXECUTE DONE** — PRE raw **1488** → … → T13–T15 **7430** → T9/G5 peers → T5 fins → t5_div_pre → live raw **7825** |
| Track B1 (LLM-friendly) | **landed** + residual/docs SoT live-sync; B1-e partial (ops/coverage/receipt CLIs); Batch Z still **DEFER** |
| Mass / READY / B0 | **NO-GO** |
| Phase 7 | **OFF / foundation only** — **must remain OFF**; no mass arming, no production READY, no Phase7 switch ON |

### Host POST/min (multi-track session, state jsonl + run log)

| Track | host POST/min | n | note |
|-------|--------------:|--:|------|
| MB solo | **10.97** | 409 | general pool |
| bars solo | **6.22** | 280 | general; 0×429; pass 264 / fail 16 |
| fins paced | **1.09–1.16** | 102 | fins pool; runner `host_jobs_per_min=1.09` |
| t5 fins family (G4 snap) | **1.34–1.37** | **76/288** | historical partial snap (superseded by FINAL) |
| t5 fins family (**FINAL**) | **1.68** | **288** | serial paced **DONE**; runner **287/1** + 2022-05 recover → unique **288**; PID dead; flag DONE |
| t5_div_pre (`fins_dividend` 2008–2017) | **4.69** | **120** | **120 pass / 0 fail**; PID **43684** natural exit; empty shells 2008-01…2013-01; nz **59** months |
| topix3 w1 / w2 | **93.48** / **62.79** | 192 / 192 | residual months (fast burst); orch re-dispatch after bars |
| t4 topix | **142.41** | 192 | all pass; burst |
| t7 master | **3.58** | 147 | 118p/29f → retry 29/29 |
| t8 misc | **9.93** | 432 | 407p/25f → retry 25/25 |
| t5 margin+earn | **7.51** | 346 | 344p/2f → retry 2/2 (2017-01/02); w=2 rpm=495 |
| merged mb+bars+topix3+fins | **12.56** | 1175 | G8 wave2 re-measure |
| merged + peers t4/t7/t8 | **17.63** | 1896 | concurrent acq included |
| w0713 t7 margin_inv (live) | **12.21** | 750+ | G10 T16; pass dominant / ~45 fail residual (peer-owned) |
| w0713 t1 bars exec / retry | **7.16** / **7.50** | 120 / 22 | G10 T16 |
| w0713 t3 topix | **54.28** | 192 | all pass |
| w0713 t2 master | **4.97** | 147 | 63p/84f (peer retry path) |
| proof | — | — | [`docs/proof/w0713_wave_close_20260814.md`](proof/w0713_wave_close_20260814.md) (G10 T15–T17) |

### observed_* (remote D1, key datasets)

| dataset | status | COMPLETE segs | observed_start | observed_end | raw manifests (COMPLETE) | notes |
|---------|--------|--------------:|----------------|--------------|--------------------------:|-------|
| `equities_bars_daily` | **PARTIAL** | **13** | **`2008-05-01`** | **`2026-08-13`** | — | **G10** COMPLETE **+1** (`2010-06` run **900772**); C8 **pass** lag **1**; worker pass ≠ COMPLETE |
| `indices_bars_daily_topix` | **PARTIAL** | **82** | **`2008-01-01`** | **`2026-08-14`** | — | **G10** + peers → **82** (PRE **32**); seals incl **2023-11/12** runs **900765/900758**; C8 lag **0** |
| `equities_master` | **PARTIAL** | **132** | **`2006-08-13`** | **`2026-08-13`** | — | **G10** + peers → **132** (PRE **94**); incl **2018-11** run **900771**; C8 lag **1**; scd2 hot |
| `markets_breakdown` | **PARTIAL** | **33** | **`2015-03-26`** | **`2026-08-13`** | — | **G10** COMPLETE **+1** (`2023-12` run **900768**); C8 **pass** lag **1** |
| `fins_summary` | **PARTIAL** | **30** | **`2008-07-01`** | **`2026-08-13`** | — | **T5 FINAL** 72/72 worker + reeval; T12 seals **+25** (2008-07…2010-07) → COMPLETE segs **30**; empty shells 2008-01…06; C8 **pass** lag **1**; dataset **not** COMPLETE |
| `markets_margin_interest` | **PARTIAL** | **17** | **`2013-01-04`** | **`2026-08-13`** | n=225 / c=224 | **G5** history 147/147; T13–T15 reeval; **C8 pass** lag **2**≤7; COMPLETE still 17; dataset **not** COMPLETE |
| `equities_earnings_calendar` | **PARTIAL** | **1** | **`2010-01-04`** | **`2026-08-13`** | — | **G5** 199/199 worker pass (2010-01…2026-07); C8 pass lag **0**; COMPLETE only **2026-08** |
| `markets_short_ratio` | **PARTIAL** | 32 | **`2013-01-04`** | **`2026-08-12`** | n≈199 | T8 + retry; observed_start moved from 2024; C8 lag **1** |
| `markets_margin_alert` | **PARTIAL** | 18 | **`2013-01-04`** | **`2026-08-12`** | n≈237 | T8 + retry; observed_start moved from 2025-03; C8 lag **1** |
| `markets_calendar` | **COMPLETE** | 224 | 2008-01-01 | 2026-08-12 | — | sticky full + aggregate fix |
| `jsda_tokyo_repo_rates` | **COMPLETE** | 1 | 2012-10-29 | 2026-08-10 | — | dataset COMPLETE |
| `fins_details` | **PARTIAL** | **34** | **`2018-01-01`** | **`2026-08-13`** | — | T12 **+20** (2018-01…2019-08) + **G9 T13 +11** (2019-09…12, 2020-02…08) → COMPLETE segs **34**; C8 **pass** lag **1**; dataset **not** COMPLETE |
| `equities_investor_types` | **PARTIAL** | **10** | **`2013-01-04`** | **`2026-08-12`** | n≈208 | T8 154/154 pass; C8 lag **2** |
| `edinet_cross_shareholdings` | PARTIAL | **8** | **`2026-01-01`** | 2026-08-13 | — | **G6** COMPLETE **2026-01…08** (+01/+05); C8 pass lag 3 |
| `edinet_major_shareholders` | PARTIAL | **8** | **`2026-01-01`** | 2026-08-13 | — | **G6** COMPLETE **2026-01…08** (+03…06); C8 pass lag 3 |
| `edinet_large_volume_shareholders` | PARTIAL | **8** | **`2026-01-01`** | 2026-08-13 | — | COMPLETE **2026-01…08** (G7); C8 pass lag 1 |
| `fins_dividend` | **PARTIAL** | **13** | **`2013-02-01`** | **`2026-08-13`** | — | **t5_div_pre** 120/120 + T5 FINAL; **G9 T13 +11** (2018-01…08,10…12) → COMPLETE segs **13** (was 2026-07/08 only); C8 **pass** lag **1**; dataset **not** COMPLETE |
| `fins_earnings_date` | **PARTIAL** | **10** | **`2018-01-01`** | **`2026-08-13`** | — | **T5 FINAL** 72/72; **G9 T13 +5** issued (2018-01…05) → COMPLETE segs **10** (was 2; concurrent peers may add); C8 **pass** lag **1**; dataset **not** COMPLETE |
| `markets_short_sale_report` | PARTIAL | **3** | — | — | — | COMPLETE **2026-06/07/08** |
| `indices_bars_daily` | PARTIAL | **7** | — | — | — | **G8 T12** COMPLETE **2024-01/08/09/10/12** + 2026-07/08 (**+5**); acq `w0713_t8_jsda_idx_*` pass 21; dataset **not** COMPLETE |
| `derivatives_bars_daily_futures` | PARTIAL | **8** | **`2026-01-01`** | **`2026-08-12`** | — | **G6** COMPLETE **2026-01…08** (+03…07); C8 pass lag 1 |
| `derivatives_bars_daily_options` | PARTIAL | **3** | **`2026-06-01`** | **`2026-08-13`** | — | **T9** COMPLETE **2026-06/07/08** (+06/+07); reeval end **2026-08-13** C8 pass; wave **done** |
| `derivatives_bars_daily_options_225` | PARTIAL | **8** | **`2026-01-01`** | **`2026-08-12`** | — | **G6** COMPLETE **2026-01…08** (+01…07); C8 pass lag 1 |

## Proof index (aggregate — do not orphan)

### COMPLETE seals
| Proof | What it closes |
|-------|----------------|
| [`docs/proof/w0713_wave_close_20260814.md`](proof/w0713_wave_close_20260814.md) | **G10 T15+T16+T17 wave close**: stagnant-4 COMPLETE **bars 12→13 / master 94→132 / topix 32→82 / breakdown 32→33**; raw **7917→9387**; COMPLETE segs **585→729**; FRESH `projgen-7b6c…` age=0; empty COMPLETE **0**; peers not killed |
| [`docs/proof/w0713_t13_t14_ops_20260814.md`](proof/w0713_t13_t14_ops_20260814.md) | **G9 T13+T14**: projection PRE age ~**16983s** → POST age≈0 (`projgen-d4677ef…`); receipts **+27** (details **+11** / div **+11** / earn_date **+5** issued); remote COMPLETE **677**; raw_n **9324**; empty COMPLETE **0**; no cf_premium |
| [`docs/proof/g8_t11_otc_t12_indices_20260814.md`](proof/g8_t11_otc_t12_indices_20260814.md) | **G8 T11+T12**: OTC **+1** (`2026-08-14` run **900661**); `indices_bars_daily` **+5** (2024-01/08/09/10/12); remote COMPLETE **677**; raw_n **9200**; FRESH `projgen-c1aacf…`; further OTC/history **DEFER** |
| [`docs/proof/t5_dividend_pre2018_20260814.md`](proof/t5_dividend_pre2018_20260814.md) | **t5_div_pre**: `fins_dividend` **2008-01…2017-12** plan **120** → **120 pass / 0 fail**; host jobs/min **4.69**; reeval `observed_start` **`2013-02-01`** (was 2018-01-01); COMPLETE segs **585** Δ0; raw_n **7825**; empty COMPLETE **0** |
| [`docs/proof/t5_fins_family_20260813.md`](proof/t5_fins_family_20260813.md) | **T5 fins family FINAL**: runner **287/1** (fail=`fins_details` 2022-05 CF1102) + split/daily recover → unique **288**; host jobs/min **1.68**; observed summary **2008-07-01** / details·div·earn **2018-01-01** → end **2026-08-13** C8 pass; receipts this close **+0** (T12 peer **+45** already); **superseded on div start** by t5_div_pre → **2013-02-01** |
| [`docs/proof/t12_receipts_wave_20260814.md`](proof/t12_receipts_wave_20260814.md) | **T12 fins receipts**: fins_details **+20** + fins_summary **+25** → remote COMPLETE **585**; empty-raw ban held; no acq launch |
| [`docs/proof/t9_options_near_close_20260814.md`](proof/t9_options_near_close_20260814.md) | **T9 options_near close**: week-chunk 9/9 pass (retry 2/2); seals **+2** (2026-06/07 run_ids **900587/900586**) → then T12 → **585**; reeval C8 pass |
| [`docs/proof/instruction_t1t16_close_20260814.md`](proof/instruction_t1t16_close_20260814.md) | **T13–T15 final sync + T1–T16 instruction close** (2026-08-14 JST): reeval×5 + FRESH age=0; raw **7430**/6535; COMPLETE segs **538** Δ0; empty COMPLETE **0**; Mass NO-GO; acq not killed |
| [`docs/proof/t6_deriv_edinet_20260813.md`](proof/t6_deriv_edinet_20260813.md) | **G6 T9+T10** t6_deriv_edinet: worker 22p/1f; seals **+18** vs G7 (futures+5 major+4 cross+2 options_225+7) → COMPLETE **538**; reeval C8 pass; options_near not killed |
| [`docs/proof/t4_t7_t8_parallel_acq_reeval_20260813.md`](proof/t4_t7_t8_parallel_acq_reeval_20260813.md) | T4/T7/T8 parallel acq + **54/54** fail-retry + observed reeval; raw **5265→7289** (target Δ n **+1398**); **no** empty COMPLETE |
| [`docs/proof/t1_master_misc_close_20260813.md`](proof/t1_master_misc_close_20260813.md) | T1/G1 monitor queue-close master/misc (fail residual → closed by T478 retry) |
| [`docs/proof/g7_t11_otc_t12_receipts_20260813.md`](proof/g7_t11_otc_t12_receipts_20260813.md) | G7 T11 OTC **+0 DEFER** (timeout); T12 receipts **+10** → COMPLETE **520** |
| [`docs/proof/mb_2015dir_reeval_edinet_plus4_20260813.md`](proof/mb_2015dir_reeval_edinet_plus4_20260813.md) | T5/T9/T10: breakdown `observed_start=2015-03-26`; OTC **+0**; EDINET **+4** → COMPLETE **510** |
| [`docs/proof/t4_breakdown_wave_20260813.md`](proof/t4_breakdown_wave_20260813.md) | T4/G3 MB week-chunk midhole (GW2019 empty expected); reeval `observed_start=2015-03-26` |
| [`docs/proof/complete_plus3_margin_ssr_jun2026_20260813.md`](proof/complete_plus3_margin_ssr_jun2026_20260813.md) | A3 **+3** margin 2026-06/08 + short_sale 2026-06 → COMPLETE **506** |
| [`docs/proof/complete_plus2_margin_ssr_jul2026_20260813.md`](proof/complete_plus2_margin_ssr_jul2026_20260813.md) | A3 **+2** margin + short_sale **2026-07** R2 raw+struct → COMPLETE **503** |
| [`docs/proof/complete_plus7_jul2026_remote_struct_20260813.md`](proof/complete_plus7_jul2026_remote_struct_20260813.md) | A3 **+7** remote 2026-07 struct + R2 raw → COMPLETE **501** |
| [`docs/proof/complete_plus4_investor_edinet_20260813.md`](proof/complete_plus4_investor_edinet_20260813.md) | A3 **+4** investor 2019-12 + edinet×3 2026-08 → COMPLETE **494** |
| [`docs/proof/complete_plus8_r2_raw_seal_20260813.md`](proof/complete_plus8_r2_raw_seal_20260813.md) | A3 **+8** via R2 raw mirror + parallel receipts → COMPLETE **490** |
| [`docs/proof/complete_plus23_parallel_receipts_20260812.md`](proof/complete_plus23_parallel_receipts_20260812.md) | A3 parallel receipts **+71** → COMPLETE **479** |
| [`docs/proof/complete_plus3_struct_hint_20260812.md`](proof/complete_plus3_struct_hint_20260812.md) | A3 +3 (earnings/fins) → **481** |
| [`docs/proof/complete_plus1_bars_202608_20260812.md`](proof/complete_plus1_bars_202608_20260812.md) | bars/2026-08 re-seal → **482** |
| [`docs/proof/complete_plus3_otc_20260812.md`](proof/complete_plus3_otc_20260812.md) | JSDA OTC honest +3 path |
| [`docs/proof/complete_plus1_20260812.md`](proof/complete_plus1_20260812.md) | earlier +1 COMPLETE procedure evidence |
| [`docs/proof/sticky_complete_verify_20260812.md`](proof/sticky_complete_verify_20260812.md) | sticky COMPLETE demotion guard live |

### Track A / raw throughput / bars history
| Proof | What it closes |
|-------|----------------|
| [`docs/proof/t5_fins_family_20260813.md`](proof/t5_fins_family_20260813.md) | **T5 FINAL 288** (runner 287/1 + recover); observed deepens + C8 pass ×4; G4 partial snap superseded |
| [`docs/proof/wave2256_final_close_20260813.md`](proof/wave2256_final_close_20260813.md) | **G8-final** closed circuit: reeval×5 + FRESH age=0 (`projgen-a059…`); session PRE raw **6447**→POST **7385**; COMPLETE segs **510→538**; empty COMPLETE **0**; Mass NO-GO; Phase7 OFF; acq not killed |
| [`docs/proof/p0_multi_track_wave2_20260813.md`](proof/p0_multi_track_wave2_20260813.md) | **G8 closed circuit** T13+T14+T15: reeval×5 + FRESH age=0 (`projgen-8927…`); raw PRE **6447**→POST **6477** (+30); COMPLETE segs **510** Δ0; host rpm bars **6.22** / topix w1 **93.48** / merged **12.56** / +peers **17.63**; no kill acq |
| [`docs/proof/p0_high_rate_parallel_acq_20260813.md`](proof/p0_high_rate_parallel_acq_20260813.md) | **High-rate parallel** PRE raw **3535**→re-verify **6378** (+2843); host rpm mb 10.97 / bars 6.22 / topix3 **93.48→62.79** / merged **12.31**; bars/fins/topix drivers done; observed_* + margin C8 **pass**; projection FRESH age=0 |
| [`docs/proof/p0_multi_track_throughput_20260813.md`](proof/p0_multi_track_throughput_20260813.md) | **Multi-track** MB/bars/fins/topix host POST/min + raw Δ **+839** (5279→6118) + reeval (fins start **2014-01-01**, breakdown **2015-03-26**, C8 pass, projection FRESH) |
| [`docs/proof/track_a_dryrun_20260812.md`](proof/track_a_dryrun_20260812.md) | Track A planner dry-run |
| [`docs/proof/raw_throughput_PRE_20260812.md`](proof/raw_throughput_PRE_20260812.md) / [`.json`](proof/raw_throughput_PRE_20260812.json) | PRE baseline |
| [`docs/proof/raw_throughput_PRE_AEXEC_20260812.md`](proof/raw_throughput_PRE_AEXEC_20260812.md) | PRE_AEXEC |
| [`docs/proof/raw_throughput_POST_AEXEC_20260812.md`](proof/raw_throughput_POST_AEXEC_20260812.md) | POST_AEXEC summary |
| [`docs/proof/raw_throughput_POST_AEXEC_20260812T141214Z.md`](proof/raw_throughput_POST_AEXEC_20260812T141214Z.md) | timestamped POST |
| [`docs/proof/raw_throughput_POST_AEXEC_20260812T142910Z.md`](proof/raw_throughput_POST_AEXEC_20260812T142910Z.md) | timestamped POST |
| [`docs/proof/raw_throughput_POST_AEXEC_20260812T143446Z.md`](proof/raw_throughput_POST_AEXEC_20260812T143446Z.md) | POST final snapshot (local mirror; remote raw SoT separate) |
| [`docs/proof/remote_raw_POST_AEXEC_snippet.txt`](proof/remote_raw_POST_AEXEC_snippet.txt) | remote raw snippet |
| [`docs/proof/bars_observed_start_move_20260812.md`](proof/bars_observed_start_move_20260812.md) | code path: receipt ∪ hot → `observed_*` |
| [`docs/proof/bars_history_observed_start_20260812.md`](proof/bars_history_observed_start_20260812.md) | bars PRE/POST **`observed_start=2008-05-01`**; raw →1889 |
| [`docs/proof/bars_gap_20060812_20080430_20260812.md`](proof/bars_gap_20060812_20080430_20260812.md) | full week-chunk gap dispatch 2006-08→2008-04 (empty shells) |
| [`docs/proof/bars_p0_gap_midhole_20260813.md`](proof/bars_p0_gap_midhole_20260813.md) | gap DEFER + mid-hole fill 2011–2025 |
| [`docs/proof/bars_p0_gap_2004_2008_reverify_20260813.md`](proof/bars_p0_gap_2004_2008_reverify_20260813.md) | **reverify** 2004–2008-04: API floor 2006-08-13 + empty `data[]`; `observed_start` stays **2008-05-01** |

### P0 / P1 other datasets (margin, topix, quality)
| Proof | What it closes |
|-------|----------------|
| [`docs/proof/p0_other_datasets_margin_topix_20260812.md`](proof/p0_other_datasets_margin_topix_20260812.md) | margin latest+Jul → **PARTIAL**; topix hist → **`observed_start=2008-01-01`** |
| [`docs/proof/p1_markets_margin_interest_stale_defer_20260812.md`](proof/p1_markets_margin_interest_stale_defer_20260812.md) | prior STALE root-cause / history DEFER (superseded on status only by P0) |
| [`docs/proof/p0_reeval_20260812.md`](proof/p0_reeval_20260812.md) | earlier reeval / projection freshness (historical COMPLETE 400) |
| [`docs/proof/p0_finish_projection_breakdown_20260813.md`](proof/p0_finish_projection_breakdown_20260813.md) | P0 finish: projection FRESH + breakdown `observed_start` **2015-04-01** restore |
| [`docs/proof/p0_margin_projection_20260813.md`](proof/p0_margin_projection_20260813.md) | margin observed_end + earlier projection freshness |
| [`docs/proof/p0_margin_c8_projection_20260813.md`](proof/p0_margin_c8_projection_20260813.md) | margin C8 receipt-plane lag (1d≤7) + projection reclock FRESH age=0 |
| [`docs/proof/p0_margin_observed_end_restore_20260813.md`](proof/p0_margin_observed_end_restore_20260813.md) | **P0** observed_end **2026-08-04→2026-08-12** restore (no execute; lag 9d FAIL→1d PASS) |
| [`docs/proof/p0_margin_c8_detail_pass_20260813.md`](proof/p0_margin_c8_detail_pass_20260813.md) | **P0** detail_json C8 **fail→pass** (receipt SoT) + projection FRESH + planner sub floor 2006-08-13 |
| [`docs/proof/g5_margin_earn_history_20260813.md`](proof/g5_margin_earn_history_20260813.md) | **G5** margin history → `observed_start=2013-01-04` + earn 199 segs; C8 pass; PARTIAL honest; t7/t8 untouched |
| [`docs/proof/p0_storage_plane_evidence.md`](proof/p0_storage_plane_evidence.md) | storage plane evidence |
| [`docs/proof/data_quality_scan_20260812.md`](proof/data_quality_scan_20260812.md) | quality scan |
| [`docs/proof/phase63_completion_20260812.md`](proof/phase63_completion_20260812.md) | Phase 6.3 guard/freshness tooling land |

### Ops notes (not proofs of COMPLETE)
- [`docs/operations/safe_complete_one_segment.md`](operations/safe_complete_one_segment.md)
- [`docs/operations/phase7_foundation_off.md`](operations/phase7_foundation_off.md)
- [`docs/operations/phase63_live_sync.md`](operations/phase63_live_sync.md) *(historical COMPLETE 400; use this residual for live counts)*
- [`docs/operations/projection_publish_guard.md`](operations/projection_publish_guard.md)

## DONE vs DEFER

| Area | Status |
|------|--------|
| Sticky COMPLETE + inventory status fix | **DONE** (+ segment_id fallback + aggregate recompute 2026-08-13) |
| Publish fail-closed guard | **DONE** |
| Honest segment COMPLETE path (raw + signed SUCCESS) | **DONE** (OTC **6**; A3 … + G7/G6/T9/T12 fins + **G8 OTC +1 + indices +5** + w0713 peers; total COMPLETE **677**) |
| JSDA min COMPLETE (otc/corp/tokyo) | **DONE** (otc **6**; corp/tokyo ≥1 each; further OTC **DEFER** site timeout + R2 MISS) |
| G8 T11 OTC + T12 indices_bars_daily | **DONE** (OTC **+1** 2026-08-14; indices COMPLETE segs **2→7** full months; proof `g8_t11_otc_t12_indices_20260814.md`) |
| Physical layout → `packages/*` planes | **DONE** (Batches 0–E; import names leaf top-level) |
| Track A planner / throughput / execute | **DONE** (infra + live execute; raw continuing under mid-hole) |
| Track B1 docs hub + plane import guards | **DONE** |
| Track B residual live-sync + docs SoT banners | **DONE** (COMPLETE **677** / raw **9200** / G8 closed; Phase7 OFF) |
| G8 closed circuit (reeval + freshness + throughput proof) | **DONE** (wave2 + **G8-final** reeval×5 + FRESH age=0; peers not killed) |
| T13–T15 final sync + T1–T16 instruction close | **DONE** (2026-08-14: reeval×5 C8 pass; FRESH `projgen-daa4…`; raw **7430**; COMPLETE **538** Δ0; proof `instruction_t1t16_close_20260814.md`) |
| G6 t6_deriv_edinet (T9+T10) seal + reeval | **DONE** (worker 22p/1f; +18 seals vs G7 → **538**; options_near closed by T9 2026-08-14) |
| T9 options_near week-chunk + seal | **DONE** (9/9 pass; COMPLETE **+2** Jun/Jul; later T12 → **585**) |
| T12 fins raw seals (details+summary) | **DONE** (**+45** → COMPLETE **585**; empty-raw ban; proof `t12_receipts_wave_20260814.md`) |
| bars `observed_start` receipt-plane union | **DONE** (remote **`2008-05-01`**) |
| multi-track bars/fins/topix paced execute + host rpm proof | **DONE** (bars 280; fins FINAL 288; topix3 192; see multi-track + T5 proof) |
| fins_summary `observed_start` history deepen | **DONE** (remote **`2008-07-01`** via T5 pre-2014 paced 72/72 + FINAL reeval; empty 2008-01…06 shells; COMPLETE segs **30** via T12 not dataset COMPLETE) |
| T5 fins family (summary+details+div+earn 288) | **DONE** — runner **287/1** (`fins_details` 2022-05 CF1102) + split/daily recover → unique **288**; host jobs/min **1.68**; reeval ×4 C8 pass; observed div/earn start **2018-01-01** at close; PID dead / flag DONE; proof [`t5_fins_family_20260813.md`](proof/t5_fins_family_20260813.md) |
| t5_div_pre `fins_dividend` 2008-01…2017-12 | **DONE** — plan **120** / **120 pass / 0 fail**; host jobs/min **4.69**; PID **43684** natural exit; reeval `observed_start` **`2013-02-01`**; empty shells 2008-01…2013-01; COMPLETE **585** Δ0; raw_n **7825**; proof [`t5_dividend_pre2018_20260814.md`](proof/t5_dividend_pre2018_20260814.md) |
| bars gap **2004-01 → 2008-04** deepen / pre-May-2008 `observed_start` | **DEFER** (catalog wants 2004; subscription floor **2006-08-13**; empty `data[]` through 2008-04; raw_n=0 on gap receipts — see reverify proof) |
| topix `observed_start` receipt-plane | **DONE** (remote **`2008-01-01`**; `observed_end` **`2026-08-13`**) |
| margin STALE → PARTIAL (freshness) | **DONE** (remote PARTIAL; `observed_end=2026-08-13`; **detail_json C8 pass** lag 1d≤7 via `receipt_observed_end`; not dataset COMPLETE) |
| margin history raw + earn segments (G5 t5_margin_earn) | **DONE** (margin worker **147/147** after retry; earn **199/199**; `observed_start` **2013-01-04** / earn **2010-01-04**; C8 pass; COMPLETE seals still DEFER) |
| planner OOS before subscription floor | **DONE** (`JQUANTS_SUBSCRIPTION_FLOOR=2006-08-13`; fail id 2522 class blocked) |
| Extra COMPLETE without raw | **DEFER** / **Forbidden** |
| OTC full archive COMPLETE | **DEFER** (thousands of trading days remain; G8 sealed tip day only) |
| `indices_bars_daily` history COMPLETE beyond 7 segs | **DEFER** (acq pass 21 months; seal only full-month raw+struct) |
| `markets_margin_interest` monthly TRUSTED seal (COMPLETE segs beyond 17) | **DEFER** (history raw present via G5; seal path separate) |
| JSDA corporate years 2015–2025 | **DEFER** |
| breakdown `observed_start` pre-2024 depth | **DONE** (remote **`2015-03-26`** via receipt reeval; MB solo 2016–2023 week done; 2015-dir partial; re-reeval after every full publish) |
| Mass / READY / Phase7 switch ON | **NO-GO** (Phase7 **OFF** maintained) |
| applied_cursor materialization | **DEFER** |
| Batch Z (`quant_platform.*` imports) | **DEFER** (ADR Accepted; out of B1) |
| B1-c full dead-code purge | **partial** — inventory only; no unsafe deletes (false-positive import scans) |
| B1-d test tier nav | **partial** — `tests/README.md` G0/G1/G2 landed; matrix split open |
| B1-e script bootstrap | **partial** — ops/coverage + receipt CLIs on `_bootstrap`; fingerprints `parents[N]` fixed; remaining scripts incremental |

## Note on COMPLETE counts
- **Dataset-level COMPLETE = 2** means only two datasets have *all* required segments COMPLETE.
- **Segment COMPLETE = 677** counts every COMPLETE segment across datasets (calendar 224 + master/topix/markets/JSDA/A3/T9/T12/G8/w0713 peers, etc.).
- Next honest +N requires additional **real raw** (R2 or official fetch) + structured + signed SUCCESS; do not invent.
- Post-G6: major/cross/large_volume/futures/options_225 all **2026-01…08** COMPLETE; options **2026-06/07/08** (T9).
- T12 fins: fins_summary COMPLETE segs **30**; fins_details **23**; remaining history months **DEFER** without local usable raw+struct.
- G8: OTC tip **2026-08-14** sealed; `indices_bars_daily` **7** COMPLETE months; further OTC/history **DEFER**.
- t5_div_pre: `fins_dividend` worker **120/120** pre-2018; `observed_start` **2013-02-01**; COMPLETE segs still **2** (no seal this wave).
- OTC archive +N blocked when `market.jsda.or.jp` times out and no R2 raw for candidate days (CF worker can still land tip files).
- Full publish resets breakdown/margin `observed_*` toward hot facts — always re-run `ops_reeval_observed_window.py` for focus datasets after apply.
- Coordinate `cf_premium_backfill` on **general** with live peers; prefer ≤40 RPM single worker. Mass / READY **NO-GO**.
- T5 close: runner natural exit (PID dead); **no** empty COMPLETE; issue_receipts this close **+0** (T12 already sealed ready months).
- t5_div_pre: PID **43684** natural exit; **no** kill / **no** double-run; empty COMPLETE **0**.

## Phase 7 OFF (explicit)
Phase 7 remains **foundation-only / OFF**. Stubs under `knowledge/`, `selection/`, `gateway/`, `research/` are scaffolding.  
Fail-closed surface: `agents/mass_research.py`, `research/readiness.py`, `selection/budget_ledger.py`.  
Ops note: [`docs/operations/phase7_foundation_off.md`](operations/phase7_foundation_off.md).  
Architecture: [`docs/architecture/phase7_fail_closed.md`](architecture/phase7_fail_closed.md).

## Agent pointers
- LLM nav map: [`docs/architecture/llm_nav_map.md`](architecture/llm_nav_map.md)
- Layout SoT: [`docs/architecture/repo_layout_migration.md`](architecture/repo_layout_migration.md)
- LLM-friendly refactor ADR: [`docs/architecture/adr_llm_friendly_refactor.md`](architecture/adr_llm_friendly_refactor.md) (**Accepted**)
- Complete segment checklist: [`docs/complete_segment_checklist.md`](complete_segment_checklist.md) (counts live **only** here)
