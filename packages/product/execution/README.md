# execution

Offline DRAFT execution plus a fail-closed Controlled Pilot boundary.

## Public entry

```python
from execution import (
    ControlledPilotExecutionService,
    ControlledPilotPending,
    OfflineFixturePaperService,
)
```

`OfflineFixturePaperService` may execute and persist DRAFT experiments. The
importable runtime rejects `Lifecycle.PAPER`. `ControlledPilotExecutionService`
has a zero-argument, no-I/O surface and reports
`PENDING: CONTROLLED_AUTHORITY_UNPROVISIONED` until a separately permissioned
authority and pinned protocol are implemented.

## Allowed imports

- `strategies`, `features`, `agents`, `paper_runtime`

## Forbidden

- Market HTTP (`ingestion`)
- Broker / live order paths
- Local creation or persistence of controlled PAPER evidence
- Caller-supplied Controlled paths, stores, verifiers, sockets, or transports

Known cycle: `agents` ↔ `execution` (intentional).
