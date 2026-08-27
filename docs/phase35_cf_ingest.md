# Phase 3.5 — CF J-Quants Premium Ingestion Closed Loop

> **Live residual / GO SoT:** [`phase62_residual_status.md`](phase62_residual_status.md)
> (Mass NO-GO · Phase 7 OFF). This file is domain/runbook history (2026-08-11),
> not live COMPLETE counts.

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

## Available_at policy (P0-1)

Each structured row carries an `available_at` timestamp — the instant the
fact became knowable on the publish-side, NOT the fetch instant. Historically
the Worker set `available_at = ingestedAt`, which made backfilled bars
invisible to PIT reads until they were re-ingested. The Worker now derives
`available_at` from a per-dataset policy implemented in
`platform/workers/ingestion-premium/src/availability.ts` (Python mirror:
`cf_platform/ingest_premium/availability.py`).

| Policy         | Rule |
|----------------|------|
| `session_close` | `equities_bars_daily`, `equities_bars_daily_am`, `indices_bars_daily`, `indices_bars_daily_topix`, `derivatives_bars_daily_options_225`, `derivatives_bars_daily_futures`, `derivatives_bars_daily_options`: `available_at` = row `Date` at the JST session close (15:30 from 2024-11-05 onward, 15:00 before). If the row lacks `Date`, fall through to `event_field` then `ingest_time`. |
| `event_field` (default) | Pick the first present event-field candidate in the order `DateTime`, `DisclosedDate`, `AnnouncementDate`, `DiscDate`, `Date`. Bare dates (`YYYY-MM-DD`) advance to **next business open at 09:00 JST** (Saturday/Sunday → Monday). Full timestamps pass through verbatim. |
| `ingest_time` | Fallback only — the fetch instant. Used when no better signal exists. |

Resolution order in `pickAvailableAt(row, datasetId, ingestedAt)`:

1. Explicit row-level `available_at` (if the upstream payload provides one).
2. Dataset-policy rule (`session_close` or `event_field`).
3. Cross-policy fallback: `session_close` rows without `Date` still try
   `event_field`; `event_field` rows without any candidate fall through.
4. `ingestedAt` — never null, PIT-safe.

Unit tests: `tests/test_phase35_availability.py` (pure-Python, no network).
The cross-language constants `SESSION_CLOSE_DATASETS` and
`EVENT_FIELD_CANDIDATES` are pinned to match the TS source byte-for-byte.

## Parallel ingestion + retry (P0-4)

The Worker runs datasets concurrently with a shared global rate limiter and
per-HTTP-request retries:

| Knob | Value | Source |
|------|-------|--------|
| Concurrency cap | default 6, max 8 | `INGEST_CONCURRENCY` env var on the Worker |
| Global rate floor | 120 ms between upstream requests | Premium ~500 req/min ceiling |
| Retry policy | 3 retries per HTTP request on 429/5xx | 429: short backoff (1–3 s) + adaptive 2× interval then recover; 5xx: exp backoff (500 ms base, 8 s cap) + jitter |
| Failure isolation | One dataset's retry/failure never aborts others | `runWithConcurrency` per-item try/catch |

The shared `RateLimiter` (in `src/rate_limit.ts`) chains `acquire()` calls
through a single Promise so the global minimum interval is enforced across
all concurrent fetches. Each dataset's `fetchDataset` invocation gets its own
retry budget (3 retries per page request); exhausting the budget for one
dataset does not consume another's.

The run summary (`/health` → `last_run`) now includes `concurrency` and
`rateLimitMs` so observability can confirm the effective settings.

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
7. **Local-readable path** — ``scripts/sync_d1_to_sqlite.py`` uses the
   operator's authenticated Wrangler session to export private D1 directly,
   then builds a local PIT DB so ``pit.get_*`` reads work offline. No public
   ingestion-premium hostname is required. The cursor-paginated HTTP export is
   retained only as a bounded migration compatibility path.

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
  --wrangler-remote \
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
| ``tests/test_phase35_availability.py`` | Available_at policy rules + cross-language constant agreement |
| ``tests/test_phase35_sync_script.py`` | Sync script offline-safety + live smoke (QP_LIVE=1) |
| ``tests/test_phase35_coverage_matrix.py`` | Validation matrix catalog completeness + daily/weekly tier membership |
| ``tests/test_phase35_coverage_daily.py`` | Daily-tier runner on bars / calendar / master (C12, X4, C8, B2, B4, K3) |
| ``tests/test_phase35_coverage_weekly.py`` | Weekly span / universe checks (C6/C7, B1, X1, X2/X3/X5) |
| ``tests/test_phase35_coverage_cli.py`` | CLI, B0 gates, ingestion_validation honesty, persist-report |

## Validation matrix

Beyond the per-job pass/fail rule in ``cf_platform.ingest_premium.validate``,
Phase 3.5 requires a wider catalog of data-quality checks: history span,
universe coverage, calendar gaps, cross-dataset consistency, addon-leak guard,
etc. The canonical catalog of check IDs (C1–C12, M*, B*, A*, K*, E*, F*, I*,
D*, S*, N*, X1–X5) and their **daily / weekly** execution tiers lives in
``docs/phase35_validation_matrix.md``. The Python mirror — pure data, no I/O —
is ``cf_platform/ingest_premium/matrix.py``; the runnable checks against a
local PIT SQLite DB are in ``cf_platform/ingest_premium/coverage.py``.

Run the matrix against a synced DB:

```bash
# Daily tier (every nightly run): C1–C5, C8, C12, B2, B4, K3, X4
python3 scripts/run_phase35_validation.py \
    --db data/structured/ingestion.sqlite --tier daily

# Weekly tier (full catalog); machine-readable JSON
python3 scripts/run_phase35_validation.py \
    --db data/structured/ingestion.sqlite --tier weekly --json
```

Exit code is ``0`` when no check reports ``status="fail"`` (``skip`` and
``warn`` are tolerated). The runner opens the DB read-only; it never writes.

### Live strict gates

**Live runs must enforce LIVE_GATES** — there is no soft path in
production. The CLI defaults to ``--strict-live-gates`` when
``QP_LIVE=1`` is set; pass ``--no-strict-live-gates`` for one-shot
diagnostic runs only. Strict mode promotes B0 (Phase-4 order-of-magnitude
gates) and the weekly C6/C7/B1/X1 checks from informational metrics to
hard failures. See
[docs/phase35_validation_matrix.md](phase35_validation_matrix.md#live-strict-gates)
for the full strict-vs-soft table.

## Storage scale path (P0-3)

The closed loop today writes every Premium core row to D1
(`jquants_records` + `*_revisions`). For the **scale runway** — R2 bulk
timeseries partitions vs D1 control plane, watermarks, and incremental
local sync — see [docs/phase35_storage_scale.md](phase35_storage_scale.md).
The current migration adds the `ingestion_watermarks` D1 table
(`migrations/0002_watermarks.sql`) and the `--incremental` /
`--since` flags on `scripts/sync_d1_to_sqlite.py`; the parquet dump itself
is documented but **not** yet implemented.

## Phase 3.5 → Phase 4 bridge

The features package reads facts through ``pit.get_*`` from a SQLite DB.
After running the sync script, that DB IS the local mirror of CF D1 — so
features automatically pick up CF-ingested Premium core rows. The closed
loop:

```
J-Quants Premium → CF Worker (cron) → R2 raw + private D1 structured
                       ↓ authenticated Wrangler D1 export
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
