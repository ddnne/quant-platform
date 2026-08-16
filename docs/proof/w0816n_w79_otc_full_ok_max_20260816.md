# W79 / w0816n — OTC archive FULL_OK max (Task B / policy B max) (2026-08-16)

**Wave:** `w0816n` / **W79** / **Task B**  
**Dataset:** `jsda_otc_bond_reference_prices`  
**Policy B max:** FULL_OK official only; 404/empty → no COMPLETE; **maximize** obtainable archive FULL_OK not yet COMPLETE  
**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (ban held)  
**empty-raw COMPLETE:** **forbidden** (held)  
**PD-D5-JSDA-OTC:** held — **never** force dataset COMPLETE; bulk densify of remaining PARTIALs **not** done (only official FULL_OK days sealed)  
**commit/push:** **not** done (wave instruction)

**Live verified:** 2026-08-16 (JST) / ~2026-08-16T08:49–09:53Z UTC  
**Worker:** temporary CF probe `quant-platform-jsda-otc-probe-w79` (deploy → GET FULL_OK probe + `/fetch` download → **deleted**)

**Artifacts:** [`.glm-logs/w0816n_w79_go_final/`](../../.glm-logs/w0816n_w79_go_final/)

---

## Verdict

| Check | Result |
|-------|--------|
| OTC COMPLETE BEFORE (D1) | **163** |
| OTC COMPLETE AFTER (D1) | **639** (**+476**) |
| FULL_OK_NEW sealed | **476** (`2024-01-04`…`2025-12-12` published trading days) |
| Tip code | still **S260817** |
| Archive bulk densify remaining PARTIAL | **not** done (only FULL_OK official) |
| empty COMPLETE | **0** |
| Dataset-level status | **PARTIAL** (639/8781) — never force COMPLETE |
| R2 put | **476/476 OK** (sample verify 3/3) |
| Platform COMPLETE segs | **3552 → 4028** (+476) |

**Return: 163 → 639 (+476).**

---

## 1. BEFORE / AFTER (D1 + local)

| Metric | BEFORE | AFTER | Δ |
|--------|-------:|------:|--:|
| `jsda_otc_bond_reference_prices` **COMPLETE** | **163** | **639** | **+476** |
| OTC PARTIAL | **8618** | **8142** | −476 |
| empty COMPLETE (OTC) | **0** | **0** | held |
| COMPLETE span | `2025-12-15` … `2026-08-17` | `2024-01-04` … `2026-08-17` | archive extend |
| Tip code | **S260817** | **S260817** | no tip advance |
| Dataset-level status | **PARTIAL** (PD-D5) | **PARTIAL** | held (never force COMPLETE) |
| Sealed this wave | — | **476** | FULL_OK_NEW archive max |
| Platform COMPLETE segs | **3552** | **4028** | +476 |
| Dataset COMPLETE (platform) | **22** | **22** | held |

Query:

```sql
SELECT status, COUNT(*) AS n, MIN(segment_id), MAX(segment_id)
FROM coverage_segments
WHERE dataset='jsda_otc_bond_reference_prices'
GROUP BY status;
```

Logs: `d1_otc_segments_before.json` · `d1_otc_segments_after.json` · `d1_otc_complete_span_before.json` · `d1_otc_complete_span_after.json` · `local_before.json` · `local_after.json` · `otc_before.json` · `otc_after.json`

---

## 2. How W78 / prior waves sealed OTC FULL_OK (reference)

| Wave | Path | Result |
|------|------|--------|
| **W41** (`w0815ah_g2_jsda`) | Tip-island residual Apr weekdays | **76 → 93 (+17)** |
| **W68–W77** | Tip island recheck / advance | **93 held** (FULL_OK_NEW=0) |
| **W78** (`w0816m`) | Staged archive `2025-12-15`…`2026-03-31` | **93 → 163 (+70)** |
| **W79** (this) | Policy B **max** archive `2024-01-04`…`2025-12-12` | **163 → 639 (+476)** |

