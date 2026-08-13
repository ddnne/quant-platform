# Phase 6.2 / 6.3 residual status

**Live residual SoT** (agents: prefer this file over any `phase62*_status` / final_report).  
**Live verified:** 2026-08-13T14:01Z (remote D1; COMPLETE segs **510**; raw_n **6477** / COMPLETE completeness **5589**; G8 reeval×5 + freshness FRESH age=0; fins `observed_start=2014-01-01`; margin **detail_json C8 pass** lag 1d≤7; Phase7 **OFF**)  
**Repo tip:** `(see post-push SHA)` — COMPLETE **510** / raw_n **6477** / bars `2008-05-01` / fins `2014-01-01` / breakdown `2015-03-26` / topix end `2026-08-13` / margin C8 **pass** / Phase7 **OFF**

## Live snapshot (remote D1 `quant-ingest`)

| Item | Value |
|------|--------|
| Dataset COMPLETE | **2** — `markets_calendar` (224/224 segs), `jsda_tokyo_repo_rates` (1/1) |
| Dataset STALE | **0** (margin PARTIAL via receipt reeval; not STALE) |
| Segment COMPLETE total | **510** (remote; G8 circuit **Δ0** — measurement only, no empty COMPLETE) |
| Segment other | PARTIAL majority / UNKNOWN (topix inventory shape) |
| calendar segments | **224 COMPLETE / 0 PARTIAL** |
| JSDA OTC COMPLETE segs | **5** — `2026-08-06`, `2026-08-07`, `2026-08-10`, `2026-08-12`, `2026-08-13` (dataset still PARTIAL; **+0** this pass — JSDA fetch timeout) |
| JSDA corporate COMPLETE segs | **1** — year `2026` (dataset still PARTIAL) |
| A3 sealed (partial datasets) | prior + **+4** edinet (major/2026-01 + cross/2026-02/03/04); also +3 margin/ssr; +2 margin/ssr 2026-07; +7/`*/2026-07`; +4 investor/edinet; … |
| Remote `raw_retention_manifests` | **6477** total / **5589** COMPLETE completeness (session PRE **6447**/**5559** → POST **6477**/**5589**, **+30**/+30; peers t7/t8/t5 still live; local research mirror still partial) |
| Track A + P0 execute | **multi-track chain DONE** — MB solo 409/409; bars solo **280** (264 pass/16 fail); fins paced **96/96**; topix3 **2×192** (w1 93.48 / w2 62.79 rpm). Peers t7_master / t8_misc / t5_margin_earn still running. **Worker pass ≠ COMPLETE** |
| master | `scd2_event_sourcing` / D1 hot |
| projection | **FRESH** — `projgen-8927d3b38aae41c18dc740df9a7ed6ad` (`generated_at=2026-08-13T14:01:21.532627+00:00`, age_seconds=0; `ops_reeval_freshness` G8) |
| sticky COMPLETE | **fixed** segment_id fallback + post-sticky dataset aggregate + COMPLETE inventory retain past UTC target_end (`coverage_ledger.py`) |
| Full publish guard | `scripts/publish_ops_projection.py` fail-closed |
| Targeted freshness | `scripts/ops_reeval_freshness.py` (no segment rewrite) |
| Observed window re-eval | `scripts/ops_reeval_observed_window.py` (SUCCESS receipts `raw_row_count>0`; no segment rewrite / no COMPLETE claim) |
| Layout migration | **DONE** — libraries under `packages/{edge,data_plane,research_runtime,product}`; import leaf names unchanged |
| Track A (historical raw accel) | **EXECUTE DONE** — PRE raw **1488** → AEXEC **1889** → high-rate PRE **3535** → live **6477** |
| Track B1 (LLM-friendly) | **landed** + residual/docs SoT live-sync; B1-e partial (ops/coverage/receipt CLIs); Batch Z still **DEFER** |
| Mass / READY / B0 | **NO-GO** |
| Phase 7 | **OFF / foundation only** — **must remain OFF**; no mass arming, no production READY, no Phase7 switch ON |

