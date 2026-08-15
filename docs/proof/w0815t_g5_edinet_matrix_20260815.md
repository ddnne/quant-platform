# W27-G5 / w0815t_g5 — T5 EDINET matrix residual segs × nz raw (2026-08-15)

**Wave:** `w0815t` / **W27-G5** / **T5**  
**Datasets:** `edinet_cross_shareholdings` residual **~28** · `edinet_large_volume_shareholders` residual **~42**  
**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (empty-raw ban held; no empty shell sealed)  
**Worker pass ≠ COMPLETE:** held  
**cf_premium forever densify ban:** **honored** — residual **matrix scan nz only**; **no** densify  
**major:** **COMPLETE skip** (verify only; **104/104**)  
**force-apply:** **not** used  
**prefix:** `w0815t_g5_*` · logs: `.glm-logs/w0815t_g5_edinet/`

**Live verified:** 2026-08-15 (JST) / ~2026-08-15T02:40Z UTC  
**Base HEAD (pre-proof):** `306bebb`  
**Proof HEAD (post-push):** `d1f0a68`  
**Projection freshness reclock:** `projgen-04a6a3dde3934161afd6fcef31b7dcbd` · `coverage_segments_untouched=1` · Mass **NO-GO**

## Rule (fixed)

```text
matrix: residual segs × nz raw on CF (raw_retention_manifests + R2 manifest windows)
HAS_RAW  (COMPLETE ∧ row_count>0 mapped to residual month) → seal → COMPLETE
EMPTY    (zero-row COMPLETE sample / no nz residual window) → DEFER fixed
no forever densify of empty residual months
```

## Summary

| Metric | PRE | POST | This W27-G5 / T5 |
|--------|----:|-----:|-----------------:|
| `edinet_major_shareholders` COMPLETE | **104** / 104 | **104** / 104 | skip (verify only) |
| `edinet_cross_shareholdings` COMPLETE | **76** / 104 | **76** / 104 | **+0** (`HAS_RAW=0` → DEFER fixed) |
| `edinet_large_volume_shareholders` COMPLETE | **62** / 104 | **62** / 104 | **+0** (`HAS_RAW=0` → DEFER fixed) |
| sealable residual nz (`seal_candidates.json`) | — | **0** | matrix empty |
| empty COMPLETE | **0** | **0** | held |
| Platform COMPLETE (remote D1) | **3457** | **3457** | **+0** this wave |
| `raw_retention_manifests` n/c/nz | **15145** / **12930** / **11430** | _(unchanged by G5)_ | no densify |

## Closed counts per dataset

| dataset | PRE COMPLETE | POST COMPLETE | closed this wave | residual remaining | outcome |
|---------|-------------:|--------------:|-----------------:|-------------------:|---------|
| `edinet_major_shareholders` | **104** | **104** | **0** | **0** | COMPLETE skip / verify only |
| `edinet_cross_shareholdings` | **76** | **76** | **0** | **28** | **DEFER_EMPTY_API_FIXED** |
| `edinet_large_volume_shareholders` | **62** | **62** | **0** | **42** | **DEFER_EMPTY_API_FIXED** |
| **T5 total closed** | — | — | **0** | **70** DEFER fixed | sealable_nz=**0** |

Artifact: `.glm-logs/w0815t_g5_edinet/closed_counts.json`

---

## Path

1. **PRE** remote D1 status + residual segment lists  
2. **Matrix** residual segs × nz COMPLETE manifests on CF (load R2 `manifest.json` windows)  
3. **HAS_RAW** → seal path (would issue receipts + restore + publish)  
4. **EMPTY** → **DEFER fixed** (no `cf_premium_backfill` residual densify)  
5. Receipt-plane **observed-window reeval** (no segment COMPLETE rewrite) + freshness  
6. Proof + **push**

Driver: `.glm-logs/w0815t_g5_edinet/scan_residual_nz.py`

---

## PRE (remote D1)

