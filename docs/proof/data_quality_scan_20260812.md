# Data quality scan — remote D1 `quant-ingest` (2026-08-12)

**Operator:** P1-3 quality check (read + post-publish reconfirm)  
**Tooling:** `npx wrangler d1 execute quant-ingest --remote` via `platform/workers/quant-ops-mcp`  
**Mass / READY / Phase7:** **NO-GO**

Scan timestamps (UTC): ~2026-08-12T13:30–13:40. Segment COMPLETE counts below are **POST** honest +3 publish (`401 → 404`); PRE baseline was **401 COMPLETE / 12539 PARTIAL**.

---

## 1. Coverage segment status counts

| status | n (POST) | PRE (start of ticket) |
|--------|----------|------------------------|
| **COMPLETE** | **404** | 401 |
| **PARTIAL** | **12537** | 12539 |
| other | 0 | 0 |

Delta: **+3 COMPLETE**, −2 PARTIAL (one new inventory segment `2026-08-13` also entered COMPLETE).

### Per-dataset COMPLETE / PARTIAL (material)

| dataset | COMPLETE | PARTIAL |
|---------|----------|---------|
| markets_calendar | 224 | 0 |
| jsda_tokyo_repo_rates | 1 | 0 |
| jsda_otc_bond_reference_prices | **5** | 8773 |
| jsda_corporate_bond_transactions | 1 | 11 |
| markets_margin_interest | 14 | 150 |
| equities_master | 94 | (rest PARTIAL) |
| indices_bars_daily_topix | 32 | 192 |
| markets_breakdown | 8 | 156 |
| markets_short_ratio | 6 | 158 |
| fins_summary | 5 | 219 |
| equities_bars_daily | 12 | … |
| markets_margin_alert | 0 | 164 |
| markets_short_sale_report | 0 | 164 |

OTC COMPLETE segment ids (POST): `2026-08-06`, `2026-08-07`, `2026-08-10`, `2026-08-12`, `2026-08-13`.

---

## 2. Dataset-level coverage (`dataset_coverage`)

| status | n |
|--------|---|
| COMPLETE | **2** (`markets_calendar`, `jsda_tokyo_repo_rates`) |
| PARTIAL | **23** |
| STALE | **1** |

### `markets_margin_interest` STALE — reconfirm

| Field | Value |
|-------|--------|
| status | **STALE** (unchanged) |
| observed_start / observed_end | `2024-01-12T00:00:00+09:00` → `2025-02-28T00:00:00+09:00` |
| row_count (coverage plane) | 251470 |
| segments | COMPLETE **14** / PARTIAL **150** (required 164) |
| watermark `last_event_date` | **2026-07-31** |
| D1 hot `jquants_records` | 21277 rows, event_time `2026-07-03` … `2026-07-31` |

Root cause unchanged vs `docs/proof/p1_markets_margin_interest_stale_defer_20260812.md`: C8 freshness (cold plane max 2025-02-28; even watermark lag >7d) + monthly vs weekly receipt identity + history gaps. **No status rewrite this ticket.**

---

## 3. `jquants_records` major datasets (D1 hot)

Hot window policy — not full history. Counts as of scan:

