# quant-platform-research-mass-eval

Cloudflare Worker for bounded research evaluation. Mass remains disabled.

Research plane only. Does **not** arm operational Mass / READY / GO / continuous paper / live.
Does **not** retune the three frozen default-path representatives.

`POST /v1/daily-path` accepts only the four governed Pilot strategy IDs. The
retired 2,254-row catalog is not bundled, imported, or inferred from ID
prefixes; catalog-style `gates` / `cs_gate` input fails closed. The immutable
catalog survives only under `artifacts/replay/legacy_strategy_catalog/`.

## What it does

1. Accepts `POST /v1/mass-eval` with `{ seed, logics[], periods[], job_id }`.
2. Runs **pure-TS** lite multi-period metrics per logic (no Python container):
   - `multi_day_hold` — sticky momentum hold + amortized cost
   - `cross_section_relative` — rank L-S sticky hold
   - other families — lite fallback via multi_day_hold knobs (full rate/mf factor legs **not-yet-implemented** on CF)
3. Writes artifacts to R2 **`quant-structured`**:

```
research/mass_eval/job={id}/manifest.json
research/mass_eval/job={id}/request.json
research/mass_eval/job={id}/summary.json
research/mass_eval/job={id}/results.json
research/mass_eval/job={id}/ranking.json
research/mass_eval/job={id}/panels_meta.json
research/mass_eval/job={id}/logic={logic_id}/result.json   # when n_logics ≤ 50
```

## Modes

| mode | behavior |
|------|----------|
| `synthetic` (default) | Deterministic synthetic Q4-lite bars from `seed` |
| `r2_panels` | Load staged `research/mass_eval/panels/{period_id}.json` |
| `nets_only` | Use per-logic `period_nets` / `period_grosses` (no bars) |

## Freezes (held)

| flag | value |
|------|-------|
Auth is **fail-closed**: unbound `MASS_EVAL_TOKEN` denies every eval/propose
route. Health is the only unauthenticated endpoint and returns `{ok,service,version}`.

Mass / daily-path / propose require typed capabilities (`src/capabilities.ts`).
Env flags can only deny. Worker does **not** bind Workers AI; propose uses
typed `GatewayService` RPC binding `AI_GATEWAY`; no shared Gateway bearer token
is present in this Worker. R2 writes are create-if-absent (duplicate job_id → 409).

| Mass (operational) | **NO-GO** |
| READY | **false / 未宣言** |
| operational GO | **false** |
| continuous paper | **UNARMED** |
| Phase7 | **OFF** |
| 3 defaults retuned | **false** |

## Deploy

```bash
cd platform/workers/research-mass-eval
npm install

# optional auth gate
# printf '%s' "$MASS_EVAL_TOKEN" | npx wrangler secret put MASS_EVAL_TOKEN

npx wrangler deploy
```

Workers.dev URL shape:

```
https://quant-platform-research-mass-eval.<account-subdomain>.workers.dev
```

## Invoke (curl)

```bash
# health
curl -sS "https://quant-platform-research-mass-eval.<subdomain>.workers.dev/health" | jq .

# mass-eval smoke
JOB_ID="w90-smoke-$(date -u +%Y%m%dT%H%M%SZ)"
curl -sS -X POST \
  "https://quant-platform-research-mass-eval.<subdomain>.workers.dev/v1/mass-eval" \
  -H 'content-type: application/json' \
  -H "X-Mass-Eval-Token: ${MASS_EVAL_TOKEN:-}" \
  -d "{
    \"seed\": 870816,
    \"job_id\": \"${JOB_ID}\",
    \"mode\": \"synthetic\",
    \"periods\": [
      {\"period_id\": \"y2019_q4_lite\", \"year\": 2019},
      {\"period_id\": \"y2021_q4_lite\", \"year\": 2021},
      {\"period_id\": \"y2023_q4_lite\", \"year\": 2023}
    ],
    \"logics\": [
      {
        \"logic_id\": \"paper_mdh_hold10_momentum_topk\",
        \"family_id\": \"multi_day_hold\",
        \"params\": {\"hold_days\": 5},
        \"thesis\": \"Multi-day momentum sticky hold earns residual after cost\"
      },
      {
        \"logic_id\": \"cross_section_hold_10\",
        \"family_id\": \"cross_section_relative\",
        \"params\": {\"hold_days\": 10, \"momentum_n\": 5, \"long_frac\": 0.3, \"short_frac\": 0.3},
        \"thesis\": \"Cross-section rank L-S sticky hold=10\"
      }
    ]
  }" | jq '{ok, job_id, n_logics, n_survivors, r2_keys, ranking}'
```

## Verify R2

```bash
cd platform/workers/research-mass-eval
npx wrangler r2 object get \
  "quant-structured/research/mass_eval/job=${JOB_ID}/summary.json" \
  --remote --file=/tmp/mass_eval_summary.json
cat /tmp/mass_eval_summary.json | jq .
```

## Relation to local factory

| path | role |
|------|------|
| **this worker** | CF minimal multi-logic batch + R2 artifacts |
| legacy `research.unique_logic` modules | explicit audit/replay compatibility only |
| exact-four `POST /v1/daily-path` | bounded daily-path evaluator; no auto-promotion |

Python helper: `research.offline.factory.try_cf_minimal_mass_batch()` reports this worker.

## Not-yet-implemented (remaining gaps)

- Full CF rate-factor / multi-factor legs (repo curve, fins, margin) without fallback
- Direct historical bar load from `structured/jsonl/…` partitions (use `r2_panels` staging)
- Queue / durable object fan-out for 200–500 logics (sync POST caps at 200)
- Auth fail-closed: missing `MASS_EVAL_TOKEN` binding denies `/v1/*` (health stays public and limited).
- Mass/daily-path/propose also require typed capabilities; `MASS_RESEARCH=NO-GO` is an execution gate, not metadata.
