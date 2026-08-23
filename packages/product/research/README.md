# research

Research control plane (Phase 7 stays OFF): readiness attestation, experiment plans.

**Mass is NO-GO.** A track result is not a pass / not GO. READY and Phase 7 stay closed.

**Recording:** results go to R2 `research/eval/job={id}/` (plus `research/mass_eval`) and a small D1 job index. Git holds catalogs and evaluators. Do **not** add `scripts/run_wNN_*.py` or wave proof scorecards. See [`docs/architecture/adr_research_recording.md`](../../../docs/architecture/adr_research_recording.md).

## Canonical SoT

- **Candidate eval:** `research.cf_daily_path_job` `POST /v1/daily-path` → R2 `research/eval/job={id}/`. Helpers: `research.daily_path_eval`.
- **Tracks:** `research.eval_tracks` `mid_n_explore` / `liq_large` (ADV-ranked; **not** head-N).
- **Live flags:** `research.eval_flags` (AND +N stopped, reconstitution apply, wave id).
- **Thesis count:** `research.unique_logic.worker_bodies.countable_thesis_ids` (catalog + Worker body; YAML clones do not count).
- **Catalog:** `specs/research_logics/*.yaml`. Worker ID arrays: generated `platform/workers/research-mass-eval/src/catalog_ids.ts` (leftover occupancy stays in `daily_path.ts`).
- **Propose:** `POST /v1/propose-thesis` (`research.cf_propose_thesis`; Workers AI 70B then glm-4.7-flash then 8B CF-internal; LLM failure is `ok:false`/`llm_failed`, not stub-as-success; review_proposal_row; no auto-inject).
- **Eval wave one-call:** `research.occupancy_audit.run_eval_wave` writes inventory / usable-read / series / cost-risk / jsonl / occupancy maps / drift / unique22 / reconstitution detect + occupancy preview / series-sleeve coverage + propose write-gate. Never injects. Does not fan out occupancy. Does not apply reconstitution. YAML remains catalog SoT. KEEP sleeves `eval-cf-dp-both-sleeves-20260824df`. Do not restitch 24ek thinner alts.
- **Smoke codes:** `research.eval_universe.HARNESS_SMOKE_CODES`. Not the eval entry.
- **`cost_models.py` / `options_225_vol_series.py`:** live math. Do not fake-split.

CF period-net (`research.cf_mass_eval_job`, `POST /v1/mass-eval`) is auxiliary; `n_survivors` is not a pass. Offline `research.offline.bar_eval` / `multiyear` / `factory` are local helpers, not candidate SoT.

## Public entry (control plane)

```python
from research import (
    ResearchReadinessService,
    VerifiedResearchReadiness,
    require_mass_research_start,
    MassResearchDisabledError,
    ExperimentPlan,
    ExperimentScheduler,
)
```

Mass start is **fail-closed** without `VerifiedResearchReadiness`; operator override is rejected.

## Allowed imports

- `selection`, `paper_runtime`
- `data_contracts.permanent_defer` (COMPLETE-21 / DEFER guard)

## Forbidden

- Market HTTP (`ingestion`)
- Claiming Mass ON without residual + proof
- Direct fact SQLite from research orchestration
- Arming Phase7 / Mass / READY from this package

See [docs/architecture/phase7_fail_closed.md](../../../docs/architecture/phase7_fail_closed.md).
