# Cloud resource inventory

Observed 2026-09-23/24 JST using management API metadata and source
`2ea7b14f8272ab7c9a18503408469501ed08661a`. This is a partial audit, not
authorization to delete resources or evidence of zero usage/cost.
No market bodies, secrets, KV values or DLQ messages were read.

| Account resource | Count | Interpretation |
|---|---:|---|
| Workers | 19 | 15 quant-prefixed, 3 news-prefixed, 1 tmp-exp-eval |
| D1 | 7 | 6 quant, 1 news |
| R2 buckets | 7 | 5 quant, 2 news; quant lifecycle/public domains checked, object sizes not inventoried |
| Queues | 4 | JSDA queue and DLQ in each environment |
| KV namespaces | 3 | quant OAuth production/staging and news OAuth |
| DO namespaces | 8 | Not an instance or billing count |
| Container applications | 2 | One production and one staging; both listed instances inactive |
| Pages projects | 0 | Empty API inventory |

## Candidates and dependencies

- `tmp-exp-eval`: no repository reference found; AI binding, no Cron.
  Retirement candidate pending ownership, inbound usage and route checks.
- `quant-platform-jsda-otc-probe-w80`: no bindings or Cron. Its two legacy
  host-local downloader/planner clients are retired by PR #271. Cloud Worker
  deletion still requires checking external consumers and usage; not deleted.
- `quant-platform-ci-aggregate-staging`: retain. Despite its old name, this
  private anchor produces the required native Cloudflare merge check. It is not
  the retired receipt-aggregation API. Two plain-text GitHub settings remain;
  their necessity is not yet established. No Cron.
- Ingestion, Receipt, Gateway and research Workers have source-level service
  dependencies. That explains their present existence, not permanent necessity
  of every separation. Evaluate consolidation against actual data/PIT/budget
  responsibilities, not Worker count alone.
- `news-*`, `news-db`, `news-text`, `news-db-backup` belong to another product;
  absence of quant callers does not authorize removing them.

## Storage and configuration findings

- D1 `quant-ingest-staging`: 8,310,325,248 bytes; production `quant-ingest`:
  752,893,952 bytes. Prioritize legacy duplication/retention analysis and verified
  R2 replacements. No historic data deletion is authorized.
- Both quota databases and production Ops projection report 24,576 bytes each.
  Do not interpret the list API's `num_tables=0` as proof they are empty/unused.
- R2 buckets: news-db-backup, news-text, quant-raw, quant-raw-staging,
  quant-receipt-evidence-staging, quant-structured, quant-structured-staging.
  Production receipt bucket is declared in source but absent from this list.
  Declarations are not live deployment evidence.
- Source declares production Receipt authority and both activation observers;
  these were absent from the live Worker list. Do not count them as idle live
  Workers or deploy them implicitly.
- Source staging JSDA declares a DLQ consumer and rejects queue; live DLQ has
  no consumer and no rejects queue was listed. Record as deployment drift,
  not an invitation to activate a held pipeline.
- DLQs without explicit producers remain referenced by their parent queue's
  dead-letter configuration. Do not treat them as orphaned or pull/purge them.

## Recurring work

Live Cron: production Premium `15 * * * *`, staging Premium `* * * * *`,
production JSDA `30 1 * * *`, staging JSDA none.

The staging Premium scheduler checks bounded control jobs, recovers PREPARED
receipts, checks a per-source/version audit canary, then invokes Ops publication
when its verification key is configured. The canary reuses ATTESTED evidence;
it does not mint a fresh audit row each minute. Nevertheless idle polling and
projection frequency need review. Preserve recovery and freshness requirements
when reducing frequency; no Cron changed by this audit.

`publishOpsProjection` also returns `noop` when the computed generation is
already active and SEALED. Therefore a minute tick does not necessarily create
a new snapshot. However table discovery, bounded source reads/evidence hashing
and the B0/B4 producer occur before that check. Prioritize measuring/reducing
these repeated reads rather than claiming one new artifact per minute. A
shortcut based only on the legacy change cursor would be unsafe: Receipt
publications are explicitly tracked as a separate feed.

## Next work, without user login

### Additional metadata observations (2026-09-24)

All19 Worker settings showed no inbound Service Binding or tail-consumer
reference to either retirement candidate. Workers invocation analytics for
2026-09-16T15:27:04Z through2026-09-23T15:27:04Z returned no invocation rows
for either, with no API errors. The positive-control staging Premium query
returned10,018 requests. This is no observed use during that window, not proof
of no external or dormant client. Neither Worker was disabled or removed.

All five quant R2 buckets have managed r2.dev access disabled and no custom
domains. This rules out direct public bucket domains at observation time,
not unauthenticated access through a Worker or another credentialed interface.
Their only lifecycle rule aborts incomplete multipart uploads after604,800
seconds. No saved-object expiry or tier-transition rule was present; this
is not a seven-day deletion rule for market data.

Source places candidate manifests, publication/state records, compressed and
physical SQLite, and PIT-scope evidence under `research/receipt-candidates/`.
A blanket prefix expiry would therefore risk deleting referenced evidence.
Key definitions do not prove which objects exist. Before retention changes,
inventory object metadata and references, separating reproducible temporary
objects from immutable evidence. No objects were downloaded or deleted.

Linked audit evidence:
https://github.com/ddnne/quant-platform/pull/271#issuecomment-5798484463.
These are metadata observations, not a completed cost or security audit.

### Follow-up live binding/public-surface check

Management settings confirm production Ops MCP still binds `OPS_DB` to
`quant-ingest`; staging Ops MCP binds it to `quant-ingest-staging`. Neither live
MCP settings response lists the newer projection/quota DB bindings declared in
source. This is deployment drift, not proof those newer databases are globally
unused: Premium already uses staging projection. Keep held MCP work held and
do not delete its planned databases based on one consumer.

Production Ops MCP has both workers.dev and preview URLs enabled; staging MCP
has both disabled. Production source declares previews disabled, so this also
needs an explicit release decision. Public URL settings alone do not establish
whether application authentication permits access.

`tmp-exp-eval` and `quant-platform-jsda-otc-probe-w80` each have workers.dev and
preview URLs enabled. The former has an AI binding. Audit authentication and
real usage before a grouped retirement/disable proposal; do not invoke the AI
endpoint merely to test it. No secret values were retrieved.

1. Inventory callers/usage and public routes for retirement candidates.
2. Measure idle scheduled work and separate acquisition/recovery needs from
   projection cadence before proposing a smaller schedule.
3. Review image/object retention and duplicated DB representations using
   metadata; never download authentic history to the host.
4. Inspect redundant CI triggers/logging/settings when their API is available.
   Existing CLI OAuth cannot access Builds (403); do not request user login
   before the user's stated Monday availability.
5. Present destructive changes as one grouped plan with impact and recovery.
   No deletion, production rollout, research execution or new service is part
   of this inventory.
