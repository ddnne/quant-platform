# research_logics

Catalog of unique_logic specs. **This is where a new hypothesis is declared.**

Do not copy `scripts/run_wNN_new_hyps_daily_dd.py`. Add a YAML here and, if the
economics are new, one `evaluate_*` function under
`packages/product/research/unique_logic/`. Then run the existing runners.

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
`python -m research.unique_logic --all` is HOLD, not candidate eval.

Scores go to R2 + D1. Do not add `scripts/run_wNN_*.py`.
