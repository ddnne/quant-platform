# Personal research development

- The main agent owns investigation, analysis, design, implementation and integration. Codex currently owns this work; do not start Grok or a paid replacement without a new user instruction.
- Subagents are only for independent critical review. Reviewers report findings and evidence, never edit files or spawn agents. The main agent evaluates findings, fixes issues and makes the final decision.
- This is a personal single-user product. Operations and backups should be very simple. Do not add enterprise authority, monitoring or backup systems without a concrete user need. Reuse existing components and remove unnecessary layers.
- The product outcome is reproducible strategy construction and comparable performance results. Report actual executions, economic rationale, periods, costs and limitations; CI, deployment and test counts are not research results.
- Simplification covers the entire repository and processing chain, not only storage: acquisition, features, evaluation, reports, execution, CI, deployment and operations. Delete unused product paths with their tests and callers; centralize existing responsibilities instead of adding wrappers. Moving/splitting code is not a reduction. Use the repo-wide worklist in [simplification](docs/architecture/personal_simplification.md).
- Periodically review the whole codebase for duplicate features, processing and scattered external access. Consolidate each domain's access in its existing owner so fixes reach every caller; avoid new general-purpose frameworks or enterprise-scale implementations for this single-user product.
- Personal DRAFT and Controlled Pilot are distinct existing paths. Do not make unrelated production completion a prerequisite for DRAFT. Do not relabel failed Controlled evidence as DRAFT, bypass explicit HOLDs, or represent DRAFT results as verified Controlled results.

## Correctness, cost and data

- Preserve numeric correctness, PIT/AM-to-PM causality, historical provenance, immutable evidence and budget limits. Missing observations are not zero returns or successful evidence. Keep Mass, FoF, broker, live orders and automatic promotion disabled unless explicitly authorized.
- Keep practical guards against corrupt/missing data, uncontrolled charges and accidental real orders. Before adding a layer or test, identify the realistic failure and whether existing structure already covers it.
- D1 is for small indexed mutable metadata, not historical bodies, repeated history-wide aggregates or per-row shadow copies. Compute run summaries while already processing the data; reuse verified R2 partitions across strategies. R2 storage alone does not prove low read/compute cost.
- Minimize paid reads across all API/storage services. Inspect source and synthetic fixtures first; reuse saved results. Do not run full-table scans, COUNTs, repeated metadata polls or market-data refetches merely for reassurance. A necessary external check must answer a specific unresolved question with the smallest bounded query; batch it and avoid repeating unchanged checks.
- Prefer one representative numeric or behavioral regression per distinct failure. Delete redundant implementation-copy, mock-self-check, library-guarantee and source-text tests. Test counts and coverage percentages are not goals. Detailed policy: [invariant test audit](docs/ci/invariant_test_audit.md).
- Do not persist authentic market history locally or run local Docker/VM backtests. Small synthetic fixtures are permitted. Historical bodies belong in R2; use bounded D1 metadata and cloud scratch. Preserve existing data and signed evidence during authorized migrations. Architecture: [cloud storage plane](docs/architecture/cf_native_storage_plane.md).
- Never read, acknowledge or purge production DLQ message bodies during ordinary development.
- This repository is public. Never put keys, tokens, credentials or secret-bearing logs in commits, PRs or artifacts. Check the staged diff before publication; use existing secret storage without printing values.

## Delivery and approvals

- Keep logical changes reviewable, push completed units, and require native Cloudflare checks on the exact final SHA before merge. Remove completed branches only after confirming their work is preserved.
- Keep logical commits but batch reviewed related commits into one push; do not use remote full CI as an edit/test loop. Run focused local synthetic checks first. Keep build dependency caching enabled. Measure build minutes, D1 reads and completed research runtime separately; reducing one does not establish savings in the others.
- Separate source delivery, staging, production, data activation, READY and Pilot execution. Simplifying documentation does not change authorization or remove HOLDs. Follow current explicit approvals; verify live state rather than trusting old completion claims.
- Group approval requests by outcome, not individual command. Explain why approval is needed, targets and periods, operations, costs and enforced limits versus estimates, stop conditions, recovery and exclusions. A monitoring target is not a billing hard cap. Re-ask only when scope, cost or destructive impact materially changes.
