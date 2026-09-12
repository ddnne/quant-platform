# data_access

Read-domain façade: **research READY** adapter and Ops/READY dispatcher.

Physically under `research_runtime/`. Ops-current SQL and sqlite connections
stay in DataPlane `ops.current_read`; this package composes that owner and
does not open the control database itself.

## Public entry

```python
from data_access import (
    QuantDataAccess,
    QuantDataConfig,
    QuantReadDomainService,
    OpsCurrentReadService,
    ResearchReadyReadService,
)
```

## Allowed imports

- `data_contracts`, `pit`, `storage`
- `features`, `paper_runtime`
- `ops.current_read` (Ops SQL owner)

## Forbidden

- Market HTTP (`ingestion` clients) for callers — ingestion stays the only egress
- Minting Coverage COMPLETE or publishing READY
- Product orchestration (`agents`, `gateway`, …)

Domain doc: [docs/quant_data_access.md](../../../docs/quant_data_access.md).
