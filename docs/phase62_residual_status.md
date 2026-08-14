# Phase 6.2 / 6.3 residual status

**Live residual SoT** (agents: prefer this file over any `phase62*_status` / final_report).  
**Live verified:** 2026-08-14 (JST) / ~2026-08-14T03:29Z UTC (remote D1; COMPLETE segs **1478**; raw_n **11242**/c **9670**; FRESH `projgen-16cfbaa5…`; empty COMPLETE **0**; Phase7 **OFF**; **W2-G9 w0814b all-sources close**)  
**Repo tip:** `7472cd630f0aa1c589f3c5f4e1d59f1a4d299c20` — COMPLETE **1478** / raw_n **11242** / FRESH `projgen-16cfbaa5…` / empty COMPLETE **0** / Phase7 **OFF** / w0814b G9 close

## Live snapshot (remote D1 `quant-ingest`)

| Item | Value |
|------|--------|
| Dataset COMPLETE | **3** — `markets_calendar` (224/224), `jsda_tokyo_repo_rates` (1/1), **`jsda_corporate_bond_transactions` (12/12)** |
| Dataset STALE | **0** (margin PARTIAL via receipt reeval; not STALE) |
| Segment COMPLETE total | **1478** (remote; PRE **1376** + w0814b peers + **W2-G9 issue/publish +102**; **no** empty COMPLETE) |
| Segment other | PARTIAL / UNKNOWN (remainder; not mass-READY) |
| calendar segments | **224 COMPLETE / 0 PARTIAL** |
| JSDA OTC COMPLETE segs | **11** — `2026-07-30/31` + `2026-08-03`…`07` + `10` + `12`…`14` (**W2-G8 +2** tip/recent raw; further history **DEFER** site timeout) |
| JSDA corporate COMPLETE segs | **12** — years **`2015`…`2026`** (**G9 +11**; full annual TORIHIKI; dataset **COMPLETE**) |
| A3 sealed (partial datasets) | prior + w0814 FINAL **1376** + w0814b margin/alert/short_ratio/mb/idx/options/OTC → COMPLETE **1478** |
| Remote `raw_retention_manifests` | **11242** total / c **9670** (w0814b multi-track acq + peers; worker pass ≠ COMPLETE) |
| Track A + P0 execute | **w0713 T1–T17 DONE/DEFER** + **w0814 peers** + **w0814b G1–G8** + **W2-G9 close**; **Worker pass ≠ COMPLETE** |
| master | `scd2_event_sourcing` / D1 hot |
| projection | **FRESH** — `projgen-16cfbaa5dfb643c9867b5aaa3b4f905a` (W2-G9 reeval freshness; segs untouched by reclock) |
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
| w0713 t7 margin_inv (**FINAL**) | **9.61** | **970** | **G7 T9+T10 DONE**; wave1 **918p/52f** + retry **52/52** → **970/970**; C8 margin **pass** lag2; seals **+0** |
| w0713 t6_deriv_edinet | **1.52** | 60 | G6 main 41p/19f + retry 48/48; w=1 rpm=50/35; seals **+60** |
| w0713 t1 bars exec / retry | **7.16** / **7.50** | 120 / 22 | G1 close; pass 86/34 + retry 21/1 |
| w0713 t3 topix | **54.28** | 192 | all pass |
| w0713 t2 master | **4.97** | 147 | G2 close; 63p/84f (seal used R2 window-ok, not worker-pass alone) |
| w0814 g4 master residual | **23.12** / **20.3** | 21 / 21 | **G4** residual; wave1 **0p/21f** + retry **0p/21f** (400×1 + 429×20); seal window_ok **0** |
| w0814 g1 bars | **13.74** | **200** | 124p/76f; max-jobs 200 natural |
| w0814 g3 topix | **34.74** | **142** | 81p/61f; seals → COMPLETE **220** |
| w0814 g2 mb residual/retry | **14.26** / **5.07** | 120 / 80 | residual **48p/72f** + retry **80p/0f**; seal+issue **+36** → COMPLETE **105** |
| w0814 g7 edinet retry | **4.26** | **36** | **36/36** pass |
| w0814 g5 fins residual | **2.0** | **48** | **G5** serial paced **48/48** pass; seal+issue **+48**; COMPLETE fins **54/47/26/26** |
| w0814 g8 misc seal | — | **80** | **G8** R2 seal+issue **+80**; C8 margin pass lag2 held; acq execute DEFER |
| w0814 all-sources G10 close | — | — | mid proof [`w0814_all_sources_wave_20260814.md`](proof/w0814_all_sources_wave_20260814.md) |
| w0814 all-sources **FINAL** | — | — | proof [`w0814_all_sources_final_20260814.md`](proof/w0814_all_sources_final_20260814.md) PRE **9687/942** → POST **10701/1376** |
| w0814b g1 bars | — | **200** | **199p/1f**; seal wave deferred / peers |
| w0814b g2 mb residual | — | **100** | **100p/0f**; seal+issue → mb **116** |
| w0814b g3 idx | — | **100** | **100p/0f**; indices COMPLETE **61** |
| w0814b g6 edinet | — | **36** | **36p/0f** |
| w0814b all-sources **G9 close** | — | — | proof [`w0814b_all_sources_wave_20260814.md`](proof/w0814b_all_sources_wave_20260814.md) PRE **10702/1376** → POST **11242/1478** |
| w0713 t4 mb residual | **10.34** | 44 | G4 close; last-state week-jobs **40p/4f** |
| proof | — | — | G1–G9 + w0814 FINAL + **w0814b G9 close** 20260814 |

