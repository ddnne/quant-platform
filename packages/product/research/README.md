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

## Standard research eval checklist (v2 · W77 · default for future hyps)

Before any hypothesis is labeled **`research_candidate`**, it must pass the
standard checklist **v2** (`standard-research-eval-checklist/v2`):

* multi-year or non-overlapping long periods
* transaction cost 10bp one-way default (extendable with reason)
* **leverage/short cost assumptions** (borrow + financing; long-only must state N/A)
* robustness_gate v2 with `net_sign_majority`
* data-gap disclosure
* **risk scenario evaluation** (crash · high_vol · rate up/down if usable · liquidity if available)
* pass ≠ READY/Mass
* holding/turnover **near-required** for high-frequency hyps

**Incomplete checklist cannot become `research_candidate`.** Short-window-only is **insufficient**.

```python
from research.eval_harness import run_standard_research_eval

# Wiring-only (no heavy R2): freezes + costs + window design + gap notes + scenario surface
out = run_standard_research_eval(dry_run=True)
assert out["checklist_version"] == "standard-research-eval-checklist/v2"
assert out["ready_declared"] is False
assert out["mass_research"] == "NO-GO"
assert out["phase7"] == "OFF"
assert out["research_candidate"] is False  # never auto-promotes
assert out["research_candidate_allowed"] is False  # wiring leaves scenarios incomplete
```

| rule | held |
|------|------|
| Default entry | `run_standard_research_eval` |
| Version | `standard-research-eval-checklist/v2` |
| Gate | cost-aware v2 (`net_sign_majority`, 10bp one-way) |
| Cost models | `research.cost_models` (short borrow · leverage financing) |
| Risk scenarios | `research.risk_scenarios` (min set) |
| S1–S5 | remain `research_baseline_rejected` (catalog); demo re-run only |
| READY / Mass / Phase7 | **not** connected on pass |
| New signals | **not** invented by this entry |

Checklist v2 proof: `docs/proof/w0816k_w77_eval_checklist_v2_20260816.md`.  
Checklist v1 (prior): `docs/proof/w0815bg_w66_standard_research_eval_checklist_20260815.md`.  
Harness proof: `docs/proof/w0815bg_w66_standard_eval_harness_entry_20260815.md`.  
COMPLETE 22 research entry (W74): `docs/proof/w0816h_w74_research_entry_complete22_20260816.md`.  
Tests: `tests/test_standard_research_eval.py`.

## Hypothesis class registry (W77 · entry space redesign)

Research ideas are typed into **hypothesis classes** so generation is not
skewed to simple daily sign mass production (S1–S5 stay
`research_baseline_rejected`).

```python
from research.hypothesis_classes import (
    CLASS_SIMPLE_DAILY_SIGN,
    default_generation_class_ids,
    select_generation_classes,
    assert_simple_daily_sign_not_default_enabled,
)
from research.idea_generator import generate_idea_payloads
from research.scheduler import select_schedule_hypothesis_classes

assert_simple_daily_sign_not_default_enabled()
assert CLASS_SIMPLE_DAILY_SIGN not in default_generation_class_ids()

# Default mix: multi_day_hold · event_post · cross_section_relative ·
# macro_conditioned · fundamentals_price · flow_demand
mix = select_generation_classes()
assert CLASS_SIMPLE_DAILY_SIGN not in mix

# simple_daily_sign only via explicit opt-in (and never alone as mass-default)
batch = generate_idea_payloads(author="human", batch_id="demo")
assert batch.simple_daily_sign_included is False
sched_mix = select_schedule_hypothesis_classes()
assert sched_mix.simple_daily_sign_default_off is True
```

| class | default generation | priority |
|-------|--------------------|----------|
| `multi_day_hold` | ON | high |
| `event_post` | ON | … |
| `cross_section_relative` | ON | … |
| `macro_conditioned` | ON | … |
| `fundamentals_price` | ON | … |
| `flow_demand` | ON | … |
| `simple_daily_sign` | **OFF** (opt-in) | **lowest** |

Module: [`hypothesis_classes.py`](hypothesis_classes.py) · generator: [`idea_generator.py`](idea_generator.py).  
Proof: `docs/proof/w0816k_w77_hypothesis_space_redesign_20260816.md`.  
Tests: `tests/test_hypothesis_classes.py`.

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
