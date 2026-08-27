# gateway

Phase 7 offline fixture gateway — **fail-closed** and permanently `DRAFT`.
It is not a production provider exit and cannot produce promotion-eligible output.
Production provider execution goes only through the Cloudflare
`research-ai-gateway` Service Binding and its persistent BudgetLedger Durable
Object.

## Public entry

```python
from gateway import OfflineFixture, OfflineFixtureAIGateway, GatewayBudget, GatewayResult, GatewaySchemaRejected
```

`AIGateway` remains a compatibility alias for `OfflineFixtureAIGateway`; both
accept only the exact frozen, data-only `OfflineFixture` type. Structural
providers, callables, subclasses, and live-provider adapters are rejected at
runtime. Failure cases use closed fixture modes rather than executable test
providers. This does not restore a Python production-provider path. Public
result evidence includes `execution_mode=OFFLINE_FIXTURE_DRAFT` and
`promotion_eligible=false`.

After fixture execution starts, exact measured usage—or the reserved prompt
estimate when usage is unavailable—is settled once to both the volatile helper
and persistent `ResearchBudgetCapability` before schema decoding. Rejected
schemas and already-started failures therefore cannot erase usage. Persistent
audit is two-phase: the provider charge trigger is committed first, then one
idempotent terminal outcome (`success`, `schema_reject`, `provider_error`,
`invalid_usage`, or `actual_overage`) is finalized without charging again.

## Allowed imports

- `agents`, `strategies`, `selection`

## Forbidden

- Treating the Python fixture provider protocol as a production provider exit
- Opening sockets / real remote LLM providers as default
- Market HTTP (`ingestion`)
- Arming Mass research or Phase 7 GO

Guard tests: `tests/test_gateway_fail_closed.py`.
