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
