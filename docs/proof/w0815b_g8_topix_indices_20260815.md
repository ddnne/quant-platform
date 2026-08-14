# W10-G8 T1+T2 — topix / indices residual `2008-01…04` re-verify (2026-08-15)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (SUCCESS requires non-empty usable raw — **not** sealed)  
**Worker pass ≠ Coverage COMPLETE**  
**prefix:** `w0815b_g8_*` · general pool · **did not kill** peers (general@~350–400 / deriv / edinet / fins R2 alive)

**Base tip at start:** `e1d8fbc` (local; origin advanced during peer waves)  
**Live verified:** 2026-08-15 (JST) / ~2026-08-14T15:45Z UTC  
**Projection:** **FRESH** `projgen-6ffab6ba59ba4478a133803ef40b4fbf` (ops_reeval_freshness; segments untouched)

## Objective

| track | dataset | action | params |
|-------|---------|--------|--------|
| **T1** | `indices_bars_daily_topix` | residual PARTIAL **2008-01…04** only (220/224 already COMPLETE) | workers **1**, general-rpm **80** |
| **T2** | `indices_bars_daily` | residual PARTIAL **same 2008-01…04** (220/224) | workers **1**, general-rpm **80** |

**Forbidden held:** no Mass; no empty COMPLETE; no invent receipt without raw; no peer kill; no rewrite of COMPLETE segs.

---

## PRE (remote D1 `quant-ingest`)

Artifacts: `.glm-logs/w0815b_g8_topix_idx/PRE_*.json`

| metric | value |
|--------|------:|
| **topix COMPLETE** | **220** / 224 |
| topix residual | **4** PARTIAL — `2008-01`, `2008-02`, `2008-03`, `2008-04` |
| topix residual detail | receipt_run_id 492–495 · `"receipt does not match required scope"` |
| **idx COMPLETE** | **220** / 224 |
| idx residual | **4** PARTIAL — same months · `"missing collection receipt"` |
| topix `observed_start` / `observed_end` | **`2008-01-01`** / `2026-08-12` |
| idx `observed_start` / `observed_end` | **`2008-05-01`** / `2026-08-11` |
| history_target_start (both, contract) | `2008-01-01` |
| platform segment COMPLETE | **2862** (live at PRE; peers advanced during wave → POST **2922**) |
| empty COMPLETE (topix/idx) | **0** |

### observed-window note (no COMPLETE rewrite)

- **idx** receipt-plane `observed_start=**2008-05-01**` — residual `2008-01…04` lies **outside** observed window but remains required by `history_target_start=2008-01-01`.
- **topix** receipt-plane `observed_start` remains **`2008-01-01`** (held by reeval; not moved to 2008-05).
- Dataset-level COMPLETE for either series is **blocked** by empty API class on `2008-01…04` unless policy/window changes.

---

## 1. Re-verify backfill (`cf_premium_backfill`)

Conservative general pool (workers **1**, rpm **80**, max-jobs **10**) so peer general@~350–400 / edinet / deriv were not starved.

### T1 topix gap — `w0815b_g8_topix_gap_*`

```text
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets indices_bars_daily_topix \
  --from-date 2008-01-01 --to-date 2008-04-30 \
  --execute --workers 1 --general-rpm 80 --max-jobs 10 \
  --sleep-on-retry 5.0 \
  --plan-out .glm-logs/cf-backfill/w0815b_g8_topix_gap_exec_plan.json \
  --queue-out .glm-logs/cf-backfill/w0815b_g8_topix_gap_exec_queue.json \
  --state-out .glm-logs/cf-backfill/w0815b_g8_topix_gap_exec_state.jsonl
```

| field | value |
|-------|------:|
| plan / queued / executed | **4 / 4 / 4** |
| **pass / fail** | **4 / 0** |
| host POST rpm | **23.9** (window ~7.5s) |
| http_429_count | **0** |
| remote run_ids | **12348, 12349, 12350, 12353** |
| state `rowsInserted` | **0** every month |

### T2 idx gap — `w0815b_g8_idx_gap_*`

```text
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets indices_bars_daily \
  --from-date 2008-01-01 --to-date 2008-04-30 \
  --execute --workers 1 --general-rpm 80 --max-jobs 10 \
  --sleep-on-retry 5.0 \
  --plan-out .glm-logs/cf-backfill/w0815b_g8_idx_gap_exec_plan.json \
  --queue-out .glm-logs/cf-backfill/w0815b_g8_idx_gap_exec_queue.json \
  --state-out .glm-logs/cf-backfill/w0815b_g8_idx_gap_exec_state.jsonl
```

| field | value |
|-------|------:|
| plan / queued / executed | **4 / 4 / 4** |
| **pass / fail** | **4 / 0** |
| host POST rpm | **2.04** (window ~88s; multi-index day loop) |
| http_429_count | **0** |
| remote run_ids | **12360, 12364, 12369, 12381** |
| state `rowsInserted` | **0** every month |

