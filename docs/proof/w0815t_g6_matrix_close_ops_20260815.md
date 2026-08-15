# W27-G6 — w0815t matrix close + docs/ops (T6–T15) (2026-08-15)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0**  
**force-apply:** **not** used (fail-closed guard held; local==remote **3457**)  
**peers killed:** **0**  
**Worker pass ≠ COMPLETE:** held  
**DEFER densify re-run:** **not** done (policy)  
**G6 role:** **T6–T7** seal close from peer matrices · **T8–T9** tip densify only non-DEFER NO_RAW (prefer DEFER) · **T10** CF-SoT language lock · **T11** residual **残 seg × raw 有無** aggregate · **T12–T15** FRESH / last_run / throughput with COMPLETE seg Δ · **push**

**Live verified:** 2026-08-15 (JST) / ~2026-08-15T02:47Z UTC  
**Wave start HEAD:** `306bebb2febf835032abf3bc210f755338b8caac`  
**Projection:** **FRESH** `projgen-2ef0e4ae259f4f61b30856fe2ceff350`  
**Artifacts:** `.glm-logs/w0815t_g6_ops/` (`PRE_remote.json`, `POST_remote.json`, `FINAL_metrics.json`, `matrix/unified_matrix_summary.json`, `publish.log`, `reeval_freshness.log`, `last_run_monitor.json`)

## Peer matrix sources (waited G1–G5)

| Peer | Log | Matrix artifact |
|------|-----|-----------------|
| **G1** fins_dividend | `.glm-logs/w0815t_g1_fins_div/` | `matrix.json` |
| **G2** fins_earnings_date | `.glm-logs/w0815t_g2_fins_earn/` | `matrix/matrix_summary.json`, `has_raw_sealable.json` |
| **G3** fins_details | `.glm-logs/w0815t_g3_fins_details/` | `matrix_summary.json`, `matrix/partial_cf_raw_matrix.json` |
| **G4** equities_bars_daily | `.glm-logs/w0815t_g4_bars/` | `pre/partial_x_raw_matrix.json` |
| **G5** EDINET | `.glm-logs/w0815t_g5_edinet/` | `matrix_residual_x_nz.json`, `scan_summary.json` |
| **G6** aggregate | `.glm-logs/w0815t_g6_ops/` | `matrix/unified_matrix_summary.json` |

## PRE / POST (remote D1 `quant-ingest`)

| Metric | PRE (~02:38Z) | POST (~02:47Z) | Δ |
|--------|--------------:|---------------:|--:|
| `raw_retention_manifests` | **15145** | **15145** | **0** |
| Segment COMPLETE total | **3457** | **3457** | **0** |
| Dataset COMPLETE | **11** | **11** | held |
| Dataset STALE | **0** | **0** | 0 |
| empty COMPLETE | **0** | **0** | held |
| FRESH generation | `projgen-69d0bd86…` | `projgen-2ef0e4ae…` | reclocked |
| `jsda_otc` COMPLETE | **72** | **72** | held (D5 archive DEFER) |
| `fins_summary` COMPLETE / PARTIAL | **218** / **6** | **218** / **6** | held (D10) |
| `tokyo_repo_rows` (easy) | local **30303** / D1 hot **252** | local **30303** / D1 hot **252** | held (plane split) |

### Dataset COMPLETE set (remote POST)

| dataset | status |
|---------|--------|
| `markets_calendar` | **COMPLETE** (held) |
| `jsda_tokyo_repo_rates` | **COMPLETE** (held) |
| `jsda_corporate_bond_transactions` | **COMPLETE** (held) |
| `edinet_major_shareholders` | **COMPLETE** (held) |
| `equities_investor_types` | **COMPLETE** (held) |
| `markets_margin_alert` | **COMPLETE** (held) |
| `markets_margin_interest` | **COMPLETE** (held) |
| `markets_short_ratio` | **COMPLETE** (held) |
| `derivatives_bars_daily_futures` | **COMPLETE** (held) |
| `derivatives_bars_daily_options_225` | **COMPLETE** (held) |
| `derivatives_bars_daily_options` | **COMPLETE** (held) |

