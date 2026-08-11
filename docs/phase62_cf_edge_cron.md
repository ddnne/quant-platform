# Phase 6.2 ops-projection scheduling — CF edge cron decision

**Status**: PARTIAL — host-cron production path exists; CF edge cron **intentionally not used** for projection.
**Date**: 2026-08-11
**Scope**: how the Ops MCP projection (coverage / B0 / READY metadata served by
`quant-ops-mcp`) stays fresh without a human running export commands each cycle.

> **Decision.** Ops projection is generated from the **research host's local
> SQLite snapshot** (`data/structured/ingestion.sqlite`) and applied to remote D1
> out-of-band. A Cloudflare Worker `scheduled` handler **cannot** do this cleanly,
> because the Worker has no access to that host DB. The production path is the
> **host cron** (`scripts/cron_publish_ops.sh`). The CF edge cron in
> `ingestion-premium` handles **ingestion only** — a different concern. This split
> is intentional and is the reason the two crons are not merged.

## Why not a CF edge cron for projection

The projection pipeline (`scripts/publish_ops_projection.py`) is, in order:

1. `refresh_coverage_ledger` against the **local** research SQLite DB.
2. `export_ops_projection` — render bounded D1 projection SQL from that same DB
   plus `data/research_snapshots`.
3. `--apply-remote` — `wrangler d1 execute quant-ingest --remote --file=…`.

Every step depends on data that lives on the research host, not on the edge.
Pushing this into a Worker `scheduled` handler would require either:

- **(a)** duplicating the coverage-ledger logic in TypeScript against D1
  directly — large, diverges from the Python source of truth, and risks the
  Worker declaring COMPLETE without the host's receipts; or
- **(b)** the Worker calling back into the host — which is the host cron
  inverted, with strictly worse auth/retry semantics than a host scheduler.

Both are **not clean**. The projection is therefore host-side by design (already
noted in [docs/phase62_production_runbook.md](phase62_production_runbook.md),
"Ops projection cron" section). This document makes that decision first-class.

## Production path — host cron

`scripts/cron_publish_ops.sh` is the production entry point. It:

1. refreshes the coverage ledger (honest PARTIAL/COMPLETE from receipts),
2. publishes the projection (local SQL + meta JSON),
3. optionally applies remote when `APPLY_REMOTE_OPS=1` and `wrangler` CF auth is present.

It **never** declares Coverage COMPLETE on its own — it only republishes whatever
the ledger reports.

### Preconditions

- Research host with the local SQLite DB at `data/structured/ingestion.sqlite`
  (override via `OPS_DB`).
- A Python interpreter (default `PYTHON=$ROOT/.venv/bin/python`).
- For remote apply: `CLOUDFLARE_API_TOKEN` / `wrangler` login with D1 write on
  `quant-ingest`, and `APPLY_REMOTE_OPS=1`.
- The `quant-ops-mcp` worker deployed with migration `0003` and the 16 read tools.

### "No human flag" wiring

Once the crontab/launchd entry sets `APPLY_REMOTE_OPS=1`, each run is fully
automatic — no per-run human flag. The flag is a **per-install** opt-in (remote
write to production D1), not a per-run gate.

### cron (portable)

```cron
# Ops projection refresh + remote apply, hourly at minute 7 (off the :00 mark).
7 * * * * APPLY_REMOTE_OPS=1 /path/to/quant-platform/scripts/cron_publish_ops.sh \
  >> /path/to/quant-platform/.glm-logs/ops-cron/cron.log 2>&1
```

### launchd (macOS — the research host is darwin)

`~/Library/LaunchAgents/com.quant-platform.ops-projection.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.quant-platform.ops-projection</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/quant-platform/scripts/cron_publish_ops.sh</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>APPLY_REMOTE_OPS</key><string>1</string>
    <key>OPS_DB</key><string>/path/to/quant-platform/data/structured/ingestion.sqlite</string>
  </dict>
  <key>StartCalendarInterval</key><dict><key>Minute</key><integer>7</integer></dict>
  <key>StandardOutPath</key><string>/path/to/quant-platform/.glm-logs/ops-cron/launchd.out.log</string>
  <key>StandardErrorPath</key><string>/path/to/quant-platform/.glm-logs/ops-cron/launchd.err.log</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
```

```bash
launchctl load -w ~/Library/LaunchAgents/com.quant-platform.ops-projection.plist
launchctl list | grep quant-platform   # confirm loaded
```

Logs land under `OPS_LOGDIR` (default `.glm-logs/ops-cron/publish_<stamp>.log`).

## CF edge cron — what it *does* cover (ingestion, separate)

`platform/workers/ingestion-premium/wrangler.toml` carries the edge cron:

```toml
[triggers]
crons = ["15 * * * *"]
```

handled by the Worker's `scheduled()` method (`src/index.ts`). This pulls source
data **into** D1. It is intentionally separate from projection publish, which
runs against the host's research snapshot **after** sync. Do not merge the two.

## Failure and restart rules

- A failed refresh must **not** block publish: `cron_publish_ops.sh` tolerates a
  refresh failure (`|| true`) and still publishes the last-known ledger truth.
- A failed remote apply leaves `projection_status = "AVAILABLE"` (not
  `APPLIED_REMOTE`); the next successful run flips it back.
- A missing projection surfaces as `UNKNOWN` plus every governed gap on the Ops
  MCP — never as a false COMPLETE.
- Remote apply requires wrangler CF auth; without it, run with `APPLY_REMOTE_OPS`
  unset to publish locally only.

## Verification

```bash
# 1. Dry run — renders SQL + meta, writes nothing remote.
.venv/bin/python scripts/publish_ops_projection.py --dry-run

# 2. One-shot host run (no remote).
./scripts/cron_publish_ops.sh

# 3. One-shot host run with remote apply.
APPLY_REMOTE_OPS=1 ./scripts/cron_publish_ops.sh

# 4. Confirm the remote Ops MCP sees fresh projection.
curl -i "$QUANT_OPS_MCP_URL/mcp" \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/call",
           "params":{"name":"ops_status","arguments":{}}}'
```

## Honest status

- [x] Host cron script production-ready: `scripts/cron_publish_ops.sh`
- [x] Optional remote apply with explicit per-install opt-in (`APPLY_REMOTE_OPS=1`)
- [x] Decision recorded: CF edge cron not used for projection (this doc)
- [x] CF ingestion edge cron unchanged and separate (`ingestion-premium`)
- [ ] Operator wires the crontab/launchd entry on the research host (human/ops)
- [ ] `APPLY_REMOTE_OPS=1` confirmed in the production install

This item is **PARTIAL / host-only**, matching
[docs/phase62_residual_status.md](phase62_residual_status.md). It is not a CF
edge cron, and that is by design.
