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
2. Runs **pure-TS** lite multi-period metrics per Mass logic:
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

The separate personal route is the normal operator path for DRAFT exact-four
research. R2 is authoritative. D1 is small job state. The Container expands
one immutable snapshot onto ephemeral disk, runs the repository `qp-research`
engine, then discards the SQLite copy. Persistent local market/price/fundamental
history is not a normal path. It does not change or arm the Mass capability.
Do not start from a local SQLite file and gzip/upload it. `qp-research` on a
laptop is developer/recovery compatibility only (`QP_ALLOW_LOCAL_MARKET_DATA=1`).

## Personal cloud exact-four

The normal operator path is `POST /v1/personal-snapshot-build` (then GET
status) followed by `POST /v1/personal-research-batch`. R2 is the snapshot
authority; D1 is small job state; Container SQLite is ephemeral job disk. Do
not gzip a local SQLite and upload it.

`POST /v1/personal-research` accepts one immutable SQLite snapshot already in
R2 and executes one closed four-candidate DRAFT cohort. The allowed cohort ids
are `price-relative-v1`, `fundamental-relative-v1`, and `diverse-core-v1`.
`compact-market-diverse-v1` is the separate market-relative cohort for
`topix_core30`, `topix_large70`, and `topix100`; the sector-relative cohorts
reject those compact universes because they cannot sustain 33 industry buckets.
`sector-relative-ls-v1` is a broad-universe-only exact-four DRAFT cohort. It
executes Paper and Risk only once per period at the fixed 3% annual baseline.
The 0% and 10% sensitivity rows deterministically reprice the same observed
post-fill short-notional trace; they do not rerun the market, rank calculation,
Paper, or Risk and cannot become executable artifacts. The formula uses 245
sessions and keeps the existing one-way fill cost separate. These rates are not
request fields and are modelled sensitivity assumptions, not stock-borrow
evidence. The current engine treats each post-fill end-of-session short book as
one close-to-next-session accrual and includes a terminal period-end accrual
even when the report has no next valued session. That terminal convention is a
disclosed DRAFT residual risk, not hidden borrow evidence.
Personal research is not Prime-limited. The default research universe is PIT
`topix_all`; the same request can select `topix_core30`, `topix_large70`,
`topix_mid400`, `topix_small1`, `topix_small2`, `topix_small`, `topix100`, or
`topix500`. Every selector is PIT-resolved and intersected with financials at
the execution decision cutoff. Default AM cohorts use 11:30 information and
same-day PM close. This personal surface is separate from the controlled Prime
contract.
The input is closed:

```json
{
  "cohort_id": "diverse-core-v1",
  "universe_id": "topix_all",
  "job_id": "exact-four-20260829",
  "snapshot_key": "research/personal/snapshots/sha256=<64-lowercase-hex>.sqlite.gz",
  "snapshot_sha256": "<64-lowercase-hex>",
  "period_start": "2022-04-19",
  "period_end": "2026-08-27"
}
```

`POST /v1/personal-snapshot-build` builds one bounded `personal-draft-history/v7`
SQLite on the Container's ephemeral disk, gzips it, and stores it immutably in
R2 at `research/personal/snapshots/sha256=<raw-64-hex>.sqlite.gz`. The request is
closed: `job_id`, `period_start`, `period_end`, and optional `lookback_sessions`
(0-252). End dates must not be in the future and must fall inside a closed
J-Quants calendar month (the governed acquisition RPC cannot serve the current
month). Snapshot build is compact v7, one continuous object, with a maximum
span of 7,000 inclusive calendar days. Warmup `data_start` stays distinct from
the evaluation period in the terminal manifest.
`POST /v1/personal-research-batch` accepts 1..8 unique closed personal-research
jobs and dispatches them concurrently.

The Container independently downloads and hashes the snapshot, runs SQLite
`quick_check`, then calls `scripts/qp-research`. Results are immutable:

```
research/personal/jobs/job={id}/result.tar.gz
research/personal/jobs/job={id}/manifest.json
```

The generated `snapshots/*.sqlite` copy is excluded from `result.tar.gz`; the
small snapshot manifest remains. Reusing a completed `job_id` is idempotent
only when every input is identical.

Cost and safety bounds are structural: one `standard-4` Container runs at most
four strategy child processes after one shared snapshot/PIT/data-quality
preparation. Distinct cohort/window jobs use job-scoped Container names derived
from runner version, job kind, and `job_id`, so independent jobs can occupy
separate instances. `max_instances=8` is a hard cap on concurrent billed
instances, not pre-warmed capacity; a ninth submitted job is rejected before
dispatch on the batch route. Snapshot builds use one singleton Container
because J-Quants acquisition is globally rate-limited. Every Container exits
after terminal evidence. The base sleeve, when required, is
computed before candidate fan-out. Candidate results are restored to registry
order before the exact-four aggregate is written. Compressed R2/HTTP snapshots
are capped at 4 GiB; expanded SQLite/builder size is capped at 5 GiB. The
route retains its 165-minute process-group timeout and 180-minute outer
Container activity window. Exact-four is also capped at 24
actual backtests (four validation folds, one stress, and one holdout per
candidate); financing sensitivity does not multiply that execution count. A
single request is limited to 7,000 inclusive calendar days as one continuous
compact v7 object. The cohort registry records the 2008/2016 data floors. The
subprocess limit
leaves fifteen minutes for verified R2 input/output and the durable terminal
manifest. The process exits immediately
after its terminal manifest, so an ordinary short run scales back to zero
without waiting for the outer window. A 190-minute active-rollout grace keeps
a deployment from replacing an accepted legacy or current-generation Container
before that watchdog ends.
Before changing the runner-bound name, every accepted job on the prior name must
have a terminal R2 manifest; do not resubmit the same `job_id` during the
two-generation migration window. Every new POST first requires the exact
current `/ready` identity. Only a positively identified
older runner may be destroyed and re-probed once; an unavailable or malformed
probe fails closed without destroying the instance.
There is no Cron, Queue, model call,
public Internet, promotion or live order. The Container `enableInternet` flag
stays false. It can reach only the personal R2 prefixes and the closed
`history.source` acquisition host via Worker-side adapters. `history.source`
accepts only the four personal history datasets through the existing
`IngestionSecretsService.fetch_governed_page` Service Binding; it does not
expose the legacy public proxy or duplicate J-Quants credentials. R2 verifies
streamed checksums before accepting objects.

