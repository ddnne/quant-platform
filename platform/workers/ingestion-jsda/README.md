# quant-platform-ingestion-jsda

Cloudflare Worker for **JSDA raw acquisition** (3 governed series).

## Why this exists

JSDA sources are **public HTTP** (no API key). They are not blocked from Cloudflare
egress. What was missing was a Worker — Python `ingestion/jsda/` historically ran
local-only (XLS/XLSX via xlrd/openpyxl; polite scraping).

## v0 scope

- Daily cron + manual `POST /v1/run` (auth: `INGESTION_RUN_TOKEN`) enqueue
  closed, typed dataset jobs to Cloudflare Queues
- A bounded Queue consumer resolves each dataset to an internal fixed JSDA URL;
  messages cannot supply URLs or arbitrary acquisition payloads
- Strictly successful discovery is acknowledged; partial, failed, capped, or
  zero-row discovery is retried and eventually routed to the configured DLQ
- Store index HTML + discovered data files to R2 `raw/jsda/{dataset}/...`
- Log runs to D1 `ingestion_run_log` (`source=jsda`, `runtime=cloudflare`)

## Not yet

- Structured parse of `.xls`/`.xlsx` into D1 fact tables
- Coverage V2 COMPLETE / READY proof for JSDA series

Until structured parse lands on CF (or a sync path from R2 raw → local/CF structured),
governed JSDA completeness still depends on the Python pipeline reading raw (local or
exported from R2).

## Deploy

```bash
cd platform/workers/ingestion-jsda
npm install
npx wrangler queues create quant-jsda-ingestion
npx wrangler queues create quant-jsda-ingestion-dlq
printf '%s' "$INGESTION_RUN_TOKEN" | npx wrangler secret put INGESTION_RUN_TOKEN
npx wrangler deploy
```

Production uses `quant-jsda-ingestion` and `quant-jsda-ingestion-dlq`.
Staging uses the distinct `quant-jsda-ingestion-staging` and
`quant-jsda-ingestion-dlq-staging` queues defined in `wrangler.staging.toml`.
No Worker consumes the DLQ automatically: inspect and replay it operationally
after correcting the underlying cause.
