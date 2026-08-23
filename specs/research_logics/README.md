# research_logics

Expanded YAML was removed in a mechanical catalog migration.

**Source of truth:** `specs/research_catalog/migration.jsonl` +
`specs/research_catalog/manifest.json` (`research.catalog_compiler`).
`CATALOG_AND_PLUS_N_STOPPED` remains on. Do not add YAML here without a dated
brief that flips the freeze.

Candidate SoT is still `POST /v1/daily-path`. Scores go to R2 + D1.

Schema (v1, fields required):

```yaml
logic_id: overnight_level_cs_tilt
family_id: overnight_level_cs
axis: funding
headline: false
generation_enabled: false
thesis: "..."
signal_definition: "..."
position_rule: "..."
datasets: [jsda_tokyo_repo_rates, equities_bars_daily]
params:
  hold_days: 10
  momentum_n: 5
evaluator: research.unique_logic.funding.evaluate_overnight_level_cs_tilt_daily_mtm
```

YAML files here are the declaration path. Evaluators live in
`packages/product/research/unique_logic/`. Candidate SoT is
`POST /v1/daily-path` (`research.cf_daily_path_job`). Local
`python -m research.unique_logic` is a retired fail-closed stub, not candidate eval.

Scores go to R2 + D1. Do not add `scripts/run_wNN_*.py`.
