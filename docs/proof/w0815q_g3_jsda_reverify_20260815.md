# W24-G3 — JSDA re-verify audit (D1 hot tip + local COMPLETE match) (2026-08-15)

**Wave:** `w0815q` / **W24-G3** / **T4 JSDA audit**  
**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty-raw ban:** held (no invent / no empty COMPLETE)  
**empty COMPLETE (OTC):** **0**  
**force-apply:** **not** used  
**this-wave seal delta:** **+0** (audit-only; no re-seal)

**Live verified:** 2026-08-15 (~01:40Z UTC)  
**Projection (reeval):** **FRESH** `projgen-432e34acc37e49e3be496d5e379ff8a2` (`coverage_segments_untouched=1`, mass=NO-GO)  
**Base HEAD (pre-proof):** `7fb2fa3`  
**Proof HEAD (post-push):** `b1eabdd`

## Verdict

| Check | Result |
|-------|--------|
| D1 `jsda_repo_rates` n=**252**, hot-only (cold=**0**) | **PASS** |
| D1 null rates on core columns | **0%** all audited |
| Local facts **30303** = SUCCESS receipt **83** = coverage COMPLETE | **PASS** |
| OTC / corp field coverage spot-check | **PASS** (schema-superset empties **DEFER**) |
| last_run partial JSDA (observable) | **Documented** + recovered (run 83) |
| Mass / READY / Phase7 | **NO-GO / OFF** |

---

## 1. D1 `jsda_repo_rates` n=252 (hot-only)

Remote D1 `quant-ingest` (wrangler `--remote`):

| Metric | Value |
|--------|------:|
| `COUNT(*)` | **252** |
| `MIN(as_of_date)` | **2026-07-01** |
| `MAX(as_of_date)` | **2026-08-10** |
| Distinct `as_of_date` | **28** |
| Cold (`as_of_date < 2026-07-01`) | **0** |
| Hot (`as_of_date >= 2026-07-01`) | **252** |

**Hot-only confirmed:** no cold rows on D1. Aligns with `publish_jsda_hot_to_d1.py` policy (`DEFAULT_HOT_CUTOFF=2026-07-01`) and prior publish proof [`jsda_hot_d1_publish_20260815.md`](jsda_hot_d1_publish_20260815.md).

### Null rates (D1, n=252)

| Column | null/empty |
|--------|----------:|
| `source` | **0** |
| `as_of_date` | **0** |
| `tenor` | **0** |
| `rate_type` | **0** |
| `rate` | **0** |
| `event_time` | **0** |
| `available_at` | **0** |
| `ingested_at` | **0** |
| `raw_payload` | **0** |

Artifacts: `.glm-logs/w0815q_g3_jsda/d1_repo_*.json`

---

## 2. Local full **30303** still matches receipt COMPLETE

Source: `data/structured/ingestion.sqlite`

| Layer | Value |
|-------|------:|
| Fact `jsda_repo_rates` COUNT | **30303** |
| Fact date range | **2012-10-29** → **2026-08-10** (3367 distinct days) |
| Local hot window (`>=2026-07-01`) | **252** (= D1 tip) |
| Local cold (`<2026-07-01`) | **30051** (full history SoT; not on D1 by design) |
| Core typed nulls (`rate`/`tenor`/`rate_type`/`as_of_date`/`available_at`/`raw_payload`/`source`) | **0** |
| `dataset_coverage.jsda_tokyo_repo_rates` | **COMPLETE**, row_count **30303** |
| Segment `jsda-era-timeseries` | **COMPLETE**, `receipt_run_id=**83**` |
| SUCCESS receipt run **83** | raw=**30303**, structured=**30303**, checked_at `2026-08-11T22:04:57+09:00` |
| Raw body digest | `sha256:6fda0ddc7edc6a5869cfcda3648afcb4ce47bcf3ef945e34c53b0c1d964ee0d6` |

**Match formula holds:**

```text
local_facts(30303) == receipt.raw(30303) == receipt.structured(30303)
  == dataset_coverage.row_count(30303) == COMPLETE
```

D1 coverage ledger also shows `jsda_tokyo_repo_rates` **COMPLETE** / row_count **30303** (receipt-owned; facts on D1 remain tip-only 252). Expected plane split — **not** data loss.

---

## 3. OTC / corporate field coverage spot-check

### 3.1 `jsda_otc_bond_reference_prices` (local n=**886494**)

