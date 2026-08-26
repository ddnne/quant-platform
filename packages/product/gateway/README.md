# gateway

Phase 7 offline fixture gateway — **fail-closed** and permanently `DRAFT`.
It is not a production provider exit and cannot produce promotion-eligible output.
Production provider execution goes only through the Cloudflare
`research-ai-gateway` Service Binding and its persistent BudgetLedger Durable
Object.

## Public entry

```python
from gateway import OfflineFixtureAIGateway, GatewayBudget, GatewayResult, GatewaySchemaRejected, OfflineStubProvider
```

`AIGateway` remains a compatibility alias for `OfflineFixtureAIGateway`; it does
not restore a Python production-provider path. Public result evidence includes
`execution_mode=OFFLINE_FIXTURE_DRAFT` and `promotion_eligible=false`.

## Allowed imports

- `agents`, `strategies`, `selection`

## Forbidden

- Treating the Python fixture provider protocol as a production provider exit
- Opening sockets / real remote LLM providers as default
- Market HTTP (`ingestion`)
- Arming Mass research or Phase 7 GO

Guard tests: `tests/test_gateway_fail_closed.py`.
