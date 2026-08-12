> **Historical snapshot** — not current residual SoT.
> Current residual: [phase62_residual_status.md](phase62_residual_status.md).
> Mass / READY / Phase7: **NO-GO / OFF** unless residual says otherwise.

# Phase 6 hardening acceptance

Acceptance date: 2026-08-11. Base: `d502db9`.

P0 UNRESOLVED = **0**.

## Findings and closure

| Finding | Severity | Phase | Fix | Structural guarantee | Status |
|---|---:|---|---|---|---|
| A. Mutable research database could be read in place | P0 | 6 | Staging → strict gate → content-addressed SQLite + manifest atomic publication | Published DB/manifest are `0444`; discovery verifies state, hashes, embedded manifest, watermarks and permissions; SQLite opens `mode=ro&immutable=1`; PIT rejects managed non-READY generations; fact/revision triggers invalidate mutable generations | RESOLVED |
| B. D1 v2 SQL identity differed on missing fields | P0 | 6 | `0005` is control/staging only; Worker application rebuild uses the shared canonical function, SHA-256 fallback, collision grouping, atomic live swap and full primary/revision/change audit | Write/export paths stay closed until migration state is READY; Python ↔ TypeScript parity is executed in tests | RESOLVED |
| C. Upstream `available_at` could become trusted metadata | P0 | 6 | Removed row-field override; only canonical contract policy derives metadata | A source field named `available_at` remains only inside payload/raw payload; Python override is an explicit trusted-caller argument | RESOLVED |
| D. Persisted StrategySpec could float feature versions | P0 | 6 | `strategy-spec/v2` requires `FeatureRef{id,version,params}` | Legacy/flat persisted specs fail closed; interpreter resolves exact approved version; hashes and experiment identity contain the pin | RESOLVED |
| E. Coverage existed only as transient validation output | P0 | 6 | Added collection contract and `dataset_coverage` ledger for all 23 canonical datasets | Status vocabulary is closed; irregular events are event-reconciled without invented daily row counts; governance tier is explicit | RESOLVED |
| F. Snapshot publication lacked one closed gate | P0 | 6 | Added BUILDING → SYNCED → VALIDATING → READY/REJECTED state machine | READY requires the complete governed set, strict B0/Phase 3.5 checks, COMPLETE coverage, and COMPLETE same-run raw manifest attestations | RESOLVED |
| G. Large endpoints retained only a sample | P1 | 6 | Worker streams every upstream response page to `raw/<dataset>/<run_id>/page-NNNNNN.json` and writes `manifest.json` | No `data_truncated` production path; per-page and aggregate SHA-256, page/row counts, bytes and completeness are attested in D1 and the READY manifest | RESOLVED |
| H. One token authorized unrelated operations | P1 | 6 | Split `JQUANTS_PROXY_TOKEN`, `INGESTION_RUN_TOKEN`, and `DATA_EXPORT_TOKEN`; local direct key requires `UNSAFE_DEV_DIRECT_JQUANTS=1` | Proxy is exact-path upstream GET only; run and export tokens cannot substitute at Worker handlers; agent objects receive none | RESOLVED |
| I. Role security depended mainly on forbidden strings | P1 | 6 | Role matrix now grants positive capability objects and the pipeline passes immutable structured messages only | No role capability represents SQLite/D1/R2, path, token, HTTP, shell, Python evaluation or broker execution | RESOLVED |
| J. FeatureContext exposed its database path | P1 | 6 | Context exposes only `as_of`, `get_input`, and PIT-scoped getters | Runtime owns the private reader closure and database scope | RESOLVED |
| K. No safe LLM data access surface | P1 | 6 | Added Quant Data Access MCP + `ops_status.py` | READY-only, read-only, `as_of`-mandatory, allowlisted, bounded and paginated; no SQL or operations writes | RESOLVED |
| L. Derived paper/risk indexes and writes needed recovery/concurrency hardening | P1 | 6 | Paper index rebuilds atomically from immutable JSON; risk uses create-if-absent and verifies content-derived id | Index is disposable; paper/risk evidence cannot be overwritten by a concurrent writer | RESOLVED |
| M. Agent outputs lacked common lineage | P1 | 6 | Added immutable `agent-artifact/v1` envelope | Artifact id covers type, version, producer, parents, snapshot, timestamp and deeply frozen payload | RESOLVED |
| N. PM/trader handoff resembled an informal plan | P1 | 6 | Added `AuthorizedPaperExecutionRequest` | It is data-only, `mode=paper`, and contains reviewed spec hash/authorization id; no broker/order capability exists | RESOLVED |
| O. Add-on governance was implicit | P1 | 6 | Coverage contract requires `governed` or `experimental` | READY publication admits exactly the governed dataset set | RESOLVED |

