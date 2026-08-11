# Phase 6.1 / Pre-Phase 7 hardening plan

Recorded start HEAD: `ac0c676 feat(phase6): hardening acceptance + data access foundation`

This phase is intentionally landed as a reviewable commit series. One logical
concern belongs in one commit; coverage, pagination, MCP, JSDA, and operational
documentation are not combined. Focused tests run after every commit that
changes code, and the full offline suite runs before completion.

## Phase 6 guarantees retained

- PIT remains mandatory for fact reads: callers provide `as_of` and structured
  rows remain bounded by `available_at <= as_of`.
- Published `READY` snapshots remain immutable and content addressed. Phase 6.1
  strengthens their admission proof; it does not add a mutable research path.
- StrategySpec v2, feature approval/version governance, raw retention, token
  separation, natural-key identity, and the capability model are extended, not
  rewritten.
- Remote MCP exposes domain-level read tools only. It never exposes SQL, D1/R2
  handles, secrets, shell, arbitrary fetch, ingestion, deletion, publication,
  feature approval, or broker capabilities.
- Local stdio MCP remains an offline/dev adapter. Browser and mobile clients use
  authenticated streamable HTTP MCP.

## Planned files

Existing files expected to change:

- Coverage and publication: `data_contracts/coverage.py`,
  `storage/coverage_ledger.py`, `storage/schema.py`, `storage/migrations.py`,
  `paper_runtime/snapshot.py`, and focused coverage/snapshot tests.
- PIT paging: `pit/api.py`, `pit/query.py`, `data_access/adapter.py`, and
  `tests/test_phase6_data_access.py` (plus a focused pagination test if clearer).
- Shared MCP domain service: `data_access/`, `mcp_servers/quant_data/server.py`,
  and the MCP/data-access tests.
- JSDA: `ingestion/jsda/`, `ingestion/pipeline.py`, `storage/sqlite_store.py`,
  `data_contracts/`, JSDA fixtures/tests, and source documentation.
- Documentation: `README.md`, `docs/architecture.md`,
  `docs/quant_data_access.md`, and `platform/README.md`.

New files/directories expected:

- A Coverage V2 migration/contract and structural tests for receipts, segments,
  and READY rejection.
- `platform/workers/quant-ops-mcp/` containing a Cloudflare Worker, D1-backed
  quota migration, Wrangler configuration, unit tests, and connection/auth docs.
- JSDA governed dataset contract(s), discovery fixtures, and a production
  migration/backfill/READY runbook under `docs/`.

The list can narrow during implementation, but additions must stay inside the
listed concerns and their own commit boundary.

## Lane dependencies

- Lane A (Coverage V2 receipts/segments) has no dependency and defines the proof
  consumed by READY, Ops MCP, and JSDA ingestion.
- Lane B (SQL keyset pagination) is independent until its cursor is wired through
  the shared read service/local adapter.
- Lane D (JSDA OTC archive contracts/discovery) starts independently, then emits
  Lane A receipts once the receipt API is stable.
- Lane C (shared service and remote Ops MCP) starts against stable Lane A query
  shapes. Research data stays local unless a published READY generation can be
  pinned in Cloudflare.
- Lane E (repo rate, corrections, and transactions) follows the governed JSDA
  contract/identity decisions from Lane D.
- Lane F (runbook and architecture docs) follows the implemented C/D surfaces.

## Ordered commit list

1. `docs: phase 6.1 plan and reviewable commit policy`
2. `feat(coverage): add collection receipts and segment model`
3. `feat(snapshot): require Coverage V2 proof for READY`
4. `feat(pit): add SQL-level keyset pagination`
5. `feat(mcp): extract shared read-domain service`
6. `feat(mcp): add Cloudflare remote Ops Read MCP`
7. `feat(auth): protect remote MCP and enforce read scopes`
8. `feat(quota): add durable remote subject quota`
9. `feat(jsda): govern OTC bond archive ingestion and receipts`
10. `feat(jsda): ingest Tokyo Repo Rate history`
11. `feat(jsda): preserve correction and revision provenance`
12. `feat(jsda): add distinct corporate bond transaction datasets`
13. `docs(mcp): document remote-first and local dev adapter`
14. `docs(ops): add production READY backfill and migration runbook`
15. `docs: update architecture for Coverage V2 and governed JSDA`

If a concern grows beyond roughly 20 files it will be split again. The existing
uncommitted `docs/quant_data_access.md` multi-client notes are preserved and
will be reconciled in commit 13, not mixed with coverage or JSDA code.
