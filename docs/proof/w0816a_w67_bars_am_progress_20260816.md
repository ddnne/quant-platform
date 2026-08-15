# W67 / w0816a — Task B `equities_bars_daily_am` progress (2026-08-16)

**Wave:** W67 / w0816a · Task B  
**Live verified:** ~2026-08-15T15:26Z UTC (remote D1 `quant-ingest`)  
**Mass / READY / Phase7:** **NO-GO / not declared / OFF**  
**empty COMPLETE:** **0** (ban held)  
**densify history:** **FORBIDDEN** (PD-D4-BARS-AM)  
**Invent COMPLETE / Dataset COMPLETE 22:** **forbidden** (held **21**)  
**Commit / push:** **out of scope**

**Machine logs:** [`.glm-logs/w0816a_w67_coverage/`](../../.glm-logs/w0816a_w67_coverage/)  
Primary: [`bars_am_progress.json`](../../.glm-logs/w0816a_w67_coverage/bars_am_progress.json) · [`bars_am_status_counts.json`](../../.glm-logs/w0816a_w67_coverage/bars_am_status_counts.json)

---

## Explicit non-actions

| claim / action | status |
|----------------|--------|
| densify history residual `2024-01…2026-07` | **FORBIDDEN** (PD-D4-BARS-AM) |
| invent history COMPLETE / raise floor to tip | **forbidden** |
| Dataset COMPLETE for bars_am | **not claimed** (still PARTIAL) |
| bulk tip densify as success metric | **none** |
| commit / push | **out of scope** |

---

## 1. Live D1 status counts (`coverage_segments`)

| dataset | status | n | span |
|---------|--------|--:|------|
| `equities_bars_daily_am` | **COMPLETE** | **1** | `2026-08` (tip) |
| `equities_bars_daily_am` | **PARTIAL** | **31** | `2024-01`…`2026-07` |

Matches expectation: tip COMPLETE **~1**, PARTIAL **~31**.

| field | value |
|-------|------:|
| required months (coverage_v2) | **32** (= 1 COMPLETE + 31 PARTIAL) |
| tip segment | **`2026-08` COMPLETE** |
| new tip month open? | **No** (`2026-09` not present) |
| dataset_coverage.status | **PARTIAL** |
| observed_start / observed_end | **`2026-08-01` / `2026-08-11`** (tip island only) |
| row_count (aggregate) | **4444** |
| history segs closed this wave | **0** |
| Δ complete_segments (bars_am) | **0** |

Query:

```sql
SELECT dataset, status, COUNT(*) AS n, MIN(segment_id), MAX(segment_id)
FROM coverage_segments
WHERE dataset='equities_bars_daily_am'
GROUP BY dataset, status;
```

---

## 2. API / policy constraint (tip-only)

### Catalog

`packages/data_plane/data_contracts/jquants_premium_core.json`:

| field | value |
|-------|-------|
| `dataset_id` | `equities_bars_daily_am` |
| `path` | `/v2/equities/bars/daily/am` |
| **`date_mode`** | **`today`** |
| `params` | `code`, `date` (no historical `from`/`to` range mode) |
| `session` | `morning` |

### Permanent DEFER

`packages/data_plane/data_contracts/permanent_defer.py`:

| id | dataset | class |
|----|---------|-------|
| **PD-D4-BARS-AM** | `equities_bars_daily_am` | tip-only AM |

Lock reaffirm (W44 SoT): TIP_ONLY_VENDOR · `date_mode=today` · densify history **FORBIDDEN** · do not raise `history_target_start` to tip to invent Dataset COMPLETE.

Coverage contract floor: `history_target_start = 2024-01-04` (`collection_coverage.json`) — residual planner still expands **today ×31** for `2024-01…2026-07`, which **cannot** produce in-window historical AM raw.

Vendor (prior live re-verify, W10-G11): same-day morning session only until ~06:00 next day; historical OHLC → full-day bars API, not AM endpoint. See [`w0815b_g11_earn_am_20260815.md`](w0815b_g11_earn_am_20260815.md).

---

## 3. Optional tip collect

| check | result |
|-------|--------|
| tip month sealable? | **already COMPLETE** (`2026-08`) |
| would tip re-collect close history PARTIAL? | **No** — vendor returns tip Dates only |
| invent history COMPLETE risk if residual plan executed? | **Yes** if forced seal without window_ok — **not done** |
| optional tip collect this wave | **SKIP** |

**Reason:** Tip is already sealed. Re-collecting tip densifies same-day raw only and must **not** jump `complete_segments` on history months. History densify remains permanent DEFER. Cron may densify tip raw independently; that is not history progress.

---

## 4. Progress (honest)

| metric | PRE (held / W44–W66) | POST (this wave) | Δ |
|--------|---------------------:|-----------------:|--:|
| bars_am COMPLETE segs | **1** | **1** | **0** |
| bars_am PARTIAL segs | **31** | **31** | **0** |
| history segs closed | — | **0** | — |
| Dataset COMPLETE (platform) | **21** | **21** | **0** |
| platform COMPLETE segs | **3478** | **3478** | **0** |
| empty COMPLETE | **0** | **0** | held |

**Honest summary:** **0 history segments closed.** Tip COMPLETE held at **1**. Residual PARTIAL **31** remains PD-D4-BARS-AM permanent DEFER. No dishonest COMPLETE jump.

---

## 5. Platform context (held)

| metric | value |
|--------|------:|
| Dataset COMPLETE | **21** |
| Dataset PARTIAL (DEFER) | **5** |
| COMPLETE segs total | **3478** |
| bars_am among DEFER 5 | yes (with master / earn_cal / otc / fins_earnings_date tip4) |

---

## Return card

| field | value |
|-------|------:|
| **bars_am COMPLETE** | **1** (`2026-08`) |
| **bars_am PARTIAL** | **31** (`2024-01…2026-07`) |
| **history segs closed** | **0** |
| **tip collect** | **SKIP** (already COMPLETE) |
| **densify history** | **FORBIDDEN** PD-D4-BARS-AM |
| **date_mode** | **today** (catalog) |
| **Dataset COMPLETE platform** | **21** held |
| **COMPLETE segs platform** | **3478** held |
| **Mass / READY / Phase7** | **NO-GO / not declared / OFF** |
| **commit / push** | **no** |

---
