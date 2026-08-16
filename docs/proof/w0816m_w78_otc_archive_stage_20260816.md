# W78 / w0816m — OTC archive backfill staged FULL_OK (Task B / policy B) (2026-08-16)

**Wave:** `w0816m` / **W78** / **Task B**  
**Dataset:** `jsda_otc_bond_reference_prices`  
**Policy B:** FULL_OK official only; 404/empty → no COMPLETE; **staged** archive (not full 8781 dump)  
**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (ban held)  
**empty-raw COMPLETE:** **forbidden** (held)  
**PD-D5-JSDA-OTC:** held — **never** force dataset COMPLETE; bulk densify of 8688 PARTIALs **not** done  
**commit/push:** **not** done (wave instruction)

**Live verified:** 2026-08-16 (JST) / ~2026-08-16T08:23–08:40Z UTC  
**Worker:** temporary CF probe `quant-platform-jsda-otc-probe-tmp` (deploy → GET FULL_OK probe + `/fetch` download → **deleted**)

**Artifacts:** [`.glm-logs/w0816m_w78_go_build/`](../../.glm-logs/w0816m_w78_go_build/)

---

## Verdict

| Check | Result |
|-------|--------|
| OTC COMPLETE BEFORE (D1) | **93** |
| OTC COMPLETE AFTER (D1) | **163** (**+70**) |
| FULL_OK_NEW sealed | **70** (`2025-12-15`…`2026-03-31` published weekdays) |
| Tip code | still **S260817** |
| Archive bulk densify 8688 | **not** done (forbidden / not this wave) |
| empty COMPLETE | **0** |
| Dataset-level status | **PARTIAL** (163/8781) — never force COMPLETE |
| R2 put | **70/70 OK** |
| Platform COMPLETE segs | **3482 → 3552** (+70) |

**Return: 93 → 163 (+70).**

---

## 1. BEFORE / AFTER (D1 + local)

| Metric | BEFORE | AFTER | Δ |
|--------|-------:|------:|--:|
| `jsda_otc_bond_reference_prices` **COMPLETE** | **93** | **163** | **+70** |
| OTC PARTIAL | **8688** | **8618** | −70 |
| empty COMPLETE (OTC) | **0** | **0** | held |
| COMPLETE span | `2026-04-01` … `2026-08-17` | `2025-12-15` … `2026-08-17` | archive extend |
| Tip code | **S260817** | **S260817** | no tip advance |
| Dataset-level status | **PARTIAL** (PD-D5) | **PARTIAL** | held (never force COMPLETE) |
| Sealed this wave | — | **70** | FULL_OK_NEW archive stage |
| Platform COMPLETE segs | **3482** | **3552** | +70 |
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

## 2. How W41 / W68 sealed OTC FULL_OK (reference)

| Wave | Path | Result |
|------|------|--------|
| **W41** (`w0815ah_g2_jsda`) | Tip-island residual Apr weekdays S260401…S260423 | **76 → 93 (+17)** |
| **W68** (`w0816b`) | Tip island recheck + advance | **93 held** (FULL_OK_NEW=0) |
| **W77** (`w0816k`) | Tip staged rescan only | **93 held** (FULL_OK_NEW=0) |

**Official URL pattern (CSV tip/archive file path):**

```text
https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/files/{YYYY}/S{YYMMDD}.csv
```

Example: `…/files/2026/S260331.csv` (2026-03-31).

**FULL_OK gate:** HTTP **200** AND body size **> 1_500_000** bytes.  
**404 / empty / small HTML:** **no seal / no COMPLETE**.

Seal path (same as W41): local parse → normalize → upsert → inventory `expected_items` → `SignedReceiptAuthority` → R2 content-addressed put → `refresh_coverage_ledger` → `sync_dataset_coverage_from_segments` → `publish_ops_projection --apply-remote`.

---

## 3. Policy B staged archive candidate set

**Not** full 8781 densify. Staged set this wave:

| class | range | notes |
|-------|-------|-------|
| Archive stage | weekdays `2025-12-15` … `2026-03-31` | before tip island start `2026-04-01` |
| Tip residual holes | incomplete days inside `2026-04-01`…`2026-08-17` | mostly weekend/holiday → 404 |
| Tip advance controls | `S260818`…`S260828` | still unpublished 404 |
| FULL_OK_REFETCH controls | S260817 / S260812 / S260810 / S260721 | already COMPLETE |

Candidate n = **135** codes. Logs: `archive_stage_candidates.json`

---

## 4. FULL_OK probe (n=135)

**Transport:** CF Workers egress (`quant-platform-jsda-otc-probe-tmp`) — local `market.jsda.or.jp` TCP intermittent block after early success (same class as W68/W77).  
**Threshold:** HTTP **200** AND size **> 1_500_000**.

| class | n | notes |
|-------|--:|-------|
| **FULL_OK_NEW** | **70** | sealable archive weekdays Dec15…Mar31 |
| **FULL_OK_REFETCH** | **4** | already COMPLETE tip island |
| **HTTP 404** | **61** | tip residual holes + tip advance + holidays (e.g. S260320, S260211, S260223, S251231, S260101/102) |
| **TIMEOUT / OTHER** | **0** | CF probe path clean |

