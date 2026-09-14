# Data contracts

`jquants_premium_core.json` is the canonical PIT/identity/availability contract
for the J-Quants Premium-core datasets and is consumed by Python and the
Cloudflare ingestion runtime. Membership is the JSON document itself (unique
non-empty dataset ids), not a frozen numeric count.

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

## SourceCapabilityContract v3

`source_capability.py` is the official-availability SoT
(`policy_version = source-capability/v3`). Coverage required inventory,
backfill planning, Ops MCP, and READY profiles must derive from this
contract and must not independently define a history start or coverage
mode that exceeds official provision.

The authoritative JSON documents ship at
`data_contracts/source_capability_contracts/*.json`. The default loader is
package-relative and rejects a missing or incomplete bundled authority;
explicit custom fixture directories retain missing/empty-as-empty behavior.
The loader rejects unknown fields and unknown `history_mode` values.
`required_domain_subset_official(contract)` is the helper later lanes call.
This package does not rewrite `plan_required_segments` and does not invent
COMPLETE.

## Equities valuation (`GET /v2/equities/valuation`)

Official 2026-09-14 Premium endpoint. Catalog, coverage, SourceCapability, and
the date-sliced acquisition target route are registered in source. Registering
the route does not collect data, deploy Workers, or enable READY/Pilot.

- Query: `code` or `date` required; collection uses the existing
  `calendar_month_sliced` `date` + `pagination_key` route.
- `event_time` is session close of `Date`. `available_at` is
  `ingest_time_conservative` (publish is approximately 16:30 JST, not a close
  instant, and vendor overwrites have no ETag/revision). Historical rows are
  observation-time available after ingest; they are not vintage observed PIT.
- Metrics may be null or negative; all-null ETF/ETN rows and REIT MktCap-only
  rows are retained. `MktCap` is million yen excluding treasury shares and must
  not replace `equities_bars_daily` market cap.
- SourceCapability describes bounded history from 2008-07-08 and excludes
  current `core` / `core_historical` / `controlled-pilot` profiles. Strategy
  consumption and historical reconstruction are follow-on after a separately
  held collection/deploy decision.
