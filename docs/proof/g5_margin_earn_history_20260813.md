# G5: markets_margin_interest history + equities_earnings_calendar segments (2026-08-13)

**Mass / READY:** NO-GO  
**empty COMPLETE:** none  
**cf_premium dual-run ban (t7/t8):** **honored** — did **not** touch `equities_master` / `markets_short_ratio` / `markets_margin_alert` / `equities_investor_types`; did **not** kill live t7/t8 (they finished on their own mid-session)  
**prefix:** `t5_margin_earn_*` · **workers=2** · **general-rpm=495**  
**base tip (PRE):** `4342091` / residual SoT tip `dbb3590`

## Goal

1. Fill `markets_margin_interest` missing history months; keep dataset **PARTIAL** honest; **do not break C8**.
2. Fill `equities_earnings_calendar` missing segments (worker pass path).
3. Reeval margin + verify detail_json **C8 pass**.

## PRE (remote D1)

| Metric | PRE |
|--------|-----|
| margin status | **PARTIAL** |
| margin `observed_start` / `observed_end` | `2024-01-01` → `2026-08-13` |
| margin COMPLETE segs | **17** (2024-01…2025-02 + 2026-06/07/08) |
| margin PARTIAL segs | **147** |
| margin detail C8 | **pass** lag 1d≤7 (`source=receipt_observed_end`) |
| earn status | **PARTIAL** |
| earn COMPLETE segs | **1** (`2026-08`) |
| earn PARTIAL segs | **199** |
| earn observed | `2010-01-04` → `2026-08-12T09:00:00+09:00` |
| raw_n (approx residual) | **6378** |

Dry-run plan: **346** jobs (`earn=199`, `margin=147`).

## Execute

```bash
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets markets_margin_interest,equities_earnings_calendar \
  --execute --workers 2 --general-rpm 495 --max-jobs 0 \
  --plan-out .glm-logs/cf-backfill/t5_margin_earn_plan.json \
  --queue-out .glm-logs/cf-backfill/t5_margin_earn_queue.json \
  --state-out .glm-logs/cf-backfill/t5_margin_earn_state.jsonl
```

| Field | Value |
|-------|-------|
| window | `2026-08-13T14:01:50Z` → `2026-08-13T14:47:48Z` (~46 min) |
| executed | **346** |
| pass / fail | **344** / **2** |
| host POST/min | **7.51** |
| HTTP 429 | **0** |
| earn | **199/199 pass**, rowsInserted sum **39004** (2010-01…2026-07) |
| margin main | **145/147 pass**, rowsInserted sum **2385836** (2013-01…2026-05) |
| margin fail | `2017-01`, `2017-02` HTTP **500** (transient) |

### Retry (fail only)

```bash
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets markets_margin_interest \
  --from-date 2017-01-01 --to-date 2017-02-28 \
  --execute --workers 1 --general-rpm 495 \
  --plan-out .glm-logs/cf-backfill/t5_margin_earn_retry_plan.json \
  --queue-out .glm-logs/cf-backfill/t5_margin_earn_retry_queue.json \
  --state-out .glm-logs/cf-backfill/t5_margin_earn_retry_state.jsonl
```

| segment | result | rowsInserted |
|---------|--------|-------------:|
| 2017-01 | **pass** 200 | 15246 |
| 2017-02 | **pass** 200 | 15241 |

→ margin plan coverage **147/147 worker pass** after retry.

## Reeval

```bash
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset markets_margin_interest --today 2026-08-13 --freshness-days 7
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset equities_earnings_calendar --today 2026-08-13 --freshness-days 7
.venv/bin/python scripts/ops_reeval_freshness.py
```

### markets_margin_interest

| Field | PRE | POST |
|-------|-----|------|
| status | PARTIAL | **PARTIAL** (honest; no COMPLETE claim) |
| `observed_start` | `2024-01-01` | **`2013-01-04`** |
| `observed_end` | `2026-08-13` | **`2026-08-13`** (held) |
| detail C8 | pass lag 0–1 | **pass** lag **1** ≤ 7 |
| C8 `latest_event_time` | receipt | **`2026-08-12`** (`source=receipt_observed_end`) |
| receipt window | — | start `2013-01-04` end `2026-08-12` n=**169** sum_raw=**2561096** |
| segments | untouched by reeval | COMPLETE **17** / PARTIAL **94** / UNKNOWN **53** |

### equities_earnings_calendar

| Field | PRE | POST |
|-------|-----|------|
| status | PARTIAL | **PARTIAL** |
| `observed_start` | `2010-01-04` | **`2010-01-04`** |
| `observed_end` | `2026-08-12T09:00:00+09:00` | **`2026-08-13`** |
| detail C8 | pass | **pass** lag **0** ≤ 7 |
| receipt window | — | start `2010-01-04` end `2026-08-13` n=**253** sum_raw=**46206** |
| segments | — | COMPLETE **1** / PARTIAL **193** / UNKNOWN **6** |

### projection

| Field | POST |
|-------|------|
| status | **FRESH** (ops_reeval_freshness) |
| `generation_id` | `projgen-23eb78448e914cd18663d0a75e929b41` |
| `activated_at` | `2026-08-13T14:49:11.128203+00:00` |
| COMPLETE fabrication | **none** |
| Mass | **NO-GO** |

## Wrangler C8 confirm (detail)

```text
markets_margin_interest  PARTIAL  2013-01-04 → 2026-08-13
  C8 pass  1 day(s)  latest=2026-08-12  max_days=7  source=receipt_observed_end

equities_earnings_calendar  PARTIAL  2010-01-04 → 2026-08-13
  C8 pass  0 day(s)  latest=2026-08-13  max_days=7  source=receipt_observed_end
```

## Honesty notes

- **Worker pass ≠ Coverage COMPLETE.** No TRUSTED monthly seals issued this ticket; segment COMPLETE counts for these two datasets **unchanged** (margin 17, earn 1).
- Dataset status remains **PARTIAL** for both (history raw + receipts present; full monthly TRUSTED seal still DEFER / separate A3 path).
- t7 (`equities_master`) + t8 (`short_ratio`/`margin_alert`/`investor_types`) were **not** killed or re-dispatched under this prefix.
- Concurrent peer traffic may move global COMPLETE/raw_n; this proof only claims the two datasets above.

## Artifacts

| Path | Role |
|------|------|
| `.glm-logs/cf-backfill/t5_margin_earn_{plan,queue,state,run,progress}.*` | main wave |
| `.glm-logs/cf-backfill/t5_margin_earn_retry_*` | 2017-01/02 retry |
| `.glm-logs/cf-backfill/t5_post/summary.json` | machine summary |
| `.glm-logs/cf-backfill/t5_post/reeval_*.log` | reeval logs |

## Result

| Item | Status |
|------|--------|
| margin history execute | **pass** (147/147 after retry) |
| earn missing segments execute | **pass** (199/199) |
| margin C8 | **pass** lag 1 |
| earn C8 | **pass** lag 0 |
| margin `observed_start` | **2013-01-04** (was 2024-01-01) |
| dataset COMPLETE claim | **none** (PARTIAL honest) |
| Mass / empty COMPLETE | **NO-GO** / none |
