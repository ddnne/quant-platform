# ingestion-premium (Phase 3.5)

Cloudflare Worker that implements the **J-Quants Premium core** ingestion loop
on CF. It owns the schedule, secrets, R2 raw persistence, D1 structured rows, and
the validation log. The loop is live only after the resources, migration,
existing secret values, Worker, and Cron Trigger are deployed successfully.

Deployment status (2026-08-11 JST): resources, migration, both existing secret
bindings, Worker, and hourly Cron Trigger are deployed; readiness and a
paginated export request have been verified.

## Resources

| Kind | Name | Purpose |
|------|------|---------|
| R2 | `quant-raw` | Full response pages + digest manifest per dataset/run |
| R2 | `quant-structured` | Reserved (future parquet/partition dumps) |
| D1 | `quant-ingest` | PIT-shaped structured rows (mirror of `storage/schema.py`) + watermarks |
| Secret | `JQUANTS_API_KEY` | Required for upstream fetch; bind the existing value |
| Secret | `INGESTION_RUN_TOKEN` | Manual run and migration rebuild only |
| Secret | `DATA_EXPORT_TOKEN` | Structured export endpoints only |

After 0002, D1 also holds `ingestion_watermarks` (one row per dataset,
advanced after every successful ingest). The local sync script reads it
through `/v1/export/d1?table=ingestion_watermarks`; see
`docs/phase35_storage_scale.md` for the full scale-path plan.

## Schedule

Cron = `"15 * * * *"` (hourly at :15; for example 00:15 UTC == 09:15 JST). Premium publishes
through the JST trading day; hourly cadence keeps the loop closed without
stressing the 500 req/min cap. Override in `wrangler.toml`.

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | none | Readiness + last-run summary |
| POST | `/v1/run?dataset=&from=&to=&today=` | `X-Ingestion-Token` | Manual trigger (one or all datasets) |
| GET | `/v1/export/d1?table=&cursor=&limit=` | `X-Ingestion-Token` | Read one cursor-paginated D1 JSON page |

## Closed-loop guarantees

1. **Scheduled** via Workers Cron (`scheduled` handler).
2. **Secrets only on CF** — upstream, run, and export capabilities are separate and never logged.
3. **Persist R2 raw + D1 structured** — every response page is retained under
   `raw/<dataset>/<run_id>/page-NNNNNN.json`; `manifest.json` records page/row
   counts, SHA-256 digests, and completeness. Production never stores a sample-only body.
4. **Incremental primary**; backfill separable via `/v1/run?from=&to=`. Date-only
   endpoints fan out one request per day, and daily bars use the confirmed bulk path.
5. **Auto validation** — every dataset result is written to
   `ingestion_validation` with explicit `status ∈ {pass, fail}`.
6. **Failures ≠ success** — a fetch error sets `status='fail'`; the run
   summary status is `pass` / `partial` / `fail` (never silent).
7. **Local-readable path** — `scripts/sync_d1_to_sqlite.py` follows export
   cursors to build a local PIT DB readable by `pit.get_*`.

## Available_at policy (P0-1)

Each structured row's `available_at` is derived from a dataset-level policy
in `src/availability.ts` (Python mirror: `cf_platform/ingest_premium/availability.py`):

An upstream payload property named `available_at` is retained in `payload` and
`raw_payload` for provenance, but is never copied into the trusted metadata
column. Only the canonical contract (or the Python normalizer's explicit
trusted-caller keyword used by controlled backfills/tests) can select it.

* **`session_close`** for OHLC bar datasets — JST close instant of the row's
  `Date` (15:30 from 2024-11-05; 15:00 before).
* **`event_field`** (default) — first present candidate from
  `DateTime / DisclosedDate / AnnouncementDate / DiscDate / Date`. Bare
  dates become next-business-open at 09:00 JST.
* **`ingest_time`** — fetch-time fallback only.

Unit tests: `tests/test_phase35_availability.py`.

## Contract-v2 natural-key rebuild

