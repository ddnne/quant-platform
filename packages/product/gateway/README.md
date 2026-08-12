# gateway

Phase 7 AI Gateway stubs — **fail-closed**. Sole intended LLM exit shape; no production LLM loop in B1.

## Public entry

```python
from gateway import AIGateway, GatewayBudget, GatewayResult, GatewaySchemaRejected, OfflineStubProvider
```

## Allowed imports

- `agents`, `strategies`, `selection`

## Forbidden

- Opening sockets / real remote LLM providers as default
- Market HTTP (`ingestion`)
- Arming Mass research or Phase 7 GO

Guard tests: `tests/test_gateway_fail_closed.py`, `tests/test_phase7_gateway.py`.