## Capability matrix

| Component | Positive authority | Explicitly absent |
|---|---|---|
| Macro / Fundamental / Quant | Structured `ResearchRequest` → memo | Data handles, paths, raw, tokens, HTTP, shell, broker |
| Composer | Compose typed memos | Facts and execution |
| Strategist | Produce closed StrategySpec with exact FeatureRef | Registration, arbitrary code, data access |
| Portfolio manager | Authorize Paper policy only | Runtime and broker access |
| Trader | Produce `AuthorizedPaperExecutionRequest(mode=paper)` | Orders, broker, credentials |
| Risk | Audit persisted immutable Paper result | Paper mutation and execution |
| Trusted Paper/Feature runtime | PIT reads from a READY generation; immutable result writes | Network and live execution |
| J-Quants proxy | Exact contract paths, upstream GET | Arbitrary path/method, ingest/export |
| Ingestion run | Manual ingestion and key rebuild | Data export |
| Data export | Bounded structured export/change feed | Ingestion and proxy |
| Quant Data Access MCP | Catalog, coverage, READY snapshot, quality, PIT query, approved feature, manifest/provenance reads | SQL, paths, R2 browse, writes, tokens, HTTP, shell, broker |

## Test hygiene

Critical invariants retained or strengthened: canonical contract parity,
Python/Worker identity parity, upstream availability forgery rejection, PIT
`as_of`, revision visibility, monotonic change feed, READY publication gate,
immutable artifact access, exact FeatureRef execution/hash identity,
parallel-safe/rebuildable experiment index, risk content hash, and full
agent→Spec→Paper→Risk E2E. Role/data-boundary AST coverage remains one broad
backstop rather than per-role/per-dataset case multiplication; no redundant
look-ahead matrix was added.

## Offline operational acceptance

This repository intentionally contains no published production READY snapshot,
so current local coverage is `UNKNOWN`, not fabricated. Compute the actual
status after sync/publication with:

```bash
.venv/bin/python scripts/ops_status.py --json
```

`snapshot.state == READY`, `coverage.governed_ready == true`, B0 `PASS`, and
validation `PASS` are the operational release conditions. `coverage_gaps`
is the authoritative incomplete/backfill list. Without a READY snapshot all
23 governed datasets remain operationally unaccepted; this does not reopen a
code finding.

Latest snapshot resolution scans and verifies immutable READY sidecars and
sorts by `committed_at`; the mutable convenience pointer is non-authoritative.

## Deferred

- Apply D1 migration `0006_raw_retention_manifests.sql`, deploy both token
  splits, run the v2 key rebuild, complete any reported backfills, sync, and
  publish the first production READY snapshot.
- A write-capable DataOps MCP is a separate future service and must not share
  this MCP's process or credentials.
- FoF, live brokers/orders, arbitrary model code evaluation, and unbounded
  self-improvement remain out of scope.

## Phase 7 decision

**Code acceptance: GO. Operational mass research: NO-GO until
`ops_status.py --json` reports a verified READY snapshot with governed coverage,
B0, validation, and raw retention all passing.**

