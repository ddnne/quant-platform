# W8-G8 T1+T2 — topix / indices residual `2008-01…04` re-verify (2026-08-14)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (SUCCESS requires `raw_row_count>0` — **not** sealed)  
**Worker pass ≠ Coverage COMPLETE**  
**prefix:** `w0814h_g8_*` · general pool · **did not kill** peers (bars / edinet / fins / deriv / g4 / g9–g10 backfill left alive)

**Base tip at start:** `e6c9e0b`  
**Live verified:** 2026-08-14 (JST) / ~2026-08-14T14:03Z UTC  
**Projection:** **FRESH** `projgen-c61de81534bf4fbfb51d5e534b935a66` age=0 (fail-closed `--apply-remote`)

## Objective

| track | dataset | action | params |
|-------|---------|--------|--------|
| **T1** | `indices_bars_daily_topix` | residual PARTIAL **2008-01…04** only (220/224 already COMPLETE) | workers **1**, general-rpm **80** (share pool; peers ~495) |
| **T2** | `indices_bars_daily` | residual PARTIAL **same 2008-01…04** (220/224) | workers **1**, general-rpm **80** |

**Forbidden held:** no Mass; no empty COMPLETE; no invent receipt without raw; no peer kill; no rewrite of COMPLETE segs.

---

## PRE (remote D1 `quant-ingest`)

Artifacts: `.glm-logs/w0814h_g8_topix_idx/PRE_*.json`

| metric | value |
|--------|------:|
| **topix COMPLETE** | **220** / 224 |
| topix residual | **4** PARTIAL — `2008-01`, `2008-02`, `2008-03`, `2008-04` |
| topix residual detail | receipt_run_id 492–495 · `"receipt does not match required scope"` |
| **idx COMPLETE** | **220** / 224 |
| idx residual | **4** PARTIAL — same months · `"missing collection receipt"` |
| topix `observed_start` / `observed_end` | **`2008-01-01`** / `2026-08-12` |
| idx `observed_start` / `observed_end` | **`2008-05-01`** / `2026-08-11` |
| history_target_start (both) | `2008-01-01` (contract) |
| platform segment COMPLETE | **2651** (live at PRE; peers advanced during wave) |
| empty COMPLETE (topix/idx) | **0** |

### observed-window note (no COMPLETE rewrite)

- **idx** already has receipt-plane `observed_start=**2008-05-01**` (hot C4 event_time also starts ~2008-05-07). Residual `2008-01…04` lies **outside** observed window but remains required by `history_target_start=2008-01-01` → dataset PARTIAL until policy/window changes.  
- **topix** receipt-plane `observed_start` remains **`2008-01-01`** (not moved to 2008-05). Reeval held start; **did not** rewrite COMPLETE segs.  
- Dataset-level COMPLETE for either series is **blocked** by empty API class on `2008-01…04` unless observed/target policy drops those months.

Dry-run residual (planner):

| dataset | plan_jobs | queued |
|---------|----------:|-------:|
| `indices_bars_daily_topix` `2008-01-01…2008-04-30` | **4** | **4** |
| `indices_bars_daily` same | **4** | **4** |

---

## 1. Re-verify backfill (`cf_premium_backfill`)

Conservative general pool (workers **1**, rpm **80**, max-jobs **10**) so peer bars@495 / edinet / master / mb were not starved.

### T1 topix gap — `w0814h_g8_topix_gap_*`

```text
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets indices_bars_daily_topix \
  --from-date 2008-01-01 --to-date 2008-04-30 \
  --execute --workers 1 --general-rpm 80 --max-jobs 10 \
  --sleep-on-retry 5.0 \
  --plan-out .glm-logs/cf-backfill/w0814h_g8_topix_gap_exec_plan.json \
  --queue-out .glm-logs/cf-backfill/w0814h_g8_topix_gap_exec_queue.json \
  --state-out .glm-logs/cf-backfill/w0814h_g8_topix_gap_exec_state.jsonl
```

| field | value |
|-------|------:|
| plan / queued / executed | **4 / 4 / 4** |
| **pass / fail** | **4 / 0** |
| host POST rpm | **28.75** (window ~6.3s) |
| http_429_count | **0** |
| remote run_ids | **11570, 11572, 11573, 11574** |
| state `rowsInserted` | **0** every month |

### T2 idx gap — `w0814h_g8_idx_gap_*`

```text
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets indices_bars_daily \
  --from-date 2008-01-01 --to-date 2008-04-30 \
  --execute --workers 1 --general-rpm 80 --max-jobs 10 \
  --sleep-on-retry 5.0 \
  --plan-out .glm-logs/cf-backfill/w0814h_g8_idx_gap_exec_plan.json \
  --queue-out .glm-logs/cf-backfill/w0814h_g8_idx_gap_exec_queue.json \
  --state-out .glm-logs/cf-backfill/w0814h_g8_idx_gap_exec_state.jsonl
```

| field | value |
|-------|------:|
| plan / queued / executed | **4 / 4 / 4** |
| **pass / fail** | **4 / 0** |
| host POST rpm | **2.05** (window ~88s; multi-index day loop) |
| http_429_count | **0** |
| remote run_ids | **11576, 11585, 11595, 11603** |
| state `rowsInserted` | **0** every month |

Worker pass only — **empty API band**. Empty-raw ban → **no seal / no COMPLETE**.

---

## 2. Empty-raw proof (D1 + R2)

### D1 `raw_retention_manifests` (remote)

