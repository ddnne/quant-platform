# Invariant test audit

This is the current test authority map. A test may demonstrate an invariant,
but it must not create the security boundary it claims to test. Production
boundaries therefore live in types, opaque capabilities, immutable stores,
transactions, cryptographic verification, Cloudflare bindings, or runtime
sandboxing. Source spelling, comments, phase names, and historical counts are
not release authorities.

| Invariant | Structural enforcement | Minimal acceptance test |
| --- | --- | --- |
| PIT time wall and daily universe | PIT readers require explicit `as_of`; the engine intersects a fixed candidate allowlist with the PIT master on every decision day | `tests/test_core_engine.py::test_fixed_allowlist_is_intersected_with_daily_pit_membership` |
| Reconciled collection receipt | Only the governed acquisition/reconciliation service can consume opaque persisted fetch evidence and mint a signed receipt | adversarial cases in `tests/test_jquants_receipt_emit.py` |
| Coverage V3 false-complete rejection | Dataset-specific SourceCapability and Coverage policy digests define the required domain; receipt eligibility is policy-bound | `tests/test_collection_coverage_v3_from_capability.py` and `tests/test_source_capability_core_v3.py` |
| Profile/closure-bound READY | The dedicated publisher verifies the signed Ops evidence, exact plan closure, PIT availability, immutable DB digest, and dedicated READY key | `tests/test_ready_policy_fail_closed.py` and `tests/test_ready_manifest.py` |
| Immutable snapshot/artifact | Snapshot handles verify read-only mode and content digest; Worker R2 create-only operations use conditional writes | `tests/test_phase6_snapshot_publication.py` and Worker R2 runtime tests |
| Controlled Paper authorization | `OfflineFixturePaperService` and `ControlledPilotExecutionService` are distinct entrypoints; the controlled type requires verified readiness and an immutable snapshot | `tests/test_controlled_pilot_execution_service.py` |
| Strict Gateway rejection | Closed request/output schemas are validated before an artifact is returned | `tests/test_gateway_fail_closed.py` and Gateway runtime tests |
| Budget concurrency and settlement | BudgetLedger Durable Object serializes reservations and settles only through the Gateway coordinator bound to lease, digest, provider-start, and a one-shot settlement capability | `platform/workers/research-ai-gateway/src/budget_runtime.test.ts` and `index_complete_budget.test.ts` |
| OAuth boundary | The Ops MCP Worker requires OAuth while public metadata remains available | `platform/workers/quant-ops-mcp/runtime/ops_runtime.test.js` and `harness/oauth_harness.test.ts` |
| Exact-four only | ExperimentPlan compilation resolves exactly four immutable strategy/feature/dataset closures; Mass accepts a distinct readiness type and remains disabled | `tests/test_experiment_plan_v2_dependency_closure.py` and `tests/test_phase7_pilot_construct.py` |

## Consolidation decisions

- Removed tests and scripts that fixed a historical `22 COMPLETE / 4 PARTIAL`
  snapshot as policy.
- Removed wave/phase filename guards and optional helper-script source checks.
- Removed repeated AST/import/comment/function-name assertions where public
  behavior, closed schemas, capabilities, runtime bindings, or OS sandbox tests
  already enforce the boundary.
- Replaced R2 implementation-source assertions with calls through the public
  adapter and an observed pinned `wrangler r2 object get --remote` command.
- Retained serialized fixture/schema/config reads only when the file itself is
  the governed input under test; those reads do not authorize READY or GO.

The final release evidence records suite totals and runtime suites. Test count
is diagnostic only and is never a GO condition.
