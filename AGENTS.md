# Development responsibilities

- Current user direction (2026-09-21): Grok's subscription has ended. Codex owns investigation, implementation, checks and Git until the user changes this direction. Do not start Grok or a paid replacement. The Grok-first rules below describe the normal arrangement when Grok is available.
- Do not re-run Grok's source/caller investigation or bounce tiny questions back to Grok inside a coherent work unit. Use Grok's diagnosis, implementation, failure analysis, self-review, Git, and exact-source native CI at work-unit granularity. Do not split command confirmation or log watching into a separate Codex lane.
- Grok owns a bounded unit end to end: investigate source and callers, choose the simplest justified design and implementation, edit, run minimal targeted local checks, diagnose failures, self-review, Git, exact-source native CI, and approved rollout. Prefer that useful investigation, design, implementation, failure analysis, and self-review over patch-only edits.
- When Grok hits an actual permission denial or missing authentication, Codex may mechanically apply only the needed operation from Grok's patch and selected checks, then return the results for Grok to diagnose. That fallback is mechanical execution only. Codex may implement only when Grok cannot; report the fallback.
- Codex owns high-level policy and direction and independent final review of the actual diff. Evaluate findings against code and behavior; record accepted fixes and evidence-backed rejections. Cross-review does not require automatic agreement or replace tests and exact-source native CI.
- Actual Grok task, session, and usage evidence is distinct from billed account usage and quota telemetry. Do not add filler work, disable caches, switch to paid APIs, top up, or add model services to move a usage meter.
- Subagents are for independent critical review only. They report findings and evidence, do not edit files, and do not spawn agents. The main agent evaluates and resolves findings.
- Keep logical changes reviewable and push completed work units. Preserve native Cloudflare required checks on the exact final source SHA; never bypass them. Remove completed branches after confirming merge and preservation of their work.
- Separate source delivery, staging rollout, production rollout, data activation, READY and Pilot execution. Source publication approval does not authorize production deployment or research execution. Preserve deployment HOLDs and use the applicable approval flow.
- Follow the current operational attachment and work ledger. Keep at most three work units in progress; do not concurrently change shared contracts.
- Do not persist authentic market history on this local machine or run local Docker/VM backtests. Small synthetic test fixtures are permitted.
- Preserve PIT and AM-to-PM causality, historical-data provenance, immutable evidence and budget limits. Keep Mass, FoF, broker, live orders and automatic promotion disabled; do not add new authorities or enterprise-only security complexity.
- Never read, acknowledge or purge production DLQ message bodies as part of ordinary development.

## Simplicity and tests

Canonical detailed policy: [docs/ci/invariant_test_audit.md](docs/ci/invariant_test_audit.md).

This is a personal single-user Cloudflare quant research product. Prefer deleting unused runtime code and its tests together over adding a replacement framework.

- Prioritize real numeric correctness: known-input/expected-output, returns/positions/PnL/costs, PIT/AM-to-PM no lookahead, and meaningful accounting.
- Keep only minimal practical guards against missing/corrupt data, uncontrolled charge, and accidental real orders.
- Trusted host, closed DSL/JSON, no arbitrary generated Python. Do not build or test hostile same-process Python reflection/subclass/frozen-object attacks, root-adversary/WebAuthn/extra signers, or enterprise authority layers unless a new explicit user need is established.
- Before adding a layer or test, state the concrete current failure it catches and whether existing code/library/schema/test already covers it. One representative numeric/behavioral regression per distinct real failure. No test-count/coverage targets, source-name/phase-label tests, exhaustive input-form matrices, just-in-case retention, or a test of this policy prose.
- Do not weaken authentic data, PIT, budget enforcement, or explicit deployment HOLDs merely to simplify.

## One-outcome approval

Ask once for a work outcome: targets, finite cost basis, stages and smokes,
rollback, and exclusions. Ordinary same-scope source fixes, tests, Git,
native CI, and PREPARED-identity recovery are included in that ask. Re-ask
only when the outcome's scope, cost, or destructive surface materially
changes. Never bypass explicit HOLDs (production auto-deploy, Mass research
GO, READY/Pilot, public Premium HTTP, local authentic market SQL).

Approval requests must be understandable without reading earlier updates.
State why the outcome is needed, exact environment/resources/data periods,
the concrete operations and their order, expected cost and enforced limits
versus estimates (never call a monitoring target a billing hard cap), success
evidence, stop conditions, rollback or forward-recovery actions, and exclusions.
Group related operations into one outcome; do not repeatedly ask per command.