Worker pass only — **empty API band**. Empty-raw ban → **no seal / no COMPLETE**.

---

## 2. Empty-raw proof (D1 + R2)

### D1 `raw_retention_manifests` (remote)

| dataset | run_id | params (R2) | row_count | page_count | completeness* |
|---------|-------:|-------------|----------:|-----------:|---------------|
| topix | 12348 | 2008-01-01…31 | **0** | 1 | COMPLETE |
| topix | 12349 | 2008-02-01…29 | **0** | 1 | COMPLETE |
| topix | 12350 | 2008-03-01…31 | **0** | 1 | COMPLETE |
| topix | 12353 | 2008-04-01…30 | **0** | 1 | COMPLETE |
| idx | 12360 | 2008-01-01…31 | **0** | 31 | COMPLETE |
| idx | 12364 | 2008-02-01…29 | **0** | 29 | COMPLETE |
| idx | 12369 | 2008-03-01…31 | **0** | 31 | COMPLETE |
| idx | 12381 | 2008-04-01…30 | **0** | 30 | COMPLETE |

\*manifest `completeness=COMPLETE` = raw fetch finished with empty `data[]` shell — **not** coverage COMPLETE.

### R2 sample (quant-raw, `--remote`)

- `raw/indices_bars_daily_topix/12348/manifest.json` → `row_count=0`, `raw_bytes=12`
- `raw/indices_bars_daily_topix/12348/page-000001.json` → **`{"data": []}`**
- `raw/indices_bars_daily/12360/page-000001.json` → **`{"data": []}`**
- All eight manifests under `.glm-logs/w0815b_g8_topix_idx/r2_manifests/`

### Seal probe

| field | value |
|------:|
| unsealed segments with non-empty raw for residual months | **0** |
| later PARTIAL months beyond 2008-01…04 (topix/idx) | **none** (only these 4 residual each) |
| seals issued this wave | **0** |

---

## 3. Legitimate dataset-COMPLETE path investigation

### What was tried (allowed automation)

| step | result |
|------|--------|
| `ops_reeval_observed_window.py` topix | observed_start **held** `2008-01-01`; observed_end → `2026-08-15`; C8 **pass** lag **0**; **status PARTIAL**; coverage_segments **untouched** |
| `ops_reeval_observed_window.py` idx | observed_start **held** `2008-05-01`; observed_end → `2026-08-14`; C8 **pass** lag **1**; **status PARTIAL** |
| `ops_reeval_freshness.py` | FRESH `projgen-6ffab6ba…`; `coverage_segments_untouched=1`; mass=NO-GO |

### Why reeval cannot invent COMPLETE

Code path (do not invent):

1. **Required inventory** is built from contract `history_target_start` → monthly segs including `2008-01…04`:
   - `packages/data_plane/storage/coverage_ledger.py` `build_required_segments` (starts at `policy.history_target_start`)
   - Contract SoT: `packages/data_plane/data_contracts/collection_coverage.json`  
     both datasets: `"history_target_start": "2008-01-01"`
2. **Segment COMPLETE** for non-event-driven requires non-empty observed items:
   - `evaluate_segment` → `"empty receipt is complete only for event-driven windows"` when `observed_items == 0`
   - trusted seal path (`issue_receipts_parallel.py`) skips empty raw
3. **Dataset COMPLETE** only if **all** required segs COMPLETE:
   - `evaluate_required_segments` aggregate: `all(status == "COMPLETE")`
4. **`ops_reeval_observed_window.py`** explicitly:  
   `coverage_segments untouched; status not forced to COMPLETE`  
   only unions SUCCESS receipts with `raw_row_count > 0` into `observed_*` + C8.

### Policy conclusion — **DEFER; no auto COMPLETE**

There is **no** current contract/receipt rule that excludes pre-API-floor empty months from required inventory without inventing raw.  
`DEFERRED_SOURCE_GAP` / `MISSING_EXPECTED_SEGMENT` still evaluate to **PARTIAL**, not COMPLETE.

**Dataset COMPLETE: NO** for both (honest).

### Human-gate path to dataset COMPLETE (without inventing raw)

Only if product policy accepts **API floor = history start** (matching idx observed_start `2008-05-01` and equities_bars floor):

1. **Contract change (human-gate):**  
   `collection_coverage.json`  
   `indices_bars_daily_topix` + `indices_bars_daily`  
   `history_target_start: "2008-01-01"` → **`"2008-05-01"`**  
   (+ regenerate worker catalog / governed.js if derived from contract)
