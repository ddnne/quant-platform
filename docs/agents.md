# Phase 6 role agents and StrategySpec

Phase 6 is an offline, deterministic vertical slice from structured research
messages to a paper result and an independent risk audit. It does not add a
general-purpose agent runtime or allow generated source code.

```text
Macro ─┐
Fundamental ─┼─> Composer -> Strategist -> StrategySpec -> PM -> Trader plan
Quant ─┘                                      |
                                               v
                                  trusted whitelist interpreter
                                               |
                                               v
                         ctx.feature -> core -> PaperRunResult -> Risk audit
```

## Roles and interfaces

`agents/roles.py` is the machine-readable role matrix. The eight roles are:

| Role | Input | Output |
|---|---|---|
| Macro | `ResearchRequest` | `ResearchMemo` |
| Fundamental | `ResearchRequest` | `ResearchMemo` / candidate `FeatureProposal` |
| Quant | `ResearchRequest` | `ResearchMemo` |
| Composer | research memos | `ComposedMemo` |
| Strategist | composed memo | `StrategySpec` |
| Portfolio manager | spec | `PortfolioDecision` |
| Trader | approved decision | paper-only `TradePlan` |
| Risk | persisted `PaperRunResult` | immutable `RiskAudit` |

The three research roles can run concurrently because they receive the same
immutable request. A request contains only `as_of`, an explicit universe, and
an objective. It never contains a database path, raw response, HTTP client, or
credential. Optional future LLM adapters must preserve these same interfaces.

## StrategySpec safety contract

`strategies/spec/schema.py` accepts only `strategy-spec/v1`, daily rebalance,
and two numeric rule types:

- `threshold`: select scores at or above a threshold, equal-weight them.
- `top_k`: select the highest `k` scores (optionally above `min_score`),
  equal-weight them.

Rules name a registered feature and JSON-scalar feature parameters. Unknown
types, fields, parameters, versions, rebalance modes, and runtime-owned
parameters (`code`, `as_of`, `db_path`) are rejected before a run. The
interpreter admits only explicitly `approved`, `signal` features. New feature
definitions default to `candidate`; an agent's `FeatureProposal` cannot
register or approve one.

The interpreter creates a normal core `Strategy`. Its only data operation is
`ctx.feature(feature_id, code=..., **validated_params)`. There is no `eval`,
`exec`, dynamic import, generated module, SQL, PIT handle, or HTTP path.

Example:

```json
{
  "version": "strategy-spec/v1",
  "strategy_id": "agent_momentum_top_k",
  "rebalance": "daily",
  "rule": {
    "type": "top_k",
    "feature_id": "momentum_n",
    "k": 1,
    "min_score": 0.0,
    "feature_params": {"n": 5}
  },
  "rationale": "approved momentum fixture"
}
```

## Orchestration and write boundaries

`AgentPaperPipeline` passes `PaperRunConfig.db_path` only to the trusted paper
runtime. It persists the paper result, reloads that immutable JSON artifact,
then gives the artifact to `RiskAgent`. Paper outputs use `data/paper`; risk
audits use `data/risk/audits`. The pipeline refuses equal or nested roots.
The risk audit id is content-derived and the audit JSON is immutable.

Run the CLI locally (no network or broker):

```bash
.venv/bin/python scripts/run_agents_paper_once.py \
  --db data/structured/ingestion.sqlite \
  --start 2025-01-06 --end 2025-03-31 \
  --universe 1332,8697 --momentum-n 5 --top-k 1
```

Boundary and offline fixture coverage lives in `tests/test_agents_*.py` and
`tests/test_strategy_spec_*.py`.
