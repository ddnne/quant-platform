# Personal product: whole-repository simplification

Current direction, 2026-09-29. This is ongoing work, not completion or deployment
approval. It supersedes old phase-specific recommendations to add layers or
source-text tests merely for architectural uniformity. Explicit execution HOLDs,
PIT/numeric correctness, cost bounds and no-live-order defaults remain intact.

## Outcome

Efficient cloud-only strategy experiments over each dataset's longest usable
history, with comparable results and economic rationale. Price-only strategies
should not inherit financial/volatility history limits. Aim for approximately
2008 through recent 2026 where observed data supports it; 2018–2023 was a bounded
trial, not the final research horizon. Do not invent coverage or use future data.
Keep a common-period comparison and per-strategy longest-period results.

Do not wait for a repo-wide rewrite before running a useful experiment. Keep
logical changes separate in commits, but batch completed fixes into pushes to
avoid repeated paid full builds. Main agent implements; reviewers only critique.

## Baseline and acceptance

Tracked files at 9291e38a, before this batch, excluding lockfiles and generated
Worker Env declarations: Python 397 files / 174,536 lines; Worker non-test
TS/JS/config 228 / 68,274; tests 400 / 161,041; Markdown 114 / 15,555.
These are textual sizes, not complexity or value. Separate code, tests, docs and
generated artifacts in the final diff. A 50% reduction is an investigation
target, not permission to discard working numerical capabilities.

## Ordered worklist across the whole processing chain

| Area | Remove or consolidate | Evidence required to close |
|---|---|---|
| Acquisition/storage | Legacy D1-body readers/writers, repeated whole-history aggregates, duplicate metadata access | New runs use R2 bodies and small D1 metadata; actual hourly reads/writes |
| Snapshot preparation | Repeated object download/parse/key validation, needless scratch rebuilds | Same vintages/results; bounded scratch; measured full scans/bytes/runtime |
| Features/universe | Duplicate PIT filters, repeated windows/joins per strategy; unnecessary financial dependency for price-only runs | Daily membership/AM time-wall regression and shared feature preparation |
| Research evaluation | Parallel old catalog/offline and current evaluation paths, duplicated normalization/metrics | Preserve used strategies and one evaluator/report contract; historical replay recoverable in Git |
| Paper/risk/results | Duplicate job/spec/lease/terminal/result adapters and repeated artifact serialization | One current entry per DRAFT/Controlled mode; no future data, uncontrolled spend or real orders |
| CI/deployment | Per-edit full builds, repeated install/build checks, docs-only full suites, duplicate deployment wrappers | Exact final-SHA native check remains meaningful; measured build-minute reduction |
| Tests/docs/tools | Implementation-copy and mock-self-check tests, dead feature tests, stale phase docs/scripts | State realistic bug each retained test catches; remove obsolete callers together |

Use the existing store/reader for each domain. Do not create a universal storage
framework, extra Workers, new signing authorities or a dependency-map service.
Legacy compatibility must name its remaining caller and removal condition;
"just in case" is not a reason to retain it. Do not delete persisted history as
a side effect of source cleanup; identify consumers and recovery first.

## First batch (source only)

- Remove the legacy D1 availability scan after R2 persistence; measure current
  normalized rows in the existing writer. Resumed partial measurement is null.
- Remove unused Artifacts join-plan and fake Parquet conversion bridge endpoints
  with their tests; repository search found no executable consumer.
- Replace the watermark SQL-string/mock test with assertions on real workerd D1
  output in the existing ingestion test.
- Retain bounded job-local offsets after initial full stored-bars validation,
  avoiding repeated full JSON/key parsing for each month; no new persistent DB.
- Provider dependency caching enabled on the two existing root CI triggers.

Remaining: the broad worklist is not closed, legacy replay/Controlled paths are
not yet removed, docs-only CI selection is not implemented, and no new long-run
strategy performance has been produced by this batch. Source acceptance alone
does not authorize a new paid attempt or establish READY/Pilot GO.

## Retired evaluation path

Remove `research.offline`: ten modules / 4,014 implementation lines comprising
the old bar evaluators, multi-year orchestration and duplicated report/gates.
No executable caller remains outside the two dedicated tests removed with it;
it was already excluded from the wheel and Container. Old source is recoverable
at `c99640944c6acc9c768afbf5080433887bcedddd`, without another archive copy.
This removes a second evaluation/report implementation, not the current
personal, AM-to-PM, financial or index-volatility capabilities. Their numerical
and PIT tests remain. The legacy `unique_logic` replay graph has other callers
and is not claimed removed by this change.
