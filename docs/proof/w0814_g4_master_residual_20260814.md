# G4 — `equities_master` residual (backfill + raw seal gate) — 2026-08-14

**Mass / READY / Phase7:** **NO-GO / OFF**  
**empty COMPLETE:** **0**  
**kill peers:** **none** (bars/mb/edinet/margin seal left alone)  
**worker pass ≠ Coverage COMPLETE**

**Prefix:** `w0814_g4_master_*`  
**Scope:** residual planner months for `equities_master` after G2 close at COMPLETE **220/314**.  
Seal **raw months only**; **skip misdated pre-2008-05** (and empty).

## PRE / POST

| Metric | PRE | POST | Δ |
|--------|----:|-----:|--:|
| **Local** `equities_master` COMPLETE segs | **220** | **220** | **0** |
| **Remote** `equities_master` COMPLETE segs | **220** | **220** | **0** |
| Local master PARTIAL | **94** | **94** | 0 |
| Remote master PARTIAL / UNKNOWN | **74 / 20** | **74 / 20** | 0 |
| Local / remote total COMPLETE segs | **942** | **942** | 0 |
| empty COMPLETE | 0 | **0** | 0 |
| Remote `raw_retention_manifests` n/c | **9687 / 8567**† | **10273 / 8712** | +peer acq |

† Instruction-final residual SoT baseline; this track did not drive the raw Δ.

Projection after reeval freshness: **FRESH** `projgen-14c0bb95ccce4fdeb72dba86770c2429`  
(`coverage_segments_untouched=1`; mass=NO-GO).

Observed window reeval (`ops_reeval_observed_window.py --dataset equities_master --today 2026-08-14`):

| field | value |
|-------|------|
| status | **PARTIAL** |
| observed_start | **`2006-08-13`** |
| observed_end | **`2026-08-13`** |
| C8 | **pass** lag **1** |

## 1) `cf_premium_backfill` residual

### Wave 1 (spec)

```text
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets equities_master \
  --execute --workers 3 --general-rpm 495 --max-jobs 0 \
  --plan-out  .glm-logs/cf-backfill/w0814_g4_master_plan.json \
  --queue-out .glm-logs/cf-backfill/w0814_g4_master_queue.json \
  --state-out .glm-logs/cf-backfill/w0814_g4_master_state.jsonl
```

| field | value |
|-------|------:|
| plan jobs | **21** (`2006-08` … `2008-04`) |
| executed | **21** |
| **pass** | **0** |
| **fail** | **21** |
| host POST/min | **23.12** (window ~52s; host envelope 429 = **0**) |

### Wave 2 (paced retry)

```text
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets equities_master \
  --execute --workers 2 --general-rpm 200 --max-jobs 0 \
  --sleep-on-retry 5 \
  --plan-out  .glm-logs/cf-backfill/w0814_g4_master_retry_plan.json \
  --queue-out .glm-logs/cf-backfill/w0814_g4_master_retry_queue.json \
  --state-out .glm-logs/cf-backfill/w0814_g4_master_retry_state.jsonl
```

| field | value |
|-------|------:|
| executed | **21** |
| **pass** | **0** |
| **fail** | **21** |
| host POST/min | **20.3** (host envelope 429 = **0**) |

### Fail taxonomy (both waves identical)

| class | n | notes |
|-------|--:|-------|
| HTTP **400** subscription edge | **1** | `2006-08` `from=2006-08-13` vs sub start `2006-08-14` |
| HTTP **429** (upstream transient) | **20** | Worker→JQ retries exhausted; concurrent general-pool peers |

**Note:** Planner residual is exactly the **21** misdated pre-2008-05 months DEFERred in G2 (`w0713_t2_master_close`). Pre-plan PARTIAL `2000-07`…`2006-07` remain outside contract history start (not queued).

## 2) Seal raw months only (window gate)

Path: local residual raw mirror + R2 first-page probe → **Date ∈ segment month**.

| class | n | action |
|-------|--:|--------|
| **window-ok** (page `Date` ∈ segment month) | **0** | none to seal |
| **window-bad** (page `Date` stuck on `2008-05-07`) | **21** | **DEFER** — not sealed |
| empty raw | **0** | — |
| sealed ready | **0** | — |

**DEFER months (no COMPLETE invented):**  
`2006-08` … `2008-04` (21). R2/local pages claim month windows but bodies are identical digests of `2008-05-07` snapshots. In-window `jquants_records` count for residual months = **0** (rows normalize into `2008-05`).

Artifacts:

- `.glm-logs/w0814-g4-master/seal_summary.json`
- `.glm-logs/w0814-g4-master/window_ok.json` (empty)
- `.glm-logs/w0814-g4-master/window_bad.json`
- `.glm-logs/w0814-g4-master/seal_map.json`
- `.glm-logs/cf-backfill/w0814_g4_master_*.jsonl` / plan / queue / run logs
- `.glm-logs/w0814-g4-master/post.json`

## 3) Receipts / publish

| step | result |
|------|--------|
| signed issue for residual | **skipped / N/A** — window_ok **0**; no honest raw+struct in residual windows |
| full `publish_ops_projection --apply-remote` | **not required** — COMPLETE Δ **0** (fail-closed path not needed) |
| `ops_reeval_freshness` | **OK** `projgen-14c0bb…`; segs untouched; Mass **NO-GO** |

## Explicit non-claims / DEFER

| Item | Status |
|------|--------|
| COMPLETE without usable in-window raw | **Forbidden** — held |
| `2006-08`…`2008-04` (21) | **DEFER** — misdated `2008-05-07` bodies; acq 0p/21f×2 |
| Pre-plan PARTIAL `2000-07`…`2006-07` | **DEFER** — outside planner residual / no honest raw |
| Backfill fail residual (21, mostly 429 + 1 sub 400) | **OPEN** optional later retry when general pool quiet; seal does not invent |
| Dataset-level COMPLETE for `equities_master` | still **PARTIAL** (history hole pre-2008-05) |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| Peer acq/issue killed? | **no** |

## Verdict

| Check | Result |
|-------|--------|
| master COMPLETE PRE→POST | **220 → 220 (+0)** local = remote |
| residual plan executed | **PASS** (21+21 jobs; honest fails) |
| raw-required seal only / misdated skip | **PASS** (window_ok **0**, sealed **0**) |
| empty COMPLETE | **0 PASS** |
| no peer kill | **PASS** |
| C8 master | **pass** lag **1** |
| Mass / Phase7 | **NO-GO / OFF PASS** |
| Overall G4 master residual | **PASS** (honest +0; 21 misdated months remain DEFER) |

## Operator repro

```bash
# residual plan (expect 21 = 2006-08…2008-04 while COMPLETE=220)
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets equities_master --workers 3 --general-rpm 495 --max-jobs 0 \
  --plan-out .glm-logs/cf-backfill/w0814_g4_master_plan.json \
  --queue-out .glm-logs/cf-backfill/w0814_g4_master_queue.json

# seal gate (window-ok only; skip misdated pre-2008-05)
.venv/bin/python -u .glm-logs/w0814-g4-master/seal_scan_and_prep.py

# reeval (no COMPLETE claim)
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset equities_master --today 2026-08-14 --freshness-days 7
.venv/bin/python scripts/ops_reeval_freshness.py
```