`POST /v1/personal-vol-research` runs four fixed ratio-only volatility screens
over the 2021, 2023, and 2025 immutable R2 panels. The older 2015, 2017, and
2019 windows are excluded because the frozen equity codes were selected with
2019 information. `POST /v1/personal-svi-2023` runs one fixed exploratory
screen that fits the front and next Nikkei 225 option smiles
day by day, uses `front SVI ATM IV / next SVI ATM IV - 1`, and conditions an
equity long-short momentum book on that term ratio. Both routes are token
gated, write immutable artifacts, and remain DRAFT screening evidence; they
cannot publish READY, promote a strategy, arm Mass, or place an order. The SVI
study is a single 2023 window and does not model stock borrow or financing, so
it must not be read as a production GO result. Neither route uses single-stock
option volatility. Both use Nikkei 225 index-option evidence with a static
2019-selected liquid 100-name equity panel; it is not the PIT TOPIX universe
used by the factor Container and is labelled separately in every report.
The SVI report keeps its unhedged result and adds a TOPIX-index proxy comparison:
126-return beta (minimum 63) through signal close, capped at 1.5x.
The `__NKY_PROXY__` alias must identify `indices_bars_daily_topix`; 1306 is only an approximation, never an ETF fill claim.
Headline comparison metrics are available only when every active interval has all
stock legs and a beta estimate. Partial or incomplete coverage preserves the
calendar as audit rows without publishing a comparison performance summary.
Hypothetical TOPIX adjustments and costs are reported outside stock fill counts.
Runner v4 applies the same complete-book trace to the primary and comparison:
an active interval missing any intended stock leg is retained as a zero-change
audit row, while the whole primary result becomes `INCOMPLETE` with no headline
performance. Earlier v143 output remains history and is not reused as v144 proof.
Branch counts expose when the bounded sample observes only contango and cannot test inversion.

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

# required auth gate; do not put the value in shell history
# printf '%s' "$MASS_EVAL_TOKEN" | npx wrangler secret put MASS_EVAL_TOKEN

npx wrangler deploy
```

A Docker-compatible engine is needed for local deploy. Workers Builds can
build the Dockerfile remotely on the production branch. This Container lane is
path-scoped and uses `npx wrangler deploy --env production`, because
`versions upload` cannot update a Container image. The repository-wide
required check still gates the merge that starts that production build.

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

# personal exact-four: build an R2 snapshot, then batch research jobs.
# R2 is authoritative; Container SQLite is ephemeral. Do not gzip a local
# SQLite and wrangler-put it.
WORKER="https://quant-platform-research-mass-eval.<subdomain>.workers.dev"
SNAPSHOT_JOB_ID="snap-$(date -u +%Y%m%dT%H%M%SZ)"
curl -sS -X POST \
  "${WORKER}/v1/personal-snapshot-build" \
  -H 'content-type: application/json' \
  -H "X-Mass-Eval-Token: ${MASS_EVAL_TOKEN:?required}" \
  -d "{
    \"job_id\": \"${SNAPSHOT_JOB_ID}\",
    \"period_start\": \"2022-04-19\",
    \"period_end\": \"2026-08-27\"
  }" | jq .

SNAPSHOT_STATUS=$(curl -sS \
  "${WORKER}/v1/personal-snapshot-build/${SNAPSHOT_JOB_ID}" \
  -H "X-Mass-Eval-Token: ${MASS_EVAL_TOKEN:?required}")
echo "$SNAPSHOT_STATUS" | jq .
# Status shape is {job:{...}}. Use job.snapshot_key as-is. Strip the sha256:
# prefix from job.raw_sha256 before posting snapshot_sha256 (64-hex only).
SNAPSHOT_KEY=$(echo "$SNAPSHOT_STATUS" | jq -r '.job.snapshot_key')
SNAPSHOT_SHA256=$(echo "$SNAPSHOT_STATUS" | jq -r '.job.raw_sha256 | ltrimstr("sha256:")')

PERSONAL_JOB_ID="exact-four-$(date -u +%Y%m%dT%H%M%SZ)"
curl -sS -X POST \
  "${WORKER}/v1/personal-research-batch" \
  -H 'content-type: application/json' \
  -H "X-Mass-Eval-Token: ${MASS_EVAL_TOKEN:?required}" \
  -d "{
    \"jobs\": [
      {
        \"cohort_id\": \"diverse-core-v1\",
        \"universe_id\": \"topix_all\",
        \"job_id\": \"${PERSONAL_JOB_ID}\",
        \"snapshot_key\": \"${SNAPSHOT_KEY}\",
        \"snapshot_sha256\": \"${SNAPSHOT_SHA256}\",
        \"period_start\": \"2022-04-19\",
        \"period_end\": \"2026-08-27\"
      }
    ]
  }" | jq .

curl -sS \
  "${WORKER}/v1/personal-research-batch?job_id=${PERSONAL_JOB_ID}" \
  -H "X-Mass-Eval-Token: ${MASS_EVAL_TOKEN:?required}" | jq .
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
