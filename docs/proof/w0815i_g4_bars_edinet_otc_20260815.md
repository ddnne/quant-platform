# W17-G4 / w0815i_g4 — T6 bars + T7–T8 EDINET + T9 JSDA OTC (2026-08-15)

**Wave:** `w0815i` / **W17-G4** / **T6–T9**  
**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (empty-raw ban held; no empty shell sealed)  
**Worker pass ≠ COMPLETE:** held  
**cf_premium dual-run ban:** **honored** — no competing densify on EDINET residual (prior empty API; scan-only)  
**Do-not-touch held:** `short_sale` / `topix` / `master` / `breakdown` / `earn_calendar` / `bars_am`  
**prefix:** `w0815i_g4_*` · logs: `.glm-logs/w0815i_g4_misc/`

**Live verified:** 2026-08-15 (JST) / ~2026-08-14T23:42Z UTC  
**Base HEAD (pre-proof):** `df061f8` (wave start PRE also recorded `307065e`; peers landed G3 fins_rest mid-window)  
**Proof HEAD (post-push):** `4630043`  
**Projection freshness reclock:** `projgen-186fbdd1e8fd4f948142ad4beb913ba9` · `coverage_segments_untouched=1` · Mass **NO-GO**

## Summary

| Metric | PRE | POST | This W17-G4 |
|--------|----:|-----:|------------|
| `equities_bars_daily` COMPLETE segs | **220** / 272 | **220** / 272 | **+0** (post-floor residual empty; pre-2008-05 DEFER) |
| bars post-floor PARTIAL residual | **[]** | **[]** | densify SKIP |
| `edinet_major_shareholders` COMPLETE | **104** / 104 | **104** / 104 | verify only |
| `edinet_cross_shareholdings` COMPLETE | **76** / 104 | **76** / 104 | **+0** seal (residual nz **0**) |
| `edinet_large_volume_shareholders` COMPLETE | **62** / 104 | **62** / 104 | **+0** seal (residual nz **0**) |
| `jsda_otc_bond_reference_prices` COMPLETE | **49** / 8781 | **49** / 8781 | **+0** (no new HTTP 200 full CSV) |
| `jsda_corporate_bond_transactions` | **12/12 COMPLETE** | **12/12 COMPLETE** | skip seal (verify only) |
| `jsda_tokyo_repo_rates` | **COMPLETE** 1/1 | **COMPLETE** 1/1 | skip seal (verify only) |
| empty COMPLETE (this wave seals) | **0** | **0** | held |
| Platform COMPLETE (remote D1) | **3409** | **3414** | G4 seals **+0** (+ peer progress) |
| `raw_retention_manifests` n/c/nz | **14953** / **12755** / **11264** | **14971** / **12756** / **11265** | peers |

---

## T6 — `equities_bars_daily` (post-floor residual only)

### Goal

1. Post-floor residual only; **pre-2008-05 DEFER skip** (no re-acq).  
2. Seal `window_ok` holes if any; densify only non-DEFER PARTIAL.  
3. reeval observed_window + freshness; proof even if **+0**.

### PRE (remote D1)

| metric | value |
|--------|------:|
| COMPLETE segs | **220** |
| PARTIAL segs | **52** (all pre-**2008-05**, range `2004-01`…`2008-04`) |
| post-floor residual PARTIAL | **[]** |
| mid-band / island targets | `2013-05`, `2013-07`, `2025-06…10` already **COMPLETE** |
| empty COMPLETE (bars/otc expected_items=0) | **0** |
| observed_start | **2008-05-01** |
| densify | **SKIP** — no non-DEFER PARTIAL |

Artifacts: `.glm-logs/w0815i_g4_misc/pre_bars_postfloor_partial.json` · `t6_bars_verify.json` · `t6_bars_window_ok.json` · `t6_bars_pre2008.json`

### Execute

| step | result |
|------|--------|
| post-floor residual inventory | **0** months |
| densify (`cf_premium_backfill`) | **not run** (rule: densify only non-DEFER PARTIAL) |
| seal window_ok holes | **none remaining** |
| pre-2008-05 | **DEFER** held — no re-acq |

Window_ok targets (all COMPLETE with non-null receipt_run_id):

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

| field | PRE | POST (final) |
|-------|-----|------|
| observed_start | **2008-05-01** | **2008-05-01** (held) |
| observed_end | 2026-08-12 | **2026-08-14** |
| status | PARTIAL | PARTIAL |
| C8 | — | **pass** lag **1** |
| COMPLETE segs | 220 | **220** (no inflate) |

