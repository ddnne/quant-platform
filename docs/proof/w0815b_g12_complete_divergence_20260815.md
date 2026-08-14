# W10-G12 / T19 — Dataset COMPLETE 集計 vs backfill 乖離 reconcile (2026-08-15)

**Wave:** `w0815b` / **W10-G12** / **T19**  
**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0**  
**empty-raw ban:** held  
**force-apply:** **not** used (fail-closed guard held)  
**peers killed:** **0** (W9/W10 peers + `w0815_g6_ops` ops_loop left alive)

**Live verified:** 2026-08-15 (JST) / ~2026-08-14T15:44Z UTC  
**Projection:** **FRESH** `projgen-09aa8c742d25435db16dc61c27b3ab5c` (ops_loop concurrent reclock after G12 reeval `projgen-b8c531cb…`)

## Verdict (one line)

**Earlier residual SoT “Dataset COMPLETE = 3” was correct for `dataset_coverage.status`.**  
**Instruction “Dataset COMPLETE (backfill) = 5” was correct for `backfill_status` / segment-ratio.**  
**After G12 surgical re-aggregate + fail-closed publish, both surfaces agree: Dataset COMPLETE = 5.**

## Surface definitions (do not conflate)

| Surface | How COMPLETE is counted | Pre-G12 | Post-G12 |
|---------|-------------------------|--------:|---------:|
| **`dataset_coverage.status`** (ops MCP `dataset_coverage` / residual SoT “Dataset COMPLETE”) | Coverage V2 aggregate row; COMPLETE only when inventory segments are all COMPLETE **and** aggregate was re-evaluated/promoted | **3** | **5** |
| **`backfill_status` state** (ops MCP `backfill_status` / `backfill_status_rows`) | `complete_segments == required_segments` → `COVERAGE_COMPLETE` (segment ratio only; no C* re-score) | **5** | **5** |
| **Segment COMPLETE total** | `COUNT(*)` on `coverage_segments` where `status='COMPLETE'` | ~2854…2902 (peer concurrent) | **2922** (remote at close) |

Code anchors:

- `backfill_status` → `platform/workers/quant-ops-mcp/src/domain.js` (`complete === required` → `COVERAGE_COMPLETE`)
- Python twin → `packages/data_plane/ops/backfill_planner.py::backfill_status_rows`
- Aggregate rule → `packages/data_plane/storage/README.md` + `coverage_ledger.py` (all required segments COMPLETE ⇒ dataset COMPLETE after refresh)

## Why residual said 3 while backfill said 5

| dataset | segs COMPLETE/total | `backfill_status` | pre `dataset_coverage.status` | reason |
|---------|--------------------:|-------------------|-------------------------------|--------|
| `markets_calendar` | 224/224 | `COVERAGE_COMPLETE` | **COMPLETE** | aligned |
| `jsda_tokyo_repo_rates` | 1/1 | `COVERAGE_COMPLETE` | **COMPLETE** | aligned |
| `jsda_corporate_bond_transactions` | 12/12 | `COVERAGE_COMPLETE` | **COMPLETE** | aligned |
| **`equities_investor_types`** | **164/164** | **`COVERAGE_COMPLETE`** | **PARTIAL** (stale) | inventory full since W8-G12 T13 residual seal (+58); aggregate never re-promoted (`restore_local_complete_from_receipt` + issue path update segs only; `ops_reeval_*` explicitly does **not** force dataset COMPLETE) |
| **`edinet_major_shareholders`** | **104/104** | **`COVERAGE_COMPLETE`** | **PARTIAL** (stale) | inventory full since W7-G5 (+12 → 104/104); same aggregate lag; residual noted “reeval holds PARTIAL” |

Stale evidence pre-fix (remote `detail_json.coverage_v2.status_counts` **lagged** live segs):

| dataset | live segs | stale `status_counts` in detail |
|---------|----------:|----------------------------------|
| `equities_investor_types` | 164 COMPLETE / 0 PARTIAL | COMPLETE **106** / PARTIAL **58** |
| `edinet_major_shareholders` | 104 COMPLETE / 0 PARTIAL | COMPLETE **92** / PARTIAL **12** |

C1–C8 checks already **pass** on both (no validation block). History inventory matches contract:

| dataset | `history_target_start` | segment_id range | inventory |
|---------|------------------------|------------------|-----------|
| `equities_investor_types` | `2013-01-04` | `2013-01` … `2026-08` | 164 months |
| `edinet_major_shareholders` | `2018-01-04` | `2018-01` … `2026-08` | 104 months |

## Fix applied (G12)