2. **Re-plan inventory** via `build_required_segments` + `record_required_segments` so `2008-01…04` are **not** required.
3. **Prune orphan residual rows** on remote D1 (existing PARTIAL segs are not auto-deleted by reeval):
   ```sql
   -- human-reviewed only
   DELETE FROM coverage_segments
   WHERE dataset IN ('indices_bars_daily_topix','indices_bars_daily')
     AND segment_id IN ('2008-01','2008-02','2008-03','2008-04');
   ```
4. **Refresh aggregate** `dataset_coverage` (local `refresh_coverage_ledger` → publish, or targeted remote update) so status becomes COMPLETE **only if** remaining segs are all COMPLETE (220/220 after prune).
5. **Do not** seal empty shells (`row_count=0` / `{"data":[]}`) as SUCCESS COMPLETE — empty-raw ban stays.

**This wave did not apply the contract change.** Residual remains PARTIAL with proof.

---

## 4. Publish / freshness

| step | result |
|------|--------|
| `ops_reeval_freshness.py` | **FRESH** `projgen-6ffab6ba59ba4478a133803ef40b4fbf` · segments untouched · mass NO-GO |
| `publish_ops_projection.py --apply-remote` | **race with peer publishes** (wrangler D1 import polling / concurrent full-projection DELETE+reinsert). Guard `local=remote` COMPLETE counts held; full apply not relied on for this track. Targeted reeval + freshness are the fail-closed SoT writes used here. |
| complete_count_guard | ok when probed (local==remote) |
| Mass / READY / Phase7 | **NO-GO / OFF** |

Note: full projection SQL contains `DELETE FROM coverage_segments` / `dataset_coverage` from **local** research mirror; concurrent peer seals + lagging local can wipe remote reeval tips. Prefer targeted reeval after any full publish race.

---

## POST (remote D1 live verify)

| metric | PRE | POST | Δ |
|--------|----:|-----:|--:|
| **topix COMPLETE segs** | **220** | **220** | **0** |
| topix residual PARTIAL | 4 (`2008-01…04`) | **4** | 0 |
| **idx COMPLETE segs** | **220** | **220** | **0** |
| idx residual PARTIAL | 4 | **4** | 0 |
| topix/idx empty COMPLETE | 0 | **0** | 0 |
| platform COMPLETE segs | ~2862 | **~2922** | peers only (this track **+0**) |
| topix observed_end | 2026-08-12 | **2026-08-15** | reeval |
| idx observed_end | 2026-08-11 | **2026-08-14** | reeval |
| projection | — | **FRESH** `projgen-6ffab6ba…` | |

### Residual DEFER (honest)

Both datasets remain **220/224 COMPLETE** with residual:

`2008-01`, `2008-02`, `2008-03`, `2008-04`

Re-dispatch **8/8 pass**, all **`row_count=0` / `rowsInserted=0` / page body `{"data":[]}`**.  
Honest empty-raw ban: **no seal**, **no COMPLETE**, **Worker pass ≠ Coverage COMPLETE**.

| dataset | dataset COMPLETE? | why |
|---------|-------------------|-----|
| `indices_bars_daily_topix` | **NO** | residual 4 empty-API months still required by contract `history_target_start=2008-01-01` |
| `indices_bars_daily` | **NO** | same residual; observed_start already `2008-05-01` but inventory still includes pre-floor months |

Prior corroboration: `docs/proof/w0814h_g8_topix_indices_20260814.md`, `docs/proof/w0814b_g3_indices_20260814.md`.

---

## Acceptance

| gate | result |
|------|--------|
| PRE remote D1 for residual months | **PASS** |
| execute both datasets 2008-01…04 | **PASS** (8/8 worker pass) |
| empty-raw ban held (no seal when row_count=0) | **PASS** |
| topix/idx COMPLETE Δ | **0 / 0** (honest) |
| empty COMPLETE | **0** |
| peer backfill PIDs not killed | **PASS** |
| reeval + freshness FRESH | **PASS** |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| T1/T2 closed | **DEFER with proof** (not dataset COMPLETE) |
| human-gate path documented | **PASS** (contract floor move + prune) |

---

## Artifacts

| path | role |
|------|------|
| `.glm-logs/w0815b_g8_topix_idx/` | wave logs, PRE/POST D1, R2 manifests, reeval, publish attempts |
| `.glm-logs/cf-backfill/w0815b_g8_{topix,idx}_gap_*` | plan/queue/state |
| `docs/proof/w0815b_g8_topix_indices_20260815.md` | this proof |

## Explicit non-claims

- **Not** dataset COMPLETE for `indices_bars_daily_topix` or `indices_bars_daily`  
- **Not** segment COMPLETE for `2008-01…04`  
- **Not** observed_start rewrite to 2008-05 for topix  
- **Not** contract `history_target_start` change (human-gate only)  
- **Not** Mass / READY / B0 / Phase7  
