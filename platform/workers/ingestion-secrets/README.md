# J-Quants ingestion secret proxy

This Worker keeps `JQUANTS_API_KEY` on Cloudflare and gives an authenticated
local ingestion runner a deliberately narrow proxy capability.

## Authority boundary

- Public `GET /health` reports only whether the key binding exists.
- `POST /v1/proxy/jquants` requires `X-Ingestion-Token` matching the
  `JQUANTS_PROXY_TOKEN` secret.
- The envelope may request only upstream `GET`.
- The target must exactly match a Premium-core path in
  [`data_contracts/jquants_premium_core.json`](../../../data_contracts/jquants_premium_core.json)
  or one of the five existing add-on paths in
  [`data_contracts/jquants_proxy_addons.json`](../../../data_contracts/jquants_proxy_addons.json).
  The Worker imports both JSON sources directly; there is no path list in its
  source. Tests pin the add-on contract to the Python ingestion catalog.
- A generic `/v2/*` prefix is not an authorization policy. New endpoints stay
  denied until added to an explicit shared contract.
- Query values must be strings. Caller headers and credentials are never
  forwarded; the Worker supplies only its bound `x-api-key` upstream.

The client-to-proxy request remains POST because it carries a JSON envelope;
"GET-only" describes the credentialed J-Quants request made by the Worker.
Responses stream through and are marked `no-store`.

## Verify offline

```bash
.venv/bin/python -m pytest -q tests/test_ingestion_secrets_worker_contract.py
npm run typecheck
```

Set secrets with Wrangler; never put their values in source or `wrangler.toml`:

```bash
npx wrangler secret put JQUANTS_API_KEY
npx wrangler secret put JQUANTS_PROXY_TOKEN
```