**Official URL pattern (CSV tip/archive file path):**

```text
https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/files/{YYYY}/S{YYMMDD}.csv
```

Example: `…/files/2025/S250701.csv` (2025-07-01).

**FULL_OK gate:** HTTP **200** AND body size **> 1_500_000** bytes.  
**404 / empty / small HTML:** **no seal / no COMPLETE**.

Seal path (same as W41/W78): local parse → normalize → upsert → inventory `expected_items` → `SignedReceiptAuthority` → R2 content-addressed put → `refresh_coverage_ledger` → `sync_dataset_coverage_from_segments` → `publish_ops_projection --apply-remote`.

---

## 3. Policy B max candidate set

**Not** full remaining PARTIAL densify. Maximize set this wave:

| class | range / notes | n |
|-------|---------------|--:|
| **archive_max** | official partial days `2024-01-01` … `2025-12-14` (before COMPLETE span start `2025-12-15`) | **714** |
| **tip_residual** | incomplete days inside tip island `2026-04-01`…`2026-08-17` | **45** |
| **tip_advance** | `S260818`…`S260828` controls | **11** |
| **refetch controls** | S260817 / S260812 / S260810 / S251215 | **4** |
| **probe total** | candidates + controls (unique) | **774** |

Logs: `archive_stage_candidates.json` · `probe_codes_ordered.json` · `partial_iso_days.txt`

---

## 4. FULL_OK probe (n=774)

**Transport:** CF Workers egress (`quant-platform-jsda-otc-probe-w79`) GET `/probe?codes=…` — POST blocked 403; GET path clean.  
**Threshold:** HTTP **200** AND size **> 1_500_000**.  
**Batching:** 8 codes/request, reverse-chrono, ~97 batches.

| class | n | notes |
|-------|--:|-------|
| **FULL_OK_NEW** | **476** | sealable archive trading days `2024-01-04`…`2025-12-12` |
| **FULL_OK_REFETCH** | **4** | already COMPLETE (tip + W78 archive control) |
| **HTTP 404** | **294** | weekends/holidays + tip residual holes + tip advance + non-published |
| **TIMEOUT / OTHER** | **0** | CF probe path clean |

### 4.1 Archive FULL_OK_NEW span

| first | last | n |
|-------|------|--:|
| **2024-01-04** (S240104) | **2025-12-12** (S251212) | **476** |

Sizes ~2.0–2.2 MB each; content-type `text/csv`.

### 4.2 Tip still S260817

Tip advance S260818+ remains **404**. Residual holiday holes inside tip island remain **404** → **no invent COMPLETE**.

### 4.3 Breakdown vs already COMPLETE

| bucket | n |
|--------|--:|
| already COMPLETE (pre-wave) | **163** |
| FULL_OK_NEW (sealed this wave) | **476** |
| FULL_OK_REFETCH (probe only) | **4** |
| HTTP 404 (no seal) | **294** |

Logs: `otc_probe.json` · `otc_probe_results.tsv` · `otc_probe_batch1…97.json` · `otc_full_ok_new.txt` · `otc_full_ok_refetch.txt` · `otc_http404.txt`

---

## 5. Download + seal + R2

| step | result |
|------|--------|
| CF `/fetch` download FULL_OK_NEW | **476/476 OK** → `data/raw/jsda/jsda_otc_bond_reference_prices/{day}/S{code}.csv` |
| Local seal (parse/upsert/receipt) | **476/476 SEALED** (run_id **903964…904439**; 2-day receipt repair for mid-kill gap) |
| raw≈struct reconcile | held (~12k rows/day) |
| empty-raw COMPLETE | **0** |
| R2 put `quant-raw` content-addressed keys | **476/476 OK** (sample get verify 3/3) |
| `refresh_coverage_ledger` | OTC COMPLETE **163 → 639** |
| `sync_dataset_coverage_from_segments` | verify_only PARTIAL **639/8781** (dataset still PARTIAL) |
| `publish_ops_projection --apply-remote` | applied; D1 COMPLETE **639** |

