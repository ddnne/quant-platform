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

`OfflineFixturePaperService` may execute and persist DRAFT experiments, but is
not used by the Controlled path. The importable DRAFT runtime rejects
`Lifecycle.PAPER`; `ControlledPilotExecutionService` is a local PENDING facade; Controlled Paper runs only in research-mass-eval Worker/Container.

Paper-only Controlled Pilot trust is the existing Cloudflare/READY publication
root, content-addressed R2 snapshot, typed Service Binding / public-key
verification, budget, and one-shot policy. Local six-principal OS custody,
Trader WebAuthn, external-anchor, quiescence, and staged canary are deferred
to a future live-order ADR and are not required for Pilot acceptance.

The isolated Controlled verify-only loader binds one signed, content-addressed
Paper → Risk → Selection → Knowledge bundle to the same READY snapshot,
plan/closure, resolved universe, StrategySpec, period, cost scenario and gross
limit. Loading that evidence does not authorize execution or promotion. The
pinned writer registry has zero active keys, so verification currently reports
`UNKNOWN: CONTROLLED_ARTIFACT_AUTHORITY_UNPROVISIONED`.

Local six-principal OS custody, Trader WebAuthn, external-anchor, quiescence,
and staged canary are not in this working tree. Git history is the archive.

## Allowed imports

- `strategies`, `features`, `agents`, `paper_runtime`

## Forbidden

- Market HTTP (`ingestion`)
- Broker / live order paths
- Local creation or persistence of controlled PAPER evidence
- Local creation of controlled Risk, Selection, or Knowledge evidence
- Caller-supplied Controlled paths, stores, verifiers, sockets, or transports

Known cycle: `agents` ↔ `execution` (intentional).
