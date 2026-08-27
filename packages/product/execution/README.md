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
`Lifecycle.PAPER`; `ControlledPilotExecutionService` remains a zero-argument
PENDING facade and cannot launch the authority implementation.

The isolated Controlled implementation returns one signed, content-addressed
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

The live handler has no executor argument. Root activation fixes an
AF_UNIX provider peer UID/socket, a protected BudgetLedger, and read-only
immutable snapshot/projection paths. The loader opens activation, key, snapshot,
and projection through `O_NOFOLLOW` file descriptors and validates every trusted
directory component. Live snapshot/projection files must be distinct,
single-link, root-owned read-only regular files; their retained descriptors are
rehashed after provider return and again immediately before commit. After it
independently consumes a Trader handoff, it
derives the READY resource digest again from the pinned snapshot/projection,
persists a worst-case budget reservation and lease, then passes those immutable
FDs to the provider. Provider output is bytes-only and is revalidated against
the exact-four result schemas before the artifact transaction commits.

Budget states are durable: `RESERVED → EXECUTING → SUCCEEDED|FAILED`; a crash
after a provider call becomes `RECOVERY_REQUIRED`, blocks new work, and has a
conservative no-retry settlement path. A successful kernel-peer-authenticated
provider response must include closed canonical usage evidence bound to the
reservation, idempotency key, pinned resources, and returned artifact digests;
the ledger releases the estimate and charges the verified actual counters.
Provider failure without trustworthy usage is charged at the reserved maximum.
Success, provider error, timeout, schema reject, and commit error all settle
exactly once. No production provider or AI Gateway usage-evidence endpoint is
provisioned, and the checked-in activation is still absent, so none of this
executes a Pilot.

The production Trader v2 wire contract is frozen and implemented but inactive.
Its authority-server handler accepts only server-minted peer context, a signed
environment/resource-scoped READY response, and a real WebAuthn assertion. It
binds governed RP and credential evidence, canonical WebAuthn bytes, one atomic
challenge/counter/event transaction, and the shared append-only
`authority-event/v2` shape. The Controlled authority independently revalidates
the handed-off bytes and peer UID; product code cannot mint a reusable positive
Trader capability.

Enrollment is also fail-closed. The CLI records a CSPRNG challenge in a durable,
expiring one-use SQLite ledger and prints browser/OS creation parameters. Its
proposal command accepts only a raw WebAuthn registration response: it verifies
`clientDataJSON`, parses `attestationObject` and authenticator-data CBOR, checks
RP hash plus the UP/UV flags, derives an exact COSE ES256 public key, and binds
the verified transcript digest into the root activation proposal. Because
`fmt=none` has no trusted attestation root, the proposal keeps
`human_enrollment_observed=false`; a root reviewer must observe the human
ceremony before changing it. Caller-supplied SPKI,
counter, or human-presence claims have no enrollment path. The browser/OS prompt
is the sole external human-presence step; no private credential is obtained.

Both environments remain `PENDING`: checked-in registries have no active live
credential, protected principals/stores are not observed, and the strict P0
gate blocks every positive operation. Enrollment/bootstrap may prepare a
root-review proposal, but cannot activate Trader, Controlled Pilot, promotion,
Mass Research, or live trading.

## Allowed imports

- `strategies`, `features`, `agents`, `paper_runtime`

## Forbidden

- Market HTTP (`ingestion`)
- Broker / live order paths
- Local creation or persistence of controlled PAPER evidence
- Local creation of controlled Risk, Selection, or Knowledge evidence
- Caller-supplied Controlled paths, stores, verifiers, sockets, or transports

Known cycle: `agents` ↔ `execution` (intentional).
