# W77 / w0816k — JSDA Tokyo Repo depth (Task C1) (2026-08-16)

**Wave:** `w0816k` / **W77** / **Task C1**  
**Dataset:** `jsda_tokyo_repo_rates`  
**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty-raw COMPLETE:** **forbidden** (held)  
**commit/push:** **not** done (wave instruction)

**Live verified:** 2026-08-16 (JST) / ~2026-08-16T07:58–08:11Z UTC  
**Artifacts:** [`.glm-logs/w0816k_w77_jsda/`](../../.glm-logs/w0816k_w77_jsda/)

---

## Verdict

| Check | Result |
|-------|--------|
| Live D1 status | **COMPLETE** (held) |
| Segment count | **1** (`jsda-era-timeseries`) |
| History depth strategy-usable? | **YES** — full JSDA-era timeseries **2012-10-29 → 2026-08-14** |
| Real nz tip available beyond sealed max? | **YES** — official `trrts.xls` max **2026-08-14** (was **2026-08-10**) |
| This-wave action | **TIP_RESEAL_FROM_REAL_NZ_RAW** → coverage **30303 → 30330** (+27 rows / +3 trading days) |
| empty-raw / invent | **no** — raw 651776 B, structured 30330, raw==struct |
| Mass / READY | **NO-GO / OFF** |

---

## 1. Live D1 BEFORE → AFTER

| Metric | BEFORE | AFTER | Δ |
|--------|-------:|------:|--:|
| `dataset_coverage.status` | **COMPLETE** | **COMPLETE** | held |
| `dataset_coverage.row_count` | **30303** | **30330** | **+27** |
| `observed_start` | 2012-10-29T15:00:00+09:00 | same | — |
| `observed_end` | 2026-08-10T15:00:00+09:00 | **2026-08-14T15:00:00+09:00** | **+4 calendar / +3 trading days** |
| segments COMPLETE | **1** | **1** | 0 |
| `segment_id` | `jsda-era-timeseries` | same | — |
| `segment_start` | 2012-10-29 | same | — |
| `segment_end` | 2026-08-10 | **2026-08-14** | tip advance |
| `receipt_run_id` | 83 | **903893** | new TRUSTED seal |
| D1 fact rows (`jsda_repo_rates`) | **252** hot tip | **252** hot tip | unchanged (hot publish not this task) |
| D1 fact max | 2026-08-10 | 2026-08-10 | facts lag coverage tip (plane split) |

Logs: `d1_jsda_coverage_before.json` · `d1_jsda_coverage_after.json` · `d1_repo_segments_detail.json` · `d1_repo_segments_after.json` · `d1_repo_facts_tip.json` · `d1_repo_facts_after.json`

---

## 2. Local mirror (research convenience — not SoT)

| Layer | BEFORE | AFTER |
|-------|-------:|------:|
| Fact `jsda_repo_rates` COUNT | **30303** | **30330** |
| Distinct `as_of_date` | **3367** | **3370** |
| Fact min → max | 2012-10-29 → 2026-08-10 | 2012-10-29 → **2026-08-14** |
| SUCCESS receipt | run **83**, raw=struct=30303 | run **903893**, raw=struct=**30330** |
| eligibility | TRUSTED_COLLECTION | **TRUSTED_COLLECTION** (ed25519) |

**Match formula (AFTER):**

```text
local_facts(30330) == receipt.raw(30330) == receipt.structured(30330)
  == dataset_coverage.row_count(30330) == COMPLETE
```

Logs: `local_before.json` · `local_after.json` · `repo_seal.json`

---

## 3. Depth assessment (strategy-usable?)

| Criterion | Evidence | Usable? |
|-----------|----------|:-------:|
| Full JSDA-era start | history_target_start **2012-10-29** = fact min | **yes** |
| Continuous years | years 2012…2026 present in workbook | **yes** |
| Tenor matrix density | 30330 rows / 3370 days ≈ 9 rates/day | **yes** |
| Official timeseries product | single authoritative `trrts.xls` (一覧) | **yes** |
| Tip freshness vs official | official latest_publication_date **2026-08-14** = sealed end | **yes** (aligned this wave) |

**Assessment:** **DEEP_HISTORY_STRATEGY_USABLE** — not vendor tip-only. Single-segment `source_time_series_file` grain already holds full history under COMPLETE receipt ownership. D1 facts remain **hot tip only** by design (CF SoT: D1 control/hot · R2 history · COMPLETE receipt-owned).