| dataset | COMPLETE | PARTIAL | residual months | dataset_coverage (PRE reeval) |
|---------|--------:|--------:|-----------------|-------------------------------|
| major | **104** | 0 | — | COMPLETE · observed_start **2019-01-01** → end **2026-08-13** |
| cross | **76** | **28** | `2018-01`…`2020-04` | PARTIAL · **2020-05-01** → **2026-08-13** |
| large | **62** | **42** | `2018-01`…`2021-06` | PARTIAL · **2021-07-01** → **2026-08-13** |

Platform remote COMPLETE **3457**.  
raw_retention_manifests **15145** / COMPLETE **12930** / nz **11430**.

---

## Matrix: residual segs × nz raw (CF)

### Scan method

For each residual segment month:

1. Enumerate remote `raw_retention_manifests` where `completeness='COMPLETE' AND row_count>0`.  
2. Load R2 `raw/{dataset}/{run_id}/manifest.json` → `params.from`/`to` → month key.  
3. Classify:
   - **HAS_RAW** if nz window maps to residual unsealed month → seal candidate  
   - **EMPTY** if residual month only has zero-row COMPLETE samples → DEFER fixed  
4. Sample zero-row COMPLETE manifests to prove empty shells exist for residual months.

### Cross — `edinet_cross_shareholdings` (28 residual)

| scan field | value |
|------------|------:|
| residual months | **28** (`2018-01`…`2020-04`) |
| nz COMPLETE manifests (remote) | **115** |
| nz windows loaded | **97** |
| nz residual windows | **0** |
| nz already-COMPLETE windows | **97** |
| zero-row residual months sampled | **28/28** |
| residual without nz/zero sample | **[]** |
| **HAS_RAW / sealable** | **0** |
| **EMPTY → DEFER fixed** | **28** |

### Large — `edinet_large_volume_shareholders` (42 residual)

| scan field | value |
|------------|------:|
| residual months | **42** (`2018-01`…`2021-06`) |
| nz COMPLETE manifests (remote) | **144** |
| nz residual windows | **0** |
| zero-row residual months sampled | **42/42** |
| residual without nz/zero sample | **[]** |
| **HAS_RAW / sealable** | **0** |
| **EMPTY → DEFER fixed** | **42** |

### Matrix outcome

| dataset | residual | HAS_RAW | EMPTY DEFER | action |
|---------|---------:|--------:|------------:|--------|
| cross | 28 | **0** | **28** | no seal |
| large | 42 | **0** | **42** | no seal |
| **total** | **70** | **0** | **70** | **DEFER fixed** |

**No seal issued.** empty-raw ban held. **No** `cf_premium_backfill` residual densify.

Artifacts:

- `.glm-logs/w0815t_g5_edinet/seal_candidates.json` → `[]`  
- `.glm-logs/w0815t_g5_edinet/matrix_residual_x_nz.json`  
- `.glm-logs/w0815t_g5_edinet/scan_summary.json`  
- `.glm-logs/w0815t_g5_edinet/residual_months.json`  
- `.glm-logs/w0815t_g5_edinet/defer_condition.txt`  
- `.glm-logs/w0815t_g5_edinet/scan_outer.log`  
- `.glm-logs/w0815t_g5_edinet/final_state.json`

### One-line residual condition

```text
DEFER_EMPTY_API: re-try seal when raw_retention_manifests COMPLETE∧row_count>0 appears for residual months cross=2018-01…2020-04 (n=28) large=2018-01…2021-06 (n=42); do not re-densify all empty months forever; major COMPLETE 104/104 skip; sealable_nz=0 this wave.
```

---

## Reeval (no segment COMPLETE rewrite)

```bash
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset edinet_major_shareholders --today 2026-08-15
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset edinet_cross_shareholdings --today 2026-08-15
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset edinet_large_volume_shareholders --today 2026-08-15
.venv/bin/python scripts/ops_reeval_freshness.py
```

| dataset | status | observed_start → end | C8 |
|---------|--------|----------------------|-----|
| major | **COMPLETE** | **`2018-01-04`** → **`2026-08-14`** | **pass** lag 1 |
| cross | **PARTIAL** | **`2020-05-01`** → **`2026-08-14`** | **pass** lag 1 |
| large | **PARTIAL** | **`2021-07-01`** → **`2026-08-14`** | **pass** lag 1 |