| dataset | run_id | params (R2) | row_count | page_count | completeness* |
|---------|-------:|-------------|----------:|-----------:|---------------|
| topix | 11570 | 2008-01-01…31 | **0** | 1 | COMPLETE |
| topix | 11572 | 2008-02-01…29 | **0** | 1 | COMPLETE |
| topix | 11573 | 2008-03-01…31 | **0** | 1 | COMPLETE |
| topix | 11574 | 2008-04-01…30 | **0** | 1 | COMPLETE |
| idx | 11576 | 2008-01-01…31 | **0** | 31 | COMPLETE |
| idx | 11585 | 2008-02-01…29 | **0** | 29 | COMPLETE |
| idx | 11595 | 2008-03-01…31 | **0** | 31 | COMPLETE |
| idx | 11603 | 2008-04-01…30 | **0** | 30 | COMPLETE |

\*manifest `completeness=COMPLETE` = raw fetch finished with empty `data[]` shell — **not** coverage COMPLETE.

### R2 sample (quant-raw, `--remote`)

- `raw/indices_bars_daily_topix/11570/manifest.json` → `row_count=0`, `raw_bytes=12`, digest matches empty shell  
- `raw/indices_bars_daily_topix/11570/page-000001.json` → **`{"data": []}`**  
- All eight manifests mirrored under `.glm-logs/w0814h_g8_topix_idx/r2_manifests/`

State jsonl receipts: `.glm-logs/w0814h_g8_topix_idx/w0814h_g8_{topix,idx}_gap_exec_state.jsonl`  
(`detail.rowsInserted=0` for all 8).

### Seal probe

| field | value |
|------:|
| unsealed segments with non-empty raw for residual months | **0** |
| later PARTIAL months beyond 2008-01…04 (topix/idx) | **none** (only these 4 residual) |
| seals issued this wave | **0** |

---

## 3. Reeval + publish (fail-closed)

```text
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset indices_bars_daily_topix --today 2026-08-14
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset indices_bars_daily --today 2026-08-14
.venv/bin/python scripts/ops_reeval_freshness.py
.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite --apply-remote
# complete_count_guard ok local=2688 remote=2687 force=False
# remote projection applied
```

| dataset | observed_start | observed_end (reeval planned) | status | C8 (reeval) |
|---------|----------------|-------------------------------|--------|-------------|
| `indices_bars_daily_topix` | **2008-01-01** (held) | 2026-08-14 | PARTIAL | **pass lag 0** |
| `indices_bars_daily` | **2008-05-01** (held) | 2026-08-13 | PARTIAL | **pass lag 1** |

**coverage_segments untouched** by reeval. **No** COMPLETE invent.  
POST dataset_coverage after publish may race peers on `observed_end` tip clock; **starts held**.

Freshness/publish: **FRESH** `projgen-c61de81534bf4fbfb51d5e534b935a66` age=0 · mass=NO-GO.

---

## POST (remote D1 live verify)

| metric | PRE | POST | Δ |
|--------|----:|-----:|--:|
| **topix COMPLETE segs** | **220** | **220** | **0** |
| topix residual PARTIAL | 4 (`2008-01…04`) | **4** | 0 |
| **idx COMPLETE segs** | **220** | **220** | **0** |
| idx residual PARTIAL | 4 | **4** | 0 |
| topix/idx empty COMPLETE | 0 | **0** | 0 |
| platform COMPLETE segs | ~2651 | **~2690** | peers only (this track **+0**) |
| projection | — | **FRESH** `projgen-c61de815…` | |

### Residual DEFER (honest)

Both datasets remain **220/224 COMPLETE** with residual:

`2008-01`, `2008-02`, `2008-03`, `2008-04`

Re-dispatch **8/8 pass**, all **`row_count=0` / `rowsInserted=0` / page body `{"data":[]}`**.  
Honest empty-raw ban: **no seal**, **no COMPLETE**, **Worker pass ≠ Coverage COMPLETE**.

**Dataset COMPLETE blocked** by empty API class on `2008-01…04` unless:

1. J-Quants starts returning non-empty data for those months, or  
2. Coverage policy changes observed/target window to exclude pre-2008-05 empty band (would require explicit policy change — **not** done here; COMPLETE segs not rewritten).

Prior wave corroboration: `docs/proof/w0814b_g3_indices_20260814.md` (same empty gap).

---

## Acceptance

| gate | result |
|------|--------|
| PRE remote D1 for residual months | **PASS** |
| dry-run + execute both datasets 2008-01…04 | **PASS** (8/8 worker pass) |
| empty-raw ban held (no seal when row_count=0) | **PASS** |
| topix/idx COMPLETE Δ | **0 / 0** (honest) |
| empty COMPLETE | **0** |
| peer backfill PIDs not killed | **PASS** (bars/edinet/master/mb alive) |
| publish fail-closed + FRESH | **PASS** |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| T1/T2 closed | **DEFER with proof** (not dataset COMPLETE) |

---

## Artifacts

| path | role |
|------|------|
| `.glm-logs/w0814h_g8_topix_idx/` | wave logs, PRE/POST D1, R2 manifests, reeval, publish |
| `.glm-logs/cf-backfill/w0814h_g8_{topix,idx}_gap_*` | plan/queue/state |
| `docs/proof/w0814h_g8_topix_indices_20260814.md` | this proof |

## Explicit non-claims

- **Not** dataset COMPLETE for `indices_bars_daily_topix` or `indices_bars_daily`  
- **Not** segment COMPLETE for `2008-01…04`  
- **Not** observed_start rewrite to 2008-05 for topix  
- **Not** Mass / READY / B0 / Phase7  
