# Phase 6.2.2 Independent Review (Grok)

**Note:** Instruction preferred independent GLM review. GLM OAuth expired / unavailable;
this is a Grok structural re-audit of main after Phase 6.2.2 remainder land.
When GLM returns, re-run full independent review over this diff.

**HEAD reviewed:** post-`62f7cb8` remainder (issuer wire + evidence + scheduler).

## Findings

| Severity | Mechanism | Fix | Structural guarantee | Status |
|----------|-----------|-----|----------------------|--------|
| P0 | Mass GO via caller scalars / `go_override` | Attestation-only `VerifiedResearchReadiness` | No scalar API on start path | **closed** |
| P0 | Gateway raw dict fallback | `GatewaySchemaRejected` fail-closed | No `decode=False` production API | **closed** |
| P0 | Handwritten backfill inventory | `BackfillPlanner` from Coverage Contract | `fins_details` auto-included | **closed** |
| P0 | JSDA max=3 PASS heuristic | Allowlist + full discovery + immutable keys | CF raw plane | **closed** |
| P0 | TRUSTED_COLLECTION string forge | `TrustedReceiptIssuer` required for COMPLETE | `is_complete_eligible_receipt` | **closed** |
| P1 | concurrent_experiments cumulative | Lease `acquire_slot` | Max active leases | **closed** |
| P1 | Policy object as "sandbox" | `SandboxedAgentRunner` | Deny shell/network/code | **closed** |
| P1 | READY multi-evaluator drift | Typed evidence + sole policy | `publish_ready_snapshot` policy gate | **closed** |
| P1 | JSDA structured on CF | Python `r2_parse` trusted path | No XLS in Workers | **closed** (foundation) |
| P2 | Live 26 COMPLETE / READY mint | Ops backfill (running) | Not a code forge | **open (ops)** |
| P2 | MCP projection FRESH live | Publish + backfill | Live evidence | **open (ops)** |
| P2 | Independent GLM re-review | Queue when OAuth restored | Process | **deferred** |

## P0 unresolved

**0** (code-level spoofing paths for mass research / COMPLETE / gateway).

## Mass research

**NO-GO** until live `ResearchReadinessService.mint()` succeeds on production DB
with all §13 conditions. Scheduler and start APIs fail closed without attestation.

## Human gates remaining

1. GLM OAuth restore for independent re-review  
2. Live capital / broker (explicitly out of scope)  
3. Waiting on long CF backfill for COMPLETE evidence (not a code task)
