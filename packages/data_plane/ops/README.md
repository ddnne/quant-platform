# ops

Ops control-plane helpers: backfill planning, range batch scheduling, projection metadata.

## Public entry

```python
from ops import (
    BackfillPlanner,
    BackfillPlan,
    BackfillJob,
    RangeBatchScheduler,
    SchedulerConfig,
    TRACK_A_DATASETS,
    plan_and_queue,
)
```

CLI drivers live under `scripts/` and `scripts/ops/` (e.g. Track A dry-run).

## Allowed imports

- `data_contracts`
- `ingestion` (catalog / dataset identity for planners)

## Forbidden

- Arming Mass / READY / Phase7
- Wrangler deploy side effects inside library code
- Inventing COMPLETE segments

Live residual: [docs/phase62_residual_status.md](../../../docs/phase62_residual_status.md).
