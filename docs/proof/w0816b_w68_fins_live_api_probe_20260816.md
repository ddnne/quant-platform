# W68 / w0816b — fins_earnings_date LIVE API probe + seal (2026-08-16)

**Wave:** W68 / `w0816b`  
**Task A:** LIVE API probe for `fins_earnings_date` tip months `2026-01…04` + seal if nz  
**As of (live D1 AFTER):** `2026-08-15T16:05:05Z`  
**Repo tip at write:** `090e407bd2d0e1e89fd20a8873ceb6ebc67f1e02`  
**Mass / READY / Phase7:** **not touched**  
**Commit/push:** **not done**

## Policy held

| gate | value |
|------|-------|
| empty-raw COMPLETE | **FORBIDDEN** · **held** (all sealed months had nz raw) |
| densify-as-success | **FORBIDDEN** · **not used** (live `/v1/run` only) |
| invent COMPLETE | **FORBIDDEN** · **not invented** (real R2 raw + signed receipts) |
| Mass / READY | **OFF** |
| rate limit | `--fins-rpm 80` `--fins-workers 1` |

Prior residual label **PD-MX-EARN-TIP** (W44) applied while tip was empty. This wave **vendor nz appeared** via live API; sealed on honest raw→structured→signed receipt→ledger path.

---

## Before (required baseline — live remote D1)

| item | value |
|------|------:|
| `fins_earnings_date` complete_segments | **100/104** |
| COMPLETE segs | **100** (`2018-01…2025-12` + `2026-05…08`) |
| PARTIAL segs | **4** = `2026-01…04` |
| Dataset COMPLETE (seg-derived) | **21** |
| Platform COMPLETE segs | **3478** |

### Tip segments BEFORE

| segment_id | status | receipt_run_id |
|------------|--------|----------------|
| `2026-01` | **PARTIAL** | null |
| `2026-02` | **PARTIAL** | null |
| `2026-03` | **PARTIAL** | null |
| `2026-04` | **PARTIAL** | null |

Artifacts: `.glm-logs/w0816b_w68_complete_delta/q_before_*.json`, `BEFORE_snapshot.json`

---

## LIVE API probe (must prove API hit — not inventory-only)

**Path:** `scripts/ops/cf_premium_backfill.py --execute`  
**Endpoint:** `POST …/v1/run?dataset=fins_earnings_date&from=…&to=…`  
**Worker:** `quant-platform-ingestion-premium.taku-haga.workers.dev`  
**Pool:** fins · `--fins-rpm 80` · `--fins-workers 1`

Dry-run first (plan only): `mode=dry-run plan_jobs=4 queued=4 executed=0`.

Then **per-month live execute** (not dry-run):

| month | from → to | HTTP | state | rowsInserted | R2 run_id | page_count | nz_pages | zero_pages | window_ok | empty vs nz |
|-------|-----------|-----:|-------|-------------:|----------:|-----------:|---------:|-----------:|:---------:|:-----------:|
| `2026-01` | 2026-01-01 → 2026-01-31 | **200** | pass | **608** | **14068** | 31 | 19 | 12 | **yes** | **nz** |
| `2026-02` | 2026-02-01 → 2026-02-28 | **200** | pass | **525** | **14069** | 28 | 18 | 10 | **yes** | **nz** |
| `2026-03` | 2026-03-01 → 2026-03-31 | **200** | pass | **3044** | **14070** | 31 | 21 | 10 | **yes** | **nz** |
| `2026-04` | 2026-04-01 → 2026-04-30 | **200** | pass | **788** | **14072** | 30 | 21 | 9 | **yes** | **nz** |

**LIVE_API_EMPTY:** **false** (all 4 months returned nz window_ok raw).

Manifest proof (R2 `raw/fins_earnings_date/{run_id}/manifest.json`):

- params.from/to same calendar month, full-month windows
- completeness=`COMPLETE`, row_count>0
- sample page fields: `PubDate`, `SchDate`, `Code`, …

Logs: `live_2026-0{1,2,3,4}_{run,queue,plan,state}.jsonl`, `live_api_results.json`, `manifests/`

---

## Seal path (only months with real nz raw — all 4)

Because **all months returned nz window_ok raw**:

1. **R2 → local raw + structured** (`seal_from_r2.py`, seal_map n=4)  
   - ready **4/4**: rows 608 / 525 / 3044 / 788  
   - raw written under `data/raw/jquants/2026/08/16/fins_earnings_date_from=…_from_r2_run{id}.json`
2. **Signed SUCCESS receipts** (`issue_signed_receipts_for_segments.py`)  
   - eligibility `TRUSTED_COLLECTION` + Ed25519 signatures  
   - run_ids: `2026-01`→**903892**, `2026-02`→**903890**, `2026-03`→**903889**, `2026-04`→**903888**
3. **Local COMPLETE restore** (`restore_local_complete_from_receipt.py` ×4)  
   - evaluate: `COMPLETE` / `receipt reconciled` / `event_zero=false`
4. **Remote publish** (`publish_ops_projection.py --apply-remote`)  
   - complete_count_guard ok local=**3482** remote=**3478**  
   - wrangler D1: **12564** queries, success

**Sealed this wave:** **4**  
**densify executed:** **0**

---

## After (live remote D1 recount)

