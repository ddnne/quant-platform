# J-Quants ingestion secret proxy

This Worker keeps `JQUANTS_API_KEY` on Cloudflare. It contains a closed typed
acquisition RPC target for a future Receipt authority and retains the existing
authenticated local-runner HTTP proxy during migration.

## Typed acquisition RPC v2 (target implemented, activation pending)

`IngestionSecretsWorker.fetch_governed_page()` is a `WorkerEntrypoint` method.
It accepts only a governed dataset/closed-month identity, canonical contract
digests, a caller nonce, and an opaque target-minted continuation token. The
target owns the official origin, path, query mode, pagination mapping,
credentials, redirect policy, and target registry. Public HTTP cannot invoke
or tunnel this method.

The reviewed target registry implements eight closed historical month routes:
daily bars, financial summary/details/dividend/earnings-date, TOPIX daily bars,
market calendar, and equities master. Equities master first fetches the official
`/v2/markets/calendar?from=&to=` response with the same bound API credential,
requires an exact row for every calendar date, and selects only `HolDiv` values
`1` and `2`. The exact calendar bytes, query, derived date list, and their
digests are bound into the acquisition identity, HMAC continuation state,
metadata query digest, and page chain. It never derives dates from weekdays.

The registry still deliberately leaves the following closure dependencies
`PENDING`:

- `equities_master` COMPLETE/reproof activation, until a governed production
  Receipt acquisition capability independently captures and create-only
  persists the official calendar bytes. The Python verifier supports that
  opaque evidence, but no production capture writer currently mints it;
- `equities_bars_daily_am` and `equities_earnings_calendar`, until a
  target-owned trading-calendar/session-cutoff authority can derive tip
  identity without trusting a caller date;
- current or partial months, including the just-ended month until 01:00 JST on
  the first day of the next month.

Successful upstream bytes are returned unchanged in the RPC `Response`.
Target-computed headers bind the raw body digest, exact query/segment identity,
provider-page and whole-segment states, and an auditable page chain. Only exact
HTTP 200 JSON with the reviewed top-level envelope and canonical pagination may
be `RAW_PAGE`; non-200 2xx bytes and any parse/schema/pagination uncertainty are
`RAW_ONLY/UNKNOWN`. Redirects, off-contract fields, cursor splicing, and
unbounded or inconsistent continuation state fail closed.

`JQUANTS_RPC_CURSOR_HMAC_KEY` is a dedicated target-only navigation key. Its
HMAC output is not an offline-verifiable receipt or COMPLETE evidence and must
never be shared with the caller/reconciler. A future Receipt authority must
consume the live Service Binding response, create-only persist exact bytes and
metadata, independently reconcile them, and issue its own Ed25519 receipt.
Persisted target headers alone remain `RAW_ONLY` after a crash unless a future
closed verification capability is added.

No live `JQUANTS_ACQUISITION` caller binding, Receipt capture writer, or
production HMAC key is provisioned by this change. Staging intentionally has
zero secret names, so the RPC returns `rpc_unavailable`; production activation,
Receipt-authority capture, receipt signing, registry activation, and historical
reproof all remain `PENDING`. The verifier models the equities-master official
daily slice sequence and provider pagination independently, but it cannot turn
caller-authored paths or headers into a positive capture capability.

## Authority boundary

- Public `GET /health` reports liveness only; it never reports whether any
  secret is bound.
- `POST /v1/proxy/jquants` requires `X-Ingestion-Token` matching the
  `JQUANTS_PROXY_TOKEN` secret.
- The envelope may request only upstream `GET`.
- The target must exactly match a Premium-core path in
  [`packages/data_plane/data_contracts/jquants_premium_core.json`](../../../packages/data_plane/data_contracts/jquants_premium_core.json)
  or one of the five existing add-on paths in
  [`packages/data_plane/data_contracts/jquants_proxy_addons.json`](../../../packages/data_plane/data_contracts/jquants_proxy_addons.json).
  The Worker imports both JSON sources directly; there is no path list in its
  source. Tests pin the add-on contract to the Python ingestion catalog.
- A generic `/v2/*` prefix is not an authorization policy. New endpoints stay
  denied until added to an explicit shared contract.
- Query values must be strings. Caller headers and credentials are never
  forwarded; the Worker supplies only its bound `x-api-key` upstream.
- Authenticated contract calls pass through a fail-closed Cloudflare Rate
  Limiting binding before any upstream request. Workers Logs receive one
  structured event containing route, outcome, status, and duration; request
  bodies, query values, authorization headers, and secret state are excluded.

The client-to-proxy request remains POST because it carries a JSON envelope;
"GET-only" describes the credentialed J-Quants request made by the Worker.
Responses stream through and are marked `no-store`.

Production and preview URLs keep `preview_urls = false`. The production
`workers.dev` hostname must be protected by Cloudflare Access before the
legacy local proxy can be considered closed; enabling Access requires the
account's one-time Zero Trust organization/auth-domain setup.

## Verify offline

```bash
npm run typecheck
npm test
uv run python scripts/generate_jquants_acquisition_registry.py
uv run python scripts/cloudflare_binding_manifest.py
```

`npm test` includes Cloudflare workerd behavior tests and a separate-isolate,
test-only caller-to-target Service Binding harness. The harness proves that
binary `Response` bytes and the fixed metadata header surface cross RPC without
upstream-header passthrough; it does not provision a live caller binding.

Set secrets with Wrangler; never put their values in source or `wrangler.toml`:

```bash
npx wrangler secret put JQUANTS_API_KEY
npx wrangler secret put JQUANTS_PROXY_TOKEN
npx wrangler secret put JQUANTS_RPC_CURSOR_HMAC_KEY
```

The HMAC key must be independently generated and has no fallback to either the
proxy token or API key. Do not provision production secrets into staging.
