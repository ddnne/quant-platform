# W67 / w0816a — fins_earnings_date COMPLETE expand attempt (honest) (2026-08-16)

**Wave:** W67 / `w0816a`  
**Task A:** mandatory honest path for `fins_earnings_date` tip months `2026-01…04`  
**As of (live D1):** `2026-08-15T15:29:40Z`  
**Repo tip at write:** `9145011e241500e9971dcfe135946d2e8dad5875`  
**Mass / READY / Phase7:** **not touched**  
**Commit/push:** **not done** (D agent owns)

## Policy held (residual + permanent_defer)

| gate | value |
|------|-------|
| **PD-MX-EARN-TIP** | `fins_earnings_date` tip `2026-01…04` — **PERMANENT_DEFER FINAL (W44)** |
| densify-as-success | **FORBIDDEN** · **not used** |
| empty-raw COMPLETE | **FORBIDDEN** · **not invented** |
| invent COMPLETE 22 | **FORBIDDEN** |
| actionable_gap | **0** held unless vendor nz appears |
| S1–S5 un-reject | **not done** |
| Mass / READY | **not done** |

Canonical code lock: [`packages/data_plane/data_contracts/permanent_defer.py`](../../packages/data_plane/data_contracts/permanent_defer.py) (`fins_earnings_date` → `PD-MX-EARN-TIP`).  
Residual SoT: [`docs/phase62_residual_status.md`](../phase62_residual_status.md) §W44/W47.

---

## Before (required baseline)

| item | value |
|------|------:|
| `fins_earnings_date` complete_segments | **100/104** |
| Dataset COMPLETE | **21** |
| Tip residual | **4** = `2026-01…04` PARTIAL (PD-MX-EARN-TIP) |

---

## After (live remote D1)

Method: `wrangler d1 execute quant-ingest --remote` under `platform/workers/ingestion-premium` via `.glm-logs/w0816a_w67_coverage/d1q.py` (retry 7403).

| item | before | after | Δ |
|------|-------:|------:|--:|
| `fins_earnings_date` COMPLETE segs | **100** | **100** | **+0** |
| `fins_earnings_date` PARTIAL segs | **4** | **4** | **+0** |
| complete_segments ratio | **100/104** | **100/104** | **+0** |
| Dataset COMPLETE | **21** | **21** | **+0** |
| Platform COMPLETE segs (all datasets) | — | **3478** | held |
| empty COMPLETE | — | **0** | held |
| sealed this wave | — | **0** | |
| densify executed | — | **0** | |

### Status counts (`fins_earnings_date`)

| status | n | min segment | max segment |
|--------|--:|------------|-------------|
| COMPLETE | **100** | `2018-01` | `2026-08` |
| PARTIAL | **4** | `2026-01` | `2026-04` |

### Tip segments `2026-01…04` (live)

| segment_id | status | segment_start | segment_end | receipt_run_id |
|------------|--------|---------------|-------------|----------------|
| `2026-01` | **PARTIAL** | 2026-01-01 | 2026-01-31 | null |
| `2026-02` | **PARTIAL** | 2026-02-01 | 2026-02-28 | null |
| `2026-03` | **PARTIAL** | 2026-03-01 | 2026-03-31 | null |
| `2026-04` | **PARTIAL** | 2026-04-01 | 2026-04-30 | null |

### COMPLETE island

- COMPLETE **100**: continuous `2018-01…2025-12` + `2026-05…08`
- Holes in span `2018-01…2026-08`: **exactly** `2026-01`, `2026-02`, `2026-03`, `2026-04`
- Dataset remains **PARTIAL** (not dataset-level COMPLETE)

### Dataset COMPLETE list (n=21, `fins_earnings_date` **absent**)

`derivatives_bars_daily_futures`, `derivatives_bars_daily_options`, `derivatives_bars_daily_options_225`, `edinet_cross_shareholdings`, `edinet_large_volume_shareholders`, `edinet_major_shareholders`, `equities_bars_daily`, `equities_investor_types`, `fins_details`, `fins_dividend`, `fins_summary`, `indices_bars_daily`, `indices_bars_daily_topix`, `jsda_corporate_bond_transactions`, `jsda_tokyo_repo_rates`, `markets_breakdown`, `markets_calendar`, `markets_margin_alert`, `markets_margin_interest`, `markets_short_ratio`, `markets_short_sale_report`

---

## Probe — HAS_RAW_SEALABLE / window_ok nz (tip only)

**Probe only.** No densify execute. No empty COMPLETE seal.

### Dry-run planner (status tool first)

```text
mode=dry-run plan_jobs=4 queued=4 executed=0
datasets=fins_earnings_date from=2026-01-01 to=2026-04-30
fins-rpm=80 fins-workers=1
by_dataset={"fins_earnings_date": 4}
queued_segments=2026-01,2026-02,2026-03,2026-04
dry-run complete (no /v1/run)
```

