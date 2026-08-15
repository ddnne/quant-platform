# COMPLETE 21 — CF read paths + DEFER exclude + PIT keys (2026-08-15)

**Wave:** W48 / w0815ao_g1 · T1–T3  
**Phase:** COMPLETE 21 **usage readiness** groundwork  
**Mass / READY / Phase7:** **not** declared · **not** enabled · densify **not** run · push **not** this task (G4)

**Sources (code + residual SoT):**

| source | path |
|--------|------|
| Residual SoT | [`docs/phase62_residual_status.md`](../phase62_residual_status.md) |
| Usage notes (21 list) | [`docs/proof/coverage_baseline_21_usage_notes_20260815.md`](coverage_baseline_21_usage_notes_20260815.md) |
| CF-native plane | [`docs/architecture/cf_native_storage_plane.md`](../architecture/cf_native_storage_plane.md) |
| R2 partitions | [`docs/architecture/r2_partition_scheme.md`](../architecture/r2_partition_scheme.md) |
| Write routing | [`docs/architecture/write_routing_rules.md`](../architecture/write_routing_rules.md) |
| Read service | `packages/data_plane/data_access/service.py` · `adapter.py` |
| Worker write path | `platform/workers/ingestion-premium/src/write_path_config.ts` · `r2_structured_writer.ts` · `ops_cold_archive.ts` · `ops_artifacts_plan.ts` |
| PIT contracts | `packages/data_plane/data_contracts/jquants_premium_core.json` · `jsda_governed.json` · `identity.py` |
| Permanent DEFER lock | [`docs/proof/w0815ak_w44_defer_lock_20260815.md`](w0815ak_w44_defer_lock_20260815.md) |

---

## 0. CF-SoT rules (held)

| plane | role | never |
|-------|------|-------|
| **D1 `quant-ingest`** | **Hot tip** + control/evidence (coverage, receipts, watermarks, projection meta, change_log) | Full history SoT; year-split D1 as primary |
| **R2 `quant-structured`** | **History** structured (JSONL / archive NDJSON → parquet bridge) | Deleted without archive+verify |
| **R2 `quant-raw`** | Raw evidence pages + manifests | Deleted when COMPLETE-linked |
| **Receipt / Coverage V2** | **COMPLETE ownership** (signed segment seals) | Redefining COMPLETE by D1/local row counts |
| **Local SQLite** | Research **mirror / convenience only** | **Never call local SQLite SoT** |

**Hot cutoff (ops counts / JSDA tip publish):** `2026-07-01`  
(`OpsCurrentReadService.storage_plane_status`, `scripts/publish_jsda_hot_to_d1.py`)

**Worker default:** all Premium-core structured writes are **R2-only** (`isR2Only` / `HIGH_VOLUME_DATASETS`). D1 structured dual-write only if `ALLOW_D1_STRUCTURED_DATASETS` env allowlists a dataset. Residual hot rows may still exist on D1 from pre-R2-path eras or tip publish scripts.

---

## 1. Shared CF key patterns

### 1.1 R2 raw (`quant-raw`)

```text
raw/{dataset}/{run_id}/page-NNNNNN.json
raw/{dataset}/{run_id}/manifest.json
```

Uncommitted fallback prefix (worker): `raw/{dataset}/uncommitted-{stamp}/…`  
(JSDA local/R2 mirror also uses calendar layout under `raw/jsda/…` for archive products.)

### 1.2 R2 structured history (`quant-structured`)

**Live ingest JSONL (P0 path in worker):**

```text
structured/jsonl/{dataset}/dt=YYYY-MM-DD/{run_id}.jsonl
```

Line schema (metadata `schema=jquants_records/v1`):  
`source`, `dataset`, `natural_key`, `event_time`, `available_at`, `ingested_at`, `payload`, `raw_payload`

**Cold archive from former D1 rows:**

```text
archive/jquants_records/{dataset}/batch/{run_id}_after{rowid}.ndjson
archive/jquants_records/{dataset}/batch/{run_id}_after{rowid}_meta.ndjson
```

**Target Hive parquet layout (scheme doc; compaction via parquet-manifest bridge):**

```text
dataset={DATASET}/year=YYYY/month=MM/day=DD/seg={SEGMENT_ID}/{content_hash}.parquet
_manifest/dataset={DATASET}/year=YYYY/month=MM/manifest.json
structured/parquet_manifest/{prefixHash}.json   # parquet-manifest/v1
```

**Master SCD2 (not Dataset COMPLETE; permanent DEFER history):**