### T6 DEFER

| Item | Why |
|------|-----|
| pre-2008-05 PARTIAL (52) | empty API band **DEFER**; no empty COMPLETE; no re-acq |
| further COMPLETE growth | only via pre-floor policy change or new tip months |

---

## T7–T8 — EDINET cross / large (nz scan only)

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

Drivers:

- live residual + nz COMPLETE manifest counts via D1  
- residual nz window map via R2 scan start (`.glm-logs/w0815i_g4_misc/scan_residual_nz.py`) + prior-wave cached manifests for zero-row DEFER proof  
- **no** `cf_premium_backfill` residual densify

| scan | cross | large |
|------|------:|------:|
| residual months | **28** | **42** |
| nz COMPLETE manifests (remote) | **112** | **141** |
| nz residual windows | **0** | **0** |
| zero-row residual months sampled | **28/28** | **42/42** |
| residual without nz/zero sample | **[]** | **[]** |
| **sealable residual nz** | **0** | **0** |

Artifacts:

- `.glm-logs/w0815i_g4_misc/seal_candidates.json` → `[]`  
- `.glm-logs/w0815i_g4_misc/scan_summary.json`  
- `.glm-logs/w0815i_g4_misc/residual_months.json`  
- `.glm-logs/w0815i_g4_misc/defer_condition.txt`  
- `.glm-logs/w0815i_g4_misc/scan_outer.log`

**No seal issued.** empty-raw ban held. **No** forever re-densify of empty residual months.

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
| cross residual 2018-01…2020-04 (28) | **DEFER_EMPTY_API** — residual months have zero-row COMPLETE R2 samples; sealable **[]** |
| large residual 2018-01…2021-06 (42) | **DEFER_EMPTY_API** — residual months zero-row; sealable **[]** |
| re-densify all empty residual months | **banned this wave** (prior empty densify known; no forever empty re-acq) |
| COMPLETE without raw / empty `{"data":[]}` | **Forbidden** |

---

## T9 — JSDA OTC tip/recent (HTTP 200 CSV only)

### Path

1. **COMPLETE skip** corp + tokyo repo (verify only).  
2. Index `market.jsda.or.jp` **HTTP 200** (62_958 B); tip codes still `S260817…S260803` (already COMPLETE).  
3. Tip extend `S260818/819/820/821` → **HTTP 404** (not published).  
4. Mid-June trading residual + late-May tip/recent probe:  
   - Prior seal `S260610` remains COMPLETE (not re-sealed).  
   - Trading residual `S260609/608/605/604/601` → **connect timeout (000 / rc=28)** → **DEFER**.  
   - Late-May band `S260529…S260515` → **timeout** → **DEFER**.  
5. Weekend inventory months in June residual list are **not** seal targets.  
6. **No new HTTP 200 full CSV** this wave → **seal delta 0**.

### Corporate / Repo (COMPLETE skip)

- **Corporate:** segment COMPLETE **12/12** (`2015`…`2026`); dataset **COMPLETE** — no seal.  
- **Tokyo repo:** dataset **COMPLETE**, segment `jsda-era-timeseries` **COMPLETE** — no seal.

Artifact: `.glm-logs/w0815i_g4_misc/verify_complete_skip.json`

### OTC sealed this wave (**+0**)

None. HTTP 200 full CSV gate failed for all probed residual / tip-extend codes (empty-raw ban held).

### POST OTC COMPLETE (**49** held)

Tip band held: `2026-08-17`, `08-14`…`08-03`, July trading band, June complete subset including prior `2026-06-10`.  
Dataset still **PARTIAL** (history target 2002-08-02; inventory **8781**; observed_start **2026-06-02** → end **2026-08-17**).

### JSDA DEFER (honest)

| Item | Why |
|------|-----|
| OTC mid-June trading residual (`06-09`,`08`,`05`,`04`,`01`) | Connect timeout (000 / curl rc=28). **No raw → no COMPLETE**. |
| Late-May tip/recent (`S260529`…`S260515` band) | Connect timeout (000 / rc=28). **No invent**. |
| Tip extend `S260818+` | **HTTP 404** not published (index tip still `S260817`). |
| June weekend inventory rows | Not trading-day seal targets. |
| OTC full archive (~8732 PARTIAL remain) | Site flake + no full archive crawl this wave. |
| COMPLETE without raw / empty shell | **Forbidden** (empty COMPLETE **0** on OTC) |

