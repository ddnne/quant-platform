# Data contracts

`jquants_premium_core.json` is the canonical PIT/identity/availability contract
for the 23 J-Quants Premium-core datasets and is consumed by Python and the
Cloudflare ingestion runtime.

`collection_coverage.json` is its one-for-one collection/governance sibling.
It defines historical targets, frequency and universe semantics, raw and
structured reconciliation requirements, and an explicit `governed` or
`experimental` tier. Event-driven modes are reconciled by collection window;
the policy never invents a daily row expectation for irregular disclosures.

`jquants_proxy_addons.json` is narrower: it is only the shared exact-path
routing allowlist that preserves the five already catalogued add-on endpoints
through the authenticated GET-only secret proxy. It is **not** a PIT dataset
contract and does not define event-time, availability, or natural-key rules.
