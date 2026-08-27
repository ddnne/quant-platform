# Phase 6.2 production runbook — ops projection, backfill status, AM diagnostics

> **HISTORICAL / NON-EXECUTABLE.** Do not run commands from this document.
> The current production runbook is
> [`operations/current_production_runbook.md`](operations/current_production_runbook.md).
>
> **Live residual SoT:** [phase62_residual_status.md](phase62_residual_status.md)  
> (COMPLETE / raw_n / Mass·READY / Phase7 — not this runbook.)  
> **Agent nav:** [architecture/llm_nav_map.md](architecture/llm_nav_map.md)  
> **Do not** launch `cf_premium_backfill` / Mass / READY from runbook prose alone.

This runbook extends Phase 6.1 with Phase 6.2 ops tooling, backfill gap reporting, and aftermarket (AM) dataset diagnostics. It assumes a working Phase 6.1 installation with D1 migrations applied and production credentials configured.

## Preconditions

All Phase 6.1 preconditions apply:

- `INGESTION_RUN_TOKEN`: J-Quants run and natural-key rebuild only.
- `DATA_EXPORT_TOKEN`: bounded D1 export only.
- `CLOUDFLARE_API_TOKEN` / account access: migration and deploy automation.
- A Cloudflare Access human policy or service token for remote MCP smoke.
- Phase 6.1 migrations applied through `0007_ops_projection.sql`.
- `ingestion-premium` worker deployed and `natural_key_migration.state == "READY"`.

## Historical monthly backfill — J-Quants (JQ)

The Worker writes a canonical required segment only when one request covers an exact calendar month. Backfill every month from the earliest governed contract target through the current month.

### Exact monthly backfill commands

For each historical month from 2004-01 through current month, execute:

```bash
# Example: Backfill January 2024
curl -fsS -X POST \
  -H "X-Ingestion-Token: $INGESTION_RUN_TOKEN" \
  "$INGESTION_PREMIUM_URL/v1/run?from=2024-01-01&to=2024-01-31"

# Example: Backfill December 2023
curl -fsS -X POST \
  -H "X-Ingestion-Token: $INGESTION_RUN_TOKEN" \
  "$INGESTION_PREMIUM_URL/v1/run?from=2023-12-01&to=2023-12-31"
```

### Complete historical range

Backfill the full Premium era from 2004-01 through the current month:

```bash
# For each year-month from 2004-01 to current:
YEAR=2004
for MONTH in {01..12}; do
  LAST_DAY=$(cal $MONTH $YEAR | awk 'NF {DAYS = $NF}; END {print DAYS}')
  curl -fsS -X POST \
    -H "X-Ingestion-Token: $INGESTION_RUN_TOKEN" \
    "$INGESTION_PREMIUM_URL/v1/run?from=${YEAR}-${MONTH}-01&to=${YEAR}-${MONTH}-${LAST_DAY}"
done
```

After historical months, execute one unfiltered current run:

```bash
curl -fsS -X POST \
  -H "X-Ingestion-Token: $INGESTION_RUN_TOKEN" \
  "$INGESTION_PREMIUM_URL/v1/run"
curl -fsS "$INGESTION_PREMIUM_URL/health"
```

Require `failed == 0` and all 23 Premium datasets successful.

## Historical monthly backfill — JSDA

Install the source-format readers and use the same mutable staging database:

```bash
.venv/bin/pip install -e '.[jsda]'

# 公社債店頭売買参考統計値: official archive, 2002 through current.
.venv/bin/python scripts/run_ingestion_once.py \
  --source jsda --jsda-dataset otc-reference \
  --jsda-from-year 2002 \
  --db data/structured/ingestion.sqlite --data-dir data

# 東京レポ・レート: authoritative JSDA-era trrts.xls, 2012-10-29 onward.
.venv/bin/python scripts/run_ingestion_once.py \
  --source jsda --jsda-dataset tokyo-repo \
  --db data/structured/ingestion.sqlite --data-dir data

# Corporate bond transactions (governed dataset in change-set 12)
.venv/bin/python scripts/run_ingestion_once.py \
  --source jsda --jsda-dataset corporate-transactions \
  --db data/structured/ingestion.sqlite --data-dir data
```

Do not convert or skip authoritative `.xls`; the governed runner parses it with `xlrd`. A missing official link/year/day is an explicit PARTIAL source gap.

## Backfill status reporting

Use the dedicated backfill status report to summarize gaps vs contracts:

```bash
.venv/bin/python scripts/backfill_status_report.py \
  --db data/structured/ingestion.sqlite \
  --snapshot-dir data/research_snapshots
```

This reports:
- Contract coverage (governed vs experimental)
- Missing historical segments by dataset
- Observed vs expected start/end dates
- Receipt completeness (raw retention, pagination exhaustion)

## AM dataset diagnostics — equities_bars_daily_am

The AM dataset (`equities_bars_daily_am`) has `historical_start: "2024-01-04"` and may show null `observed_end` before data is ingested. Use the ops status with AM diagnostics:

```bash
.venv/bin/python scripts/ops_status.py \
  --snapshot-dir data/research_snapshots \
  --json | jq '.coverage_gaps[] | select(.dataset == "equities_bars_daily_am")'
```

The diagnostic will report:
- `observed_start`: First AM event time (may be null if no data)
- `observed_end`: Latest AM event time (may be null if no data)
- `row_count`: Number of AM records
- `status`: One of COMPLETE, PARTIAL, STALE, UNKNOWN, FAILED

AM data is only available from 2024-01-04 onward. Null dates before that period are expected — not an error.

## Sync and publish ops projection

The former direct projection-D1 mutation and deploy commands have been removed.
This document is historical and non-executable, and the old example also named
the ingestion source database rather than the isolated projection database.
Use the current production runbook; publication remains PENDING until the
dedicated Ops projection authority is provisioned and accepted.

## Remote MCP ops verification

After deploy, smoke the remote Ops MCP endpoint:

```bash
curl -i "$QUANT_OPS_MCP_URL/mcp" \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl-smoke","version":"1"}}}'
```

The unauthenticated response must be `401`. Authenticated calls should succeed and tools/list must contain exactly 16 Ops read tools (inventory, projection, SLA).

## Failure and restart rules

- A failed month/year/source-file is retried at the same segment scope.
- A correction never rewrites an earlier PIT view.
- A missing projection returns UNKNOWN and every governed gap.
- If AM `observed_end` is null but `row_count > 0`, check data quality — AM data may be sparse.
- AM null dates before 2024-01-04 are expected — not an error.

## Ops projection cron (local / host)

> Decision record and full launchd/cron wiring:
> [docs/phase62_cf_edge_cron.md](phase62_cf_edge_cron.md). CF edge cron is
> intentionally **not** used for projection — it is generated from the host SQLite
> snapshot. The CF ingestion cron (`ingestion-premium`) is a separate concern.

```bash
# every hour (example)
0 * * * * cd /path/to/quant-platform && APPLY_REMOTE_OPS=1 ./scripts/cron_publish_ops.sh
```

- Default does **not** apply remote unless `APPLY_REMOTE_OPS=1`.
- Requires working local DB; remote apply needs `wrangler` CF auth.
- Does **not** auto-declare Coverage COMPLETE — only republishes ledger truth.
- CF Worker cron for ingestion is separate (`ingestion-premium` hourly); projection
  publish is intentionally host-side so D1 projection SQL can be generated from
  the research SQLite snapshot after sync.