### Host POST/min (multi-track session, state jsonl + run log)

| Track | host POST/min | n | note |
|-------|--------------:|--:|------|
| MB solo | **10.97** | 409 | general pool |
| bars solo | **6.22** | 280 | general; 0×429; pass 264 / fail 16 |
| fins paced | **1.09–1.16** | 102 | fins pool; runner `host_jobs_per_min=1.09` |
| topix3 w1 / w2 | **93.48** / **62.79** | 192 / 192 | residual months (fast burst); orch re-dispatch after bars |
| t7 master (live peer) | **3.65** | ~136 | equities_master; not killed |
| t8 misc (live peer) | **10.50** | ~393 | short_ratio / margin_alert / investor; not killed |
| merged mb+bars+topix3+fins | **12.56** | 1175 | G8 wave2 re-measure |
| merged + peers t4/t7/t8 | **17.63** | 1896 | concurrent acq included |
| proof | — | — | [`docs/proof/p0_multi_track_wave2_20260813.md`](proof/p0_multi_track_wave2_20260813.md) |

### observed_* (remote D1, key datasets)

| dataset | status | COMPLETE segs | observed_start | observed_end | raw manifests (COMPLETE) | notes |
|---------|--------|--------------:|----------------|--------------|--------------------------:|-------|
| `equities_bars_daily` | **PARTIAL** | **12** | **`2008-05-01`** | **`2026-08-12`** | growing (n≈2000) | multi-track 280 week jobs done; worker pass ≠ COMPLETE |
| `indices_bars_daily_topix` | **PARTIAL** | **32** | **`2008-01-01`** | **`2026-08-13`** | n≈1190 | topix3 2×192 pass; C8 lag 0 |
| `markets_breakdown` | **PARTIAL** | **32** | **`2015-03-26`** | **`2026-08-12`** | n≈1056 | reeval after MB solo+2015-dir; full publish resets → re-run reeval |
| `fins_summary` | **PARTIAL** | **5** | **`2014-01-01`** | **`2026-08-12`** | n≈304 | paced 2016–2023 done; reeval moved start from 2024-01-01 |
| `markets_margin_interest` | **PARTIAL** | **17** | **`2024-01-01`** | **`2026-08-13`** | — | **detail_json C8 pass** (lag **1**≤7, receipt SoT); COMPLETE months include **2026-06/07/08**; dataset **not** COMPLETE |
| `markets_short_ratio` | PARTIAL | 32 | 2024-01-04 | 2026-08-10 | — | A3 sealed months |
| `markets_margin_alert` | PARTIAL | 18 | 2025-03-03 | 2026-08-07 | — | A3 sealed months |
| `markets_calendar` | **COMPLETE** | 224 | 2008-01-01 | 2026-08-12 | — | sticky full + aggregate fix |
| `jsda_tokyo_repo_rates` | **COMPLETE** | 1 | 2012-10-29 | 2026-08-10 | — | dataset COMPLETE |
| `fins_details` | PARTIAL | **3** | — | — | — | +2026-08 seal |
| `equities_investor_types` | PARTIAL | **10** | — | — | — | +2019-12 + 2026-07 + 2026-08 seals |
| `edinet_cross_shareholdings` | PARTIAL | **5** | 2026-02-01 | 2026-08-13 | — | COMPLETE **2026-02/03/04/07/08** |
| `edinet_major_shareholders` | PARTIAL | **3** | 2026-01-01 | 2026-08-13 | — | COMPLETE **2026-01/07/08** |
| `edinet_large_volume_shareholders` | PARTIAL | **2** | 2026-05-13 | 2026-08-13 | — | COMPLETE 2026-07 + 2026-08 only |
| `fins_dividend` / `fins_earnings_date` | PARTIAL | **2** each | — | — | — | COMPLETE 2026-07 + 2026-08 |
| `markets_short_sale_report` | PARTIAL | **3** | — | — | — | COMPLETE **2026-06/07/08** |
| `indices_bars_daily` | PARTIAL | **2** | — | — | — | COMPLETE 2026-07 + 2026-08 |
| `derivatives_bars_daily_{futures,options,options_225}` | PARTIAL | **1** each | — | — | — | first COMPLETE month |

