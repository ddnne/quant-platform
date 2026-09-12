# Development responsibilities

- Grok is the default coding implementer (including fixes and test changes). Codex may implement when Grok is unavailable or rate-limited; report the fallback.
- Grok also performs a primary review of its changes. Codex independently reviews the actual diff and evaluates findings against code and behavior; record accepted fixes and evidence-backed rejections. Cross-review does not require automatic agreement or replace tests and exact-source native CI.
- Codex owns task direction, investigation, review, verification, commits, pushes, PRs, required CI and merges. The user approved this division on 2026-09-11; apply it to subsequent development too.
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