### observed_* (remote D1, key datasets)

| dataset | status | COMPLETE segs | observed_start | observed_end | raw manifests (COMPLETE) | notes |
|---------|--------|--------------:|----------------|--------------|--------------------------:|-------|
| `equities_bars_daily` | **PARTIAL** | **72** | **`2008-05-01`** | **`2026-08-13`** | — | **G1 w0814** COMPLETE **42→72 (+30)**; C8 **pass** lag **1**; worker pass ≠ COMPLETE |
| `indices_bars_daily_topix` | **PARTIAL** | **220** | **`2008-01-01`** | **`2026-08-14`** | — | **w0814 G3** COMPLETE **82→220 (+138)**; C8 **pass** lag **0**; dataset **not** COMPLETE |
| `equities_master` | **PARTIAL** | **220** | **`2006-08-13`** | **`2026-08-13`** | — | **G2 master** COMPLETE **94→220 (+126)**; **G4 residual** plan **21** acq **0p/21f×2** + seal window_ok **0** → COMPLETE **220→220 (+0)**; 21 misdated pre-2008-05 **DEFER**; C8 **pass** lag **1**; scd2 hot |
| `markets_breakdown` | **PARTIAL** | **116** | **`2015-03-26`** | **`2026-08-13`** | — | prior **105** + **w0814b G2/G9 +11** (`2021-04…2022-04` subset) → COMPLETE **116**; **2022-05…2023-11** DEFER; C8 **pass** lag **1** |
| `fins_summary` | **PARTIAL** | **54** | **`2008-07-01`** | **`2026-08-13`** | — | prior **42** + **G5 w0814_g5_fins +12** (`2011-08…2012-07` runs **901652–901663**) → COMPLETE segs **54**; empty shells 2008-01…06; C8 **pass** lag **1**; dataset **not** COMPLETE |
| `markets_margin_interest` | **PARTIAL** | **49** | **`2013-01-04`** | **`2026-08-13`** | — | prior **33** + **w0814b G7/G9 +16** `2014-05…2015-08`; **C8 pass** lag **2** (**held**); dataset **not** COMPLETE |
| `equities_earnings_calendar` | **PARTIAL** | **1** | **`2010-01-04`** | **`2026-08-14`** | — | G7 worker; G8 history seal **DEFER** (tip-dated Date); C8 **pass** lag **0**; COMPLETE only **2026-08** |
| `markets_short_ratio` | **PARTIAL** | **64** | **`2013-01-04`** | **`2026-08-13`** | — | prior **48** + **w0814b G7/G9 +16** `2014-05…2015-06`; C8 **pass** lag **1** |
| `markets_margin_alert` | **PARTIAL** | **47** | **`2012-12-28`** | **`2026-08-13`** | — | prior **34** + **w0814b G7/G9 +13**; C8 **pass** lag **1**; observed_start reeval **2012-12-28** |
| `markets_calendar` | **COMPLETE** | 224 | 2008-01-01 | 2026-08-12 | — | sticky full + aggregate fix |
| `jsda_tokyo_repo_rates` | **COMPLETE** | 1 | 2012-10-29 | 2026-08-10 | — | dataset COMPLETE (G9 verify only) |
| `jsda_otc_bond_reference_prices` | **PARTIAL** | **11** | **`2026-07-30`** | **`2026-08-14`** | — | **W2-G8 +2** (`2026-07-30/31` runs **901821/901820**); prior tip **9**; history **DEFER** site timeout; dataset **not** COMPLETE |
| `jsda_corporate_bond_transactions` | **COMPLETE** | **12** | **`2015-11-02`** | **`2026-08-14`** | — | **G9 +11** full annual TORIHIKI2015–2026 (runs **901244–901255**); dataset **COMPLETE** |
| `fins_details` | **PARTIAL** | **47** | **`2018-01-01`** | **`2026-08-13`** | — | prior **35** + **G5 w0814_g5_fins +12** (`2020-09…2021-08` runs **901688–901699**) → COMPLETE segs **47** (`2018-01…2021-08` + tips); C8 **pass** lag **1**; dataset **not** COMPLETE |
| `equities_investor_types` | **PARTIAL** | **26** | **`2013-01-04`** | **`2026-08-12`** | — | **G8 misc** COMPLETE **10→26 (+16)** `2013-01…2014-04`; C8 **pass** lag **3** |
| `equities_bars_daily_am` | **PARTIAL** | **1** | **`2026-08-01`** | **`2026-08-13`** | n=108 / c=107 | **G7** 31/31 worker (rowsInserted 0 history shells); C8 **pass** lag **1**; deep history **DEFER** |
| `edinet_cross_shareholdings` | PARTIAL | **32** | **`2024-01-01`** | 2026-08-13 | — | **G7 w0814_g7_edinet** COMPLETE **20→32 (+12)** `2024-01…12`; C8 pass lag 4 |
| `edinet_major_shareholders` | PARTIAL | **32** | **`2024-01-01`** | 2026-08-13 | — | **G7 w0814_g7_edinet** COMPLETE **20→32 (+12)** `2024-01…12`; C8 pass lag 4 |
| `edinet_large_volume_shareholders` | PARTIAL | **32** | **`2024-01-01`** | 2026-08-13 | — | **G7 w0814_g7_edinet** COMPLETE **20→32 (+12)** `2024-01…12`; C8 pass lag 1 |
| `fins_dividend` | **PARTIAL** | **26** | **`2013-02-01`** | **`2026-08-13`** | — | prior **14** + **G5 w0814_g5_fins +12** (`2013-02…2014-01` runs **901676–901687**) → COMPLETE segs **26** (`2013-02…2014-01` + `2018-01…12` + tips); C8 **pass** lag **1**; dataset **not** COMPLETE |
| `fins_earnings_date` | **PARTIAL** | **26** | **`2018-01-01`** | **`2026-08-13`** | — | prior **14** + **G5 w0814_g5_fins +12** (`2019-01…12` runs **901664–901675**) → COMPLETE segs **26** (`2018-01…12` + `2019-01…12` + tips); C8 **pass** lag **1**; dataset **not** COMPLETE |
| `markets_short_sale_report` | PARTIAL | **20** | **`2012-01-10`** | **`2026-08-13`** | — | prior **19** + w0814b peer **+1**; C8 **pass** lag **1**; observed_start reeval **2012-01-10** |
| `indices_bars_daily` | PARTIAL | **61** | — | — | — | prior **33** + **w0814b G3 +28**; dataset **not** COMPLETE |
| `derivatives_bars_daily_futures` | PARTIAL | **44** | **`2024-01-01`** | **`2026-08-13`** | — | prior **32** + peer residual **+12**; C8 pass lag 1; dataset **not** COMPLETE |
| `derivatives_bars_daily_options` | PARTIAL | **8** | **`2026-01-01`** | **`2026-08-13`** | — | prior **5** + **w0814b G5/G9 +3** (incl. **2026-03**); **2026-04…05** seal in flight / **2025 DEFER**; C8 pass |
| `derivatives_bars_daily_options_225` | PARTIAL | **32** | **`2024-01-01`** | **`2026-08-13`** | — | **G6 w0814** 2024+2025+tips; C8 pass lag 1 |

