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

The future production Trader v2 wire contract is separately frozen. Its
audit-only compiler derives a deterministic pre-approval subject from unsigned
READY claims; a distinct positive entrypoint accepts only the unavailable
`VerifiedPilotReadinessV2` capability. The structural envelope binds governed
RP and credential evidence, canonical WebAuthn bytes, one atomic one-use and
counter transaction, and the shared append-only `authority-event/v2` shape.
The final lifetime is derived exactly from the committed authority observation
and bound challenge expiry. A sequence-independent decision/idempotency key
gives the future store one atomic uniqueness key for retries and ledger reuse.
The former unsigned `TraderAuthorizationClaimsV2` remains only for historical
result-manifest replay and cannot satisfy the positive Trader or controlled
execution gates. No governed CSPRNG challenge generator, active RP/credential
registry, signature verifier, transactional ledger, authority event store, or
controlled v2 consumer is provisioned, so Trader v2 remains unconditionally
`PENDING`.

## Allowed imports

- `strategies`, `features`, `agents`, `paper_runtime`

## Forbidden

- Market HTTP (`ingestion`)
- Broker / live order paths
- Local creation or persistence of controlled PAPER evidence
- Local creation of controlled Risk, Selection, or Knowledge evidence
- Caller-supplied Controlled paths, stores, verifiers, sockets, or transports

Known cycle: `agents` ↔ `execution` (intentional).
