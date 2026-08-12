# data_access

Read-domain façade: **Ops current** vs **research READY** planes.

Physically under `data_plane/`, but intentionally a **cross-plane read adapter**
(ADR: may import `features` and `paper_runtime`).

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
- `features`, `paper_runtime` (**documented exception**)

## Forbidden

- Market HTTP (`ingestion` clients) for callers — ingestion stays the only egress
- Minting Coverage COMPLETE or publishing READY
- Product orchestration (`agents`, `gateway`, …)

Domain doc: [docs/quant_data_access.md](../../../docs/quant_data_access.md).
