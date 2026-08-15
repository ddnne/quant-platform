# W59 / w0815az_g3b — T9–T11 long-window S1 signal eval via R2 bridge

**Wave:** W59 / w0815az_g3b · T9–T11 (follow-up to G1 bridge + G2 verify)  
**Label:** **小サンプル / 研究用・未宣言**  
**Mass / Phase7:** **NO-GO / OFF** (held · not armed)  
**READY:** **not** declared  
**Order execution:** **none**  
**densify / tip collect as primary:** **none**  
**Invent COMPLETE / Dataset COMPLETE 22:** **forbidden** (held **21**)  
**Push:** **not** this task  
**Significance / edge claim:** **none**

**Primary this lane (G3b):** live R2 key listing for `equities_bars_daily` + `indices_bars_daily_topix` spanning ≥40 trading days; if sufficient, run S1 multiday nextday eval with `history_source="r2"` for **40–60 trading days** · **20–30 codes** · research-only labels · look-ahead ban · write R2 `job=w0815az-g3-long`.

**Prior (G1 bridge):** [`w0815az_w59_r2_feature_context_bridge_20260815.md`](w0815az_w59_r2_feature_context_bridge_20260815.md) · `r2_feature_context.py` · `history_source="r2"|"d1_tip"`  
**Prior (G2 verify):** `can_build_40d_asof=yes` (code path + synthetic 45d) · [`.glm-logs/w0815az_g2_verify/`](../../.glm-logs/w0815az_g2_verify/)  
**Prior (G3 pre-bridge DEFER):** same proof path earlier as DEFER — **superseded** by this live R2 long eval  
**Prior (W58 tip-max):** [`w0815ay_w58_history_window_eval_20260815.md`](w0815ay_w58_history_window_eval_20260815.md) · tip max **n_days=28**

**Signal:** `c21_topix_relative_sign@1.0.0` · `candidate_only=False` · status `candidate` · approved legs only  
**Live verified:** 2026-08-15 ~`12:48Z` UTC  
**Logs:** [`.glm-logs/w0815az_g3b_long/`](../../.glm-logs/w0815az_g3b_long/)

---

## Verdict

| gate | result |
|------|--------|
| **Live R2 list (bars + topix ≥40d)** | **PASS** — CF API list + artifacts-join-plan; JSONL bars 2024-09…2025-03; topix archive 2008-05-07…2026-06-30 (4440 days) |
| **can_build_40d_asof (live rows)** | **yes** — bars **74** / topix **74** trading days · span `2024-09-02`…`2024-12-18` |
| **T9 40–60 day S1 re-eval** | **PASS** — `history_source="r2"` · **n_days=50** · **n_codes=30** |
| **T10 research report (this doc)** | **PASS** (未宣言 · metrics recorded · no edge claim) |
| **T11 R2 write `job=w0815az-g3-long`** | **PASS** — `batch_summary.json` + `manifest.json` + 50 day signals · HEAD verified |
| Look-ahead ban | **held** (`NEXTDAY_LOOKAHEAD_POLICY`) |
| Mass / READY / densify / push | **OFF / not declared / none / none** |

**Honesty:** Long window is **real R2 structured history** (JSONL bars + archive topix/calendar), not D1 tip and not invented rows. Calendar archive `available_at` was ingest wall-clock (~2026); research-only repair sets `available_at=event_time` so PIT calendar gate works for historical as_of (documented · not SoT rewrite of R2). Bars/topix `available_at` left as envelope (event close). No significance / edge claim.

---

## 0. Look-ahead policy (held)

| field | value |
|-------|------:|
| **feature_as_of** | signal day **T** session close (`T15:30:00+09:00`) |
| **feature PIT** | `available_at <= feature_as_of` |
| **return** | `close(T+1) / close(T) − 1` |
| **evaluation_as_of** | next trading day **T+1** session close |
| **return PIT** | both T and T+1 bars require `available_at <= evaluation_as_of` |
| **label** | 小サンプル / 研究用・未宣言 |
| **significance_claimed** | **false** |
| **edge_claimed** | **false** |

