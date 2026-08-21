# P1-1 DEFER: `markets_margin_interest` STALE (2026-08-12)

**Decision: DEFER — no remote status rewrite, no Mass/READY, no fabricated COMPLETE.**

Investigated remote D1 `quant-ingest` (wrangler `--remote`), local `data/structured/ingestion.sqlite`, local `data/raw`, and R2 `quant-raw` manifests.

## PRE (remote D1)

| Field | Value |
|-------|--------|
| `dataset_coverage.status` | **STALE** |
| `observed_start` / `observed_end` | `2024-01-12T00:00:00+09:00` → `2025-02-28T00:00:00+09:00` |
| `row_count` (coverage plane) | 251470 |
| `evaluated_at` | `2026-08-12T11:45:20.216897+00:00` |
| `projection_generation_id` | `projgen-4d234884d6f34fd4839e8b0e6487f607` |
| coverage_v2 segments | required=**164**, COMPLETE=**14**, PARTIAL=**150** |
| `ingestion_watermarks.last_event_date` | **2026-07-31** |
| `ingestion_watermarks.last_ingested_at` | `2026-08-12T22:15:29+09:00` |
| `collection_receipts` SUCCESS | **42** (range `2026-05-13` … `2026-08-11`) |
| receipts with `raw_row_count>0` | **12** (weekly windows `2026-05-13` … `2026-08-04`) |
| `jquants_records` (D1 hot) | **21277** rows, event_time `2026-07-03` … `2026-07-31` only |

### C8 fail (direct cause of STALE)

From `detail_json.checks` C8:

```text
stale: 530 day(s) > 7
latest_event_time=2025-02-28T00:00:00+09:00
reference=2026-08-12
max_days=7
```

Gate path (`storage/coverage_ledger.py` `_dataset_status`): any C8 fail → dataset status **STALE** (before segment aggregate). Segment aggregate alone would be PARTIAL (14/164 COMPLETE), not COMPLETE.

## Root causes (honest)

### 1. Freshness plane mismatch + weekly lag

- Coverage C8 used the **evaluation/cold plane** max `event_time` = **2025-02-28** (matches local structured 251470 rows).
- Remote control-plane truth is newer: watermark **2026-07-31**, D1 hot rows in **2026-07**.
- Even if C8 were re-pointed at watermark `2026-07-31`, lag vs `2026-08-12` is **~12 calendar days > max_days=7** → **still STALE** under current policy.
- Dataset is `expected_frequency=weekly`; empty SUCCESS receipts for 2026-08 daily cron (0 rows, pagination exhausted) match source publication lag, not a silent write failure.

### 2. History / gap not receipt-complete

| Window | Evidence | Segment status |
|--------|----------|----------------|
| 2013-01 → 2023-12 | No local raw; no remote SUCCESS monthly receipts | PARTIAL (`missing collection receipt`) |
| 2024-01 → 2025-02 | Local raw+structured+signed monthly receipts (run_id 900243–900280 **local only**); remote sticky COMPLETE 14 segs | COMPLETE (sticky) |
| 2025-03 → 2026-05-12 | Local raw only empty days to 2025-03-05; no full month raw+struct | PARTIAL |
| 2026-05-13 → 2026-07 | R2 raw manifests + SUCCESS **weekly** receipts; D1 hot holds July structured | Monthly segs still PARTIAL |
| 2026-08 | Hourly SUCCESS with **0 rows** | PARTIAL / empty |

Required segments are **`calendar_month`** (`collection_coverage.json` default). CF ingest receipts use **weekly** `segment_start/end` (e.g. `2026-07-01`–`2026-07-07` with `segment_id=2026-07`). Identity match in `evaluate_segment` requires equal `segment_id` **and** start/end/scope → weekly receipts **do not** satisfy monthly required segments → `missing collection receipt` / scope mismatch.

### 3. Remote COMPLETE receipts are sticky local artifacts

- Remote COMPLETE months cite `receipt_run_id` 900243–900280.
- Remote `collection_receipts` has **0** rows with `run_id >= 900000`.
- Local sqlite has those 900xxx SUCCESS receipts with real raw/structured counts.
- Sticky COMPLETE preserved the 14 months; demotion not applied. **Do not invent** remote 900xxx receipts.