### Key segment COMPLETE (remote PRE→POST)

| dataset | PRE | POST | Δ | note |
|---------|----:|-----:|--:|------|
| `jsda_otc_bond_reference_prices` | **72** | **72** | **0** | tip held; archive PARTIAL **8709** DEFER D5 |
| `fins_summary` | **218** | **218** | **0** | residual PARTIAL **6** DEFER D10 held |
| platform total | **3457** | **3457** | **0** | matrix seal gap empty |

## T6–T7 — seal close remaining HAS_RAW_SEALABLE

From peer matrices: **no** residual segment classifies as **HAS_RAW_SEALABLE** (nz COMPLETE raw + params/data window_ok + PARTIAL unsealed).

| dataset | HAS_RAW_SEALABLE | closed this wave | disposition |
|---------|-----------------:|-----------------:|-------------|
| `fins_dividend` | **0** | **0** | EMPTY_SHELL **61** DEFER pre-history |
| `fins_earnings_date` | **0** | **0** | NO_RAW_FOR_MONTH **100** DEFER (pre2018 + tip `2026-01…04`) |
| `fins_details` | **0** | **0** | DEFER_PRE2018_EMPTY **120** |
| `equities_bars_daily` | **0** | **0** | ALL_52_PRE_FLOOR_DEFER (NO_RAW **31** + EMPTY **21**) |
| `edinet_cross_shareholdings` | **0** | **0** | DEFER_EMPTY_API_FIXED **28** |
| `edinet_large_volume_shareholders` | **0** | **0** | DEFER_EMPTY_API_FIXED **42** |
| `edinet_major_shareholders` | **0** | **0** | COMPLETE **104/104** verify-only |
| **TOTAL** | **0** | **0** | **0 ok** |

G6-owned issue/restore: **0**. Empty-raw ban held. No dual-issue.

## T8–T9 — tip densify (non-DEFER NO_RAW only)

**Primary densify: not run.** Policy: densify only if matrix shows **NO_RAW** for **non-DEFER** tip holes (rare). Prefer **DEFER fix** for empty history.

| Item | Result |
|------|--------|
| G2 tip `2026-01…04` | NO_RAW_FOR_MONTH but **DEFER** `tip_2026_01_04` — densify **SKIP** |
| G2 densify_summary | `decision=SKIP` reason=DEFER known empty only; no tip-densify-as-success |
| Non-DEFER tip NO_RAW holes | **0** |
| G6 densify jobs | **0** |

## T10 — CF-SoT language (column_null_audit / JSDA)

Scan of `docs/proof/column_null_audit_20260815.md`, `docs/proof/w0815m_g4_jsda_audit_20260815.md`, `docs/proof/jsda_hot_d1_publish_20260815.md`:

| Check | Result |
|-------|--------|
| Affirmative “local SoT” claims | **none** remaining |
| Negation lock language | **held** (“not local SoT”; mirror only) |
| CF SoT | **D1 = hot tip · R2 = history · COMPLETE = receipt-owned** |
| Edits this wave | **0** (already locked W24-G1 / W25-G1) |

## T11 — residual SoT: 残 seg × raw 有無 (unified)

Canonical aggregate: `.glm-logs/w0815t_g6_ops/matrix/unified_matrix_summary.json`  
Also mirrored into `docs/phase62_residual_status.md` (this wave header + matrix table).