---

## 1. Live R2 key inventory (≥40 trading days)

### 1.1 Discovery methods

| method | result |
|--------|--------|
| `POST/GET` worker `artifacts-join-plan/v1` | 50 keys/prefix (truncated for bars JSONL+archive); D1 tip still `2026-07-01`…`2026-08-10` (**28** days) |
| Cloudflare R2 list API (OAuth via wrangler) | full prefix list with cursor; delimiter prefixes for JSONL `dt=` |
| `wrangler r2 object get --remote` | sample GETs for archive topix/calendar + JSONL bars |

Logs: `artifacts_join_plan_live.json` · `r2_key_summary.json` · `bars_jsonl_dates_scan.json` · `topix_archive_keys.json` · `jsonl_filter_summary.json`

### 1.2 equities_bars_daily

| plane | span evidence |
|-------|----------------|
| Live JSONL | `structured/jsonl/equities_bars_daily/dt=YYYY-MM-DD/…` — continuous shards **2024-09-02…2025-03-31** (62 listed shard dates; each shard holds multi-day events) |
| Cold archive | `archive/jquants_records/equities_bars_daily/batch/` — **1100** data objects (~390 MB); per-batch ~400 codes × 1 day (sparse for fixed universe) |
| **Used for eval** | **32 JSONL shards** · filtered to 30 codes · **74 event trading days** · `2024-09-02`…`2024-12-18` |

### 1.3 indices_bars_daily_topix

| plane | span evidence |
|-------|----------------|
| Cold archive (complete, 12 files, ~1.4 MB) | **4440** days · `2008-05-07`…`2026-06-30` |
| **Used for eval** | all 12 archive objects · 74 days in period |

### 1.4 markets_calendar

| plane | span evidence |
|-------|----------------|
| Cold archive (17 files) | **6756** days · `2008-01-01`…`2026-06-30` |
| PIT note | envelope `available_at` ≈ archive ingest **2026-08-11** → fails historical as_of; research repair → `available_at=event_time` (log: `calendar_pit_repair.json`) |

### 1.5 can_build_40d_asof (live)

```json
{
  "can_build_40d_asof": true,
  "equities_bars_trading_days": 74,
  "topix_days": 74,
  "bar_day_span": ["2024-09-02", "2024-12-18"],
  "topix_day_span": ["2024-09-02", "2024-12-18"]
}
```

---

## 2. T9 — long S1 multiday nextday eval

| field | value |
|-------|------:|
| **API** | `execute_multiday_nextday_return_eval` · `history_source="r2"` |
| **job_id** | `w0815az-g3-long` |
| **period** | `2024-09-02` … `2024-12-18` |
| **max_days / min_days** | **50** / **40** |
| **n_days achieved** | **50** (as_of `2024-10-08` … `2024-12-18`) |
| **n_codes** | **30** (W57 universe) |
| **feature_row_limit** | 20000 |
| **input channel** | `r2_local_paths_by_dataset` (disposable mirror of live R2 GET · **not** local SoT) |
| **long_eval_ran** | **yes** |

### 2.1 Codes (30)

`13010` · `72030` · `67580` · `99840` · `83060` · `68610` · `65010` · `40630` · `80350` · `94320` · `45020` · `63670` · `60980` · `79740` · `69810` · `45680` · `80010` · `80020` · `80580` · `94330` · `29140` · `33820` · `46610` · `49010` · `51080` · `54010` · `57130` · `62730` · `63010` · `65030`

### 2.2 Signal aggregate

| metric | value |
|--------|------:|
| signal_count | **1500** (50 × 30) |
| non_null | **1500** |
| non_null_rate | **1.0** |
| sign `+1` | **767** |
| sign `-1` | **733** |
| sign null | **0** |

### 2.3 Nextday return by sign (研究用・未宣言)

