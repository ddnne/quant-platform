# research

Phase 7 research control plane: readiness attestation, experiment plans, evaluation harness.

## Public entry

```python
from research import (
    ResearchReadinessService,
    VerifiedResearchReadiness,
    require_mass_research_start,
    MassResearchDisabledError,
    ExperimentPlan,
    ExperimentScheduler,
    EvaluationHarness,
    # …
)
```

Mass start is **fail-closed** without `VerifiedResearchReadiness`; operator override is rejected.

## Allowed imports

- `selection`, `paper_runtime`

## Forbidden

- Market HTTP (`ingestion`)
- Claiming Mass ON without residual + proof
- Direct fact SQLite from research orchestration

See [docs/architecture/phase7_fail_closed.md](../../../docs/architecture/phase7_fail_closed.md).