### 4. Raw inventory (no fabrication)

**Local `data/raw/jquants/`**

- 430 files tagged `markets_margin_interest` (ingest day 2026-08-11).
- Date labels: `2024-01-01` … `2025-03-05`.
- Non-empty payloads: **59** (weekly cadence), dates `2024-01-12` … `2025-02-28` only.
- Empty list payloads dominate (371) — consistent with weekly margin interest + day-by-day fetch of non-publish days.

**R2 `quant-raw` (remote)**

- Layout: `raw/markets_margin_interest/{run_id}/manifest.json` + pages.
- Non-empty manifests: runs **161–172** (page_count=7, ~4253–4272 rows each) covering weekly windows **2026-05-13 → 2026-08-04**.
- Recent hourly runs (e.g. 906–923): `row_count=0`, `raw_bytes=12` (empty `[]` body).
- No R2 evidence for 2013–2023 or 2025-03–2026-05-12 in this investigation.

**D1 structured hot**

- Only **2026-07** retained in `jquants_records` (hot-window policy); historical structured for 2024–2025 lives in local cold / prior projection row_count, not full remote D1 history.

## Why repair was refused

| Candidate fix | Why not applied |
|---------------|-----------------|
| Flip STALE → COMPLETE | C8 fails; 150/164 segments PARTIAL; would be fabrication |
| Freshness reeval only (bump `evaluated_at` / C8 metrics) | True latest event still ≥12d lag → remains STALE; does not fix gaps |
| Receipt refresh from local raw for 2024–2025 | Already COMPLETE sticky for those months; remote 900xxx not present; raw-only rebuild path is **RECOVERED_RAW_ONLY** (never COMPLETE-eligible) |
| Promote weekly 2026-05..07 SUCCESS → monthly COMPLETE | Requires calendar_month receipt identity + Ed25519 TRUSTED path + full-month reconciliation; weekly windows do not equal monthly required scope; Mass/READY forbidden |
| Historical backfill 2013+ | No raw+structured on hand for DEFER scope; needs governed ingest, not ledger rewrite |

**Repair scope that remains honest for a later ticket (not done here):**

1. CF / premium backfill monthly (or re-issue **calendar_month** TRUSTED receipts) for 2013-01-04 → target_end, with R2 raw + structured reconciliation.
2. Align ingest receipt `segment_id`/`segment_start`/`segment_end` to `plan_required_segments` monthly identity (or change policy granularity deliberately with contract bump — out of band).
3. Re-run coverage refresh + fail-closed `publish_ops_projection` only after C8 and segment evidence are real.
4. Optionally revisit C8 `max_days` for `expected_frequency=weekly` (policy change; not a silent ops patch).

## Actions taken this ticket

- Read-only remote D1 queries (coverage, segments, watermarks, receipts, jquants_records, raw_retention_manifests).
- Local raw emptiness audit + local sqlite cross-check.
- Remote R2 manifest sample for run 172 (non-empty weekly window confirmed).
- **No** `dataset_coverage` / `coverage_segments` UPDATE.
- **No** `publish_ops_projection`.
- **No** Mass / READY / B0 claims.

## POST

| Metric | POST |
|--------|------|
| `markets_margin_interest` status | **STALE** (unchanged) |
| COMPLETE segments | **14** (unchanged sticky 2024-01..2025-02) |
| PARTIAL segments | **150** (unchanged) |
| Mass / READY | **NO-GO** |

## Evidence anchors (no secrets)

- Policy: `data_contracts/collection_coverage.json` → `markets_margin_interest` weekly / history_target_start `2013-01-04`.
- STALE gate: `storage/coverage_ledger.py` `_dataset_status` C8 fail → STALE; then segment aggregate only if validation COMPLETE.
- Segment identity: `evaluate_segment` requires receipt scope match monthly required segment.
- Known ops note: markets_margin_interest can be empty market-wide (historical Phase 3.5 acceptance).
