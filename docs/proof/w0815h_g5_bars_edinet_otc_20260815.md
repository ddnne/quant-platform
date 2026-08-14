# W16-G5 / w0815h_g5 — T7 bars + T8–T9 EDINET + T10 JSDA OTC (2026-08-15)

**Wave:** `w0815h` / **W16-G5** / **T7–T10**  
**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (empty-raw ban held; no empty shell sealed)  
**Worker pass ≠ COMPLETE:** held  
**cf_premium dual-run ban:** **honored** — no competing densify on EDINET residual (prior empty API; scan-only)  
**prefix:** `w0815h_g5_*` · logs: `.glm-logs/w0815h_g5_misc/`

**Live verified:** 2026-08-15 (JST) / ~2026-08-14T23:09Z UTC  
**Base HEAD (pre-proof):** `d674f3b`  
**Proof HEAD (post-push):** `7daadf7`  
**Projection freshness reclock:** `projgen-7176afff0c274129a670d3015db92597` · `coverage_segments_untouched=1` · Mass **NO-GO**

## Summary

| Metric | PRE | POST | This W16-G5 |
|--------|----:|-----:|------------|
| `equities_bars_daily` COMPLETE segs | **220** / 272 | **220** / 272 | **+0** (post-floor residual empty; pre-2008-05 DEFER) |
| bars post-floor PARTIAL residual | **[]** | **[]** | window_ok already sealed prior waves |
| `edinet_major_shareholders` COMPLETE | **104** / 104 | **104** / 104 | verify only |
| `edinet_cross_shareholdings` COMPLETE | **76** / 104 | **76** / 104 | **+0** seal (residual nz **0**) |
| `edinet_large_volume_shareholders` COMPLETE | **62** / 104 | **62** / 104 | **+0** seal (residual nz **0**) |
| `jsda_otc_bond_reference_prices` COMPLETE | **48** / 8781 | **49** / 8781 | **+1** (`2026-06-10`) |
| `jsda_corporate_bond_transactions` | **12/12 COMPLETE** | **12/12 COMPLETE** | skip seal (verify only) |
| `jsda_tokyo_repo_rates` | **COMPLETE** 1/1 | **COMPLETE** 1/1 | skip seal (verify only) |
| empty COMPLETE (this wave seals) | **0** | **0** | held |
| Platform COMPLETE (remote D1) | **3391** | **3403** | G5 OTC **+1** (+ peer progress) |
| `raw_retention_manifests` n/c/nz | **14910** / **12730** / **11241** | **14930** / **12732** / **11243** | peers + G5 R2 put |

---

## T7 — `equities_bars_daily` (post-floor residual only)

### Goal

1. Post-floor residual only; **pre-2008-05 DEFER skip** (no re-acq).  
2. Seal `window_ok` holes if any; densify only non-DEFER PARTIAL.  
3. reeval observed_window + freshness; proof even if **+0**.

### PRE (remote D1)

| metric | value |
|--------|------:|
| COMPLETE segs | **220** |
| PARTIAL segs | **52** (all pre-**2008-05**) |
| post-floor residual PARTIAL | **[]** |
| mid-band / island targets | `2013-05`, `2013-07`, `2025-06…10` already **COMPLETE** (prior W9/W11) |
| empty COMPLETE | **0** |
| observed_start | **2008-05-01** |
| densify | **SKIP** — no non-DEFER PARTIAL |

Artifacts: `.glm-logs/w0815h_g5_misc/pre_bars_postfloor_partial.json` · `t7_bars_verify.json`

### Execute

| step | result |
|------|--------|
| post-floor residual inventory | **0** months |
| densify (`cf_premium_backfill`) | **not run** (rule: densify only non-DEFER PARTIAL) |
| seal window_ok holes | **none remaining** (prior waves sealed all 7) |
| pre-2008-05 | **DEFER** held — no re-acq |

Local verify (window_ok targets all COMPLETE with non-null receipt_run_id):

| segment | status | receipt_run_id |
|---------|--------|---------------:|
| 2013-05 | COMPLETE | 903384 |
| 2013-07 | COMPLETE | 903409 |
| 2025-06…10 | COMPLETE | 903254 / 903370…903373 |
| 2026-01…08 | COMPLETE | tip band held |

### Reeval

```bash
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset equities_bars_daily --today 2026-08-15
```

| field | PRE | POST |
|-------|-----|------|
| observed_start | **2008-05-01** | **2008-05-01** (held) |
| observed_end | 2026-08-12 | **2026-08-14** |
| status | PARTIAL | PARTIAL |
| C8 | — | **pass** lag **1** |
| COMPLETE segs | 220 | **220** (no inflate) |

### T7 DEFER

| Item | Why |
|------|-----|
| pre-2008-05 PARTIAL (52) | empty API band **DEFER**; no empty COMPLETE; no re-acq |
| further COMPLETE growth | only via pre-floor policy change or new tip months |

---

## T8–T9 — EDINET cross / large (nz scan only)

### Goal

