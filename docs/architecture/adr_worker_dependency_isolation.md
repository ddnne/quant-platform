# ADR: Worker dependency isolation

| Field | Value |
|-------|-------|
| **Status** | **Accepted (review after native-build parity exists)** |
| **Date** | 2026-08-25 |
| **Scope** | Seven active Cloudflare Workers under `platform/workers/` |
| **Related** | [`../ci/workers_builds.md`](../ci/workers_builds.md), [`adr_llm_friendly_refactor.md`](./adr_llm_friendly_refactor.md) |

## Context

The preferred repository shape is one npm workspace, one lockfile, and shared
TypeScript/Vitest configuration. The seven active Workers are currently deployable
units with independent Cloudflare build roots and independent rollback surfaces.
Changing dependency ownership while the native required check and production
bindings are being closed would combine a release-boundary migration with the
trust-boundary changes in Phase 6.3.1.

The deprecated `ci-aggregate` Worker and its former seventh lockfile were
removed. The later `receipt-evidence-authority` boundary deliberately introduced
one isolated lockfile again: it is a dedicated signing authority with an
independent Cloudflare build root, Durable Object migration, activation
ceremony, and rollback surface. The resulting seven lockfiles belong only to
active deployable Workers. Wrangler and Cloudflare test-tool versions are pinned
to the same exact versions and checked by the repository-root native build.

## Decision

Keep one lockfile per active Worker for this release. This is a temporary build
isolation exception, not permission for dependency drift.

The following are mandatory while the exception exists:

- the binding manifest and native required check cover all seven Workers from
  the machine-readable active-Worker inventory;
- base, production, and staging dry-runs are executed for every Worker;
- Wrangler, Vitest, and Cloudflare runtime-test packages use repository-wide
  exact versions;
- generated `Cloudflare.Env` types and typechecks must pass;
- no shared runtime code is copied between Worker directories merely to avoid a
  workspace package.

## Exit criteria

Move to one npm workspace and one lockfile only after a trial proves all of the
following on a review branch:

1. every Worker can still build and deploy from its documented Cloudflare root;
2. build-watch paths do not skip a required Worker check;
3. staging and production dry-runs remain isolated and deterministic;
4. per-Worker rollback does not require resolving unrelated dependency changes;
5. the authoritative required-check name and source do not change silently.

Until those conditions are demonstrated, consolidating the seven lockfiles is a
deferred refactor. The receipt-authority lockfile is the reviewed temporary
exception for its dedicated authority and rollback boundary; adding an eighth
active-Worker lockfile requires a new reviewed ADR amendment and matching
machine-inventory coverage.