```text
structured/scd2/equities_master/CURRENT.json
structured/scd2/equities_master/events/dt={asOf}/{run_id}.ndjson
```

### 1.3 D1 hot tip (bounded)

**J-Quants generic facts** (when present on D1 — tip/residual only):

```sql
SELECT source, dataset, natural_key, event_time, available_at, payload
  FROM jquants_records
 WHERE dataset = ?
   AND substr(event_time, 1, 10) >= ?   -- hot lower bound (e.g. 2026-07-01)
   AND substr(event_time, 1, 10) <= ?
 ORDER BY event_time, natural_key
 LIMIT 10000;
```

**JSDA tip tables** (hot publish script; full history is **not** on D1 by design):

| dataset | D1 fact table | hot filter column |
|---------|---------------|-------------------|
| `jsda_tokyo_repo_rates` | `jsda_repo_rates` | `as_of_date >= hot_cutoff` |
| `jsda_corporate_bond_transactions` | `jsda_corporate_bond_transactions` | publication/trade date ≥ cutoff |
| `jsda_otc_bond_reference_prices` | `jsda_otc_bond_reference_prices` | publication_label_date ≥ cutoff (**tip island only**; archive DEFER) |

**Control plane (COMPLETE ownership — always D1):**

```sql
-- receipt-owned COMPLETE, not fact COUNT
SELECT * FROM dataset_coverage WHERE dataset = ?;
SELECT * FROM coverage_segments WHERE dataset = ? AND status = 'COMPLETE';
SELECT * FROM collection_receipts /* signed digests */ ;
```

### 1.4 Research read path (local/dev; not CF SoT)

`QuantDataAccess` / `ResearchReadyReadService` → published READY snapshot SQLite + `pit.get_jquants_records` (PIT-gated).  
**No READY generation is declared in this wave.** Local mirror DB is **not** CF SoT.

Ops visibility: `OpsCurrentReadService` over projected control DB / remote D1 — status & coverage only (no unbounded fact export as SoT).

---

## 2. T1 — Per-dataset CF read paths (21 COMPLETE)

**Legend**

| field | meaning |
|-------|---------|
| **History SoT** | Where full history lives for research/joins |
| **Tip SoT** | Where recent tip may be read for ops/MCP |
| **COMPLETE SoT** | Always receipt/coverage (not row counts) |
| **R2 history pattern** | Primary structured prefix to list/read |
| **R2 raw pattern** | Evidence pages |
| **D1 tip** | Table + filter if applicable |

### 2.1 Equities / bars / calendar / investor

| dataset | History SoT | Tip SoT | COMPLETE SoT | R2 history | R2 raw | D1 tip |
|---------|-------------|---------|--------------|------------|--------|--------|
| `equities_bars_daily` | R2 structured JSONL/archive (+ parquet bridge) | D1 `jquants_records` residual/tip if present | receipt | `structured/jsonl/equities_bars_daily/dt=…` · `archive/jquants_records/equities_bars_daily/…` | `raw/equities_bars_daily/{run_id}/…` | `jquants_records` `dataset='equities_bars_daily'` · event_time ≥ hot |
| `equities_investor_types` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/equities_investor_types/…` | `raw/equities_investor_types/{run_id}/…` | `jquants_records` same pattern |
| `markets_calendar` | R2 structured (tiny; may also fit D1 allowlist if env set) | D1 residual/tip | receipt | `structured/jsonl/markets_calendar/…` | `raw/markets_calendar/{run_id}/…` | `jquants_records` · calendar grain |
| `markets_breakdown` | R2 structured (high-volume) | D1 residual/tip | receipt | `structured/jsonl/markets_breakdown/…` · archive | `raw/markets_breakdown/{run_id}/…` | `jquants_records` |

### 2.2 Indices

| dataset | History SoT | Tip SoT | COMPLETE SoT | R2 history | R2 raw | D1 tip |
|---------|-------------|---------|--------------|------------|--------|--------|
| `indices_bars_daily` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/indices_bars_daily/…` | `raw/indices_bars_daily/{run_id}/…` | `jquants_records` |
| `indices_bars_daily_topix` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/indices_bars_daily_topix/…` | `raw/indices_bars_daily_topix/{run_id}/…` | `jquants_records` |

### 2.3 Derivatives

| dataset | History SoT | Tip SoT | COMPLETE SoT | R2 history | R2 raw | D1 tip |
|---------|-------------|---------|--------------|------------|--------|--------|
| `derivatives_bars_daily_futures` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/derivatives_bars_daily_futures/…` | `raw/derivatives_bars_daily_futures/{run_id}/…` | `jquants_records` |
| `derivatives_bars_daily_options` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/derivatives_bars_daily_options/…` | `raw/derivatives_bars_daily_options/{run_id}/…` | `jquants_records` |
| `derivatives_bars_daily_options_225` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/derivatives_bars_daily_options_225/…` | `raw/derivatives_bars_daily_options_225/{run_id}/…` | `jquants_records` |

