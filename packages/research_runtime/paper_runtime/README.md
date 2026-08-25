# paper_runtime

Trusted helpers for reproducible paper experiments: READY policy, snapshots, coherence, code fingerprints, experiment index.

Lives **outside** `strategies` so strategy code stays isolated from storage.

## Public entry

```python
from paper_runtime import (
    open_ready_snapshot,
    latest_ready_snapshot,
    check_ready_coherence,
    ExperimentIndex,
    data_snapshot_id,
    strategy_definition_hash,
    # …
)
from paper_runtime.ready_policy import ReadyPublicationPolicy, ReadyEvidenceBundle
from research.ready_manifest import publish_exact_four_pilot_ready_snapshot
```

Production READY publication is exposed only through the plan/profile-bound
exact-four bridge. It returns the immutable snapshot together with the signed
`VerifiedPilotReadiness` sidecar. The generic publisher is private and
test-fixture-only.

## Allowed imports

- `data_contracts`, `storage`, `strategies`, `features`
- `cf_platform` (**documented exception** — coverage / B0 measurement reuse)
- `execution` / `agents` (**documented exception** — `paper_runtime.execution`
  DTO adapter only; imports agents first so the agents↔execution cycle can
  finish, then delegates to `execution.paper_service.PaperExecutionService`;
  does not call `run_paper`)

## Forbidden

- Forging READY without proof / coherence
- Market HTTP (`ingestion`)
- Product gateway / Mass arming

Residual: [docs/phase62_residual_status.md](../../../docs/phase62_residual_status.md).