Note: major receipt-plane observed_start reclocked **2019-01-01 → 2018-01-04** (SUCCESS nz receipts); **coverage_segments untouched**.

Freshness:

```text
ops_reeval_freshness gen=projgen-04a6a3dde3934161afd6fcef31b7dcbd
OK coverage_segments_untouched=1 mass=NO-GO
```

## Publish

**SKIP** `publish_ops_projection.py --apply-remote` — no this-wave segment COMPLETE delta (sealable_nz=0).  
No `--force-apply-remote`.

## POST COMPLETE months (remote, verified)

| dataset | COMPLETE segment_ids | n | residual |
|---------|----------------------|--:|----------|
| major | 2018-01…2026-08 contiguous | **104** | **[]** |
| cross | 2020-05…2026-08 | **76** | 2018-01…2020-04 (**28**) |
| large | 2021-07…2026-08 | **62** | 2018-01…2021-06 (**42**) |

Platform remote COMPLETE **3457** held.

---

## EDINET DEFER (honest / fixed)

| Item | Why |
|------|-----|
| cross residual 2018-01…2020-04 (**28**) | **DEFER_EMPTY_API_FIXED** — residual months have zero-row COMPLETE R2 samples; HAS_RAW **0**; sealable **[]** |
| large residual 2018-01…2021-06 (**42**) | **DEFER_EMPTY_API_FIXED** — residual months zero-row; HAS_RAW **0**; sealable **[]** |
| re-densify all empty residual months | **banned this wave** (no forever empty re-acq) |
| COMPLETE without raw / empty `{"data":[]}` | **Forbidden** |
| major re-acq | **skip** (104/104 COMPLETE) |

**Retry condition (only):** nz raw appears (`raw_retention_manifests` COMPLETE ∧ `row_count>0` for residual month windows) → seal → COMPLETE those segs. Do **not** re-densify all 70 empty months forever.

---

## Explicit non-claims

- EDINET cross/large residual segment COMPLETE **not** claimed (+0).  
- cross / large dataset-level COMPLETE **not** claimed (still PARTIAL).  
- Platform Mass / READY / Phase7 **not** claimed.  
- No densify / no dual-run residual acq this wave.  
- empty COMPLETE **0**.  
- Platform COMPLETE **+0** this agent (3457 held).

## Forbidden held

- empty COMPLETE — **0**  
- Mass / READY / Phase7 ON — **NO-GO / OFF**  
- forever densify EDINET empty residual — **none**  
- invent COMPLETE without nz raw — **none**  
- kill peer jobs — **none**

---

## Operator repro

```bash
# T5 matrix residual segs × nz raw on CF (expect sealable=0)
.venv/bin/python -u .glm-logs/w0815t_g5_edinet/scan_residual_nz.py
cat .glm-logs/w0815t_g5_edinet/seal_candidates.json   # []
cat .glm-logs/w0815t_g5_edinet/closed_counts.json
cat .glm-logs/w0815t_g5_edinet/defer_condition.txt
# HAS_RAW only: if seal_candidates.json non-empty → seal → restore → publish
# EMPTY: DEFER fixed — do not densify forever

.venv/bin/python scripts/ops_reeval_observed_window.py --dataset edinet_cross_shareholdings --today 2026-08-15
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset edinet_large_volume_shareholders --today 2026-08-15
.venv/bin/python scripts/ops_reeval_freshness.py
```

---

## Logs

`.glm-logs/w0815t_g5_edinet/` — PRE/POST D1 counts, residual lists, matrix residual×nz scan, seal_candidates=[], closed_counts, defer_condition, reeval major/cross/large, freshness, final_state.

## Report line

`SHA=d1f0a68ca847ee441897f3eddfb542e3954cfcff COMPLETE PRE major/cross/large=104/76/62 POST=104/76/62 (+0/+0/+0); closed_this_wave=0/0/0; residual DEFER fixed cross=28 large=42; matrix HAS_RAW=0 EMPTY=70; sealable_nz=0; densify ban held; empty COMPLETE=0; platform remote 3457 held; Mass=NO-GO; FRESH projgen-04a6a3dd…`
