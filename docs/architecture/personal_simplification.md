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

## Retired paths and retained guarantees

- `research.offline`: ten old evaluators/orchestrators/reports (4,014 lines),
  plus orphaned holding/sign-selection reports (986 lines), had no current
  executable caller. Source is recoverable at `c99640944c6acc9c768afbf5080433887bcedddd`.
- The retired catalog graph: thesis-proposal and Mass/daily-path Python
  clients, catalog compiler/adapters, basket/occupancy/reconstitution reports,
  `research.unique_logic` evaluators and duplicate phrase policies are removed.
  No product consumer remained outside that graph. Old source is recoverable
  at `c353c2802f53cca0f5eeb5edbfcbbc96e722fd4a`.
- The frozen catalog JSONL/manifest and persisted results remain unchanged.
  No executable replay copy, new policy registry or generator replaces them.
  Current personal/Controlled services, closed DSL, AM-to-PM timing, financial
  and index-volatility/SVI features, portfolio/risk math and PIT tests remain.
- Dedicated old catalog/count/phrase/alias tests leave with their subject.
  Retire the separate replay CI lane and duplicate suite collection. Offline
  and Node/npm toolchain checks remain mandatory. Actual workerd tests still
  prove authenticated 403 with no external execution for the three old routes.
- Remove the old wave-specific queue, implicit dispatch-only liquidity context
  and packaging exclusions for deleted code. ADV stays an explicit input;
  keep actual missing-ADV/cost behavior tests and current installed imports.

Retiring unused paths reduces maintenance and test collection, not observed
cloud runtime. Deleted lines are not measured billing savings. Do not claim
the requested whole-repository reduction or a 50% target is complete.

## Measured active-path consolidation

Coverage refresh used to verify each signed receipt for observed history,
candidate ranking, segment evaluation and selected-run persistence. It now
verifies once for those steps, shares the existing immutable verified closure, and
indexes candidates by exact segment identity. Required scope/policy checks use
the same verifier-owned function; environment, signature and transport binding
still run before preparation. No process-global receipt cache, new authority,
external call or database is introduced. A later evaluation verifies again.
The final persistence gate for existing COMPLETE inventory still independently
verifies its exact inventory; this change does not bypass that gate or promise
only one signature check across every production publication path.

On the same synthetic publication fixture (6,000 data rows, 3,764 receipts,
24 datasets), cProfile measured 15,056 to 3,764 receipt verifications and
37.8 to 8.3 seconds for publication. Fixture construction itself was about
2.4 seconds: repeated real processing, not fixture construction, was the main
cost. These are local instrumented measurements, not production throughput or
billing savings. Keep the existing policy/sticky-COMPLETE tests and one real
signature regression for changed scope and changed transport across calls.

## Next acceptance work

Continue the table above: consolidate active feature/evaluation/data access,
remove repeated current-path scans and heavyweight test setup, and reduce
unnecessary build selection. Validate actual runtime/bytes/D1 reads separately
from source size. Do not wait for this worklist to be exhausted before an
authorized useful experiment. No new long-history performance was produced
by source retirement; source acceptance does not authorize another paid
attempt, change existing HOLDs, or establish READY/Pilot GO.
