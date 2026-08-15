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

`permanent_defer.py` is the fail-closed list of residual PARTIAL datasets
(W44/W47 lock; **n=4** after W68) that must not be treated as full-history
COMPLETE in research history loaders. W44 `PD-MX-EARN-TIP` / `fins_earnings_date`
tip4 is **superseded by W68 live seal** (tip months COMPLETE; no longer fail-closed).
Remaining: master, earn_cal, bars_am, OTC. See
`docs/proof/complete21_cf_read_paths_20260815.md` §T2 and
`docs/proof/w0816b_w68_complete_delta_close_20260816.md`.