| sign | count | non_null_R | mean_R | median_R | null_R_rate |
|------|------:|----------:|-------:|---------:|------------:|
| **+1** | 767 | 751 | **−0.000182** | **−0.001168** | 0.0209 |
| **−1** | 733 | 719 | **−0.000245** | **−0.001977** | 0.0191 |
| **overall** | 1500 | 1470 | **−0.000213** | **−0.001440** | **0.02** |

**No edge claim:** both signs have near-zero / slightly negative mean next-day return on this sample; not READY; not Mass.

### 2.4 Calendar PIT repair (research-only)

First live run had **signal non_null_rate=0** because `is_trading_day` saw 0 calendar rows (archive `available_at` > historical as_of). Re-run after setting calendar `available_at=event_time` when envelope available_at post-dates event day (**6366/6756** lines). Bars/topix envelopes unchanged. Documented in `calendar_pit_repair.json` · `e2e_rerun_calfix.log`.

---

## 3. T10 — research report

This document: **`docs/proof/w0815az_w59_long_window_signal_eval_20260815.md`**

| field | value |
|-------|------:|
| **status** | **written** |
| **claim level** | **小サンプル / 研究用・未宣言** |
| **READY** | **not** declared |
| **significance / edge** | **none** |
| **long_eval metrics** | **present** (§2) |

---

## 4. T11 — R2 write

| field | value |
|-------|------:|
| **job_id** | `w0815az-g3-long` |
| **prefix** | `research/single_shot/job=w0815az-g3-long/` |
| **batch_summary** | `…/batch_summary.json` · **362683** bytes · `put_ok` |
| **manifest** | `…/manifest.json` · **11525** bytes · exists |
| **per-day signals** | 50 × `days/date=YYYY-MM-DD/signals.json` |
| **HEAD sample** | first day `2024-10-08` (60608 B) · last `2024-12-18` (59463 B) |
| **history_source in artifact** | `"r2"` · `tip_plane=R2_history` |

Log: `r2_heads.json` · `execution.json` · `batch_summary.json`

---

## 5. Code / artifact map

| item | path |
|------|------|
| R2→FeatureContext bridge | `packages/product/research/r2_feature_context.py` |
| Multiday + nextday API | `packages/product/research/single_shot_job.py` |
| Eval harness | `packages/product/research/eval_harness.py` |
| G3b logs | `.glm-logs/w0815az_g3b_long/` |
| Disposable R2 mirror | `.glm-logs/w0815az_g3b_long/r2_mirror/` (not SoT) |
| This proof | `docs/proof/w0815az_w59_long_window_signal_eval_20260815.md` |

---

## 6. Explicit non-claims

* **READY** not declared / not published  
* **Mass research** not started / not connected  
* **Phase7** not armed  
* **Orders** not emitted  
* **densify** not run  
* **local SQLite** is not Source of Truth (mirror disposable)  
* **significance / edge** not claimed  
* Signal **status remains `candidate`**  
* Calendar available_at repair is **research-only metadata** on local mirror, not a claim that CF R2 objects were rewritten  
* Outputs labeled **小サンプル / 研究用・未宣言**

---

## Return card

| field | value |
|-------|------:|
| **long_eval_ran** | **yes** |
| **n_days** | **50** |
| **n_codes** | **30** |
| **metrics** | signal non_null_rate **1.0** · sign +1:767 / −1:733 · mean_R +1:**−0.000182** / −1:**−0.000245** · overall mean_R **−0.000213** · return_null_rate **0.02** |
| **history_source** | **r2** |
| **bridge_supports_ge_40_days** | **yes** (live) |
| **T9** | **PASS** |
| **T10 proof** | **written** (this doc · 未宣言) |
| **T11 R2** | **PASS** (`job=w0815az-g3-long`) |
| **label** | **小サンプル / 研究用・未宣言** |
| **Mass / READY** | **OFF** / **not declared** |
| **pass/fail** | **PASS_LONG_R2** |