1. Prior residual empty — **scan nz only**.  
2. If empty → **DEFER**; **no full re-densify forever**.  
3. major COMPLETE skip (verify only).  
4. Seal only residual months with COMPLETE∧`row_count>0` raw.

### PRE (remote D1)

| dataset | COMPLETE | PARTIAL | residual months | dataset_coverage |
|---------|--------:|--------:|-----------------|------------------|
| major | **104** | 0 | — | **COMPLETE** |
| cross | **76** | **28** | 2018-01…2020-04 | PARTIAL |
| large | **62** | **42** | 2018-01…2021-06 | PARTIAL |

### Execute (seal-only / no densify)

Driver: `.glm-logs/w0815h_g5_misc/scan_residual_nz.py`

1. Remote residual PARTIAL month lists.  
2. Remote `raw_retention_manifests` COMPLETE ∧ `row_count>0` (cross **111**, large **140**).  
3. Load R2 manifests → window month → filter residual ∧ unsealed ∧ nz.  
4. Sample zero-row COMPLETE manifests for DEFER proof.

| scan | cross | large |
|------|------:|------:|
| residual months | **28** | **42** |
| nz COMPLETE manifests | 111 | 140 |
| nz windows loaded | 97 | (loaded) |
| nz windows already COMPLETE months | 97 | (complete band only) |
| **nz residual windows** | **0** | **0** |
| zero-row residual months sampled | **28/28** | **42/42** |
| residual without empty densify sample | **[]** | **[]** |
| **sealable residual nz** | **0** | **0** |

Artifacts:

- `.glm-logs/w0815h_g5_misc/seal_candidates.json` → `[]`  
- `.glm-logs/w0815h_g5_misc/scan_summary.json`  
- `.glm-logs/w0815h_g5_misc/residual_months.json`  
- `.glm-logs/w0815h_g5_misc/defer_condition.txt`

**No seal issued.** empty-raw ban held. **No** `cf_premium_backfill` residual densify (forever re-burn ban).

### One-line residual condition

```text
DEFER_EMPTY_API: re-try seal when raw_retention_manifests COMPLETE∧row_count>0 appears for residual months cross=2018-01…2020-04 (n=28) large=2018-01…2021-06 (n=42); do not re-densify all empty months forever; major COMPLETE 104/104 skip; sealable_nz=0 this wave.
```

### Reeval (no segment COMPLETE rewrite)

| dataset | status | observed_start → end | C8 |
|---------|--------|----------------------|-----|
| major | **COMPLETE** | **`2018-01-04`** → `2026-08-14` | **pass** lag 1 |
| cross | **PARTIAL** | **`2020-05-01`** → `2026-08-14` | **pass** lag 1 |
| large | **PARTIAL** | **`2021-07-01`** → `2026-08-14` | **pass** lag 1 |

### EDINET DEFER (honest)

| Item | Why |
|------|-----|
| cross residual 2018-01…2020-04 (28) | **DEFER_EMPTY_API** — all 28 months zero-row COMPLETE R2 manifests; sealable **[]** |
| large residual 2018-01…2021-06 (42) | **DEFER_EMPTY_API** — all 42 months zero-row; sealable **[]** |
| re-densify all empty residual months | **banned this wave** (prior empty densify known; no forever empty re-acq) |
| COMPLETE without raw / empty `{"data":[]}` | **Forbidden** |

---

## T10 — JSDA OTC tip/recent (HTTP 200 CSV only)

### Path

1. **COMPLETE skip** corp + tokyo repo (verify only).  
2. Index `market.jsda.or.jp` **HTTP 200** (62_958 B); tip codes `S260817…S260803` already COMPLETE.  
3. Tip extend `S260818/819/820` → **HTTP 404** (not published).  
4. Mid-June residual + late-May tip/recent probe:  
   - **`S260610`** full **HTTP 200** CSV (2_140_474 B, **12319** lines) → **seal**.  
   - Remaining mid-June (`S260609…601`) + late-May band → **connect timeout (000 / rc=28)** → **DEFER**.  
5. Operator seal → R2 put (sha match) → publish → freshness.

### Corporate / Repo (COMPLETE skip)

- **Corporate:** segment COMPLETE **12/12** (`2015`…`2026`); dataset **COMPLETE** — no seal.  
- **Tokyo repo:** dataset **COMPLETE**, segment `jsda-era-timeseries` **COMPLETE** — no seal.

Artifact: `.glm-logs/w0815h_g5_misc/verify_complete_skip.json`

### OTC sealed this wave (**+1**)

| segment_id | raw | rows | receipt run_id | digest (sha256) |
|------------|-----|-----:|---------------:|-----------------|
| **2026-06-10** | `S260610.csv` | **12319 / 12319** | **903805** | `8e712679…1b6a5dd9` |

Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / identity-matched inventory.  
Fetched via: `direct_jsda_http+local_raw` (site window) + R2 put for retention.

R2 key (GET sha match):

```text
raw/jsda/jsda_otc_bond_reference_prices/file_S260610.csv/8e712679caa062c0c71cfb7ffd26c3a1002893e7d79cff0b1c8411521b6a5dd9.csv
```