| Field | null/empty % | class |
|-------|-------------:|-------|
| security_code, bond_name, maturity_date | **0%** | full |
| average_price | **~0.0003%** | negligible |
| coupon_rate | **~0.38%** | source blanks |
| average_yield | **~0.28%** | source blanks |
| individual_investor_flag | **~2.78%** | pre-layout / missing attr |
| available_at, raw_payload | **0%** | full |

| Coverage | Value |
|----------|------:|
| Dataset status | **PARTIAL** (history target 2002-08-02; tip-heavy) |
| COMPLETE segs | **72** / 8781 inventory |
| PARTIAL segs | **8709** |
| empty COMPLETE | **0** |

### 3.2 `jsda_corporate_bond_transactions` (local n=**156079**, dataset **COMPLETE** 12/12)

| Field | null/empty % | class |
|-------|-------------:|-------|
| security_code, issuer_name | **0%** | full |
| coupon_rate | **~6.3%** | source blank |
| transaction_type | **~20.4%** | era blank (2015–2017+partial 2018) |
| execution_price | **~20.3%** | same era pattern |
| execution_yield | **~0.45%** | source blank |
| **isin** | **100%** | **schema-superset** — **DEFER** |
| **buyer_counterparty_type** | **100%** | **schema-superset** — **DEFER** |
| **seller_counterparty_type** | **100%** | **schema-superset** — **DEFER** |
| **face_value_mil_jpy** | **100%** | **schema-superset** — **DEFER** |
| **trade_amount_mil_jpy** | **100%** | **schema-superset** — **DEFER** |
| available_at, raw_payload | **0%** | full |

**Conclusion (unchanged from W20-G4):** always-empty counterparty/ISIN/face/amount columns are **not parse loss** — official TORIHIKI CSV is an **11-column** source; schema is intentionally wider. **Do not invent.**

### 3.3 Remote D1 coverage ledger (unchanged policy)

| Dataset | status | notes |
|---------|--------|-------|
| `jsda_tokyo_repo_rates` | COMPLETE | facts tip-only n=252 |
| `jsda_corporate_bond_transactions` | COMPLETE | 12/12 year segs |
| `jsda_otc_bond_reference_prices` | PARTIAL | 72 COMPLETE / 8709 PARTIAL |
| Platform COMPLETE segs | **3457** | local = D1 |

---

## 4. last_run partial JSDA — root cause + recovery

### 4.1 Local research plane (observable)

`ingestion_run_log` for source=`jsda` / dataset `jsda_tokyo_repo_rates`:

| id | ran_at (JST) | status | detail summary |
|----|--------------|--------|----------------|
| **80** | 2026-08-11T21:45:06 | **partial** | deferred=1, raw_rows=0, structured=0 |
| **81** | 2026-08-11T21:57:50 | **partial** | deferred=1, raw_rows=0, structured=0 |
| **82** | 2026-08-11T22:03:20 | **partial** | deferred=1, raw_rows=0, structured=0 |
| **83** | 2026-08-11T22:04:57 | **ok** | completed=1, raw_rows=**30303**, structured=**30303** |

Matching FAILED receipts (80–82):

| Field | Value |
|-------|-------|
| `status` | FAILED |
| `error` | `official workbook contains no JSDA-era observations` |
| `failure_kind` | **`DEFERRED_SOURCE_GAP`** |
| `source_parsed_rows` | **0** |
| `raw` digest | `sha256:6fda0ddc…e0d6` (**identical** to SUCCESS 83) |
| source URL | `…/trr/files/trrts.xls` |

Code path (`packages/data_plane/ingestion/jsda/repo_archive.py`):

- `_governed_records` raises `RepoSourceGap("official workbook contains no JSDA-era observations")` when the post-parse JSDA-era filter yields **empty**.
- Empty `source_parsed_rows` on 80–82 means **`parse_repo_xls` returned 0 rows** for a workbook that later parsed to 30303 with the **same bytes** (digest match).
- Run status mapping: `deferred > 0` → `ingestion_run_log.status = "partial"` (not hard `error`).

**Root cause class:** transient **parse-path / governed-filter empty** on an otherwise valid official workbook (DEFERRED_SOURCE_GAP). Not missing raw (raw was saved under `data/raw/jsda/2026/08/11/trrts_*.xls`). Not empty-raw invent. Not coverage fraud.