Artifact: `.glm-logs/w0815i_g4_misc/jsda_defer.json` · `probe_summary.txt` · `download_ok.txt` · `download_fail.txt`

---

## Publish (fail-closed)

```text
complete_count_guard ok local=3414 remote=3414 force=False
remote projection applied (13014 queries)
ops_reeval_freshness → projgen-186fbdd1e8fd4f948142ad4beb913ba9
OK coverage_segments_untouched=1 mass=NO-GO
```

No `--force-apply-remote`.  
Remote D1 post-check: OTC COMPLETE **49**; bars **220**; EDINET major/cross/large **104/76/62**; empty COMPLETE on bars/otc **0**.

Platform remote COMPLETE **3409 → 3414** is **peer progress** during the wave window (G4 seals **+0**).

Post-publish observed_window reclock (final):

| dataset | status | observed_start → end | C8 |
|---------|--------|----------------------|-----|
| bars | PARTIAL | 2008-05-01 → **2026-08-14** | pass lag 1 |
| major | COMPLETE | **2018-01-04** → **2026-08-14** | pass lag 1 |
| cross | PARTIAL | 2020-05-01 → **2026-08-14** | pass lag 1 |
| large | PARTIAL | 2021-07-01 → **2026-08-14** | pass lag 1 |
| OTC | PARTIAL | 2026-06-02 → 2026-08-17 | pass lag 3 |

---

## Explicit non-claims

- bars COMPLETE growth **not** claimed (+0; residual already closed).  
- EDINET cross/large residual segment COMPLETE **not** claimed (+0).  
- OTC segment COMPLETE growth **not** claimed (+0; no HTTP 200 full CSV).  
- OTC dataset-level COMPLETE **not** claimed (still PARTIAL vs 8781-day inventory).  
- Platform Mass / READY / Phase7 **not** claimed.  
- Corporate/repo seals **not** re-run (already COMPLETE).  
- Timeout-band residual June/May days **not** sealed.  
- No forever re-densify of EDINET empty residual.  
- Do-not-touch datasets **not** modified.

## Forbidden held

- empty COMPLETE — **0**  
- Mass / READY / Phase7 ON — **NO-GO / OFF**  
- invent JSDA CSV / partial body seal — **none**  
- kill peer jobs — **none**  
- short_sale / topix / master / breakdown / earn_calendar / bars_am — **untouched**

---

## Operator repro

```bash
# T6 bars residual (expect post-floor [])
.venv/bin/python - <<'PY'
import sqlite3
con=sqlite3.connect('data/structured/ingestion.sqlite')
print(con.execute("SELECT status, COUNT(*) FROM coverage_segments WHERE dataset='equities_bars_daily' GROUP BY status").fetchall())
post=con.execute("SELECT segment_id FROM coverage_segments WHERE dataset='equities_bars_daily' AND status!='COMPLETE' AND segment_id>='2008-05'").fetchall()
print('post-floor residual', post)
PY
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset equities_bars_daily --today 2026-08-15

# T7–T8 EDINET nz scan (expect sealable=0)
.venv/bin/python -u .glm-logs/w0815i_g4_misc/scan_residual_nz.py
cat .glm-logs/w0815i_g4_misc/seal_candidates.json   # []
cat .glm-logs/w0815i_g4_misc/defer_condition.txt

# T9 OTC tip (when market.jsda.or.jp accepts)
# only seal if HTTP 200 + size>100k + lines>1000 (full official CSV)
curl -o /tmp/S2606XX.csv \
  "https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/files/2026/S2606XX.csv"
.venv/bin/python scripts/publish_ops_projection.py --db data/structured/ingestion.sqlite --apply-remote
.venv/bin/python scripts/ops_reeval_freshness.py
```

---

## Logs

`.glm-logs/w0815i_g4_misc/` — PRE/POST D1, bars verify, EDINET scan/DEFER, OTC probe, publish, reeval, freshness.

## Report line

`SHA=4630043a690c761c504b5145b874f5ae472f7619 COMPLETE PRE bars/major/cross/large/otc=220/104/76/62/49 POST=220/104/76/62/49 (+0/+0/+0/+0/+0); bars post-floor residual=[]; EDINET sealable nz=0 DEFER_EMPTY_API; OTC HTTP200 full CSV=0 tip-extend 404 mid-June timeout; platform remote PRE=3409 POST=3414 (peers); empty COMPLETE=0; Mass=NO-GO; FRESH projgen-186fbdd1…`