## Proof index (aggregate — do not orphan)

### COMPLETE seals
| Proof | What it closes |
|-------|----------------|
| [`docs/proof/mb_2015dir_reeval_edinet_plus4_20260813.md`](proof/mb_2015dir_reeval_edinet_plus4_20260813.md) | T5/T9/T10: breakdown `observed_start=2015-03-26`; OTC **+0**; EDINET **+4** → COMPLETE **510** |
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
| Honest segment COMPLETE path (raw + signed SUCCESS) | **DONE** (OTC 5; A3 +71/+3/+1/+8/+4/+7/+2/+3/+4; total COMPLETE **510**) |
| JSDA min COMPLETE (otc/corp/tokyo) | **DONE** (otc 5; corp/tokyo ≥1 each; further OTC **DEFER** site timeout) |
| Physical layout → `packages/*` planes | **DONE** (Batches 0–E; import names leaf top-level) |
| Track A planner / throughput / execute | **DONE** (infra + live execute; raw continuing under mid-hole) |
| Track B1 docs hub + plane import guards | **DONE** |
| Track B residual live-sync + docs SoT banners | **DONE** (COMPLETE **510** / raw **6477** / breakdown `2015-03-26` / C8 pass / Phase7 OFF; G8 wave2) |
| G8 closed circuit (reeval + freshness + throughput proof) | **DONE** (FRESH age=0; COMPLETE Δ0; peers not killed) |
| bars `observed_start` receipt-plane union | **DONE** (remote **`2008-05-01`**) |
| multi-track bars/fins/topix paced execute + host rpm proof | **DONE** (bars 280; fins i=96; topix3 192; see multi-track proof) |
| fins_summary `observed_start` history deepen | **DONE** (remote **`2014-01-01`** via paced raw + reeval; further pre-2014 open) |
| bars gap **2004-01 → 2008-04** deepen / pre-May-2008 `observed_start` | **DEFER** (catalog wants 2004; subscription floor **2006-08-13**; empty `data[]` through 2008-04; raw_n=0 on gap receipts — see reverify proof) |
| topix `observed_start` receipt-plane | **DONE** (remote **`2008-01-01`**; `observed_end` **`2026-08-13`**) |
| margin STALE → PARTIAL (freshness) | **DONE** (remote PARTIAL; `observed_end=2026-08-13`; **detail_json C8 pass** lag 1d≤7 via `receipt_observed_end`; not dataset COMPLETE) |
| planner OOS before subscription floor | **DONE** (`JQUANTS_SUBSCRIPTION_FLOOR=2006-08-13`; fail id 2522 class blocked) |
| Extra COMPLETE without raw | **DEFER** / **Forbidden** |
| OTC full archive COMPLETE | **DEFER** (thousands of trading days remain) |
| `markets_margin_interest` full history / monthly TRUSTED seal | **DEFER** |
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
- **Segment COMPLETE = 510** counts every COMPLETE segment across datasets (calendar 224 + master/topix/markets/JSDA/A3 seals, etc.).
- Next honest +N requires additional **real raw** (R2 or official fetch) + structured + signed SUCCESS; do not invent.
- Post-+4 EDINET: major **2026-01** + cross **2026-02/03/04**; large_volume H1 and further months still open.
- OTC archive +N blocked when `market.jsda.or.jp` times out and no R2 raw for candidate days.
- Full publish resets breakdown `observed_*` toward hot facts — always re-run `ops_reeval_observed_window.py --dataset markets_breakdown` after apply.
- Coordinate `cf_premium_backfill` on **general** with live bars solo (near-ceiling RPM); prefer ≤40 RPM single worker or wait for bars idle. Mass / READY **NO-GO**.

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
