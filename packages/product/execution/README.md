# execution

Authorized paper execution service — sole positive capability that reaches trusted paper runtime from agents.

## Public entry

```python
from execution import PaperExecutionService, PaperExecutionRejected
```

Re-derives authorization fields, verifies pinned snapshot and research-data-profile digest, resolves FeatureRefs, then may call `strategies.paper.run_paper`. Nothing else on the agent path may call `run_paper` directly. `paper_runtime.execution` is a DTO adapter that delegates here.

## Allowed imports

- `strategies`, `features`, `agents`, `paper_runtime`

## Forbidden

- Market HTTP (`ingestion`)
- Broker / live order paths
- Bypassing snapshot / FeatureRef checks

Known cycle: `agents` ↔ `execution` (intentional).
