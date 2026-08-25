# Phase 6.1 production backfill, READY, and remote MCP runbook

> **Live residual SoT:** [phase62_residual_status.md](phase62_residual_status.md)  
> (COMPLETE / raw_n / Mass·READY / Phase7 — not this runbook.)  
> **Agent nav:** [architecture/llm_nav_map.md](architecture/llm_nav_map.md)

This runbook turns the Phase 6.1 code path into a production generation. A
green offline suite proves the implementation; it does not prove that live
J-Quants/JSDA history, Cloudflare bindings, Access policy, or a READY artifact
exist. Record command output and UTC/JST timestamps in the operations log.

## 1. Preconditions and recovery point

Required credentials are deliberately separate:

- `INGESTION_RUN_TOKEN`: J-Quants run and natural-key rebuild only.
- `DATA_EXPORT_TOKEN`: bounded D1 export only.
- `CLOUDFLARE_API_TOKEN` / account access: migration and deploy automation.
- A Cloudflare Access human policy or service token for remote MCP smoke.

Do not print token values. Check only presence and Wrangler identity:

```bash
test -n "${INGESTION_RUN_TOKEN:-}" && echo INGESTION_RUN_TOKEN=present
test -n "${DATA_EXPORT_TOKEN:-}" && echo DATA_EXPORT_TOKEN=present
test -n "${CLOUDFLARE_API_TOKEN:-}" && echo CLOUDFLARE_API_TOKEN=present
npx wrangler whoami
```

Stop if the production D1 database/bucket names or IDs differ from the
reviewed Wrangler files. Back up the mutable local staging DB before opening it
with the new code. READY artifacts are immutable and are never migrated in
place.

```bash
mkdir -p data/backups
cp -p data/structured/ingestion.sqlite \
  "data/backups/ingestion-pre-phase61-$(date -u +%Y%m%dT%H%M%SZ).sqlite"
```

## 2. Apply migrations in order

Opening `SqliteStore` applies every unapplied local migration transactionally:

```bash
.venv/bin/python -c \
  'from storage.sqlite_store import SqliteStore; s=SqliteStore("data/structured/ingestion.sqlite"); s.close()'
sqlite3 data/structured/ingestion.sqlite \
  'SELECT version,name FROM schema_migrations ORDER BY version;'
```

Apply D1 migrations in filename order. Migration `0005` intentionally closes
J-Quants writes/exports until the application rebuild reaches READY.

```bash
cd platform/workers/ingestion-premium
for migration in migrations/000{1,2,3,4,5,6,7}_*.sql; do
  npx wrangler d1 execute quant-ingest --remote --file="$migration" || exit 1
done
```

Deploy ingestion-premium, rebuild v2 natural keys, then verify READY before
starting an ingest or export:

```bash
npx wrangler deploy
curl -fsS -X POST \
  -H "X-Ingestion-Token: $INGESTION_RUN_TOKEN" \
  "$INGESTION_PREMIUM_URL/v1/admin/rebuild-natural-keys-v2"
curl -fsS "$INGESTION_PREMIUM_URL/health"
```

The health response must contain `natural_key_migration.state == "READY"`.
Do not bypass this gate or rebuild natural keys with ad-hoc SQL.

Apply the isolated Ops projection and quota schemas. The Ops Worker must never
run a migration against `quant-ingest`; ingestion-premium is its sole owner:

First verify the canonical owner/checksum inventory. Its source-controlled
`applied_state` is deliberately `UNVERIFIED`; record actual remote state only in
the immutable release evidence after each apply.

```bash
.venv/bin/python scripts/cloudflare_d1_migration_manifest.py
```

```bash
cd ../quant-ops-mcp
npx wrangler d1 migrations apply quant-ops-projection --remote \
  --config=wrangler.toml
npx wrangler d1 migrations apply quant-ops-quota --remote \
  --config=wrangler.toml
cd ../../..
```

All migration files are idempotent, but do not reorder them.

## 3. J-Quants Coverage V2 backfill

The Worker writes a canonical required segment only when one request covers an
exact calendar month. Cross-month and partial-month requests are useful for
diagnostics but cannot make that month COMPLETE. Backfill every month from the
earliest governed contract target through the current month. Each request runs
all 23 Premium-core datasets and is safe to retry; completed receipt/segment
state remains auditable.

For each month, substitute the first and last calendar dates:

```bash
curl -fsS -X POST \
  -H "X-Ingestion-Token: $INGESTION_RUN_TOKEN" \
  "$INGESTION_PREMIUM_URL/v1/run?from=YYYY-MM-01&to=YYYY-MM-DD"
```

After historical months, execute one unfiltered current run. This must be a
23-dataset pass and supplies the current run-level validation/raw manifest
evidence retained from Phase 6:

```bash
curl -fsS -X POST \
  -H "X-Ingestion-Token: $INGESTION_RUN_TOKEN" \
  "$INGESTION_PREMIUM_URL/v1/run"
curl -fsS "$INGESTION_PREMIUM_URL/health"
```

Require `failed == 0`. A receipt with incomplete pagination, failed raw
retention, or a raw/structured mismatch cannot complete its segment.

## 4. JSDA governed backfills