| dataset | 残 seg | raw 有 (HAS_RAW_SEALABLE) | raw 空 (EMPTY) | raw 無 (NO_RAW) | closed Δ | disposition |
|---------|-------:|-------------------------:|---------------:|----------------:|----------:|-------------|
| `fins_dividend` | 61 | 0 | 61 | 0 | 0 | DEFER empty pre-history |
| `fins_earnings_date` | 100 | 0 | 0 | 100 | 0 | DEFER pre2018 + tip `2026-01…04` |
| `fins_details` | 120 | 0 | 120 | 0 | 0 | DEFER_PRE2018_EMPTY |
| `equities_bars_daily` | 52 | 0 | 21 | 31 | 0 | DEFER_PRE_FLOOR D7 |
| `edinet_cross_shareholdings` | 28 | 0 | 28 | 0 | 0 | DEFER_EMPTY_API D6 |
| `edinet_large_volume_shareholders` | 42 | 0 | 42 | 0 | 0 | DEFER_EMPTY_API D6 |
| `edinet_major_shareholders` | 0 | 0 | 0 | 0 | 0 | COMPLETE held |
| `fins_summary` | 6 | 0 | 6 | 0 | 0 | DEFER D10 |
| `markets_short_sale_report` | 10 | 0 | 10 | 0 | 0 | DEFER D9 |
| `indices_bars_daily` | 4 | 0 | 4 | 0 | 0 | DEFER D1 |
| `indices_bars_daily_topix` | 4 | 0 | 4 | 0 | 0 | DEFER D1 |
| `markets_breakdown` | 27 | 0 | 27 | 0 | 0 | DEFER D3 |
| `equities_master` | 94 | 0 | 0 | 94* | 0 | DEFER D2 (*misdate/no in-window nz) |
| `equities_earnings_calendar` | 199 | 0 | 0 | 0 | 0 | DEFER D4 tip-date |
| `equities_bars_daily_am` | 31 | 0 | 0 | 0 | 0 | DEFER D4 tip-only |
| `jsda_otc_bond_reference_prices` | 8709 | 0 | 0 | 8709 | 0 | DEFER D5 site |

\* master residual is misdate / pre-plan (params may look OK; data Date not in-window) — not sealable.

## T12–T15 — FRESH / last_run / throughput / push

### Publish + reeval

```text
publish_ops_projection --apply-remote
  complete_count_guard ok local=3457 remote=3457 force=False → applied
  dual-coord: waited peer w0815s_g4_ops ops_loop (cycles 13–14) → DEAD then publish
  no --force

ops_reeval_freshness
  → projgen-2ef0e4ae259f4f61b30856fe2ceff350
  coverage_segments_untouched=1 mass=NO-GO
```

### last_run monitor (no peer kill)

| Track | state | Action |
|-------|-------|--------|
| `w0815s_g4_ops` ops_loop | **ALIVE** mid-window → **DONE** | leave alone; dual-publish skip until dead |
| peer issue workers | **none** | free for G6 publish |
| G1–G5 matrix builders | finished matrices | HAS_RAW_SEALABLE **0** all |

### Throughput (session COMPLETE seg Δ)

| Track | host POST/min | n | note |
|-------|--------------:|--:|------|
| G6 matrix seal/issue | — | **0** | HAS_RAW_SEALABLE empty |
| G6 tip densify | — | **0** | DEFER policy |
| Session raw Δ | — | **0** | 15145→15145 |
| Session COMPLETE seg Δ | — | **0** | 3457→3457 |
| Dataset COMPLETE count | — | **11** | held |
| general catalog target rpm | — | **~495** | note (not re-run this wave) |
| fins separate pool | — | yes | held |

## Gates

| Gate | Status |
|------|--------|
| empty COMPLETE | **0** held |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| force-apply | **not** used |
| peers killed | **0** |
| CF-SoT language | **CONFIRMED** |
| DEFER densify | **not** re-run |

## Residual SoT live-sync

Updated `docs/phase62_residual_status.md` LIVE header/snapshot to remote POST **3457** / raw **15145** / Dataset COMPLETE **11** / FRESH `projgen-2ef0e4ae…` / OTC **72** + **W27-G6** unified matrix summary table.

This proof: `docs/proof/w0815t_g6_matrix_close_ops_20260815.md`
