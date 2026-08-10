# Phase 3.5 — CF J-Quants Premium Ingestion Closed Loop

The Cloudflare Worker `quant-platform-ingestion-premium` implements the
J-Quants **Premium core** ingestion loop end-to-end on CF. Once its resources,
migration, existing secret values, Worker, and Cron Trigger are deployed, it
owns the schedule, secrets, raw + structured persistence, and validation log.

Deployment status (2026-08-11 JST): `quant-ingest`, `quant-raw`, and
`quant-structured` exist; the migration, both existing secret bindings, Worker,
and hourly Cron Trigger are deployed. `/health` reports the key binding ready,
and an authenticated paginated export smoke succeeds.

## What's in scope (Premium core, 23 datasets)

| Group        | Datasets |
|--------------|----------|
| Equities     | `equities_master`, `equities_bars_daily`, `equities_bars_daily_am`, `equities_earnings_calendar`, `equities_investor_types` |
| Fins         | `fins_summary`, `fins_details`, `fins_dividend`, `fins_earnings_date` |
| Markets      | `markets_calendar`, `markets_margin_interest`, `markets_margin_alert`, `markets_short_ratio`, `markets_short_sale_report`, `markets_breakdown` |
| Indices      | `indices_bars_daily_topix`, `indices_bars_daily` |
| Derivatives  | `derivatives_bars_daily_options_225`, `derivatives_bars_daily_futures`, `derivatives_bars_daily_options` |
| EDINET       | `edinet_major_shareholders`, `edinet_cross_shareholdings`, `edinet_large_volume_shareholders` |

**Out of scope** (Premium **addons** — minute, tick/TDnet): `equities_bars_minute`,
`equities_trades`, `td_list`, `td_files`, `td_bulk`. These are NEVER in the
required schedule. See ``tests/test_phase35_premium_set.py`` for the static
guard.

## Closed-loop guarantees

1. **Scheduled** via Workers Cron (`scheduled` handler, hourly at :15 UTC).
2. **Secrets only on CF** — same names: `JQUANTS_API_KEY` (required for fetch)
   + optional `INGESTION_PROXY_TOKEN` (gates `/v1/run` and `/v1/export/d1`).
3. **Persist R2 raw + D1 structured** — every fetch lands both. R2 raw is at
   `raw/{dataset}/{yyyy}/{mm}/{dd}/{stamp}.json`; D1 rows go in
   `jquants_records` (and the revisions mirror) with full PIT columns.
4. **Incremental primary; backfill separable** — cron uses recent from/to
   windows; `/v1/run?from=&to=` backfills a span. Endpoints that accept only
   `date` fan out once per day, while `equities_bars_daily` prefers its
   confirmed `/v2/bulk/equities/bars/daily` transport.
5. **Auto validation** — per-dataset result written to `ingestion_validation`
   with explicit `status ∈ {pass, fail}`.
6. **Failures ≠ success** — a fetch error sets `status='fail'`; the run
   summary status is `pass` / `partial` / `fail` (never silent). See
   ``cf_platform.ingest_premium.validate.classify_dataset`` for the rule.
7. **Local-readable path** — ``scripts/sync_d1_to_sqlite.py`` follows the
   cursor-paginated `/v1/export/d1` response and builds a local PIT DB so
   ``pit.get_*`` reads work offline.

## Resources

| Kind | Name | Purpose |
|------|------|---------|
| R2   | `quant-raw` | Verbatim source JSON, partitioned by dataset/date |
| R2   | `quant-structured` | Reserved (future parquet/partition dumps) |
| D1   | `quant-ingest` | PIT-shaped structured rows (mirror of `storage/schema.py`) |
| Worker | `quant-platform-ingestion-premium` | Cron + manual run + export |

Schema migration: ``platform/workers/ingestion-premium/migrations/0001_init.sql``.

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET    | `/health` | none | Readiness + last-run summary |
| POST   | `/v1/run?dataset=&from=&to=&today=` | `X-Ingestion-Token` | Manual trigger (one or all datasets) |
| GET    | `/v1/export/d1?table=&cursor=&limit=` | `X-Ingestion-Token` | Read one cursor-paginated D1 JSON page (`limit` 1–1000) |

## Secrets policy

* **Do NOT reissue** the J-Quants key. The existing value is bound on the
  Phase-1 ``quant-platform-ingestion-secrets`` worker; re-use that same value
  as a secret on this worker.
* The Worker logs the *boolean* `has_jquants_key` only — never the value.
* Names are fixed across phases (`JQUANTS_API_KEY`,
  `INGESTION_PROXY_TOKEN`).

## Deploy (runbook)

```bash
cd platform/workers/ingestion-premium

# One-time resources
npx wrangler r2 bucket create quant-raw
npx wrangler r2 bucket create quant-structured
npx wrangler d1 create quant-ingest
# Paste the printed database_id into wrangler.toml.
npx wrangler d1 execute quant-ingest --remote --file=migrations/0001_init.sql

# Secrets (same values as the secrets-proxy worker — DO NOT reissue the key)
printf '%s' "$JQUANTS_API_KEY" | npx wrangler secret put JQUANTS_API_KEY -c wrangler.toml
printf '%s' "$INGESTION_PROXY_TOKEN" | npx wrangler secret put INGESTION_PROXY_TOKEN -c wrangler.toml

# Deploy
npx wrangler deploy -c wrangler.toml
```

## Local sync (S6)

```bash
python3 scripts/sync_d1_to_sqlite.py \
  --url https://quant-platform-ingestion-premium.<acct>.workers.dev \
  --token "$INGESTION_PROXY_TOKEN" \
  --db data/structured/ingestion.sqlite

# Then verify pit reads work:
python3 -c "
import pit
r = pit.get_equity_bars_daily(as_of='2025-04-01T17:00:00+09:00', code='8697')
print(r.metadata, len(r))
"
```

## Ops

* **Manual run**: ``curl -X POST -H "X-Ingestion-Token: $INGESTION_PROXY_TOKEN" \
  "$URL/v1/run?dataset=equities_master&today=2025-04-01"``
* **Inspect last run**: ``curl -sS "$URL/health" | jq .last_run``
* **Validation table**: query ``ingestion_validation`` via D1 console or
  ``/v1/export/d1?table=ingestion_validation``.

## Tests

| File | Purpose |
|------|---------|
| ``tests/test_phase35_premium_set.py`` | Premium set = required set, no addons, TS mirror agrees |
| ``tests/test_phase35_validate.py`` | Pass/fail classification (Python source of truth) |
| ``tests/test_phase35_natural_key.py`` | Cross-language natural-key consistency |
| ``tests/test_phase35_sync_script.py`` | Sync script offline-safety + live smoke (QP_LIVE=1) |

## Phase 3.5 → Phase 4 bridge

The features package reads facts through ``pit.get_*`` from a SQLite DB.
After running the sync script, that DB IS the local mirror of CF D1 — so
features automatically pick up CF-ingested Premium core rows. The closed
loop:

```
J-Quants Premium → CF Worker (cron) → R2 raw + D1 structured
                       ↓ /v1/export/d1
              sync_d1_to_sqlite.py (S6)
                       ↓
                local ingestion.sqlite
                       ↓
                  pit.get_* (Phase 2)
                       ↓
              features.compute (Phase 4)
                       ↓
              core.run_backtest (Phase 3)
```
