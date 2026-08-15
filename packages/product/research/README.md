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

## Eval harness (W56 stable pipeline · single_shot only)

Preferred public entry for the reusable research pipeline:

```text
signal (approved legs) → multiday → next_day_return eval → R2 batch_summary
```

```python
from research.eval_harness import (
    APPROVED_SIGNAL_LEGS,
    assert_harness_closed,
    require_approved_signal_legs,
    require_harness_datasets,
    run_full_pipeline,          # alias of run_nextday_return_eval
    run_multiday_signal_eval,
    run_nextday_return_eval,
)

assert_harness_closed()  # Mass NO-GO · Phase7 OFF · READY OFF · approved legs
require_harness_datasets()  # COMPLETE 21 only; permanent DEFER hard-reject
require_approved_signal_legs()  # registry status == approved for each leg

# Full pipeline (研究用・未宣言). dry_run stages R2 puts when remote write is off.
ex = run_nextday_return_eval(
    period_start="2026-08-01",
    period_end="2026-08-15",
    job_id="demo-eval-harness",
    codes=["13010", "72030", "67580"],
    dry_run=True,
)
assert ex.attach_nextday_returns is True
assert ex.mass_research == "NO-GO"
assert ex.ready_declared is False
# R2: research/single_shot/job={id}/batch_summary.json (+ per-day signals)
```

| rule | held |
|------|------|
| Inputs | residual **COMPLETE 21** only (`permanent_defer` hard-reject) |
| Signal legs | registry-**approved** only (`topix_relative_1d` · `is_trading_day` · `volume_change_1d`) |
| Pipeline | approved-leg signal → multiday as_of → next-day return → R2 `batch_summary` |
| Read | CF D1 `quant-ingest` **hot tip** (default) or R2 structured history (`history_source="r2"`) |
| Output path | R2 `quant-structured` · `research/single_shot/job={id}/…` (local **not** SoT) |
| Mass loop | **not** connected |
| READY | **not** set |
| Phase7 | **OFF** |
| Order execution | **none** |
| Densify | **none** |
| Label | 小サンプル / 研究用・未宣言 (when nextday returns attached; no edge claim) |

### R2 history bridge (W59)

Optional research path to build FeatureContext from R2 structured JSONL/archive
(not local SQLite SoT). Default eval path remains D1 tip.

```python
from research.r2_feature_context import (
    extract_r2_history_feature_rows,
    build_r2_feature_context,
    S1_SIGNAL_HISTORY_DATASETS,
)
from research.eval_harness import run_nextday_return_eval

# Direct bridge (fixtures / keys)
extract = extract_r2_history_feature_rows(
    list(S1_SIGNAL_HISTORY_DATASETS),
    period_start="2026-04-01",
    period_end="2026-06-30",
    codes=["13010"],
    raw_lines_by_dataset={...},  # or object_keys_by_dataset + r2_get
)
ctx = build_r2_feature_context(extract["rows_by_dataset"], as_of="2026-06-03T15:30:00+09:00")

# Harness wiring (default history_source remains "d1_tip")
ex = run_nextday_return_eval(
    period_start="2026-04-01",
    period_end="2026-06-30",
    history_source="r2",
    r2_raw_lines_by_dataset={...},
    dry_run=True,
)
```

Module: [`r2_feature_context.py`](r2_feature_context.py). Proof:
`docs/proof/w0815az_w59_r2_feature_context_bridge_20260815.md`.

Module: [`eval_harness.py`](eval_harness.py) (re-exports multiday/nextday helpers from [`single_shot_job.py`](single_shot_job.py)).  
Tests: `tests/test_eval_harness.py`, `tests/test_single_shot_research_job.py`, `tests/test_mass_research_gate.py`, `tests/test_r2_feature_context.py`.

## Single-shot job (W49 skeleton · W50 CF execute · W51 tip features · W52 signal)

Lower-level CF tip execute / feature / single-day signal path. Prefer
[`eval_harness.py`](eval_harness.py) for multiday + nextday research batches.

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