R2 key shape:

```text
raw/jsda/jsda_otc_bond_reference_prices/file_S{YYMMDD}.csv/{sha256}.csv
```

Logs: `otc_download.json` · `otc_sealable_days.json` · `otc_seal.json` · `seal_result.json` · `otc_seal_repair.json` · `r2_put_summary.json` · `r2_put.log` · `r2_put_progress.jsonl` · `sync_dataset_coverage.json` · `publish_ops_projection.log`

---

## 6. Seal decision (policy holds)

| check | result |
|-------|--------|
| FULL_OK_NEW | **476** |
| seal executed | **true** |
| sealed days | **476** (`2024-01-04`…`2025-12-12` published trading days with FULL_OK) |
| invent COMPLETE from 404/empty | **false** |
| densify full remaining archive PARTIALs | **false** (only FULL_OK official URLs) |
| empty-raw COMPLETE | **0** / forbidden held |
| force dataset COMPLETE | **false** (still PARTIAL 639/8781) |
| tip advance invent | **false** (still S260817) |

**Reason:** Official archive files for 2024–2025 (pre W78 COMPLETE span) are published at the standard `files/{YYYY}/S{YYMMDD}.csv` URL and meet FULL_OK. Policy B max sealed **all** probe-confirmed FULL_OK_NEW in the staged maximize window; 404 days left PARTIAL.

---

## 7. Return (exact)

```json
{
  "FULL_OK_NEW_count": 476,
  "FULL_OK_NEW_span": ["2024-01-04", "2025-12-12"],
  "FULL_OK_REFETCH_count": 4,
  "HTTP404_n": 294,
  "OTC_delta": 476,
  "otc_complete_pre": 163,
  "otc_complete_post": 639,
  "tip_still": "S260817",
  "sealed_n": 476,
  "r2_put_ok": 476,
  "dataset_status": "PARTIAL (639/8781)"
}
```

**COMPLETE: 163 → 639 (+476).**

---

## 8. Policy holds

| policy | held? |
|--------|:-----:|
| FULL_OK official only (HTTP 200 + size > 1.5MB) | **yes** |
| 404/empty → no COMPLETE | **yes** |
| Maximize obtainable FULL_OK (not invent) | **yes** (476 days) |
| PD-D5 — never force dataset COMPLETE | **yes** (dataset still PARTIAL) |
| empty-raw COMPLETE forbidden | **yes** (empty COMPLETE = 0) |
| Mass / READY OFF | **yes** |
| no git commit/push | **yes** |

---

## 9. Logs index (`.glm-logs/w0816n_w79_go_final/`)

```text
otc_before.json / otc_after.json / otc_return.json / otc_seal.json / seal_result.json
otc_seal_repair.json / seal_resume_final.py / seal_resume_final.log / seal_otc_max.py
otc_probe.json / otc_probe_results.tsv / otc_probe_batch1.json … batch97.json
otc_full_ok_new.txt / otc_full_ok_refetch.txt / otc_http404.txt / otc_other.txt
archive_stage_candidates.json / probe_codes_ordered.json / otc_sealable_days.json
otc_download.json / r2_put_summary.json / r2_put.log / r2_put_progress.jsonl / r2_put_resume.py
local_before.json / local_after.json
d1_otc_segments_before.json / d1_otc_segments_after.json
d1_otc_complete_span_before.json / d1_otc_complete_span_after.json
d1_platform_complete_before.json / d1_platform_complete_after.json
d1_otc_empty_complete_after.json / d1_dataset_coverage_after.json
sync_dataset_coverage.json / sync_dataset_coverage.log / publish_ops_projection.log
otc_cf_probe_deploy.log / otc_cf_probe_delete.log / otc_cf_health.txt / otc_connectivity.txt
FINAL_metrics.json / start_utc.txt / end_utc.txt / d1q.py
cf_probe_worker/   (tmp; worker deleted post-wave)
```