Planner residual still surfaces the 4 tip months as pending jobs. That is **not** sealable-raw evidence; worker pass ≠ Coverage COMPLETE.

### R2/D1 raw inventory (window_ok nz)

Scanned **247** `raw_retention_manifests` with `completeness='COMPLETE' AND row_count>0` for `fins_earnings_date`; loaded all manifests from R2.

| probe field | value |
|-------------|------:|
| nz manifests scanned | **247** |
| tip param hits (from/to month in `2026-01…04`) | **0** |
| window_ok nz tip | **0** |
| HAS_RAW_SEALABLE any tip month | **false** |
| zero-row tip month manifests (sample 38 zeros) | **0** |
| seal decision | **NO_SEAL** |

No manifest params window maps to tip months `2026-01…04` with `row_count>0`. Nearby 2026 COMPLETE months (`2026-05…08`) already sealed; tip hole remains empty.

---

## Per-month disposition `2026-01…04`

| month | live status | disposition | reason |
|-------|-------------|-------------|--------|
| `2026-01` | PARTIAL | **PERMANENT_DEFER / NO_RAW** | NO_RAW_FOR_MONTH_TIP · PD-MX-EARN-TIP FINAL (W44) · window_ok nz **0** |
| `2026-02` | PARTIAL | **PERMANENT_DEFER / NO_RAW** | same |
| `2026-03` | PARTIAL | **PERMANENT_DEFER / NO_RAW** | same |
| `2026-04` | PARTIAL | **PERMANENT_DEFER / NO_RAW** | same |

**Sealed this wave:** **0**  
**If raw had appeared with nz:** real seal path would be raw → structured → signed receipt → ledger. **Did not apply** (no nz).

---

## Honesty explicit

- **densify not used** (densify-as-success FORBIDDEN for PD-MX-EARN-TIP)
- **empty COMPLETE not invented** (empty-raw COMPLETE FORBIDDEN)
- **COMPLETE 22 not invented** (Dataset COMPLETE held **21**)
- **actionable_gap = 0** held (vendor nz did not appear)
- Did **not** un-reject S1–S5
- Did **not** Mass / READY
- Did **not** commit/push

---

## Wave A result

### **wave A incomplete for COMPLETE expand**

| field | value |
|-------|-------|
| outcome | **INCOMPLETE** for COMPLETE expand |
| block reason | **NO_RAW_FOR_MONTH_TIP** on `2026-01…04`; **PD-MX-EARN-TIP FINAL (W44)**; **HAS_RAW_SEALABLE=0**; densify forbidden; empty COMPLETE forbidden |
| complete_segments | held **100/104** |
| Dataset COMPLETE | held **21** (not 22) |
| cure condition | vendor nz raw for tip residual months + real seal path (raw→structured→signed receipt→ledger); **no densify-as-success** |

No miraculous raw; no Dataset COMPLETE 21→22.

---

## Machine logs (gitignored OK)

Prefix: [`.glm-logs/w0816a_w67_coverage/`](../../.glm-logs/w0816a_w67_coverage/)

| artifact | purpose |
|----------|---------|
| `d1q.py` | remote D1 helper (retry 7403) |
| `q_fins_status_counts.json` | status counts |
| `q_fins_tip_segments.json` | tip month rows |
| `q_fins_complete_segments.json` | COMPLETE segment list (n=100) |
| `q_fins_all_segments_span.json` | 100/104 span |
| `q_platform_complete.json` | platform COMPLETE segs |
| `q_dataset_complete_n.json` | Dataset COMPLETE n |
| `q_dataset_complete_list.json` | Dataset COMPLETE list |
| `q_empty_complete.json` | empty COMPLETE guard |
| `q_raw_manifests_*.json` | raw_retention_manifests probes |
| `dry_tip_plan.json` / `dry_tip_queue.json` / `dry_tip_run.log` | dry-run tip window |
| `probe_tip_raw_sealable.json` | HAS_RAW_SEALABLE probe result |
| `manifests/` | R2 manifest cache for probe |
| `LIVE_D1_SNAPSHOT.json` | assembled live snapshot |
| `FINAL_metrics.json` | before/after machine metrics |

---

## Exact numbers (return)

```text
BEFORE: complete_segments=100/104  dataset_complete=21
AFTER:  complete_segments=100/104  dataset_complete=21  platform_complete_segs=3478  empty_complete=0
DELTA:  complete_segments=+0  dataset_complete=+0  sealed_n=0  densify_executed=0
TIP:    2026-01..04 all PARTIAL · NO_RAW · PD-MX-EARN-TIP PERMANENT_DEFER FINAL
WAVE A: INCOMPLETE for COMPLETE expand
BLOCK:  NO_RAW_FOR_MONTH_TIP + PD-MX-EARN-TIP FINAL + HAS_RAW_SEALABLE=0
```
