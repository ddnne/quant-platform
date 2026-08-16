# W72 / w0816f — tip auto-collect path (bars_am + OTC) (2026-08-16)

**Wave:** W72 / `w0816f` · Task B  
**Implementer:** GLM5.3 (Grok does not implement)  
**Mass / READY / Phase7:** **NO-GO / not declared / OFF**  
**empty-raw COMPLETE:** **FORBIDDEN**  
**Do not break existing tip COMPLETE:** held (bars_am tip `2026-08` · OTC island **93**)  
**Commit/push:** wave close (Task D)

**Logs:** [`.glm-logs/w0816f_w72_tip_only/`](../../.glm-logs/w0816f_w72_tip_only/)

---

## 1. Cron / tip collect entrypoints (found)

### bars_am — premium worker (continuous tip)

| item | value |
|------|-------|
| Worker | `quant-platform-ingestion-premium` |
| Config | [`platform/workers/ingestion-premium/wrangler.toml`](../../platform/workers/ingestion-premium/wrangler.toml) |
| Cron | **`15 * * * *`** (hourly :15 UTC) |
| Handler | `scheduled` → `runIngestion(env, {}, "cron", fetch)` |
| Dataset set | all `PREMIUM_CORE_DATASETS` (includes `equities_bars_daily_am`) |
| Vendor contract | `date_mode=today` · path `/v2/equities/bars/daily/am` · params `code`,`date` |
| Manual tip | `POST /v1/run?dataset=equities_bars_daily_am` (auth gated) |
| History backfill | **not** tip path · PD-D4 history re-probe **FORBIDDEN** (W71 empty) |

Source: `platform/workers/ingestion-premium/src/index.ts` · `catalog.ts` · `jquants_premium_core.json`.

### OTC — JSDA worker (tip island / wait FULL_OK)

| item | value |
|------|-------|
| Worker | `quant-platform-ingestion-jsda` |
| Config | [`platform/workers/ingestion-jsda/wrangler.toml`](../../platform/workers/ingestion-jsda/wrangler.toml) |
| Cron | **`30 1 * * *`** (01:30 UTC = 10:30 JST) |
| Handler | `scheduled` → `runAll(env, "cron")` |
| Dataset | `jsda_otc_bond_reference_prices` (plus repo + corp) |
| Index | `market.jsda.or.jp` OTC reference index |
| Manual tip | `POST /v1/run?dataset=jsda_otc_bond_reference_prices` |
| Bulk archive densify | **FORBIDDEN** (PD-D5) |

Source: `platform/workers/ingestion-jsda/src/index.ts`.

---

## 2. Path: new tip → collect → seal → aggregate sync

```text
[1 COLLECT]
  bars_am: premium cron / POST /v1/run  (date_mode=today → tip day only)
  OTC:     jsda cron / POST /v1/run     (discovery + FULL_OK gate)

[2 EVIDENCE]
  raw in R2 (non-empty) + structured rows + digests
  empty raw → stop (empty-raw COMPLETE FORBIDDEN)

[3 SEAL]
  issue_signed_receipts_for_segments.py   OR
  issue_receipts_parallel.py              OR
  restore_local_complete_from_receipt.py
  → signed SUCCESS receipt + coverage_segments COMPLETE
  (OTC: only FULL_OK_NEW days; prior seal_otc_tip pattern)

[4 AGGREGATE SYNC]
  sync_dataset_coverage_from_segments(conn, datasets=[…])
  → honest dataset_coverage.status / status_counts
  → never invents segs; refuses empty COMPLETE

[5 OPS FRESH]
  scripts/ops_reeval_freshness.py
  (coverage_segments untouched)
```

Checklist refs:

- [`docs/complete_segment_checklist.md`](../complete_segment_checklist.md) §9 aggregate follow-up  
- [`docs/operations/safe_complete_one_segment.md`](../operations/safe_complete_one_segment.md) §5b  
- W70 aggregate path: [`w0816d_w70_aggregate_followup_20260816.md`](w0816d_w70_aggregate_followup_20260816.md)

---

## 3. Gap found + minimal wire (W72)

| path | pre-W72 | W72 |
|------|---------|-----|
| `restore_local_complete_from_receipt.py` | already called `sync_dataset_coverage_from_segments` (W70) | **held** |
| `issue_signed_receipts_for_segments.py` | refresh only · **no surgical re-agg** | **wired** post-refresh sync |
| `issue_receipts_parallel.py` | refresh only · **no surgical re-agg** | **wired** post-refresh sync |
| premium / jsda cron collect | tip collect already live | **unchanged** (no break tip COMPLETE) |

### Wire detail

After successful issue + `refresh_coverage_ledger`:

```python
reagg = sync_dataset_coverage_from_segments(
    conn,
    datasets=ds_list,  # or touched
    wave="issue_signed_receipts_for_segments",  # or issue_receipts_parallel
)
```

Rules (fail-closed, same as restore/W70):

- promotes `dataset_coverage` → COMPLETE only when **all** segs COMPLETE  
- never invents / rewrites `coverage_segments`  
- refuses empty COMPLETE (`receipt_run_id` null/0)  
- safe on tip-only PARTIAL datasets (bars_am 1/31, OTC 93/8781): action is `verify_only` / `counts_refreshed`, **not** invent Dataset COMPLETE  

### Existing tip COMPLETE held

| dataset | tip COMPLETE | this wave seal | invent |
|---------|-------------:|:--------------:|:------:|
| bars_am | **1** (`2026-08`) | **0** | no |
| OTC | **93** | **0** | no |

No densify history · no FULL_OK invent · no empty-raw seal.

---

## 4. Operator tip-only loop (policy-aligned)

```bash
# bars_am tip only — never residual history queue (PD-D4 history_reprobe FORBIDDEN)
# Prefer cron; manual:
# POST premium /v1/run?dataset=equities_bars_daily_am

# OTC tip only — seal only when FULL_OK_NEW; no archive densify
# Prefer cron; manual FULL_OK probe then seal path as prior waves

# After nz tip seal (issue path now auto-syncs aggregate):
.venv/bin/python scripts/issue_signed_receipts_for_segments.py \
  --db data/structured/ingestion.sqlite --dataset equities_bars_daily_am --limit 5

# Explicit re-agg still available:
.venv/bin/python scripts/sync_dataset_coverage_from_segments.py \
  --db data/structured/ingestion.sqlite --datasets equities_bars_daily_am

.venv/bin/python scripts/ops_reeval_freshness.py
```

---

## 5. Return

| check | result |
|-------|--------|
| bars_am cron tip path found | **yes** · hourly premium |
| OTC cron tip path found | **yes** · daily JSDA |
| seal → aggregate sync wired on issue paths | **yes** (minimal) |
| existing tip COMPLETE broken | **no** |
| history densify / COMPLETE invent | **no** |