### 2.4 Fins (COMPLETE subset)

| dataset | History SoT | Tip SoT | COMPLETE SoT | R2 history | R2 raw | D1 tip |
|---------|-------------|---------|--------------|------------|--------|--------|
| `fins_summary` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/fins_summary/…` | `raw/fins_summary/{run_id}/…` | `jquants_records` |
| `fins_details` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/fins_details/…` | `raw/fins_details/{run_id}/…` | `jquants_records` |
| `fins_dividend` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/fins_dividend/…` | `raw/fins_dividend/{run_id}/…` | `jquants_records` |

### 2.5 Markets margin / short

| dataset | History SoT | Tip SoT | COMPLETE SoT | R2 history | R2 raw | D1 tip |
|---------|-------------|---------|--------------|------------|--------|--------|
| `markets_margin_interest` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/markets_margin_interest/…` | `raw/markets_margin_interest/{run_id}/…` | `jquants_records` |
| `markets_margin_alert` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/markets_margin_alert/…` | `raw/markets_margin_alert/{run_id}/…` | `jquants_records` |
| `markets_short_ratio` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/markets_short_ratio/…` | `raw/markets_short_ratio/{run_id}/…` | `jquants_records` |
| `markets_short_sale_report` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/markets_short_sale_report/…` | `raw/markets_short_sale_report/{run_id}/…` | `jquants_records` |

### 2.6 EDINET

| dataset | History SoT | Tip SoT | COMPLETE SoT | R2 history | R2 raw | D1 tip |
|---------|-------------|---------|--------------|------------|--------|--------|
| `edinet_major_shareholders` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/edinet_major_shareholders/…` | `raw/edinet_major_shareholders/{run_id}/…` | `jquants_records` |
| `edinet_cross_shareholdings` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/edinet_cross_shareholdings/…` | `raw/edinet_cross_shareholdings/{run_id}/…` | `jquants_records` |
| `edinet_large_volume_shareholders` | R2 structured | D1 residual/tip | receipt | `structured/jsonl/edinet_large_volume_shareholders/…` | `raw/edinet_large_volume_shareholders/{run_id}/…` | `jquants_records` |

### 2.7 JSDA (COMPLETE subset)

| dataset | History SoT | Tip SoT | COMPLETE SoT | R2 history / raw | D1 tip |
|---------|-------------|---------|--------------|------------------|--------|
| `jsda_tokyo_repo_rates` | **R2** sealed history (+ local mirror **not** SoT) | D1 `jsda_repo_rates` hot (`as_of_date >= 2026-07-01`) | receipt (`jsda-era-timeseries` segment class) | Raw under JSDA product paths / R2 mirror; structured history sealed off D1 full backfill | `SELECT … FROM jsda_repo_rates WHERE as_of_date >= '2026-07-01'` |
| `jsda_corporate_bond_transactions` | **R2** sealed history (+ local mirror not SoT) | D1 `jsda_corporate_bond_transactions` hot | receipt | Annual/event archive raw + structured seal | hot tip publish only |

**Note:** `jsda_otc_bond_reference_prices` is **not** in the 21 COMPLETE set (permanent DEFER archive long-tail; tip island COMPLETE segments only). See §3.

### 2.8 How to read (operator sketch)

1. **Confirm COMPLETE (receipt-owned):** remote Ops / D1 `dataset_coverage` + `coverage_segments` — not `COUNT(*)` on facts.  
2. **History join / research:** list/read R2 `structured/jsonl/{dataset}/` and/or `archive/jquants_records/{dataset}/`; use `parquet-manifest/v1` / artifacts-join-plan for discovery.  
3. **Tip / ops:** bounded D1 SQL above; JSDA via hot tables after `publish_jsda_hot_to_d1.py`.  
4. **Never** claim local `data/structured/ingestion.sqlite` as CF SoT.  
5. **Research fact API (when READY exists):** `QuantDataAccess.query_dataset` / PIT — permanent DEFER blocked (see §3).

---

## 3. T2 — Permanent DEFER exclude guard

### 3.1 Permanent DEFER 5 (not Dataset COMPLETE)

| dataset | PD id | class (summary) |
|---------|-------|-----------------|
| `equities_master` | PD-D2-MASTER | MISDATE + PRE_PLAN residual |
| `equities_earnings_calendar` | PD-D4-EARN-CAL | vendor tip-only history |
| `equities_bars_daily_am` | PD-D4-BARS-AM | tip-only AM |
| `fins_earnings_date` | PD-MX-EARN-TIP | tip holes `2026-01…04` |
| `jsda_otc_bond_reference_prices` | PD-D5-JSDA-OTC | archive long-tail; tip island only |

Densify on these classes: **FORBIDDEN** (NO_DENSIFY held). Do **not** invent Dataset COMPLETE 22.

### 3.2 Code path (**added** W48)

| piece | path |
|-------|------|
| Constant + helpers | `packages/data_plane/data_contracts/permanent_defer.py` |
| Public export | `data_contracts.PERMANENT_DEFER_DATASETS`, `filter_permanent_defer`, `reject_permanent_defer_for_history`, `require_history_eligible` |
| Research history fail-closed | `QuantDataAccess._require_history_dataset` → used by `query_dataset` / `trace_provenance` (and thus `get_series`) |
| Unit test | `tests/test_permanent_defer_history_guard.py` |

**Behavior:**

* **Reject (fail-closed):** any research history fact load through `QuantDataAccess` that names a permanent DEFER dataset → `PermanentDeferHistoryError` (subclass of `PermissionError`).  
* **Filter:** `filter_permanent_defer(datasets)` for loaders that accept dataset lists and should drop DEFER ids.  
* **Metadata still allowed:** `describe_dataset` / coverage tools may reference DEFER ids for discovery; only **history fact** loads are blocked.  
* Ops / ingestion / backfill planners are **not** rewritten here (acquisition may still touch DEFER residuals under residual SoT rules).

**Usage:**

```python
from data_contracts import (
    PERMANENT_DEFER_DATASETS,
    filter_permanent_defer,
    reject_permanent_defer_for_history,
)

