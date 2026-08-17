# quant-platform-mass-eval

W90 / `w0816y` — Cloudflare Worker for **multi-logic × multi-period** research evaluation (lite shard).

## Freezes

- Mass research: **NO-GO**
- READY / operational GO: **not declared**
- continuous paper: **UNARMED**
- live orders: **OFF**

## Endpoints

| method | path | auth |
|--------|------|------|
| GET | `/health` | none |
| POST | `/v1/research/mass_eval` | `Authorization: Bearer $RESEARCH_RUN_TOKEN` (or `INGESTION_RUN_TOKEN`) |

## Artifacts (R2 `quant-structured`)

```
research/mass_factory/job={job_id}/manifest.json
research/mass_factory/job={job_id}/input_plan.json
research/mass_factory/job={job_id}/batch_summary.json
research/mass_factory/job={job_id}/results.json
research/mass_factory/job={job_id}/screens.json
research/mass_factory/job={job_id}/ranking.json
```

## Lite shard

- ≤ ~15–20 equity codes from D1 tip density
- ≤ ~60–80 trading days per period
- Multiple Q/H periods
- Bar-native logics: multi_day_hold, cross_section_relative, vol_risk_adjusted

Non-bar-native logics (fund/flow/rate/event) return `data_missing` on CF lite unless an extra panel is supplied later; evaluate those on local factory / class_hyp.

## Deploy

```bash
cd platform/workers/mass-eval
npm install
npx wrangler secret put RESEARCH_RUN_TOKEN   # or INGESTION_RUN_TOKEN
npx wrangler deploy
```

## Invoke (Python)

```python
from research.cf_mass_eval_job import run_cf_mass_eval_job
pack = run_cf_mass_eval_job(deploy_if_needed=True)
print(pack["job_id"], pack["status"], pack["artifact_paths"])
```
