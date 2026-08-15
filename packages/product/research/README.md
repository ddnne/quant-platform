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

## Single-shot job (W49 skeleton · W50 CF execute · W51 tip features · W52 signal)

```python
from research.single_shot_job import (
    COMPLETE_21_DATASETS,
    DEFAULT_CANDIDATE_FEATURES,
    DEFAULT_SIGNAL_ID,
    build_single_shot_job_spec,
    execute_single_shot_job,
    assert_mass_and_phase7_off,
)

# COMPLETE 21 only (permanent DEFER rejected). Output keys are R2, not local SoT.
spec = build_single_shot_job_spec(
    dataset_ids=["equities_bars_daily", "markets_calendar", "indices_bars_daily_topix"],
    period_start="2026-08-01",
    period_end="2026-08-15",
)
assert_mass_and_phase7_off()  # Mass NO-GO · Phase7 OFF · READY not declared

# One CF-backed pass: D1 tip extract → optional candidate features/signal → R2 artifacts.
# dry_run=True stages puts without remote write when R2 credentials missing.
# compute_features=True builds tip FeatureContext (not local SQLite) and writes
# features JSON + manifest feature_id/version/row_counts.
# compute_signals=True writes minimal candidate-only signal under …/signals/.
ex = execute_single_shot_job(
    dataset_ids=["equities_bars_daily", "markets_calendar", "indices_bars_daily_topix"],
    period_start="2026-08-01",
    period_end="2026-08-15",
    job_id="demo-job",
    dry_run=False,
    compute_features=True,
    compute_signals=True,  # signal_id = c21_topix_relative_sign (candidate_only)
    feature_ids=DEFAULT_CANDIDATE_FEATURES,  # volume_change_1d · is_trading_day · topix_relative_1d
)
assert DEFAULT_SIGNAL_ID == "c21_topix_relative_sign"
```

| rule | held |
|------|------|
| Inputs | residual **COMPLETE 21** only (`permanent_defer` excluded) |
| Read | CF D1 `quant-ingest` **hot tip** (bounded; history SoT remains R2) |
| Features | tip `FeatureContext` + COMPLETE-21 min **candidate** features (no local SoT) |
| Signal (W52) | `c21_topix_relative_sign` = sign(topix_relative) × trading-day filter · **candidate_only** · no orders |
| Output path | R2 `quant-structured` · `research/single_shot/job={id}/…` (local **not** SoT) |
| Mass loop | **not** connected (`agents.mass_research` untouched) |
| READY | **not** set |
| Phase7 | **OFF** (foundation only; no arming switches) |
| Order execution | **none** |

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