Migration `0005_natural_keys_v2.sql` creates only control/staging tables and
sets the rebuild state to `PENDING`; it intentionally does not synthesize keys
with SQLite `json_object()`. D1 has no portable SHA-256 function, so missing
required identity fields must be handled by the Worker's canonical function.

After applying `0005` and deploying the Worker, run the authenticated rebuild:

```bash
curl -fsS -X POST \
  -H "X-Ingestion-Token: $INGESTION_RUN_TOKEN" \
  "$INGESTION_PREMIUM_URL/v1/admin/rebuild-natural-keys-v2"
curl -fsS "$INGESTION_PREMIUM_URL/health"
```

The rebuild stages rows page by page, groups collisions into one primary plus
revision history, atomically replaces the affected live rows, then audits all
Premium-core primary/revision/change-feed rows against
`canonical_natural_key(payload)`. Ingestion and structured exports are blocked
until `/health` reports `natural_key_migration.state == "READY"`.

## Parallel ingestion + retry (P0-4)

Datasets run concurrently with a shared **120 ms** global rate floor
(theoretical **500 req/min** upstream) and a per-HTTP-request 3-retry budget.
On **429**: short backoff (1–3 s) + temporary 2× interval, then
`notifyOk()` restores the base floor. 5xx uses longer exponential backoff +
jitter. Per-dataset failures are isolated — one fail does not abort siblings.

* Concurrency: `INGEST_CONCURRENCY` env var (default **6**, cap 8).
* Rate limiter: `src/rate_limit.ts` chains `acquire()` calls so all
  concurrent fetches share the same minimum-interval reservation.

## Premium core dataset set

Mirrors `PREMIUM_CORE_DATASETS` in `ingestion/jquants/catalog.py` and is
asserted in `tests/test_phase35_premium_set.py`. Add-ons (minute / trades /
TDnet) are **not** in the schedule.

## Deploy

```bash
# Resources (one-time)
npx wrangler r2 bucket create quant-raw
npx wrangler r2 bucket create quant-structured
npx wrangler d1 create quant-ingest
# Paste the printed database_id into wrangler.toml.
npx wrangler d1 execute quant-ingest --remote --file=migrations/0001_init.sql

# Secrets (JQUANTS_API_KEY already exists on the secrets-proxy worker — but
# ingestion-premium needs its own binding. Re-put the SAME value, do NOT
# reissue the key.)
printf '%s' "$JQUANTS_API_KEY" | npx wrangler secret put JQUANTS_API_KEY -c platform/workers/ingestion-premium/wrangler.toml
printf '%s' "$INGESTION_RUN_TOKEN" | npx wrangler secret put INGESTION_RUN_TOKEN -c platform/workers/ingestion-premium/wrangler.toml
printf '%s' "$DATA_EXPORT_TOKEN" | npx wrangler secret put DATA_EXPORT_TOKEN -c platform/workers/ingestion-premium/wrangler.toml

# Deploy
npx wrangler deploy -c platform/workers/ingestion-premium/wrangler.toml
```

> **Do not reissue** the J-Quants key. Reuse the existing value (held on the
> secrets-proxy worker) by re-putting it as a secret on this worker.

## Local sync (Phase 3.5 S6)

```bash
# Pull each D1 table to local SQLite so pit.get_* can read it.
python3 scripts/sync_d1_to_sqlite.py \
  --url "$INGESTION_PREMIUM_URL" \
  --token "$DATA_EXPORT_TOKEN" \
  --db data/structured/ingestion.sqlite

# Incremental: skip rows already mirrored locally by ingested_at watermark.
python3 scripts/sync_d1_to_sqlite.py --incremental \
  --url "$INGESTION_PREMIUM_URL" \
  --token "$DATA_EXPORT_TOKEN" \
  --db data/structured/ingestion.sqlite
```

See [docs/phase35_cf_ingest.md](../../../docs/phase35_cf_ingest.md) for the
full closed-loop spec and ops runbook, and
[docs/phase35_storage_scale.md](../../../docs/phase35_storage_scale.md) for
the storage scale path (R2 parquet + watermarks + incremental sync).