**Recovery (already done):** run **83** re-ingested same official `trrts.xls` → SUCCESS receipt raw=structured=**30303** → segment `jsda-era-timeseries` COMPLETE with `receipt_run_id=83`. **No re-seal needed this wave.**

Also observable (historical): earlier local JSDA runs 54/59/71 = `error` on `market.jsda.or.jp` **transport timeout** (`Errno 60`) — orthogonal OTC archive path flake; empty-raw ban held (no COMPLETE without full CSV).

### 4.2 D1 / Cloudflare worker last_run (partial expected)

Latest CF `ingestion_run_log` source=`jsda` entries are routinely **`status=partial`** for cron/manual discovery:

- OTC job: `data_discovered` hundreds / `stored=3` tip files → worker **partial**
- Corp job: similar tip-store partial
- Tokyo repo discover job often **`pass`** (index + trrts + trr stored)

This is **Worker pass ≠ COMPLETE** policy: CF raw discovery stores tip artifacts to R2; COMPLETE is receipt-owned via local governed seal + coverage projection. **Not fact loss; not incomplete tip publish for repo (D1 hot n=252 still present).**

---

## 5. Plane semantics (re-confirmed)

| Plane | `jsda_repo_rates` facts | COMPLETE meaning |
|-------|------------------------:|------------------|
| Local research sqlite | **30303** full history | receipt + segment |
| D1 control / hot tip | **252** (`>=2026-07-01`) | coverage projected; tip facts only |
| R2 structured / raw | SoT for full history / archives | — |

`FACT_VS_COVERAGE_COUNT_MISMATCH` (252 tip vs 30303 ledger) on D1 remains **expected** after hot publish; `COMPLETE_WITHOUT_LOCAL_FACTS` should **not** fire while tip rows exist.

---

## 6. Explicit non-claims

- No Mass ON / READY / Phase7.
- No claim that D1 holds full JSDA history.
- No re-seal of COMPLETE tokyo_repo / corporate segments.
- No fabrication of ISIN / counterparty / face / trade amount.
- No OTC full-archive seal this wave (+0).
- No empty COMPLETE.

---

## 7. Logs

`.glm-logs/w0815q_g3_jsda/`

| Artifact | Content |
|----------|---------|
| `d1_repo_range.json` / `d1_repo_cold.json` / `d1_repo_hot.json` / `d1_repo_nulls.json` | D1 tip audit |
| `d1_jsda_cov.json` / `d1_jsda_segs.json` / `d1_plat_complete.json` | D1 coverage |
| `d1_jsda_run_log.json` | CF last_run partial evidence |
| `local_repo_*.json` / `local_jsda_*.json` | local facts + receipt match |
| `local_otc_nulls.json` / `local_corp_nulls.json` | field coverage |
| `local_jsda_run_log.json` / `local_repo_receipt_chain.json` | partial→ok recovery chain |
| `audit_summary.json` | consolidated machine summary |
| `freshness.log` | ops_reeval_freshness |

---

## 8. Operator repro

```bash
# D1 hot-only
cd platform/workers/ingestion-premium
./node_modules/.bin/wrangler d1 execute quant-ingest --remote --json --command \
  "SELECT COUNT(*) n, MIN(as_of_date) min_d, MAX(as_of_date) max_d FROM jsda_repo_rates"
./node_modules/.bin/wrangler d1 execute quant-ingest --remote --json --command \
  "SELECT COUNT(*) cold FROM jsda_repo_rates WHERE as_of_date < '2026-07-01'"

# Local match
sqlite3 data/structured/ingestion.sqlite \
  "SELECT COUNT(*) FROM jsda_repo_rates;
   SELECT dataset,status,row_count FROM dataset_coverage WHERE dataset='jsda_tokyo_repo_rates';
   SELECT segment_id,status,receipt_run_id FROM coverage_segments WHERE dataset='jsda_tokyo_repo_rates';
   SELECT run_id,raw_row_count,structured_row_count,status FROM collection_receipts
     WHERE dataset='jsda_tokyo_repo_rates' AND status='SUCCESS' ORDER BY checked_at DESC LIMIT 1;"

# Partial chain
sqlite3 data/structured/ingestion.sqlite \
  "SELECT id,ran_at,status,detail FROM ingestion_run_log WHERE source='jsda' ORDER BY id DESC LIMIT 10;"
```
