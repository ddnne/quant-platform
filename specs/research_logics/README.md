# research_logics

Expanded YAML was removed in a mechanical catalog migration.

**Replay artifact:** `artifacts/replay/legacy_strategy_catalog/migration.jsonl` +
`artifacts/replay/legacy_strategy_catalog/manifest.json`.
`CATALOG_AND_PLUS_N_STOPPED` remains on. Do not add YAML here without a dated
brief that flips the freeze.

New experiments use the current personal DRAFT or READY-bound Controlled
service. `/v1/daily-path` is retired and refuses execution.

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

This directory contains no YAML. The schema above is historical only; its
evaluator strings are not importable in the current product. The old Python
catalog and evaluator graph was removed and is recoverable from Git history
before this retirement (for example `c353c2802f53cca0f5eeb5edbfcbbc96e722fd4a`).
Neither Pilot nor Mass imports the frozen JSONL; do not add YAML here or revive
`python -m research.unique_logic` as a second execution path.

Scores go to R2 + D1. Do not add `scripts/run_wNN_*.py`.
