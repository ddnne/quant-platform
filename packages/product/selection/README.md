# selection

Phase 7 selection / screening hooks and research budget ledger.

## Public entry

```python
from selection import (
    SelectionDecision,
    DECISIONS,
    ExperimentBudget,
    screen_candidates,
    early_stop,
    ResearchBudgetCapability,
    require_budget_capability,
    BudgetExhaustedError,
    MassResearchDisabledError,
)
```

## Allowed imports

- None required (stdlib / local modules)

## Forbidden

- Market HTTP (`ingestion`)
- Budget without readiness / Mass disabled paths that claim GO
- Direct PIT/SQLite fact reads (use upstream research/paper paths)
