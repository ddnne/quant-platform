# execution

Offline DRAFT execution plus a fail-closed Controlled Pilot boundary.

## Public entry

```python
from execution import (
    ControlledArtifactAuthorityPending,
    ControlledPilotExecutionService,
    ControlledPilotPending,
    OfflineFixturePaperService,
    load_verified_controlled_execution_artifacts,
)
```

`OfflineFixturePaperService` may execute and persist DRAFT experiments. The
importable runtime rejects `Lifecycle.PAPER`. `ControlledPilotExecutionService`
has a zero-argument, no-I/O surface and reports
`PENDING: CONTROLLED_AUTHORITY_UNPROVISIONED` until a separately permissioned
authority and pinned protocol are implemented.

The product has no controlled artifact writer. A future separately
permissioned authority must return one signed, content-addressed
Paper → Risk → Selection → Knowledge bundle. The verify-only loader binds all
four artifacts to the same exact Trader authorization, READY snapshot,
plan/closure, resolved universe, StrategySpec, period, cost scenario and gross
limit. It requires the authority-returned bytes for exactly those four stages,
hashes them against every signed content digest, and retains the immutable
verified bytes. The returned value is evidence only: loading it, including a
repeat load, does not authorize execution or promotion. Its dedicated pinned
writer registry intentionally has zero active keys, so verification currently
reports
`UNKNOWN: CONTROLLED_ARTIFACT_AUTHORITY_UNPROVISIONED`.

## Allowed imports

- `strategies`, `features`, `agents`, `paper_runtime`

## Forbidden

- Market HTTP (`ingestion`)
- Broker / live order paths
- Local creation or persistence of controlled PAPER evidence
- Local creation of controlled Risk, Selection, or Knowledge evidence
- Caller-supplied Controlled paths, stores, verifiers, sockets, or transports

Known cycle: `agents` ↔ `execution` (intentional).