1. **Surgical re-aggregate** (local research DB; segments **untouched**):
   - For each target: if `COUNT(COMPLETE) == COUNT(*)` and no failing `detail_json.checks` → set `dataset_coverage.status='COMPLETE'` and rewrite `coverage_v2.status_counts` to match live inventory.
   - Result local: investor + edinet_major **PARTIAL → COMPLETE**; platform dataset COMPLETE **3 → 5**.
2. **`publish_ops_projection.py --apply-remote`** fail-closed:
   - First attempt raced concurrent ops_loop import (`Not currently import at bookmark…`) → refused/failed cleanly.
   - Retry: `complete_count_guard ok local=2902 remote=2902 force=False` → **applied** (no `--force-apply-remote`).
3. **`ops_reeval_freshness.py`**: reclock FRESH; `coverage_segments_untouched=1`.
4. Concurrent **ops_loop** continued issuing ready seals (margin/fins/bars) and reclocked projection further — peers **not** killed.

## Remote D1 POST (governed 26)

**Live:** COMPLETE segs **2922** · raw_n **13924** · dataset_coverage **COMPLETE=5 / PARTIAL=21** · empty COMPLETE **0** · FRESH `projgen-09aa8c74…`

| dataset | COMPLETE/total | dataset_coverage | observed_start | observed_end |
|---------|---------------:|------------------|----------------|--------------|
| `derivatives_bars_daily_futures` | **92**/164 | **PARTIAL** | 2020-01-01 | 2026-08-12 |
| `derivatives_bars_daily_options` | **37**/164 | **PARTIAL** | 2024-07-01 | 2026-08-12 |
| `derivatives_bars_daily_options_225` | **92**/164 | **PARTIAL** | 2020-01-01 | 2026-08-12 |
| `edinet_cross_shareholdings` | **76**/104 | **PARTIAL** | 2020-05-01 | 2026-08-13 |
| `edinet_large_volume_shareholders` | **62**/104 | **PARTIAL** | 2021-07-01T09:05:00+09:00 | 2026-08-13 |
| **`edinet_major_shareholders`** | **104**/104 | **COMPLETE** | 2019-01-01 | 2026-08-13 |
| `equities_bars_daily` | **214**/272 | **PARTIAL** | 2008-05-01 | 2026-08-12 |
| `equities_bars_daily_am` | **1**/32 | **PARTIAL** | 2026-08-01 | 2026-08-14 |
| `equities_earnings_calendar` | **1**/200 | **PARTIAL** | 2010-01-04 | 2026-08-15 |
| **`equities_investor_types`** | **164**/164 | **COMPLETE** | 2012-12-28T00:00:00+09:00 | 2026-08-12 |
| `equities_master` | **220**/314 | **PARTIAL** | 2008-05-01 | 2026-08-12T00:00:00+09:00 |
| `fins_details` | **104**/224 | **PARTIAL** | 2018-01-01 | 2026-08-12 |
| `fins_dividend` | **98**/224 | **PARTIAL** | 2013-02-01 | 2026-08-12 |
| `fins_earnings_date` | **98**/200 | **PARTIAL** | 2018-01-01 | 2026-12-11T00:00:00+09:00 |
| `fins_summary` | **153**/224 | **PARTIAL** | 2008-07-01 | 2026-08-11 |
| `indices_bars_daily` | **220**/224 | **PARTIAL** | 2008-05-01 | 2026-08-14 |
| `indices_bars_daily_topix` | **220**/224 | **PARTIAL** | 2008-01-01 | 2026-08-15 |
| **`jsda_corporate_bond_transactions`** | **12**/12 | **COMPLETE** | 2015-11-02T15:00:00+09:00 | 2026-08-14 |
| `jsda_otc_bond_reference_prices` | **34**/8782 | **PARTIAL** | 2026-06-29T15:00:00+09:00 | 2026-08-17T15:00:00+09:00 |
| **`jsda_tokyo_repo_rates`** | **1**/1 | **COMPLETE** | 2012-10-29T15:00:00+09:00 | 2026-08-10T15:00:00+09:00 |
| `markets_breakdown` | **137**/164 | **PARTIAL** | 2015-03-26 | 2026-08-14 |
| **`markets_calendar`** | **224**/224 | **COMPLETE** | 2008-01-01T00:00:00+09:00 | 2026-08-12 |
| `markets_margin_alert` | **130**/164 | **PARTIAL** | 2012-12-28T00:00:00+09:00 | 2026-08-12 |
| `markets_margin_interest` | **149**/164 | **PARTIAL** | 2013-01-04 | 2026-08-13 |
| `markets_short_ratio` | **144**/164 | **PARTIAL** | 2013-01-04T00:00:00+09:00 | 2026-08-12 |
| `markets_short_sale_report` | **115**/164 | **PARTIAL** | 2012-01-10T00:00:00+09:00 | 2026-08-12 |