## Proof index (aggregate — do not orphan)

### COMPLETE seals
| Proof | What it closes |
|-------|----------------|
| [`docs/proof/w0814b_all_sources_wave_20260814.md`](proof/w0814b_all_sources_wave_20260814.md) | **W2-G9 w0814b all-sources close**: PRE tip `be7ad33` raw **10702** COMPLETE **1376** → POST raw **11242**/c **9670** COMPLETE **1478** (+102); margin **49**/alert **47**/short_ratio **64**/mb **116**/idx **61**/options **8**/OTC **11**; reeval×5 C8 pass; FRESH `projgen-16cfbaa5…`; empty **0**; peers not killed |
| [`docs/proof/w0814_all_sources_final_20260814.md`](proof/w0814_all_sources_final_20260814.md) | **FINAL w0814 all-sources**: PRE tip `cac338b` raw **9687** COMPLETE **942** → POST raw **10701**/c **9129** COMPLETE **1376** (+434); mb **69→105**; reeval×5 C8 pass; FRESH `projgen-f1d9b952…` age=0; empty **0**; peers not killed |
| [`docs/proof/w0814_g2_breakdown_20260814.md`](proof/w0814_g2_breakdown_20260814.md) | **G2 w0814_g2_mb**: residual **48p/72f** + retry **80p/0f** host **14.26/5.07**; R2 seal **36/36**; issue **+36** (`2018-04…2021-03` **901702–901738**); COMPLETE **69→105**; platform **1376**; C8 pass lag1; empty **0** |
| [`docs/proof/w0814_g5_fins_residual_20260814.md`](proof/w0814_g5_fins_residual_20260814.md) | **G5 w0814_g5_fins residual**: acq **48/48** host **2.0**/min; R2 seal **48/48**; issue **+48** (12×4); remote COMPLETE **1339**; fins COMPLETE **54/47/26/26**; C8 pass×4; empty **0**; fins pool only |
| [`docs/proof/w0814_g7_edinet_20260814.md`](proof/w0814_g7_edinet_20260814.md) | **G7 w0814_g7_edinet**: acq 2024 (main 3p/33f + retry **36/36**); seals **+36** (major/cross/large **+12** each); COMPLETE **20→32** each; platform **1260**; observed_start **`2024-01-01`**; empty **0**; FRESH `projgen-ce19380…` |
| [`docs/proof/w0814_g8_misc_20260814.md`](proof/w0814_g8_misc_20260814.md) | **G8 misc w0814_g8_misc**: R2 seal+issue **+80** (margin/alert/short_ratio/short_sale/investor ×16); COMPLETE **1212**; C8 margin **pass lag2 held**; earn history DEFER tip-Date; acq execute DEFER (G7 970/970); empty **0**; FRESH `projgen-5be221…` |
| [`docs/proof/w0814_all_sources_wave_20260814.md`](proof/w0814_all_sources_wave_20260814.md) | **G10 w0814 all-sources wave close**: PRE tip `cac338b` raw **9687** COMPLETE **942** → POST raw **10662**/c **9090** COMPLETE **1106** (+164); topix **82→220**; futures **20→32**; host rpm g1 **13.74** / g3 topix **34.74** / g2 mb **14.38**; reeval×5 C8 pass; FRESH `projgen-d28bfce…` age=0; empty **0**; peers not killed |
| [`docs/proof/w0814b_g8_jsda_20260814.md`](proof/w0814b_g8_jsda_20260814.md) | **W2-G8 JSDA**: OTC tip/recent **+2** (`2026-07-30/31` runs **901821/901820**) → COMPLETE **11**; corporate **12/12** + repo COMPLETE verify; remote COMPLETE **1442**; empty **0**; FRESH `projgen-1e79a513…`; further tip/history **DEFER** site timeout; year-archive sort fix |
| [`docs/proof/w0814_g9_jsda_20260814.md`](proof/w0814_g9_jsda_20260814.md) | **G9 JSDA**: OTC **+3** (`2026-08-03/04/05` runs **901241–901243**) → COMPLETE **9**; corporate **+11** annual 2015–2025 + full 2026 re-seal → **12/12 dataset COMPLETE** (runs **901244–901255**); repo verify COMPLETE; remote COMPLETE **1056**; empty **0**; FRESH `projgen-e1b67b…`; history DEFER |
| [`docs/proof/w0814_g4_master_residual_20260814.md`](proof/w0814_g4_master_residual_20260814.md) | **G4 `w0814_g4_master` residual**: plan **21** (`2006-08…2008-04`); acq wave1 **0p/21f** + retry **0p/21f** (400 sub + 429×20); seal window_ok **0** / window_bad **21** DEFER; COMPLETE **220→220 (+0)**; C8 pass lag1; FRESH `projgen-14c0bb…`; empty **0** |
| [`docs/proof/w0713_instruction_final_20260814.md`](proof/w0713_instruction_final_20260814.md) | **W0713 instruction final T1–T17**: PRE tip `83fe7c0` raw **7917** COMPLETE **585** 停滞4 **12/94/32/32** → POST raw **9687**/c **8567** COMPLETE **942** 停滞4 **42/220/82/69**; reeval×5 C8 pass; FRESH `projgen-98b032…` age=0; empty **0**; Mass NO-GO; Phase7 OFF |
| [`docs/proof/g7_t9_t10_margin_inv_20260814.md`](proof/g7_t9_t10_margin_inv_20260814.md) | **G7 T9+T10 `w0713_t7_margin_inv`**: plan **970** → wave1 **918p/52f** + retry **52/52** = **970/970**; host POST/min **9.61**; raw **8008→9687**; short_sale start **2013-11-01**; **C8 margin pass lag2 held**; COMPLETE +N **0**; empty **0**; FRESH `projgen-f15c9…` |
| [`docs/proof/w0713_t6_deriv_edinet_20260814.md`](proof/w0713_t6_deriv_edinet_20260814.md) | **G6 T7+T8 w0713_t6_deriv_edinet**: acq 2025 (main 41p/19f + retry 48/48); seals **+60** (futures/opt225/edinet×3 **2025-01…12**); COMPLETE **882→942**; observed_start **`2025-01-01`**; options full 2025 **DEFER**; empty **0**; FRESH `projgen-08c14…` |
| [`docs/proof/w0713_t4_breakdown_close_20260814.md`](proof/w0713_t4_breakdown_close_20260814.md) | **G4 T4 markets_breakdown close**: residual week-jobs **40p/4f**; R2 seal map **36/36** ready; issue **+36** (`2015-04…2018-03` **900927–900962**); COMPLETE **32→69 (+37)**; platform COMPLETE **882**; empty **0**; FRESH `projgen-b8c5…` |
| [`docs/proof/w0713_t2_master_close_20260814.md`](proof/w0713_t2_master_close_20260814.md) | **G2 T2 equities_master close**: backfill **63p/84f**; window-ok seal **+126** COMPLETE **94→220**; 21 misdated months DEFER; empty **0** |
| [`docs/proof/w0713_t1_bars_close_20260814.md`](proof/w0713_t1_bars_close_20260814.md) | **G1 T1 equities_bars_daily close**: exec **86p/34f** + retry **21p/1f**; R2 seal **30** ready; COMPLETE **12→42 (+30)**; empty **0** |
| [`docs/proof/w0713_t5_fins_residual_seal_20260814.md`](proof/w0713_t5_fins_residual_seal_20260814.md) | **G5 w0713_t5_fins residual seal**: R2 raw-only **48/48** ready; issue **+18** (summary **+12** / details **+1** / div **+1** / earn_date **+4**); remote COMPLETE **742**; fins COMPLETE **42/35/14/14**; raw_n **9455**; C8 pass×4; empty COMPLETE **0**; no fins/general pool acq |
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
| W0713 T1–T17 instruction final close | **DONE** (2026-08-14 ~00:49Z: remote D1 measure; reeval×5 C8 pass; FRESH `projgen-98b032…` age=0; raw **9687**/c **8567**; COMPLETE **942**; 停滞4 **42/220/82/69**; empty **0**; proof `w0713_instruction_final_20260814.md`) |
| W0814 all-sources G10 closed circuit | **DONE** (2026-08-14 ~01:32Z: monitor ~18m; reeval×5 C8 pass; FRESH `projgen-d28bfce…`; raw **10662**; COMPLETE **1106**; topix **220**; empty **0**; proof `w0814_all_sources_wave_20260814.md`) |
| W0814 G2 markets_breakdown residual seal | **DONE** — residual **48p/72f** + retry **80p/0f**; seal+issue **+36** (`2018-04…2021-03`); COMPLETE **69→105**; platform **1376**; C8 pass lag1; empty **0**; proof [`w0814_g2_breakdown_20260814.md`](proof/w0814_g2_breakdown_20260814.md) |
| W0814 all-sources FINAL wave sync | **DONE** (2026-08-14 ~02:38Z: remote measure; reeval×5 C8 pass; FRESH `projgen-f1d9b952…` age=0; raw **10701**/c **9129**; COMPLETE **1376**; mb **105**; empty **0**; proof `w0814_all_sources_final_20260814.md`) |
| W0814b all-sources W2-G9 close | **DONE** (2026-08-14 ~03:29Z: issue margin/alert/short_ratio/mb; publish fail-closed; reeval×5 C8 pass; FRESH `projgen-16cfbaa5…`; raw **11242**/c **9670**; COMPLETE **1478**; empty **0**; peers not killed; proof `w0814b_all_sources_wave_20260814.md`) |
| G6 t6_deriv_edinet (T9+T10) seal + reeval | **DONE** (worker 22p/1f; +18 seals vs G7 → **538**; options_near closed by T9 2026-08-14) |
| T9 options_near week-chunk + seal | **DONE** (9/9 pass; COMPLETE **+2** Jun/Jul; later T12 → **585**) |
| T12 fins raw seals (details+summary) | **DONE** (**+45** → COMPLETE **585**; empty-raw ban; proof `t12_receipts_wave_20260814.md`) |
| G5 w0713_t5_fins residual seal (summary+details+div+earn) | **DONE** — R2 raw-only **48/48** ready; issue **+18** (summary **+12** / details **+1** / div **+1** / earn_date **+4**); remote COMPLETE **742**; fins COMPLETE **42/35/14/14**; C8 pass×4; empty COMPLETE **0**; no fins/general pool acq; proof [`w0713_t5_fins_residual_seal_20260814.md`](proof/w0713_t5_fins_residual_seal_20260814.md) |
| G5 w0814_g5_fins residual (summary+details+div+earn) | **DONE** — acq **48/48** pass host **2.0**; R2 seal **48/48**; issue **+48**; remote COMPLETE **1339**; fins COMPLETE **54/47/26/26**; C8 pass×4; empty **0**; fins pool only; proof [`w0814_g5_fins_residual_20260814.md`](proof/w0814_g5_fins_residual_20260814.md) |
| bars `observed_start` receipt-plane union | **DONE** (remote **`2008-05-01`**) |
| multi-track bars/fins/topix paced execute + host rpm proof | **DONE** (bars 280; fins FINAL 288; topix3 192; see multi-track + T5 proof) |
| fins_summary `observed_start` history deepen | **DONE** (remote **`2008-07-01`** via T5 pre-2014 paced 72/72 + FINAL reeval; empty 2008-01…06 shells; COMPLETE segs **54** via T12+G5 waves not dataset COMPLETE) |
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
| `markets_margin_interest` monthly TRUSTED seal | **partial** — COMPLETE **49** (`2013-01…2015-08` band + tips); further **DEFER** |
| G8 misc residual seal (margin family + investor) | **DONE** (+80; proof `w0814_g8_misc_20260814.md`) |
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
- **Segment COMPLETE = 882** counts every COMPLETE segment across datasets (calendar 224 + G1 bars / G2 master / G3 topix / G4 breakdown / fins / JSDA / A3 / T9… seals, etc.).
- Next honest +N requires additional **real raw** (R2 or official fetch) + structured + signed SUCCESS; do not invent.
- Post-G6: major/cross/large_volume/futures/options_225 all **2026-01…08** COMPLETE; options **2026-06/07/08** (T9).
- G5 w0814_g5_fins: fins_summary COMPLETE segs **54**; fins_details **47**; dividend **26**; earnings_date **26**; remaining history months **DEFER** next seal wave (raw inventory remains).
- **G1 bars:** COMPLETE **42** (`2008-05…2010-10` + tip islands); further history after 2010-10 **DEFER** next seal wave.
- **G2 master:** COMPLETE **220**; **21** misdated pre-2008-05 R2 pages **DEFER** (not sealed).
- **G4/G2/w0814b breakdown:** COMPLETE **116** (`2015-04…2021-03` + `2021-04…2022-04` subset + tips); **2022-05…2023-11** + pre-2015-03 **DEFER** next seal wave.
- **W2-G9 w0814b close:** PRE raw **10702**/COMPLETE **1376** → POST **11242/1478**; FRESH `projgen-16cfbaa5…`; empty **0**; peers not killed.
- G8: OTC tip **2026-08-14** sealed; `indices_bars_daily` **7** COMPLETE months; further OTC/history **DEFER**.
- t5_div_pre: `fins_dividend` worker **120/120** pre-2018; `observed_start` **2013-02-01**; later G9/G5 sealed **2018-01…12**.
- OTC archive +N blocked when `market.jsda.or.jp` times out and no R2 raw for candidate days (CF worker can still land tip files).
- Full publish resets breakdown/margin `observed_*` toward hot facts — always re-run `ops_reeval_observed_window.py` for focus datasets after apply.
- Coordinate `cf_premium_backfill` on **general** with live peers; prefer ≤40 RPM single worker. Mass / READY **NO-GO**. Fins residual acq uses **fins pool only** (`--fins-rpm` / `--fins-workers`).
- T5 close: runner natural exit (PID dead); **no** empty COMPLETE; issue_receipts this close **+0** (T12 already sealed ready months).
- t5_div_pre: PID **43684** natural exit; **no** kill / **no** double-run; empty COMPLETE **0**.
- G5 w0713_t5_fins: seal-only (no acq); issue **+18**; empty COMPLETE **0**; peers not killed.
- G5 w0814_g5_fins: acq **48/48** + seal/issue **+48**; empty COMPLETE **0**; fins pool only; peers not killed.
- G4 w0713_t4_mb: residual backfill natural exit; seal-only +36 issue; empty COMPLETE **0**; peers not killed.
- G2 w0814_g2_mb: residual+retry natural exit; seal+issue **+36**; COMPLETE **105**; empty COMPLETE **0**; peers not killed; FINAL sync raw **10701** / COMPLETE **1376**.

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
