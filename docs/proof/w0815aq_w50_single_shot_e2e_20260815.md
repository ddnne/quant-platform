# W50 / w0815aq — single_shot_job CF E2E (T1–T4) (2026-08-15)

**Mass / Phase7:** **NO-GO / OFF** (held · not armed)  
**empty COMPLETE:** not re-evaluated this lane  
**densify / tip collect as primary:** **none**  
**Invent COMPLETE / Dataset COMPLETE 22:** **forbidden** (held **21**)  
**Primary this lane (G1):** one real CF-backed single-shot execute — D1 tip extract → R2 `quant-structured` result+manifest · DEFER 5 fail-closed  
**Not:** Mass loop connection · Phase7 ON · densify · invent COMPLETE 22 · push (G5)

**Live verified:** 2026-08-15 ~`09:50Z` UTC  
**Code HEAD at run:** `dc2a70539665fa16306ea742c021f010b21ee223` (working tree had local single_shot execute extension)  
**Logs:** [`.glm-logs/w0815aq_g1_e2e/`](../../.glm-logs/w0815aq_g1_e2e/)

---

## Verdict

| gate | result |
|------|--------|
| **E2E overall** | **PASS** |
| T1 execute (D1 tip + R2 put) | **PASS** |
| T2 R2 object head | **PASS** (3/3 keys exist) |
| T3 DEFER 5 fail-closed | **PASS** (unit + live) |
| T4 this proof | **written** |

**Honesty:** pass means a **bounded tip-window** single-shot path read CF D1 hot tip and wrote small research artifacts to R2 under the designed keys. Success does **not** mean Mass GO, Phase7 ON, full-history research load, or coverage baseline change.

---

## 1. What was implemented (minimal)

| item | path |
|------|------|
| Execute path | `packages/product/research/single_shot_job.py` — `execute_single_shot_job`, `extract_d1_tip_summaries`, `default_d1_execute`, `default_r2_put`, `head_r2_object` |
| Exports | `packages/product/research/__init__.py` |
| README | `packages/product/research/README.md` |
| Tests | `tests/test_single_shot_research_job.py` (DEFER → `PermanentDeferHistoryError`, dry-run inject execute) |

### Behaviour (held contracts)

| rule | held |
|------|------|
| Inputs | COMPLETE **21** subset only |
| Permanent DEFER 5 | fail-closed `PermanentDeferHistoryError` **before** D1 |
| Tip read | remote D1 `quant-ingest` · table `jquants_records` · date-bounded |
| Artifact write | R2 bucket **`quant-structured`** · prefix `research/single_shot/job={id}/…` |
| Local FS | **not** SoT (optional dry-run staging only) |
| Mass / Phase7 | **NO-GO / OFF** · no env arming switches · AST still blocks mass imports |

`dry_run=True` is available when R2 credentials fail: still runs design + D1 read and stages payloads. **This E2E used real R2 put** (`dry_run=False`).

---

## 2. T1 — live execute (CF)

**Job id:** `w0815aq-g1-e2e`  
**Datasets (speed subset):** `equities_bars_daily`, `markets_calendar`  
**Tip window:** `2026-08-01` … `2026-08-15` (inclusive calendar filter on `substr(event_time,1,10)`)  
**Plane:** D1 hot tip (`quant-ingest`) via wrangler remote

| dataset | tip row_count |
|---------|--------------:|
| `equities_bars_daily` | **26671** |
| `markets_calendar` | **11** |

| field | value |
|-------|-------|
| content_hash | `sha256:61c30b7d3d279667062a9e4d92657a146625321ad9cf76711fb630c624c23c62` |
| R2 put statuses | `put_ok` × 3 |
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| ready_declared | **false** |

Artifacts (logs): `execution.json`, `tip_extract.json`, `freeze_status.json`.

---

## 3. T2 — R2 keys confirmed

Bucket: **`quant-structured`**  
Confirm method: `wrangler r2 object get … --remote` (head-by-download).

| key | exists | bytes |
|-----|:------:|------:|
| `research/single_shot/job=w0815aq-g1-e2e/input_plan.json` | yes | 538 |
| `research/single_shot/job=w0815aq-g1-e2e/result/sha256_61c30b7d3d279667062a9e4d92657a146625321ad9cf76711fb630c624c23c62.json` | yes | 8706 |
| `research/single_shot/job=w0815aq-g1-e2e/manifest.json` | yes | 1019 |

Log: `r2_heads.json`.

Probe (preflight): `research/single_shot/_probe/w0815aq_g1_probe.json` also put/get OK.

---

## 4. T3 — DEFER 5 fail-closed

### Unit

```text
.venv/bin/python -m pytest \
  tests/test_single_shot_research_job.py \
  tests/test_mass_research_gate.py \
  tests/test_permanent_defer_history_guard.py -v
# 28 passed
```

Log: `.glm-logs/w0815aq_g1_e2e/pytest.log`

Asserts `PermanentDeferHistoryError` for each permanent DEFER id and for mixed COMPLETE+DEFER input; execute path does **not** call D1 when DEFER present.

### Live attempt

| case | result |
|------|--------|
| `equities_master` + COMPLETE subset | **rejected** `PermanentDeferHistoryError` (PD-D2-MASTER) |
| each of DEFER 5 alone | **all rejected** |

DEFER 5 ids:

* `equities_master` (PD-D2-MASTER)
* `equities_earnings_calendar` (PD-D4-EARN-CAL)
* `equities_bars_daily_am` (PD-D4-BARS-AM)
* `fins_earnings_date` (PD-MX-EARN-TIP)
* `jsda_otc_bond_reference_prices` (PD-D5-JSDA-OTC)

Logs: `t3_defer_reject.json`, `t3_defer_all5.json`.

---

## 5. Freeze surface (reconfirm)

| constant | value |
|----------|------:|
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| ready_publication | **OFF** |
| ready_declared | **false** |
| connected_to_mass_research_loop | **false** |
| local_sot | **false** |
| COMPLETE 21 count | **21** |
| permanent DEFER count | **5** |

---

## 6. Not done / out of scope

* densify / tip collect as primary  
* mass_research loop wiring  
* Phase7 arming  
* invent Dataset COMPLETE 22  
* full-history R2 JSONL research load (this pass is **D1 tip only**)  
* push to origin (G5)  
* ops FRESH reclock / residual SoT rewrite (other lanes)

---

## 7. Return summary (operator)

| field | value |
|-------|-------|
| **e2e** | **PASS** |
| **R2 paths written** | see §3 (3 keys under `research/single_shot/job=w0815aq-g1-e2e/`) |
| **DEFER reject** | **confirmed** (`PermanentDeferHistoryError` · all 5 + mixed live) |
| **Mass / Phase7** | **NO-GO / OFF** |

Prior waves: [W49 usage deepen](w0815ap_w49_usage_deepen_20260815.md) · [W48 usage readiness](w0815ao_w48_usage_readiness_20260815.md) · [COMPLETE 21 CF read paths](complete21_cf_read_paths_20260815.md).
