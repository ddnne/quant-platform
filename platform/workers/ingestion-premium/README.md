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
| R2 | `quant-raw` | Verbatim source JSON per fetch, partitioned by dataset/date |
| R2 | `quant-structured` | Reserved (future parquet/partition dumps) |
| D1 | `quant-ingest` | PIT-shaped structured rows (mirror of `storage/schema.py`) + watermarks |
| Secret | `JQUANTS_API_KEY` | Required for upstream fetch; bind the existing value |
| Secret | `INGESTION_PROXY_TOKEN` | Optional; gates the manual `/v1/run` endpoint |

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
2. **Secrets only on CF** — same names (`JQUANTS_API_KEY`,
   `INGESTION_PROXY_TOKEN`). Never logged.
3. **Persist R2 raw + D1 structured** — every fetch lands both.
4. **Incremental primary**; backfill separable via `/v1/run?from=&to=`. Date-only
   endpoints fan out one request per day, and daily bars use the confirmed bulk path.
5. **Auto validation** — every dataset result is written to
   `ingestion_validation` with explicit `status ∈ {pass, fail}`.
6. **Failures ≠ success** — a fetch error sets `status='fail'`; the run
   summary status is `pass` / `partial` / `fail` (never silent).
7. **Local-readable path** — `scripts/sync_d1_to_sqlite.py` follows export
   cursors to build a local PIT DB readable by `pit.get_*`.

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
printf '%s' "$INGESTION_PROXY_TOKEN" | npx wrangler secret put INGESTION_PROXY_TOKEN -c platform/workers/ingestion-premium/wrangler.toml

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
  --token "$INGESTION_PROXY_TOKEN" \
  --db data/structured/ingestion.sqlite

# Incremental: skip rows already mirrored locally by ingested_at watermark.
python3 scripts/sync_d1_to_sqlite.py --incremental \
  --url "$INGESTION_PREMIUM_URL" \
  --token "$INGESTION_PROXY_TOKEN" \
  --db data/structured/ingestion.sqlite
```

See [docs/phase35_cf_ingest.md](../../../docs/phase35_cf_ingest.md) for the
full closed-loop spec and ops runbook, and
[docs/phase35_storage_scale.md](../../../docs/phase35_storage_scale.md) for
the storage scale path (R2 parquet + watermarks + incremental sync).