| item | before | after | Δ |
|------|-------:|------:|--:|
| `fins_earnings_date` COMPLETE segs | **100** | **104** | **+4** |
| `fins_earnings_date` PARTIAL segs | **4** | **0** | **−4** |
| complete_segments ratio | **100/104** | **104/104** | **+4** |
| Dataset COMPLETE (seg-derived) | **21** | **22** | **+1** |
| Platform COMPLETE segs | **3478** | **3482** | **+4** |
| empty COMPLETE tip receipts | — | **0** | held |
| sealed this wave | — | **4** | |
| densify executed | — | **0** | |

### Tip segments AFTER

| segment_id | status | receipt_run_id | evaluated_at (UTC) |
|------------|--------|---------------:|--------------------|
| `2026-01` | **COMPLETE** | 903892 | 2026-08-15T15:51:11Z |
| `2026-02` | **COMPLETE** | 903890 | 2026-08-15T15:51:11Z |
| `2026-03` | **COMPLETE** | 903889 | 2026-08-15T15:51:11Z |
| `2026-04` | **COMPLETE** | 903888 | 2026-08-15T15:51:11Z |

### COMPLETE island

- COMPLETE **104**: continuous **`2018-01…2026-08`** (no holes in span)
- Dataset **seg-derived COMPLETE** includes `fins_earnings_date` (**22** datasets)
- Note: `dataset_coverage.status` row for fins still reads **PARTIAL** (stale aggregate; not re-run full `refresh_coverage_ledger` evidence pass). **Segment ledger is SoT for complete_segments** = **104/104**.

### Dataset COMPLETE list (n=22, now includes `fins_earnings_date`)

`derivatives_bars_daily_futures`, `derivatives_bars_daily_options`, `derivatives_bars_daily_options_225`, `edinet_cross_shareholdings`, `edinet_large_volume_shareholders`, `edinet_major_shareholders`, `equities_bars_daily`, `equities_investor_types`, `fins_details`, `fins_dividend`, **`fins_earnings_date`**, `fins_summary`, `indices_bars_daily`, `indices_bars_daily_topix`, `jsda_corporate_bond_transactions`, `jsda_tokyo_repo_rates`, `markets_breakdown`, `markets_calendar`, `markets_margin_alert`, `markets_margin_interest`, `markets_short_ratio`, `markets_short_sale_report`

---

## Honesty explicit

- **Live API attempted and succeeded** (HTTP 200 ×4, rowsInserted nz ×4) — not inventory-only
- **densify not used**
- **empty COMPLETE not invented** (raw_row_count / structured_row_count > 0 on sealed receipts)
- **COMPLETE only after** raw (R2) + structured + signed SUCCESS receipt + restore + remote publish
- Did **not** Mass / READY
- Did **not** commit/push

---

## Wave A result

### **wave A COMPLETE for tip expand**

| field | value |
|-------|-------|
| outcome | **COMPLETE** tip close `2026-01…04` |
| complete_segments | **100/104 → 104/104** |
| Dataset COMPLETE | **21 → 22** |
| API returned data | **yes** (all 4 months nz) |
| LIVE_API_EMPTY | **false** |
| sealed_n | **4** |

---

## Machine logs (gitignored OK)

Prefix: [`.glm-logs/w0816b_w68_complete_delta/`](../../.glm-logs/w0816b_w68_complete_delta/)

| artifact | purpose |
|----------|---------|
| `d1q.py` | remote D1 helper |
| `BEFORE_snapshot.json` / `q_before_*.json` | before counts |
| `dry_run.log` / `dry_plan.json` / `dry_queue.json` | planner dry-run |
| `live_2026-0*_run.log` / `*_queue.json` / `*_state.jsonl` | per-month live API |
| `live_api_results.json` | per-month API summary table |
| `manifests/` | R2 manifests for runs 14068/69/70/72 |
| `pages/` | sample raw pages |
| `seal_map.json` / `seal_from_r2.py` / `seal_run.log` / `seal_result.jsonl` | R2→local seal |
| `issue.log` / `restore.log` | signed receipts + COMPLETE restore |
| `publish.log` / `export_proj.log` | remote projection apply |
| `q_after_*.json` | after D1 recount |
| `FINAL_metrics.json` / `LIVE_D1_SNAPSHOT.json` | machine metrics |

---

## Exact numbers (return)

```text
BEFORE: complete_segments=100/104  dataset_complete=21  platform_complete_segs=3478
AFTER:  complete_segments=104/104  dataset_complete=22  platform_complete_segs=3482  empty_complete_tip=0
DELTA:  complete_segments=+4  dataset_complete=+1  sealed_n=4  densify_executed=0
LIVE API (all HTTP 200 pass nz window_ok):
  2026-01 rowsInserted=608  run=14068 pages=31 nz_pages=19
  2026-02 rowsInserted=525  run=14069 pages=28 nz_pages=18
  2026-03 rowsInserted=3044 run=14070 pages=31 nz_pages=21
  2026-04 rowsInserted=788  run=14072 pages=30 nz_pages=21
LIVE_API_EMPTY=false
TIP: 2026-01..04 all COMPLETE (receipts 903892/903890/903889/903888)
WAVE A: COMPLETE for tip expand 100/104 → 104/104
```
