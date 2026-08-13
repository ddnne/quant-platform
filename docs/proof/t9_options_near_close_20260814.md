# T9 options_near close — week-chunk acq + June/July COMPLETE seals (2026-08-14)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** none (raw + structured + signed SUCCESS only)  
**cf_premium dual-run ban:** **honored** — did **not** kill live `t5_fins_paced` / other peers  
**prefix:** `t6_options_near_*` + retry · workers=1 · general RPM 25 · week-chunks 7d  
**PRE tip (residual):** COMPLETE **538** / raw_n **7430** (T13–T15 sync)

## Goal

1. Finish live `t6_options_near` wave for `derivatives_bars_daily_options` `2026-06-01`…`2026-07-31`.
2. Resume only if dead with residual queue (June mid-weeks HTTP 503).
3. Seal **only** months with non-empty raw (empty-raw ban) → signed receipts → fail-closed publish.
4. Reeval options observed window (no segment rewrite / no COMPLETE claim from reeval).

## Worker pass (acq)

### Primary wave (`t6_options_near_state.jsonl`, max-jobs=16)

```bash
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets derivatives_bars_daily_options \
  --from-date 2026-06-01 --to-date 2026-07-31 \
  --execute --workers 1 --general-rpm 25 --sleep-on-retry 10 --max-jobs 16 \
  --week-chunks --chunk-days 7 \
  --plan-out .glm-logs/cf-backfill/t6_options_near_plan.json \
  --state-out .glm-logs/cf-backfill/t6_options_near_state.jsonl
```

| Field | Value |
|-------|-------|
| plan jobs | **9** week-chunks |
| primary state | **7 pass / 2 fail** |
| fails | `2026-06-15..21`, `2026-06-22..28` — **HTTP 503** |
| process | exited after full plan drain (not killed) |

### Resume (`t6_options_near_retry_*`, same dataset)

```bash
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets derivatives_bars_daily_options \
  --from-date 2026-06-15 --to-date 2026-06-28 \
  --execute --workers 1 --general-rpm 25 --max-jobs 16 \
  --week-chunks --chunk-days 7 \
  --plan-out .glm-logs/cf-backfill/t6_options_near_retry_plan.json \
  --state-out .glm-logs/cf-backfill/t6_options_near_retry_state.jsonl
```

| Field | Value |
|-------|-------|
| retry jobs | **2** |
| retry result | **2/2 pass** |
| unique pass windows | **9/9** covering Jun–Jul near range |

Worker pass ≠ Coverage COMPLETE.

## Seal path (raw-required, empty-raw ban)

Week-chunk R2 runs merged per calendar month → local full raw (audit) + sealpage under 25MB usable-raw gate → `jquants_records` upsert → `issue_receipts_parallel.py --struct-hint` → fail-closed `publish_ops_projection.py --apply-remote`.

| dataset | segment_id | structured | sealpage bytes | receipt run_id | R2 week runs (ex.) |
|---------|------------|----------:|---------------:|---------------:|--------------------|
| `derivatives_bars_daily_options` | **2026-07** | **842608** | 5315381 | **900586** | 6360, 6368, 6377, 6339, 6345 |
| `derivatives_bars_daily_options` | **2026-06** | **866966** | 5315395 | **900587** | 6331, 6385, 6401, 6408, 6360 |

Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`.  
Empty `{"data":[]}` / zero-row pages rejected. No month sealed without non-empty raw.

### Session +N (this T9 seal set)

| item | +N |
|------|---:|
| options **2026-06** + **2026-07** new COMPLETE | **+2** |

### Publish (fail-closed)

```text
complete_count_guard ok local=560 remote=538 force=False → remote=560
```

Local ledger already held peer-ready COMPLETE inventory (e.g. T12 fins seal wave) at **558** before this session's two options issues (**559** then **560**). Publish applied full local inventory honestly. **T9 options contribution remains +2**; remote tip moved **538 → 560** (**+22** total incl. peer-ready seals already on the local mirror).

## POST (remote D1 — verified)

| Metric | POST |
|--------|-----:|
| Segment COMPLETE | **560** |
| Dataset COMPLETE | **2** (calendar + tokyo_repo; unchanged) |
| `raw_retention_manifests` | **7483** |
| Projection | **FRESH** `projgen-eed4156f98884bc78324481299499199` age=0 |

### options COMPLETE months (remote)

| dataset | COMPLETE segment_ids | n |
|---------|----------------------|--:|
| `derivatives_bars_daily_options` | **2026-06**, **2026-07**, **2026-08** | **3** |

## Reeval

```bash
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset derivatives_bars_daily_options --today 2026-08-14
.venv/bin/python scripts/ops_reeval_freshness.py
```

| dataset | status | observed_start → end | C8 |
|---------|--------|----------------------|-----|
| options | **PARTIAL** | `2026-06-01` → **`2026-08-13`** | **pass** lag 1 |

No segment rewrite. No COMPLETE / Mass / READY claim from reeval. Dataset remains **PARTIAL** honest (catalog months remain open before 2026-06).

## Forbidden held

- empty COMPLETE — none
- Mass / READY / Phase7 ON — **NO-GO / OFF**
- kill fins / peers — none (`t5_fins_paced_runner` left running)

## Report line

`SHA=513e264 COMPLETE=560 options_near pass=9/9 (retry 2/2) fail_primary=2×503 sealed=+2 (2026-06/07 run_ids 900587/900586) remote+22 incl peer-ready`
