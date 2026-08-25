# quant-platform-ingestion-jsda

Cloudflare Worker for **JSDA raw acquisition** (3 governed series).

## Why this exists

JSDA sources are **public HTTP** (no API key). They are not blocked from Cloudflare
egress. What was missing was a Worker — Python `ingestion/jsda/` historically ran
local-only (XLS/XLSX via xlrd/openpyxl; polite scraping).

## v2 acquisition graph

- Daily cron + manual `POST /v1/run` (auth: `INGESTION_RUN_TOKEN`) enqueue
  daily stable `discover_root` jobs.
- Root discovery persists its frontier, then creates `discover_year` and
  `fetch_file` children. Fetch identity is a three-part contract: stable
  `SourceObject` URL, D1-owned monotonic `Observation` sequence, and
  content-addressed `Artifact` digest with a separate R2 location join.
  Dated archive URLs keep one observation; rolling current-year URLs are
  re-observed per governed run. `current_*` on a SourceObject advances only
  by compare-and-set when the candidate sequence is strictly newer.
- Each delivery advances at most 25 children and enqueues a continuation,
  so the archive converges without a latest-year or file-count cap.
  Exhausting a discovery frontier is `waiting_children`, not terminal
  success. The parent and `jsda_run_closures` row become completed only
  after every governed descendant is durably successful; a rejected
  descendant fails the run. Cron re-enqueue repairs an incomplete ancestor
  aggregate instead of skipping it.
- D1 is authoritative for job, source-object, observation, artifact,
  location, and run-closure state. A duplicate cron or Queue delivery cannot
  reacquire a completed observation, and a completed rolling observation
  does not permanently complete its URL.
- Raw artifacts and Queue audit receipts are create-only, content-addressed R2
  objects. A delivery is acknowledged only after its audit receipt and D1/run
  evidence are durable.
- Invalid messages are written to both R2 audit and `jsda_queue_rejects_v2`
  before acknowledgement. Evidence-write failures retry and eventually reach
  the configured DLQ.
- Initial URLs, discovered links, and every post-redirect URL are restricted to
  the official JSDA HTTPS host allowlist.

## Not yet

- Structured parse of `.xls`/`.xlsx` into D1 fact tables
- Coverage COMPLETE / READY proof issuance. Raw acquisition is evidence input;
  it cannot mint research-readiness evidence.

Until structured parse lands on CF (or a sync path from R2 raw → local/CF structured),
governed JSDA completeness still depends on the Python pipeline reading raw (local or
exported from R2).

## Deploy

```bash
cd platform/workers/ingestion-jsda
npm install
npm test
npx wrangler queues create quant-jsda-ingestion
npx wrangler queues create quant-jsda-ingestion-dlq
printf '%s' "$INGESTION_RUN_TOKEN" | npx wrangler secret put INGESTION_RUN_TOKEN
npx wrangler deploy
```

Apply `ingestion-premium/migrations/0012_jsda_observation_identity.sql` through
the canonical `quant-ingest` migration owner before deploying this Worker.

Production uses `quant-jsda-ingestion` and `quant-jsda-ingestion-dlq`.
Staging uses the distinct `quant-jsda-ingestion-staging` and
`quant-jsda-ingestion-dlq-staging` queues defined in `wrangler.staging.toml`.
No Worker consumes the DLQ automatically: inspect and replay it operationally
after correcting the underlying cause.