Contract refs: `jsda_governed.json` · `collection_coverage.json` (`history_target_start: 2012-10-29`).

---

## 4. Official tip probe (real nz raw)

| Step | Result |
|------|--------|
| Direct GET `…/trr/files/trrts.xls` | HTTP **200**, size **651776**, Last-Modified **Fri, 14 Aug 2026 03:30:01 GMT** |
| Parse (`parse_repo_xls`) | **30330** rows, **3370** dates, max **2026-08-14** |
| Newer vs sealed max 2026-08-10 | **3** trading days: 2026-08-12, 2026-08-13, **2026-08-14** |
| CF index re-discovery (post-flake) | `DISCOVERED`, `latest_publication_date=2026-08-14`, source_url matches |
| Live local re-fetch later | TCP timeout intermittent (documented); seal used **already-acquired** raw |

Logs: `repo_curl_head.txt` · `repo_curl_get.txt` · `trrts_probe.xls` · `repo_probe_parse.json` · `repo_discovery_cf.json` · `repo_index_from_cf.html`

---

## 5. Acquire → seal → sync

| Step | Detail |
|------|--------|
| Acquire | Official `trrts.xls` saved to `data/raw/jsda/2026/08/16/trrts_20260816T170846.xls` (651776 B) |
| raw digest | `sha256:46a1255037d92c609dd8305d419fa1eabb2b6dd76c2b87c25b74b43ebe2493f8` |
| Upsert facts | 30330 rows → table `jsda_repo_rates` |
| Receipt | run_id **903893**, SUCCESS, raw=struct=30330, segment_end **2026-08-14** |
| eligibility | **TRUSTED_COLLECTION** / ed25519 `dev-receipt-v1` |
| `refresh_coverage_ledger` | segment + dataset COMPLETE updated |
| `sync_dataset_coverage_from_segments` | verify_only COMPLETE (1/1); no invent |
| Ops projection publish | `--apply-remote` applied (COMPLETE-count guard local=remote=3482) |

Logs: `repo_seal.json` · `repo_index_note.json` · `sync_dataset_coverage.json` · `publish_ops_projection.log`

**Not done this wave (out of C1 scope):** re-publish D1 hot tip facts beyond 2026-08-10 (`publish_jsda_hot_to_d1`). Coverage tip advanced; D1 fact table remains prior hot window (252 / max 2026-08-10) — expected plane split until next hot publish.

---

## 6. Policy holds

| policy | held? |
|--------|:-----:|
| empty-raw COMPLETE forbidden | **yes** (raw>0, struct>0, reconcile) |
| no invent COMPLETE | **yes** |
| Mass / READY OFF | **yes** |
| no git commit/push | **yes** |
| no bars_am densify | **n/a** (not this task) |

---

## 7. Return numbers (exact)

```json
{
  "dataset": "jsda_tokyo_repo_rates",
  "BEFORE": {
    "status": "COMPLETE",
    "segments": 1,
    "segment_end": "2026-08-10",
    "row_count": 30303,
    "fact_days": 3367
  },
  "AFTER": {
    "status": "COMPLETE",
    "segments": 1,
    "segment_end": "2026-08-14",
    "row_count": 30330,
    "fact_days": 3370,
    "receipt_run_id": 903893
  },
  "delta_rows": 27,
  "delta_days": 3,
  "newer_dates": ["2026-08-12", "2026-08-13", "2026-08-14"],
  "strategy_usable": true,
  "depth_assessment": "DEEP_HISTORY_STRATEGY_USABLE"
}
```

---

## 8. Logs index (`.glm-logs/w0816k_w77_jsda/`)

```text
d1_jsda_coverage_before.json / d1_jsda_coverage_after.json
d1_jsda_segments_before.json / d1_jsda_segments_after.json
d1_repo_segments_detail.json / d1_repo_segments_after.json
d1_repo_facts_tip.json / d1_repo_facts_after.json
local_before.json / local_after.json
repo_curl_head.txt / repo_curl_get.txt / trrts_probe.xls
repo_probe_parse.json / repo_discovery_cf.json / repo_index_from_cf.html
repo_index_note.json / repo_seal.json / repo_return.json
repo_reseal.log / sync_dataset_coverage.json / publish_ops_projection.log
FINAL_metrics.json / end_utc.txt
```