Install the source-format readers and use the same mutable staging database.
These runners save official index/file bytes before parsing, write checksums,
URLs, fetch times and Coverage V2 receipts, and resume exact COMPLETE scope.

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
```

Do not convert or skip authoritative `.xls`; the governed runner parses it
with `xlrd`. A missing official link/year/day is an explicit PARTIAL source
gap. The contract documents the separate BoJ legacy era rather than silently
claiming it as JSDA coverage.

Re-run with `--jsda-force` when an official correction is announced. Changed
content for the same natural key must create a revision whose `available_at`
is no earlier than the known correction publication time, or the conservative
ingest time when the publication timestamp is unknown. Verify the old `as_of`
still returns the earlier value before proceeding.

The corporate-bond transaction command is added with its distinct governed
dataset in change-set 12; use the exact CLI shown by `--help` after that
change-set is landed. Never substitute the legacy combined `jsda` pass as
evidence for this dataset.

## 5. Inspect coverage and raw evidence

Coverage must list every governed JQ and JSDA dataset, with no gaps. Min/max
bounds are diagnostics only; inspect the required segment and selected receipt
counts.

```bash
.venv/bin/python - <<'PY'
from data_contracts import all_coverage_contracts
from storage import coverage_gaps, coverage_summary

db = "data/structured/ingestion.sqlite"
governed = [c.dataset_id for c in all_coverage_contracts()
            if c.governance_tier == "governed"]
print({"governed": len(governed), "summary": coverage_summary(db),
       "gaps": coverage_gaps(db)})
PY
```

Every COMPLETE segment must reference one successful receipt with:

- exact segment start/end/scope and expected items;
- `pagination_exhausted=1`;
- at least one retained raw page and a raw digest;
- raw/structured row reconciliation;
- no error.

Event windows may legitimately reconcile 0 raw rows to 0 structured rows. A
random early/late fact row cannot replace this receipt proof. Preserve raw
objects/files according to the receipt digest/path or R2 manifest key; never
delete raw evidence while a READY artifact references its proof.

## 6. Sync and publish the first full governed READY

The full sync pulls J-Quants facts/control evidence into the mutable local DB.
It preserves locally ingested JSDA tables and receipts. The sync publishes only
after all governed contracts pass Coverage V2, strict JQ B0/daily validation,
raw evidence, natural-key state, and immutable manifest checks.

```bash
.venv/bin/python scripts/sync_d1_to_sqlite.py \
  --wrangler-remote \
  --db data/structured/ingestion.sqlite \
  --snapshot-dir data/research_snapshots

.venv/bin/python scripts/ops_status.py \
  --snapshot-dir data/research_snapshots --json
```

Require all of the following before announcing production READY:

- sync exit 0 and no skipped/failed required table;
- latest J-Quants run is a complete 23-dataset pass;
- all governed coverage segments and receipts are COMPLETE;
- B0/quality and validation are PASS;
- `latest-ready.json` resolves to a content-addressed `0444` SQLite artifact;
- opening the READY artifact re-verifies its Coverage V2 proof digest.

A targeted `--table` sync intentionally cannot publish READY.

## 7. Project Ops metadata and deploy remote MCP

The projection contains generation-scoped coverage, segment, B0, READY,
authoritative raw-segment, sync-cursor, and materialized storage metadata. The
Worker reads only the active immutable generation from `OPS_PROJECTION_DB`;
quota writes go only to `QUOTA_DB`.

Remote publication additionally requires a dedicated Ops Projection Ed25519
private key and key id. Provision its public key in both
`specs/ops_projection/verify_public_keys.json` and the Worker's
`OPS_PROJECTION_VERIFY_KEYS_JSON`; Receipt and READY keys are not valid here.
An empty/unknown registry keeps every generation `NOT_PROJECTED`.

```bash
.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite \
  --snapshot-dir data/research_snapshots \
  --apply-remote

cd platform/workers/quant-ops-mcp
npm test
npm run typecheck
npx wrangler deploy --dry-run --env=production
npx wrangler deploy --env=production
```

The publisher does not accept cursor or signing-key overrides. It derives both
cursor pins from the latest COMPLETE authenticated D1 sync audit, verifies the
content identity and local applied cursor in one read transaction, and loads
only the dedicated Ops signing configuration.

Before deploy, replace the fail-closed public placeholders in `wrangler.toml`
with the reviewed Access team domain, dedicated Ops application AUD, Managed
OAuth authorization server, and exact browser origins. Keep secrets out of the
file. Configure the Access application exclusively for `quant.read.ops`;
research and write capabilities require different applications/services.

Smoke the deployed endpoint:

```bash
curl -i "$QUANT_OPS_MCP_URL/mcp" \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl-smoke","version":"1"}}}'
```

The unauthenticated response must be `401`. Through the configured
Access/Managed OAuth flow, call `initialize`, `tools/list`, and `ops_status`;
the authenticated smoke must succeed and charge the D1 daily quota. Confirm
that `tools/list` contains exactly the 17 documented Ops reads and no write or
research-row tool. Add the same `/mcp` URL to ChatGPT remote connectors; local
stdio is only the offline/dev adapter.

## 8. Failure and restart rules

- A failed month/year/source-file is retried at the same segment scope. Do not
  delete its failed receipt; the next run adds auditable evidence.
- A correction never rewrites an earlier PIT view. Stop publication if the old
  `as_of` changes.
- A missing projection returns UNKNOWN and every governed gap; it is not an
  empty success.
- A rejected build remains REJECTED. Fix evidence and publish a new generation;
  never mutate an existing READY artifact.
- If credentials are unavailable, stop after offline verification and record
  migrations, backfill, READY, OAuth smoke, and deploy as production gaps.
