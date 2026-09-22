# quant-platform-research-mass-eval

Cloudflare research Worker. The historical service name does not enable Mass.

## Current entrypoints

| Route | Role |
|---|---|
| `POST /v1/personal-snapshot-build`, `POST /v1/personal-research-batch` | Personal DRAFT snapshot and research; not Controlled readiness |
| `POST /v1/receipt-candidate` | Receipt-backed cloud candidate construction; a candidate is not READY |
| `POST /v1/controlled-pilot` | Separately gated exact-four Controlled Pilot |
| `POST /v1/mass-eval`, `POST /v1/daily-path`, `POST /v1/propose-thesis` | Disabled: authenticated requests return 403 `capability_missing`; flags cannot enable them |

Route implementation: [src/http_routes.ts](src/http_routes.ts).
Source support does not establish deployment, data completeness, READY or execution
authorization. Preserve all current cancel/HOLD decisions. The retired catalog is
replay-only under `artifacts/replay/legacy_strategy_catalog/`, not runtime input.

The separate personal route is the normal operator path for DRAFT
four-candidate research. R2 is authoritative. D1 is small job state. The Container expands
one immutable snapshot onto ephemeral disk, runs the repository `qp-research`
engine, then discards the SQLite copy. Persistent local market/price/fundamental
history is not a normal path. It does not change or arm the Mass capability.
Do not start from a local SQLite file and gzip/upload it. `qp-research` on a
laptop is developer/recovery compatibility only (`QP_ALLOW_LOCAL_MARKET_DATA=1`).

## Personal cloud Draft research

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
`sector-relative-ls-v1` is a broad-universe-only four-candidate DRAFT cohort. It
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
  "job_id": "draft-factor-20260829",
  "snapshot_key": "research/personal/snapshots/sha256=<64-lowercase-hex>.sqlite.gz",
  "snapshot_sha256": "<64-lowercase-hex>",
  "period_start": "2022-04-19",
  "period_end": "2026-08-27"
}
```

`POST /v1/personal-snapshot-build` builds one bounded `personal-draft-history/v8`
SQLite on the Container's ephemeral disk, gzips it, and stores it immutably in
R2 at `research/personal/snapshots/sha256=<raw-64-hex>.sqlite.gz`. The request is
closed: `job_id`, `period_start`, `period_end`, and optional `lookback_sessions`
(0-252). End dates must not be in the future and must fall inside a closed
J-Quants calendar month (the governed acquisition RPC cannot serve the current
month). Snapshot build is compact v8, one continuous object, with a maximum
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
order before the four-candidate aggregate is written. Compressed R2/HTTP snapshots
are capped at 4 GiB; expanded SQLite/builder size is capped at 5 GiB. The
route retains its 165-minute process-group timeout and 180-minute outer
Container activity window. Draft research is also capped at 24
actual backtests (four validation folds, one stress, and one holdout per
candidate); financing sensitivity does not multiply that execution count. A
single request is limited to 7,000 inclusive calendar days as one continuous
compact v8 object. The cohort registry records the 2008/2016 data floors. The
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

## Operations and authorization

Use the [current production runbook](../../../docs/operations/current_production_runbook.md)
for staged deployment, authenticated checks, finite execution bounds and recovery.
The [work ledger](../../../docs/operations/current_work_ledger.json) records accepted
scope and HOLDs; recorded observations do not replace live checks.

Do not deploy directly from this README, enable production auto-deployment, or
launch a smoke backtest merely because source CI passes. Source delivery, staging,
production, data activation, READY and Pilot are separate outcomes.

Missing `MASS_EVAL_TOKEN` denies research execution. Controlled readiness and
Trader authorization are separate from that transport token. A successful DRAFT
result, receipt candidate or Pilot attestation cannot authorize Mass. The
`AI_GATEWAY` Service Binding does not enable the disabled propose route.

No laptop market-history persistence, local Docker backtest, live order, FoF,
automatic promotion or unbounded catalog fan-out is part of this service's normal
operation. See the [architecture](../../../docs/architecture.md) for boundaries.