### 4.1 Archive FULL_OK_NEW span

| first | last | n |
|-------|------|--:|
| **2025-12-15** (S251215) | **2026-03-31** (S260331) | **70** |

Sizes ~2.12–2.18 MB each; content-type `text/csv`.

### 4.2 Tip still S260817

Tip advance S260818+ remains **404**. Residual holiday holes inside tip island remain **404** → **no invent COMPLETE**.

Logs: `otc_probe.json` · `otc_probe_results.tsv` · `otc_probe_batch1…17.json` · `otc_full_ok_new.txt` · `otc_full_ok_refetch.txt` · `otc_http404.txt`

---

## 5. Download + seal + R2

| step | result |
|------|--------|
| CF `/fetch` download FULL_OK_NEW | **70/70 OK** → `data/raw/jsda/jsda_otc_bond_reference_prices/{day}/S{code}.csv` |
| Local seal (parse/upsert/receipt) | **70/70 SEALED** (run_id **903894…903963**) |
| raw≈struct reconcile | held (≈12.2k rows/day) |
| empty-raw COMPLETE | **0** |
| R2 put `quant-raw` content-addressed keys | **70/70 OK** |
| `refresh_coverage_ledger` | OTC COMPLETE **93 → 163** |
| `sync_dataset_coverage_from_segments` | verify_only PARTIAL **163/8781** (dataset still PARTIAL) |
| `publish_ops_projection --apply-remote` | applied; D1 COMPLETE **163** |

R2 key shape:

```text
raw/jsda/jsda_otc_bond_reference_prices/file_S{YYMMDD}.csv/{sha256}.csv
```

Logs: `otc_download.json` · `otc_sealable_days.json` · `otc_seal.json` · `seal_result.json` · `r2_put_summary.json` · `r2_put.log` · `sync_dataset_coverage.json` · `publish_ops_projection.log`

---

## 6. Seal decision (policy holds)

| check | result |
|-------|--------|
| FULL_OK_NEW | **70** |
| seal executed | **true** |
| sealed days | **70** (`2025-12-15`…`2026-03-31` published weekdays) |
| invent COMPLETE from 404/empty | **false** |
| densify full 8688 archive PARTIALs | **false** (forbidden; staged only) |
| empty-raw COMPLETE | **0** / forbidden held |
| force dataset COMPLETE | **false** (still PARTIAL 163/8781) |
| tip advance invent | **false** (still S260817) |

**Reason:** Official archive files for staged pre-tip weekdays are still published at the standard `files/{YYYY}/S{YYMMDD}.csv` URL and meet FULL_OK. Prior tip-only waves (W68–W77) did not probe archive-before-island; policy B staged that window this wave.

---

## 7. Return (exact)

```json
{
  "FULL_OK_NEW_count": 70,
  "FULL_OK_NEW_span": ["2025-12-15", "2026-03-31"],
  "FULL_OK_REFETCH_count": 4,
  "FULL_OK_REFETCH": ["S260721", "S260810", "S260812", "S260817"],
  "OTC_delta": 70,
  "otc_complete_pre": 93,
  "otc_complete_post": 163,
  "tip_still": "S260817",
  "sealed_n": 70,
  "r2_put_ok": 70,
  "dataset_status": "PARTIAL (163/8781)"
}
```

**COMPLETE: 93 → 163 (+70).**

---

## 8. Policy holds

| policy | held? |
|--------|:-----:|
| FULL_OK official only (HTTP 200 + size > 1.5MB) | **yes** |
| 404/empty → no COMPLETE | **yes** |
| Staged not full 8781 dump | **yes** (70 days) |
| PD-D5 — never force dataset COMPLETE | **yes** (dataset still PARTIAL) |
| empty-raw COMPLETE forbidden | **yes** (empty COMPLETE = 0) |
| Mass / READY OFF | **yes** |
| no git commit/push | **yes** |

---

## 9. Logs index (`.glm-logs/w0816m_w78_go_build/`)

```text
otc_before.json / otc_after.json / otc_return.json / otc_seal.json / seal_result.json
otc_probe.json / otc_probe_results.tsv / otc_probe_batch1.json … batch17.json
otc_full_ok_new.txt / otc_full_ok_refetch.txt / otc_http404.txt
archive_stage_candidates.json / otc_download.json / otc_sealable_days.json
r2_put_summary.json / r2_put.log
local_before.json / local_after.json
d1_otc_segments_before.json / d1_otc_segments_after.json
d1_otc_complete_span_before.json / d1_otc_complete_span_after.json
d1_platform_complete_after.json
sync_dataset_coverage.json / publish_ops_projection.log
otc_cf_probe_deploy.log / otc_cf_probe_delete.log / otc_cf_health.txt / otc_connectivity.txt
FINAL_metrics.json / end_utc.txt / d1q.py
cf_probe_worker/   (tmp; worker deleted post-wave)
```
