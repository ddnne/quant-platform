# Data contracts

`jquants_premium_core.json` is the canonical PIT/identity/availability contract
for the 23 J-Quants Premium-core datasets and is consumed by Python and the
Cloudflare ingestion runtime.

`jquants_proxy_addons.json` is narrower: it is only the shared exact-path
routing allowlist that preserves the five already catalogued add-on endpoints
through the authenticated GET-only secret proxy. It is **not** a PIT dataset
contract and does not define event-time, availability, or natural-key rules.