### Dataset COMPLETE = 5 (aligned)

1. `markets_calendar` (224/224)
2. `jsda_tokyo_repo_rates` (1/1)
3. `jsda_corporate_bond_transactions` (12/12)
4. **`equities_investor_types` (164/164)** — promoted this wave
5. **`edinet_major_shareholders` (104/104)** — promoted this wave

## Per-surface explanation (investor / edinet_major)

| Surface | investor_types | edinet_major | notes |
|---------|----------------|--------------|-------|
| **ops MCP `backfill_status`** | always `COVERAGE_COMPLETE` once 164/164 | always `COVERAGE_COMPLETE` once 104/104 | segment ratio only |
| **ops MCP `dataset_coverage`** | was PARTIAL (stale counts) → **COMPLETE** after publish | was PARTIAL (stale counts) → **COMPLETE** after publish | residual SoT follows this |
| **residual SoT (pre)** | PARTIAL 164 segs; Dataset COMPLETE **3** | PARTIAL 104/104; “reeval holds PARTIAL” | honest vs then-live `dataset_coverage` |
| **residual SoT (post)** | **COMPLETE** 164/164; Dataset COMPLETE **5** | **COMPLETE** 104/104; Dataset COMPLETE **5** | this proof |

Root cause (ops path lag): `scripts/restore_local_complete_from_receipt.py` and many issue/restore loops update **`coverage_segments` only** and never recompute `dataset_coverage` aggregate. Full `refresh_coverage_ledger` was often skipped under peer DB lock / time pressure; `ops_reeval_observed_window` / `ops_reeval_freshness` deliberately leave status un-promoted.

## T14–T18 support (concurrent ops)

| Ticket | Action | Result |
|--------|--------|--------|
| **T14** ready seals | Scan ready seal maps; skip peer-owned datasets (ops_loop margin/fins/bars, G4 short seal, G5 edinet, G8 topix/idx, G9 mb, G10 master, earn/am DEFER tip-dated) | **0** additional G12-owned issues (ops_loop already issuing; no dual-issue) |
| **T14** ops_loop (peer) | Live PID; issued **48** ready (fins_summary **27**, margin_interest **20**, bars **1**) | left alive |
| **T15** freshness | `ops_reeval_freshness` → FRESH; concurrent ops_loop reclock continued | live `projgen-09aa8c74…` |
| **T16** last_run | peers_alive (deriv paced, margin seal, bars seal, edinet acq, general acq, …) | **no kill / no dual-resume** |
| **T17** throughput snap | host POST/min from state jsonl | general wave ~**86**/min (n=386); fins wave1~**59**/min (429fail label); general w2 ~**9**/min |
| **T18** residual + proof | this file + `docs/phase62_residual_status.md` live-sync + push | mandatory |

## Leak-check

| Check | Result |
|-------|--------|
| empty COMPLETE | **0** |
| `--force-apply-remote` | **not** used |
| peers killed | **0** |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| dual-issue peer-owned ready | **not** done |
| empty-raw COMPLETE | **forbidden / held** |

## Explicit non-claims

- Other 21 governed datasets remain **PARTIAL** (segment inventory incomplete vs plan).
- `edinet_major` observed_start still **`2019-01-01`** on aggregate row (receipt/hot window lag); segment inventory **does** include **`2018-01…12` COMPLETE** — observed_* reeval optional follow-up, not required for COMPLETE status under inventory rule.
- No claim that backfill history beyond sealed inventory exists.
- No Mass / READY / Phase7 arming.

## Operator repro

```bash
# Remote segment ratio (backfill surface)
npx wrangler d1 execute quant-ingest --remote --command \
  "SELECT dataset,
     SUM(CASE WHEN status='COMPLETE' THEN 1 ELSE 0 END) AS complete,
     COUNT(*) AS total
   FROM coverage_segments GROUP BY dataset ORDER BY dataset;"

# Remote dataset_coverage (residual SoT surface)
npx wrangler d1 execute quant-ingest --remote --command \
  "SELECT dataset, status FROM dataset_coverage ORDER BY dataset;"

# After seals: if complete==total but status PARTIAL, re-aggregate then publish
# (surgical status rewrite from segment inventory; or full refresh_coverage_ledger)
.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite --apply-remote
.venv/bin/python scripts/ops_reeval_freshness.py
```

## Artifacts

| Path | Role |
|------|------|
| `docs/proof/w0815b_g12_complete_divergence_20260815.md` | this proof |
| `docs/phase62_residual_status.md` | live residual SoT sync |
| `data/ops/projection.sql` / `projection_meta.json` | last export used for apply |
