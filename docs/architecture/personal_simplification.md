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

### Scheduled acquisition

`ingestion-premium/src/fetch_jq.ts` owns both query dates and Cron selection;
the handler passes the scheduled timestamp, never backdating acquisition/PIT
timestamps. Explicit manual and staging ranges keep their existing semantics.
The hourly trigger remains; skipped datasets get no acquisition, validation or
COMPLETE receipt. No new scheduler, DB, cache authority or resources are needed.

The [official publication schedule](https://jpx-jquants.com/ja/spec/data-update)
informs these JST hours (each at :15), including later catchup:

| Data | Hours |
| --- | --- |
| Financial summary/details | Hourly; 00/01 and 07 revisit yesterday |
| EDINET | 08–18 and 07 for yesterday |
| Master | 08/09/18/20, current date only |
| AM tip | 12/13 |
| Dividend | 12–20 and 07 |
| Earnings dates / earnings calendar tip | 10/11/20 and 07 / 19/20 |
| Trading calendar | 20 |
| Derivatives | 03/04/07, previous date, including Saturday |
| Margin interest | 16/17/20 and 07, publication-date filter |
| Short-sale report / breakdown | 18/20 and 07 |
| Other daily/weekly datasets | 17/20 and 07 |

07 revisits yesterday; existing range endpoints retain their five-day window.
Weekly statistics are not restricted to Thursday because holidays shift release.
Publication times are estimates, not completion evidence. Corrections outside
these windows still require explicit bounded collection; this is not historical
recertification. Query-plan reduction alone does not establish invoice savings.
The current master SCD2 format dates observations at collection. Do not request
tomorrow's membership; if JQ redirects a holiday query to a future `Date`, reject
it before updating CURRENT. Raw acquisition stays available, not COMPLETE proof.

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

### Feature read scopes

The existing feature runtime projects declared bar fields for both Controlled
selection and DRAFT PIT/AM readers. Pure observation-count scopes select the
latest decision-visible N rows once per compute, then apply caller date filters;
an older `to_event` cannot shift that declared tail into old history. An
unbounded retry reuses that tail, and undeclared datasets/oversized reads are
refused before storage access. Split-safety scopes retain their predecessor plus
anchor interval rather than incorrectly truncating the whole interval to N.

Fundamental ratio scopes use one closed `mode` branch: the existing latest
statement plus comparable prior, per-share bars plus the selected statement's
split anchor, and unread bar membership for the other modes. Compiler and
runtime resolve the same effective inputs; state mismatch or catalog bypass
is refused before statement-cache lookup. Non-nested cases do not change
ordinary scope bytes or legacy v1 feature hashes. No calculation is changed.

Price-ratio scopes use the same closed mode resolution: latest 1 ordinary/2 AM
rows for size, `long_n` for turnover and `long_n + 1` for price windows. AM
turnover is MVa throughout, including zero; scalar aliases use the existing
ingestion normalization priority, while positive price parsing is unchanged.
Size aliases are projected by one DataPlane owner, not the full vendor payload.
The D AM row omits full-day turnover, size and payload; optional size evidence
stays `absent_am_allowlist` and the consumer uses strictly-prior size. Scoped AM
result metadata comes from the existing trusted session capability. Legacy v1
hashes and formulas are unchanged; new scope-enabled metadata binds these needs.

This is not complete DRAFT plan binding: other legacy declarations and DRAFT
closure-to-runtime identity remain open work. Raw v0 features whose null-tail
fallback can inspect older history are not falsely assigned a fixed count.
Do not add READY/Receipt authorities to close that DRAFT gap.
Existing real SQLite boundary/numeric regressions cover these guards rather
than new getter-routing spies or context-shape-only tests.

Dataset membership is now checked at the same runtime entry for every feature,
including legacy definitions without field/window scopes. Generic catalog and
financial-state reads use the requested dataset identity, and an undeclared read
is refused before storage. The existing boundary regression covers this without
new test functions or authorities. This does not establish complete AM scope
projection or DRAFT closure binding.
Package and result metadata derive the feature runtime version from one value.

Personal `am_signal_pm_close` uses historical morning fields inside daily bars,
not the tip-only AM endpoint. Its closure and coverage read use that same daily
source and canonical retrospective field mask. A nonpositive/missing morning
adjusted close is missing evidence, never a daily-close fallback. Coverage is
labelled `RETROSPECTIVE_FIELD_TIME`, with no contemporaneous publication claim.
Paper reads retain the adapter's fixed, non-promotable observation cutoff; the
Controlled snapshot clock and READY requirements are unchanged. The existing
AM report test now runs a synthetic daily-only cohort through actual evaluation,
instead of stopping before warmup; compact coverage keeps its missing-price case.
Corporate-action AM-tip evidence can still be UNKNOWN and remains an explicit
report limitation, not a fictitious PASS.

The existing job-local prepared frame also reuses a measured logical snapshot
ID for an unchanged, standalone read-only DRAFT file. Initial ID comparison is
real; run boundaries check file identity/stat/permissions and sidecars. Mutable
input keeps its before/after measurements, Controlled is unchanged, and the
service's final raw-byte hash/catalog/SQLite verification remains. This removes
repeated whole-history COUNT/MAX work across folds without a new cache store.
Reusing a prepared view also requires the same normalized dataset membership,
period and dependency-closure digests. A changed request is rejected before
the existing artifact verification; it needs a separately bound view.
Personal prepared feature cells are DRAFT-only: the engine neither loads nor
stores them when a governed view or bound feature consumer is present. Thus a
matching cached value cannot skip Controlled current-plan validation. The
existing Controlled numeric/foreign-consumer regression warms real cells first;
DRAFT cache reuse remains covered by its existing query-count regression.

Financial ratio selection belongs to the existing DataPlane financial owner.
It selects the latest broadly qualifying finite statement and the latest prior
comparable distinct period, retaining stable tie order, counts and same-row
ratios. It is deliberately not the older BPS-preferred state. The selected
current/prior pair is compact; initial history is still traversed for PIT and
owner evidence, without a full statement sort. The existing ephemeral prepared
frame shares this state across modes only for a verified unchanged readonly
DRAFT snapshot and the same decision/observation clock. Mutable inputs and
Controlled sealed selection do not use it. Financial selection hits are counted
separately from completed feature hits. The existing numeric/SQL regression
observes four cold mode reads becoming one, with identical results; this does
not prove cloud runtime or billing savings or complete DRAFT closure-to-runtime
binding. Ratio financial/anchor declarations above use this same selector.

Scalar canonical encoding reuses the existing JSON encoder and directly renders
safe integers; binary64 coercion outside that range and finite/Unicode guards
are unchanged. New compact facts do not hash content for a comparison when no
previous vintage exists. Actual stored-vintage conflicts and idempotence retain
their comparisons. A bounded synthetic preparation profile preserves all stored
columns, source-response and facts digests; its local improvement is not evidence
of cloud runtime or invoice savings. Existing identity/numeric/hydration tests
cover the change; no additional mock or test-count target is introduced.

Stored-bar indexing emits bounded process-log metadata every 32 objects and when
a month is staged into the source spool, not when final snapshot facts complete.
It reuses measured counters, without reading storage, bodies
or secrets for diagnosis. Object-key `dt` names only the first row date and must
not be reported as the current hydration month. Logs help distinguish parsing,
range reuse and phase progress when a hard deadline prevents a terminal manifest;
they are neither snapshot completion nor permission for another paid attempt.
Private scratch keeps decoded bar payloads instead of parsing them again on daily
selection. Acquisition-cache expansion hashes its bounded output chunks while
writing, removing the subsequent whole-file hash read. Original object/span/raw
digests, vintage checks, gzip bounds and SQLite validation remain unchanged.
These removed passes do not establish full cloud runtime or invoice savings.

Compact stored-bar insertion reuses its latest-vintage lookup when that row has
the requested clocks, and skips an exact-vintage query when no prior row exists.
An older requested vintage still receives its exact conflict check before any
content-idempotence shortcut. No clock, digest, schema or transaction changes.
The existing real hydration regression covers replay and rejects changed values
at both latest and older clocks. A synthetic 4,000-row/two-vintage preparation
retained identical stored values, source-response digest and facts digest, while
price lookup SELECTs fell from 8,000 to 6,000. This measures scratch SQLite work,
not D1 RowsRead, full cloud runtime or invoice savings.

The existing month-window regression also covers a positive small reuse bound:
the full object with an out-of-period prefix cannot fit, but both requested
month windows fit. The real client receives `reuse_start`; both months survive
scratch reset without an additional R2 GET, with unchanged ordinals, rows and
source/span digests. Zero-cache and overlapping-window fallback cases remain
in the same regression. This does not close the observed 180-minute a4 timeout:
its historical logs do not establish phase timings or cache saturation.

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

- Compile each four-plan shortlist and its dependency closures once per loader
  call; derive profiles and execution pins from the same artifacts. Public
  constructors still compare complete artifacts with freshly compiled canonical
  values. Remove the second canonical compilation after that validation, not
  the validation itself. No global cache, new authority or changed digest format.
  Keep file edits observable on the next call and retain immutable owned values.
- Retire the local mirror's legacy HTTP transport (`--url`), its separate
  paging loop and mock-only transport tests. Cloud research already consumes
  R2; synthetic PIT fixtures now import real SQLite artifacts through the
  existing apply path. Keep cursor/revision/crash recovery and the existing
  apply-only/READY refusal checks. Signed private-mirror verification remains
  because READY consumers still import it; this change does not enable that
  path locally or delete any stored data.
- Retire its matching Worker `/v1/export/d1` and `/v1/export/changes` handlers;
  the repository has no remaining executable caller. Unknown/retired paths use
  the existing 404 without storage access. Keep the current bounded
  receipt-product metadata endpoint/RPC and its real workerd tests. Replace
  the old transport's Node matrix with three public-dispatch checks. No new
  proxy, redirect, database migration, history deletion or secret rotation.
  Unknown external callers are not claimed to have been inspected.

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
- Remove the remaining unreachable Worker proposal/Gateway client, request
  parser, period-ranking and daily-path wrappers, along with their dedicated
  tests and unused evaluator re-export. Their only executable callers were
  inside this retired graph or its tests; recover it from `0511df48dc00d22101482466e26471a0cf5d41e2`.
  Keep the actual Worker 403 route tests, current Personal/Controlled handlers,
  Gateway service and its budget tests, and shared index-volatility held-book
  calculations. This does not retire a deployed Worker or alter stored results.
- Follow the deleted wrappers' dependencies: remove their now-orphaned local
  strategy classifier, event-clock and path-label helpers and obsolete Mass
  request/result types. Remove the cross-runtime test whose only Worker target
  was that dead event-clock helper; the existing Python PIT entry regression
  covers missing/midnight/after-close clocks. Canonical Controlled plan
  validation and Personal signal construction are unchanged.
- Remove the isolated Python cost-comparison/daily-MTM/eval-registry graph,
  retired panel-staging stubs and historical hardcoded window lists. Their only
  remaining callers were each other and dedicated tests. Retain current Paper
  accounting, liquidity-linked costs, personal performance metrics and their
  tests. No D1 tables, R2 evidence or results are deleted; source recovery is
  available at `a2c5c90770874426c462690f8f9b4a7cd3dc98ff`.

Retiring unused paths reduces maintenance and test collection, not observed
cloud runtime. Deleted lines are not measured billing savings. Do not claim
the requested whole-repository reduction or a 50% target is complete.

## Measured active-path consolidation

Month-cache shard writing streams SQLite rows into a single prepared batch
instead of retaining a second complete row list and rebuilding SQL per row.
The verifier keeps bounded whole-table counts, checks each exact page's actual
rows once, and compares total observed rows against the table count. This
covers foreign/orphan rows without separate ownership scans or per-page COUNTs.
Cache bytes, schema, provenance and completion digests are unchanged. Import
remains one rollback-capable transaction; no new database, format or authority.
Six unused spool convenience/read methods are removed with test-only callers
redirected to the real verifier. Existing cache corruption/reuse tests retain
their guarantees; foreign-month and fractional-page cases plus a real SQLite
interrupted-import assertion extend those tests rather than adding a parallel
mock suite. Page ordinals must be actual integers, not truncated floats, so
the ownership check agrees with the later row/page join.

On a synthetic 60,000-row / 20-page shard (three tracemalloc-instrumented runs),
write median changed from 1.766s / 39.75MB peak to 0.269s / 2.12MB; verification
from 2.215s to 1.718s. The output SQLite SHA-256 was identical. Import time was
not improved (0.444s before / 0.456s after); its batch removes repetitive glue,
not proven runtime cost. These are local synthetic processing measurements,
not end-to-end cloud timings, fewer R2 requests or D1/invoice savings.

Personal DRAFT snapshot creation reuses its own measured dataset observations
and hashes when constructing the returned value. The backup still checks the
final standalone SQLite file; publication checks destination bytes and exact
manifest collisions. Reopening artifacts and end-of-run verification retain
the full independent verifier. No caller-supplied evidence or verification-skip
switch is added. A synthetic 18,976,768-byte fixture (three fresh creations)
reduced creation-only median time from 0.0835 to 0.0549 seconds: full-file hashes
3→2, dataset aggregate passes 2→1 and SQLite quick checks 3→1. This is not a cloud
snapshot benchmark or invoice measurement; the post-benchmark external verify
also passed and is excluded from those timings.

The continuous index-volatility base sleeve and subsequent candidate evaluation
share the existing bounded prepared frame for one pinned view. Do not delete
that cache between these stages. Snapshot/feature/session/as-of keys, size caps
and exception cleanup are unchanged; numerical rules and execution clocks are
unchanged. The service regression now runs a real canonical cohort on synthetic
data through both stages and observes reuse, replacing the isolated dispatch
predicate probe. Existing cached/uncached result-equivalence tests remain.

Structured-bar scratch text is internal JSON decoded by the same source client,
not a signed artifact or digest input. Use the standard finite JSON encoder
there; decoded rows still use canonical encoding at protocol/evidence boundaries.
A synthetic 12,000-row insertion with an already verified index took median 0.396 seconds
with the canonical renderer versus 0.125 seconds with standard JSON (three
passes, identical selected values). This excludes initial verification, the
whole cloud snapshot and billing. Page primary keys and existing contiguous
ordinal checks also make a second duplicate-page GROUP BY unnecessary.

Hourly production ingestion excludes the same-day AM tip before its official
noon-JST publication window and records `BEFORE_SAME_DAY_PUBLICATION` separately
from attempted dataset results. No vendor fetch, receipt or successful empty
segment is produced for that skip. Explicit manual requests are unchanged;
missing/malformed responses after the window still fail. See the
[official update schedule](https://jpx-jquants.com/ja/spec/data-update).

The shared Python/Worker key contract accepts explicitly null `Code` only for
EDINET major-shareholder filings, which include unlisted companies. It still
requires `DocId` and preserves the existing `{Code, DocId}` key for listed
filings. Omitted fields and unrelated dataset null keys still fail. No legacy
key rewrite, migration, history scan or data deletion is needed. Evidence:
[official document scope](https://jpx-jquants.com/ja/spec/edinet-major-shareholders).
Extend the existing cross-runtime vectors and real D1/R2 ingestion test instead
of adding a parallel mock suite. This is a contract repair, not recertification
of old receipts or authorization for another paid research run.

Full TSE cash sessions use one shared predicate in history hydration, PIT
universe selection, compiled scope, snapshot range checks, Coverage gap checks,
the index-volatility equity panel and the engine.
The [official 2020-10-01 whole-day halt](https://www.jpx.co.jp/news/1030/20201001-04.html)
is not a price-data gap. Retain the original calendar evidence and exclude
this documented halt from the execution session axis: do not fabricate prices,
zero returns or empty COMPLETE segments. An ordinary day's missing bars still
fail. Business dates for master/settlement and derivatives remain distinct;
this is not a general empty-day skip or permission to retry a paid run.

The cloud acquisition spool selects individual symbols and exact dates through
its existing indexes. SQLite's month-first plan otherwise scans unrelated rows
again for each financial series. Month/PIT predicates, ordering and provenance
are unchanged; range-only reads retain planner choice. No new index or cache.
On a synthetic 6,000-row / three-month fixture, one symbol selection fell from
36,274 to 225 SQLite VM steps and one exact-date selection from 36,206 to 121.
Rows and provenance hashes matched before/after. One real SQLite regression
bounds work rather than asserting SQL text or wall-clock timing. These are
synthetic measurements, not production runtime or invoice savings.

The stored-bars reader reuses its job-local month offsets for one bounded
R2 Range GET or one selected read from the existing 1 GiB compressed cache.
Initial whole-object verification is retained; selected-span hashes are derived
from that verified body, without rehashing overlapping monthly windows. The
reader keeps original ordinals, vintages and full-object provenance, and rejects
short responses or changed selected spans without a second full GET. Interleaved
input uses one enclosing range, not a request per span. The same 1 GiB cache now
stores verified month-window gzip files within the planned calendar range,
avoiding prefix reinflation for each month. If enclosing windows together exceed
the object size, retain one shared full gzip instead of duplicating them; this
fallback still seeks/decompresses the prefix. Inputs without a retained index
keep full verification and one shared gzip only when a requested month exists.
No new persistent cache, format or cloud resource is added. Existing behavior
tests cover both transports, month resets, shared fallback and corrupt spans;
no new test function or source-text check is added.

A synthetic 48 MiB body with 24 equal 2 MiB month windows gave a final-window
read median of 6.62 ms with full-gzip seeking versus 0.179 ms with month gzip;
returned bytes matched. Total compressed bytes rose from 376,902 to 385,104,
showing the per-window dictionary/header tradeoff. These are isolated synthetic
reads, not whole-snapshot or invoice savings. Initial flat-input validation
still reads all 927 objects (26,859,132,390 bytes for the pinned trial manifest).
Capacity fallback can still require R2 rereads. Actual runtime, transferred bytes
and billing must be measured from completed jobs; this source change does not
alter the already-running a4 image or retroactively improve a failed run.

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

Runtime universe binding now consumes the existing run-length mapping directly
instead of expanding, sorting and recompressing every day's codes. Ordinary
mapping inputs retain normalization, declared-run comparison and content digest
checks. The daily PIT-master intersection is unchanged. Coalescing builds one
run per interval, not a replacement run for every day. No data fetch or new
cache is added. A synthetic 2008–2026, 4,885-session / 4,000-code / 977-run
adapter measurement under tracemalloc changed from 6.29s / 1.00MiB peak to
1.61s / 0.66MiB; the digest is identical. This is not end-to-end cloud timing.

Personal DRAFT now passes its expected snapshot id to the canonical paper
runner. The runner alone reads logical identity before and after calculation,
rejecting an initial mismatch before financing/engine reads and any change
during execution. This removes the adapter's duplicate pair (four identity
reads become two per backtest), without caching mutable identity or removing
the final artifact check. A freshly materialized snapshot already returns
verified, so its caller no longer immediately repeats the full hash/catalog
verification. These savings concern cloud scratch SQLite/CPU, not D1 billing.

Financial statement selection, alias handling, comparable-period growth and
ratios now have one calculation owner for ordinary and AM-session DRAFT
features. AM capability checks, strict-prior price selection and split blackout
stay in the existing session-specific price callback. Dataset reads, original
clocks and result metadata are unchanged; this is not full dependency-scope
closure, READY acceptance or measured cloud cost reduction. Remove the copied
registry/mode constant test; the existing known-value alias cases now exercise
both feature entries and compare metadata apart from the explicit session tag.
Existing statement-revision, missing-value, AM causality and split tests remain.

## Next acceptance work

Ops projection no longer mints legacy B0/B4 attestations. That producer always
had null export/applied cursors (hence UNKNOWN), yet re-counted the whole change
log, re-read validation/Coverage and inserted another signed source-DB row.
Remove it and its legacy quality reader: global Ops B0/B4 stays explicitly
UNKNOWN, while the existing native READY observer retains snapshot-scoped proof.
Historical quality tables/rows and migrations are preserved, not deleted.
The existing projection test now runs against an actually read-only source DB
with a legacy PASS row, verifies UNKNOWN and unchanged-source no-op behavior.
This removes queries by construction; production read/fee savings remain unmeasured.

Continue the table above: consolidate active feature/evaluation/data access,
remove repeated current-path scans and heavyweight test setup, and reduce
unnecessary build selection. Validate actual runtime/bytes/D1 reads separately
from source size. Do not wait for this worklist to be exhausted before an
authorized useful experiment. No new long-history performance was produced
by source retirement; source acceptance does not authorize another paid
attempt, change existing HOLDs, or establish READY/Pilot GO.