| dataset | row_count | min event_time | max event_time |
|---------|-----------|----------------|----------------|
| derivatives_bars_daily_futures | 126 | 2026-08-10T09:00:00+09:00 | 2026-08-10T09:00:00+09:00 |
| derivatives_bars_daily_options | 42460 | 2026-08-10T09:00:00+09:00 | 2026-08-10T09:00:00+09:00 |
| derivatives_bars_daily_options_225 | 10534 | 2026-08-10T09:00:00+09:00 | 2026-08-10T09:00:00+09:00 |
| equities_bars_daily | 124367 | 2026-07-01T09:00:00+09:00 | 2026-08-10T09:00:00+09:00 |
| equities_bars_daily_am | 4444 | 2026-08-10T09:00:00+09:00 | 2026-08-10T09:00:00+09:00 |
| equities_earnings_calendar | 137 | 2026-08-12T09:00:00+09:00 | 2026-08-12T09:00:00+09:00 |
| equities_investor_types | 20 | 2026-07-03T00:00:00+09:00 | 2026-08-11T02:16:19+09:00 |
| equities_master | 128811 | 2026-07-01T00:00:00+09:00 | 2026-08-12T09:00:00+09:00 |
| fins_details | 266 | 2026-08-10T09:00:00+09:00 | 2026-08-10T09:00:00+09:00 |
| fins_dividend | 2203 | 2026-07-01T08:59:00+09:00 | 2026-08-11T09:19:33+09:00 |
| fins_earnings_date | 3762 | 2026-07-03T00:00:00+09:00 | 2027-07-15T00:00:00+09:00 |
| fins_summary | 3021 | 2026-07-01T14:00:00+09:00 | 2026-08-10T09:00:00+09:00 |
| indices_bars_daily | 4256 | 2026-07-01T15:30:00+09:00 | 2026-08-10T09:00:00+09:00 |
| indices_bars_daily_topix | 28 | 2026-07-01T15:30:00+09:00 | 2026-08-10T09:00:00+09:00 |
| markets_breakdown | 117693 | 2026-07-01T00:00:00+09:00 | 2026-08-10T09:00:00+09:00 |
| markets_calendar | 42 | 2026-07-01T09:00:00+09:00 | 2026-08-11T09:00:00+09:00 |
| markets_margin_alert | 5844 | 2026-07-01T00:00:00+09:00 | 2026-08-11T09:19:50+09:00 |
| markets_margin_interest | 21277 | 2026-07-03T00:00:00+09:00 | 2026-07-31T00:00:00+09:00 |
| markets_short_ratio | 952 | 2026-07-01T00:00:00+09:00 | 2026-08-10T09:00:00+09:00 |
| markets_short_sale_report | 21202 | 2026-07-01T00:00:00+09:00 | 2026-08-10T09:00:00+09:00 |

**Notes**

- Hot D1 is a retention window (~July–August 2026 for most series), not cold history.
- `markets_margin_interest` hot max **2026-07-31** vs calendar today **2026-08-12** (~12d lag).
- Several datasets show single-day spikes on `2026-08-10` (derivatives AM options, etc.) — consistent with recent premium ingest, not full backfill.

---

## 4. NULL / anomaly probes

### `ingestion_watermarks.last_export_cursor`

| metric | value |
|--------|-------|
| total watermark rows | 23 |
| `last_export_cursor IS NULL` | **0** |
| `last_event_date IS NULL` | **3** (non-fatal): `fins_dividend`, `fins_earnings_date`, `markets_margin_alert` |

`last_export_cursor` all non-null (previously healed; reconfirmed **0** nulls).

### Other observations

- SUCCESS local receipts with matching raw/structured counts still **PARTIAL** when not Ed25519 TRUSTED (e.g. many `equities_earnings_calendar` monthly rows) — not auto-promoted.
- Ops projection after publish: generation `projgen-e5879899a5fb408eb97a1c253968c6f2`, status **FRESH**.

---

## 5. JSDA fact tables (remote D1)

| table | remote row_count | notes |
|-------|------------------|-------|
| `jsda_otc_bond_reference_prices` | **12403** | publication_label_date=`2026-08-12` only on remote fact plane |
| `jsda_corporate_bond_transactions` | **89** | publication_label_date=`2026-08-10` |
| `jsda_repo_rates` | **0** | Tokyo Repo COMPLETE is local/projection ledger evidence; D1 fact empty |
| `jsda_otc_bond_reference_prices_revisions` | (not re-counted) | present |

**Important:** ops projection publishes **coverage ledgers**, not full fact backfill. Local sqlite holds additional OTC days closed this ticket (`2026-08-06/07/13` + prior `08-10`); remote D1 fact for OTC still reflects the hot/prior CF path (primarily `2026-08-12`).

Local structured OTC counts (research DB, post ticket):

| publication_label_date | n |
|------------------------|---|
| 2026-08-06 | 12405 |
| 2026-08-07 | 12402 |
| 2026-08-10 | 12401 |
| 2026-08-12 | 12403 |
| 2026-08-13 | 12402 |

---

## 6. Explicit non-claims

- No Mass ON / READY / B0.
- No fabricated COMPLETE; no `markets_margin_interest` STALE flip.
- No packages/ reorg participation; storage/coverage_ledger untouched this ticket.
- Remote fact ≠ local fact for newly closed OTC days (coverage plane only on remote).