### POST OTC COMPLETE (**49**)

`2026-06-02`, `2026-06-03`, **`2026-06-10`**, `2026-06-11`, `2026-06-12`, `2026-06-15`…`2026-06-19`, `2026-06-22`…`2026-06-26`, `2026-06-29`, `2026-06-30`, July full trading band, `2026-08-03`…`08-07`, `08-10`, `08-12`…`08-14`, `08-17`.  
Dataset still **PARTIAL** (history target 2002-08-02; inventory **8781**; observed_start **2026-06-02**).

### JSDA DEFER (honest)

| Item | Why |
|------|-----|
| OTC mid-June residual (`06-09`…`06-01` excl sealed `06-10`) | Connect timeout (000 / curl rc=28). **No raw → no COMPLETE**. |
| Late-May tip/recent (`S260529`…`S260508` band) | Connect timeout (000 / rc=28). **No invent**. |
| Tip extend `S260818+` | **HTTP 404** not published. |
| OTC full archive (~8732 PARTIAL remain) | Site flake + no full archive crawl this wave. |
| Non-trading / missing official tip days | Not sealed as COMPLETE |
| COMPLETE without raw / empty shell | **Forbidden** (empty COMPLETE **0** on OTC) |

Artifact: `.glm-logs/w0815h_g5_misc/jsda_defer.json` · `probe_summary.txt` · `download_ok.txt` · `download_fail.txt`

---

## Publish (fail-closed)

```text
complete_count_guard ok local=3403 remote=3402 force=False
remote projection applied (13014 queries)
ops_reeval_freshness → projgen-7176afff0c274129a670d3015db92597
OK coverage_segments_untouched=1 mass=NO-GO
```

No `--force-apply-remote`.  
Remote D1 post-check: OTC COMPLETE **49**; bars **220**; EDINET major/cross/large **104/76/62**; empty COMPLETE on sealed datasets **0**.

Platform remote COMPLETE **3391 → 3403** includes G5 OTC **+1** and concurrent peer seals mid-window.

---

## Explicit non-claims

- bars COMPLETE growth **not** claimed (+0; residual already closed).  
- EDINET cross/large residual segment COMPLETE **not** claimed (+0).  
- OTC dataset-level COMPLETE **not** claimed (still PARTIAL vs 8781-day inventory).  
- Platform Mass / READY / Phase7 **not** claimed.  
- Corporate/repo seals **not** re-run (already COMPLETE).  
- Timeout-band residual June/May days **not** sealed.  
- No forever re-densify of EDINET empty residual.

## Forbidden held

- empty COMPLETE — **0**  
- Mass / READY / Phase7 ON — **NO-GO / OFF**  
- invent JSDA CSV / partial body seal — **none**  
- kill peer jobs — **none**

---

## Operator repro

```bash
# T7 bars residual (expect post-floor [])
.venv/bin/python - <<'PY'
import sqlite3
con=sqlite3.connect('data/structured/ingestion.sqlite')
print(con.execute("SELECT status, COUNT(*) FROM coverage_segments WHERE dataset='equities_bars_daily' GROUP BY status").fetchall())
post=con.execute("SELECT segment_id FROM coverage_segments WHERE dataset='equities_bars_daily' AND status!='COMPLETE' AND segment_id>='2008-05'").fetchall()
print('post-floor residual', post)
PY
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset equities_bars_daily --today 2026-08-15

# T8–T9 EDINET nz scan (expect sealable=0)
.venv/bin/python -u .glm-logs/w0815h_g5_misc/scan_residual_nz.py
cat .glm-logs/w0815h_g5_misc/seal_candidates.json   # []
cat .glm-logs/w0815h_g5_misc/defer_condition.txt

# T10 OTC tip (when market.jsda.or.jp accepts)
mkdir -p data/raw/jsda/jsda_otc_bond_reference_prices/2026-06-10
curl -o data/raw/jsda/jsda_otc_bond_reference_prices/2026-06-10/S260610.csv \
  "https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/files/2026/S260610.csv"
.venv/bin/python -u .glm-logs/w0815h_g5_misc/seal_otc_tip.py
.venv/bin/python scripts/publish_ops_projection.py --db data/structured/ingestion.sqlite --apply-remote
.venv/bin/python scripts/ops_reeval_freshness.py
```

---

## Logs

`.glm-logs/w0815h_g5_misc/` — PRE/POST D1, bars verify, EDINET scan, OTC probe/seal/R2, publish, reeval, freshness, defer.

## Report line

`SHA=7daadf7911091690a8341bc1a61a53052da835aa COMPLETE PRE bars/major/cross/large/otc=220/104/76/62/48 POST=220/104/76/62/49 (+0/+0/+0/+0/+1); bars post-floor residual=[]; EDINET sealable nz=0 DEFER_EMPTY_API; OTC sealed 2026-06-10 run=903805; platform remote PRE=3391 POST=3403; empty COMPLETE=0; Mass=NO-GO; FRESH projgen-7176afff…`
