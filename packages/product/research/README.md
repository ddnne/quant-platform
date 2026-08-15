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

## Single-shot job skeleton (W49 T8)

```python
from research.single_shot_job import (
    COMPLETE_21_DATASETS,
    build_single_shot_job_spec,
    assert_mass_and_phase7_off,
)

# COMPLETE 21 only (permanent DEFER rejected). Output keys are R2, not local SoT.
spec = build_single_shot_job_spec(
    dataset_ids=["equities_bars_daily", "markets_calendar"],
    period_start="2024-01-01",
    period_end="2024-12-31",
)
assert_mass_and_phase7_off()  # Mass NO-GO · Phase7 OFF · READY not declared
```

| rule | held |
|------|------|
| Inputs | residual **COMPLETE 21** only (`permanent_defer` excluded) |
| Output path | R2 `quant-structured` · `research/single_shot/job={id}/…` (local **not** SoT) |
| Mass loop | **not** connected (`agents.mass_research` untouched) |
| READY | **not** set |
| Phase7 | **OFF** (foundation only; no arming switches) |

Module: [`single_shot_job.py`](single_shot_job.py). Tests: `tests/test_single_shot_research_job.py`, `tests/test_mass_research_gate.py`.

## Allowed imports

- `selection`, `paper_runtime`
- `data_contracts.permanent_defer` (COMPLETE-21 / DEFER guard for single-shot inputs)

## Forbidden

- Market HTTP (`ingestion`)
- Claiming Mass ON without residual + proof
- Direct fact SQLite from research orchestration
- Arming Phase7 / Mass / READY from this package

See [docs/architecture/phase7_fail_closed.md](../../../docs/architecture/phase7_fail_closed.md).