# list-style research history allowlist
datasets = filter_permanent_defer(requested)

# fail-closed when any DEFER slipped in
reject_permanent_defer_for_history(datasets, context="my_history_loader")
```

### 3.3 Guard status

| check | status |
|-------|--------|
| Permanent DEFER constant in code | **added** |
| Fail-closed research history reject | **added** (`QuantDataAccess` fact APIs) |
| Filter helper for dataset lists | **added** |
| Unit test | **added** |

---

## 4. T3 — PIT keys table (Code / Date / event_time / available_at)

Natural keys and PIT fields come from `jquants_premium_core.json` / `jsda_governed.json` via `data_contracts.identity` (`natural_key`, `event_time_for`, `available_at_for`).  
Stored rows use JSON natural_key objects (or `hash:sha256:…` fallback) on `jquants_records.natural_key`.

### 4.1 COMPLETE 21 families

| dataset | natural_key fields (Code/Date family) | event_time source | available_at policy / field | common aliases |
|---------|----------------------------------------|-------------------|-----------------------------|----------------|
| `equities_bars_daily` | **Code**, **Date** | session_close ← Date | session_close ← Date | — |
| `equities_investor_types` | **PubDate**, **Section** | observation_date ← **EnDate** | explicit_disclosure_date ← PubDate (+1d 00:00 if date-only) | — |
| `fins_summary` | **Code**, **DiscDate**, **DiscNo** | DiscDate+DiscTime | explicit_timestamp_field ← DiscDate+DiscTime | DiscDate←DisclosedDate; DiscTime←DisclosedTime |
| `fins_details` | **Code**, **DiscDate**, **DiscNo** | DiscDate+DiscTime | explicit_timestamp_field | same as summary |
| `fins_dividend` | **Code**, **RefNo** | PubDate+PubTime | explicit_timestamp_field ← PubDate+PubTime | PubDate←AnnouncementDate; PubTime←AnnouncementTime; RefNo←ReferenceNumber,CARefNo |
| `indices_bars_daily` | **Date**, **Code** | session_close ← Date | session_close ← Date | — |
| `indices_bars_daily_topix` | **Date** | session_close ← Date | session_close ← Date | (no Code) |
| `derivatives_bars_daily_futures` | **Date**, **Code** | session_close ← Date | session_close ← Date | Code = contract id |
| `derivatives_bars_daily_options` | **Date**, **Code** | session_close ← Date | session_close ← Date | Code = contract id |
| `derivatives_bars_daily_options_225` | **Date**, **Code** | session_close ← Date | session_close ← Date | Code = contract id |
| `markets_calendar` | **Date** | observation_date ← Date | calendar_prepublished → **ingest_time** fallback | — |
| `markets_breakdown` | **Date**, **Code** | observation_date ← Date | ingest_time_conservative | — |
| `markets_margin_interest` | **Date**, **Code** | observation_date ← Date | ingest_time_conservative | — |
| `markets_margin_alert` | **Code**, **PubDate**, **AppDate** | observation_date ← **AppDate** | explicit_disclosure_date ← PubDate | — |
| `markets_short_ratio` | **Date**, **S33** | observation_date ← Date | ingest_time_conservative | S33 = sector discriminator (not equity Code) |
| `markets_short_sale_report` | **DiscDate**, **CalcDate**, **Code**, **DICName**, **FundName** | observation_date ← **CalcDate** | explicit_disclosure_date ← DiscDate | day_param disc_date |
| `edinet_major_shareholders` | **Code**, **DocId** | SubDate+SubTime | explicit_timestamp_field ← SubDate+SubTime | — |
| `edinet_cross_shareholdings` | **Code**, **DocId** | SubDate+SubTime | explicit_timestamp_field | — |
| `edinet_large_volume_shareholders` | **Code**, **DocId** | SubDate+SubTime | explicit_timestamp_field | — |
| `jsda_tokyo_repo_rates` | source, **as_of_date**, tenor, rate_type | source observation date | ingest_time_conservative when publication TS unknown | table `jsda_repo_rates` |
| `jsda_corporate_bond_transactions` | source, publication_label_date, **trade_date**, security_code, source_record_id | source trade_date | ingest_time_conservative when publication TS unknown | — |

### 4.2 Session close clock (bars / indices / derivatives)

`session_close_jst(Date)`:

* Full-day session: `15:00:00+09:00` if Date &lt; `2024-11-05`, else `15:30:00+09:00`  
* Morning session (AM bars — DEFER dataset): `11:30:00+09:00`

`event_time` and `available_at` for session_close policy both use that close instant.

### 4.3 PIT join recipe

1. Join entities on natural_key fields (or JSON natural_key equality).  
2. Gate all research reads with `available_at <= as_of` (PIT API enforces).  
3. Prefer contract `event_time` for chronology; do not substitute wall-clock.  
4. When `available_at_policy` is ingest_time_conservative / calendar_prepublished, treat historical publication as **unknown** → conservative ingest stamp (no invented lag).  
5. Disclosure date-only fields: availability becomes **next calendar day 00:00 JST** (`explicit_disclosure_date`).

### 4.4 Permanent DEFER datasets (PIT keys — do not use for full-history claims)

| dataset | natural_key | event_time | available_at | note |
|---------|-------------|------------|--------------|------|
| `equities_master` | Code, Date (contract); SCD2 CURRENT separate | observation_date ← Date | ingest_time_conservative | PD-D2-MASTER |
| `equities_earnings_calendar` | Date, Code | observation_date ← Date | calendar_prepublished → ingest | PD-D4-EARN-CAL |
| `equities_bars_daily_am` | Code, Date | session_close morning | session_close AM | PD-D4-BARS-AM |
| `fins_earnings_date` | Code, PubDate, SchDate | observation_date ← SchDate | explicit_disclosure_date ← PubDate | PD-MX-EARN-TIP |
| `jsda_otc_bond_reference_prices` | source, publication_label_date, security_code, bond_name | quote session close 15:00 JST policy | ingest_time_conservative when unknown | PD-D5-JSDA-OTC |

---

## 5. Explicit non-claims

This document does **not**:

* declare Mass Autonomous Research **ON**
* declare production **READY** / B0 **GO**
* enable **Phase7**
* invent Dataset COMPLETE **22**
* re-open densify / tip densify as primary
* treat local SQLite as SoT

---

## 6. Related

| artifact | path |
|----------|------|
| Usage notes (21) | `docs/proof/coverage_baseline_21_usage_notes_20260815.md` |
| Residual SoT | `docs/phase62_residual_status.md` |
| JSDA hot tip publish | `docs/proof/jsda_hot_d1_publish_20260815.md` |
| PIT API | `docs/pit_api.md` |
| Guard module | `packages/data_plane/data_contracts/permanent_defer.py` |
| Guard tests | `tests/test_permanent_defer_history_guard.py` |
