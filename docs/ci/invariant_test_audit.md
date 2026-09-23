# Invariant test audit

This is a personal single-user Cloudflare quant research product on a trusted
host. Tests catch real current failures; they do not simulate an untrusted
multi-tenant enterprise.

## Retired research deploy adapter

The unused `deploy_cf_mass_eval_worker` adapter, its environment toggle and
unused deploy protocols are removed together with
`tests/test_cf_mass_eval_deploy_opt_in.py`. Repository caller inspection found
only that test invoking the adapter. Its three cases checked the toggle,
missing-toggle refusal and a fake deploy-port/subprocess success. Deleting the
adapter removes that deployment capability rather than leaving an untested
entrypoint. Actual Ops deployment configuration/version acceptance and its
tests remain unchanged, as do Mass host refusal and no-HTTP tests. No numerical
or budget calculation is removed. External users of this internal Python API
were not inventoried; this is not cloud Worker retirement or rollout approval.

**Policy**

1. Prioritize real numeric correctness: known-input/expected-output,
   returns/positions/PnL/costs, PIT/AM-to-PM no lookahead, and meaningful
   accounting.
2. Keep only minimal practical guards against missing/corrupt data,
   uncontrolled charge, and accidental real orders.
3. Closed DSL/JSON only. Do not build or test hostile same-process Python
   reflection/subclass/frozen-object attacks, root-adversary/WebAuthn/extra
   signers, or extra enterprise authority layers unless a new explicit user
   need is established. Cheap production type guards, including ``@final``,
   do not require hostile-subclass tests; do not add such tests.
4. Before adding a layer or test, state the concrete current failure it
   catches and whether existing code, library, schema, or test already covers
   it. Prefer deletion/consolidation over a replacement framework. No
   test-count or coverage targets, source-name or phase-label tests,
   exhaustive input-form matrices, just-in-case retention, or a test of this
   policy prose.
5. Review runtime code and tests together for dead code, duplicate ownership,
   and needless abstraction. Delete unused runtime code and its tests
   together. Do not keep env-flag helpers or constant-equality tests that
   production never consults. Test doubles must follow the production contract;
   production must not keep reflection or compatibility branches only for stale
   fakes. Small logical commits; do not drop active numerical semantics.
6. Do not weaken authentic data, PIT, budget enforcement, or explicit
   deployment HOLDs merely to simplify.

This document is the detailed policy linked from root `AGENTS.md`. It is not
a claim that every module or test has been reviewed.

A test may demonstrate an invariant, but it must not create the security
boundary it claims to test. Where a real production boundary exists today, it
lives in types, opaque capabilities, immutable stores, transactions,
cryptographic verification, or Cloudflare bindings. Do not add OS-sandbox
or extra authority frameworks. The unused macOS sandbox-exec runner was
removed; Cloudflare Container / enableInternet=false / closed DSL remain.
Source spelling, comments, phase names, and historical counts are not
release authorities. Table wording such as malicious CWD or adversarial
cases describes those existing packaging and signed-receipt checks, not a
charter for extra hostile-Python tests.

| Invariant | Structural enforcement | Minimal acceptance test |
| --- | --- | --- |
| PIT time wall and daily universe | PIT readers require explicit `as_of`; the engine intersects a fixed candidate allowlist with the PIT master on every decision day | `tests/test_core_engine.py::test_fixed_allowlist_is_intersected_with_daily_pit_membership` |
| Reconciled collection receipt | Only the governed acquisition/reconciliation service can consume opaque persisted fetch evidence and mint a signed receipt | adversarial cases in `tests/test_jquants_receipt_emit.py` |
| Installed SourceCapability authority | The exact 11 JSON contracts are package data beside the loader; default loading has no repository/CWD fallback and fails closed on an incomplete bundle | `scripts/verify_source_capability_wheel.py` builds and installs the real wheel, then probes it from empty and malicious-decoy CWDs |
| Installed Receipt verification authorities | Coverage-transition public keys and signed Receipt claim schema are immutable package data beside their verify-only consumers; repository/CWD lookup is absent | `tests/test_storage_authority_packaging.py` pins their bytes/canonical digests and the installed-wheel probe imports the acquisition and reconciliation runtimes |
| Coverage V3 false-complete rejection | Dataset-specific SourceCapability and Coverage policy digests define the required domain; receipt eligibility is policy-bound | `tests/test_collection_coverage_v3_from_capability.py` and `tests/test_source_capability_core_v3.py` |
| Profile/closure-bound READY | Dedicated publisher verifies Ops evidence, exact-four closure, PIT, immutable DB digest, and the READY key. Native pointer publication binds admitted source/physical identity, snapshot-quality inventory, unsigned dependency-scope, plan period, and the committed READY registry. Native execution is accepted source (PR168). Paired Paper Trader v2 mint is source-only behind `TRADER_ED25519_PRIVATE_KEY` and one ACTIVE pinned trader key. Premium unit tests sign with a test-only trader key and call the shared batch verifier with `controlledPilotRequestDigest`; they mock pinned registries. Mass Node `controlled_pilot.test.ts` native lifecycle consumes those Premium-serialized READY+Trader bytes with the real native and Trader verifiers; Container Paper children remain synthetic Python artifacts rebound only onto identity fields already on each row. Mass workerd publication tests still stub `publishAdmittedReceiptCandidate` and are not deployed multi-Worker RPC. GET/status is read-only | `tests/test_ready_policy_fail_closed.py`, `tests/test_ready_manifest.py`, `platform/workers/ingestion-premium/src/ready_publication.test.ts`, `platform/workers/research-mass-eval/src/controlled_pilot.test.ts`, `platform/workers/research-mass-eval/runtime/personal_research_r2.runtime.test.ts` |
| Premium named-entrypoint inventory | Operator vs audit vs product vs publication RPC lists are frozen by `WORKER_ENTRYPOINT_RPC_POLICY`. A Premium workerd harness fetch that returned a hardcoded 409 without calling `AUDIT_ONLY`, plus copied generated entrypoint/service assertions and a D1 sentinel around that fake route, was removed; it never invoked RPC | `scripts/cloudflare_binding_manifest.py` and `tests/test_cloudflare_binding_manifest.py`; remaining Premium workerd tests cover receipt product/read paths |
| Admitted COMPLETED vs retryable publication | Immutable receipt-candidate COMPLETED/PASS admission stays committed even when pointer publication stalls or rejects; GET is historical/read-only and does not sign or write; explicit completed POST may retry publication without rematerializing. The workerd/R2 lifecycle test stubs `publishAdmittedReceiptCandidate` at the Mass binding boundary and is not deployed multi-Worker RPC evidence | `platform/workers/research-mass-eval/runtime/personal_research_r2.runtime.test.ts` (`publishes after admitted PASS without rematerializing on retry`) |
| Immutable snapshot/artifact | Snapshot handles verify read-only mode and content digest; Worker R2 create-only operations use conditional writes | `tests/test_phase6_snapshot_publication.py` and Worker R2 runtime tests |
| Controlled Paper authorization | `OfflineFixturePaperService` and `ControlledPilotExecutionService` are distinct entrypoints; the controlled type requires verified readiness and an immutable snapshot | `tests/test_controlled_pilot_execution_service.py` |
| Strict Gateway rejection | Closed request/output schemas are validated before an artifact is returned | `tests/test_gateway_fail_closed.py` and Gateway runtime tests |
| Budget concurrency and settlement | BudgetLedger Durable Object serializes reservations and settles only through the Gateway coordinator bound to exact lease, digest, provider-start, and a retry-safe one-shot settlement capability | `platform/workers/research-ai-gateway/src/budget_runtime.test.ts` and `index_complete_budget.test.ts` |
| OAuth boundary | The Ops MCP Worker requires OAuth while public metadata remains available | `platform/workers/quant-ops-mcp/runtime/ops_runtime.test.js` and `harness/oauth_harness.test.ts` |
| Controlled Pilot identity | Runtime discriminant is exactly `controlled_pilot_v1`; Draft/Personal purpose IDs cannot substitute | `tests/test_controlled_pilot_identity.py` |
| generated `controlled_pilot_v1` contract | Python exact-four compiler emits the Worker/Container binding; CI drift check is `scripts/verify_controlled_pilot_v1_drift.py` | `tests/test_controlled_pilot_p0.py` and `platform/workers/research-mass-eval/src/controlled_pilot.test.ts` |
| Exact-four only | ExperimentPlan compilation resolves the `controlled_pilot_v1` four-plan closures; Mass accepts a distinct readiness type and remains disabled | `tests/test_experiment_plan_v2_dependency_closure.py` and `tests/test_phase7_pilot_construct.py` |

## Consolidation decisions

- Receipt monthly recovery keeps one realistic synthetic runtime regression
  (80,707 rows, >100 MB product) because the former five-row happy path could
  not catch monthly memory/D1 limits. It verifies acquisition through signing,
  bounded continuation and no upstream refetch. The existing calendar-recovery
  case also covers pre-upgrade v1 product reuse instead of adding a version
  matrix. These are local runtime checks, not deployed capacity evidence.
- Removed unused `scripts/verify_all.sh`. It duplicated local pytest plus optional worker `npm test` with skip flags; native CI remains `scripts/verify_ci.sh` on Workers Builds, and local developer verification remains pytest.
- Removed tests and scripts that fixed a historical `22 COMPLETE / 4 PARTIAL`
  snapshot as policy.
- Removed wave/phase filename guards and optional helper-script source checks.
- Removed repeated AST/import/comment/function-name assertions where public
  behavior, closed schemas, capabilities, or runtime bindings
  already enforce the boundary.
- Removed `tests/test_research_default_r2_put_callers.py`, whose glob and
  implementation-string assertions duplicated the stronger R2 boundary.
  Acceptance now calls the public adapter: Python remote writes fail closed,
  local dry runs only stage bytes, and immutable remote writes use the Worker
  children-then-manifest operation. Read acceptance observes the pinned
  `wrangler r2 object get --remote` invocation.
- Removed the production-runbook prose scanner and the Phase 3.5 validation
  matrix's Markdown/count coupling. Machine-readable binding and migration
  manifests remain executable authorities; matrix uniqueness/tier behavior is
  still tested directly.
- Replaced the watermark migration's SQL spelling assertions with an applied
  SQLite schema/index observation.
- Removed duplicate core/features substring import bans. DataPlane import
  direction is checked from source Import/ImportFrom in
  ``tests/test_plane_import_boundaries.py`` without executing those imports;
  dynamic importlib strings and paths outside setuptools where=/py-modules
  are not verified. core/features tests observe PIT calls and assert that
  runtime contexts expose no DB handle.
- C04 personal JSON-boundary (trusted host): removed same-process subclass,
  stateful mapping, and equality-confused tests from D1 sync, receipt
  signature, controlled artifacts, ops projection extra-field mix, Gateway
  FixtureSubclass/budget-subclass/setattr freeze, READY DatasetId/DatasetList
  and evidence-type subclass, coverage-transition StatefulDocument/EvilString,
  runtime-attestation EqualityConfusedScope and nested containers, and
  sync-dataset EvilStr/ConfusedStatus/StatefulPolicy. Retained unsigned D1
  cursor signature fail, A-signature on B-claims, extra projection envelope
  field, missing/extra/swapped artifact bytes, Gateway StructuralProvider/
  lambda constructor contract, fixture duplicate-key/NaN JSON, Mass-disabled
  missing budget, READY duplicate-key/nonfinite JSON and environment mismatch,
  signed coverage transition content-addressed COMPLETE, unbounded TTL, and
  ordinary-dict COMPLETE write remaining PARTIAL. Deleted ops-projection
  SwitchingEnvelope: it only failed ``exact finite JSON`` on an in-process
  Mapping; public-wire A-signature/B-payload is already
  ``test_signed_projection_envelope_binds_content_cursors_and_gate_evidence``
  (JSON copy, mutated ``applied_cursor``, ``signature is invalid``),
  frozen observation after mutate, unsigned-B identity isolation, extra
  envelope field, and strict duplicate/NaN JSON. ``VerifiedPilotReadiness``
  staying ``@final`` is a cheap production type guard; no hostile-subclass
  test is required and none should be added. This is the reviewed personal-
  JSON test slice, not a global all-test or all-finding close.
- Replaced the remaining aggregate-namespace string scan with that DataPlane
  source-owner check and removed its deferred-phase existence assertion.
- Removed the research harness's AST/function-name/environment-spelling freeze;
  Mass fail-closed behavior is already exercised through the public start gate
  and Worker scheduler/runtime tests.
- Removed the dead W83-W86 three-pin freeze surface and smoke-universe count
  guards. Exact-four plans now own their immutable strategy/feature parameters;
  Mass and Paper remain disabled by their capability gates.
- Historical isolated-runner `shell=False` source-string check was replaced by
  an intercepted subprocess contract; that unused macOS sandbox-exec runner is
  now removed.
- Removed the JSDA recovery sealer's function-name/import spelling assertions;
  its local-index input and persisted `FAILED / RECOVERED_RAW_ONLY` evidence are
  exercised directly, including a zero structured-row count and no COMPLETE.
- Replaced the OTC pipeline's source-text wiring assertions with a real SQLite
  observation that an absent official index creates neither required segments
  nor receipts.
- Retained serialized fixture/schema/config reads only when the file itself is
  the governed input under test; those reads do not authorize READY or GO.

- Retired full catalog compatibility uses a selected ``replay`` marker. Default
  addopts are ``not replay``. A CLI ``-m`` replaces addopts ``-m`` and does not
  AND. Native CI runs three disjoint non-live lanes in this order: ordinary
  offline (``not toolchain and not live and not replay``), replay
  (``replay and not toolchain and not live``), npm install, then toolchain
  (``toolchain and not live``, including any future replay+toolchain). Frozen
  artifact digest, installed-wheel/Container exclusion, numeric occupancy,
  unknown dispatch, disabled unique_logic CLI, and live unique_logic
  numerical/PIT kernels stay in the ordinary offline lane. This is not a claim
  that every retired catalog consumer is marked.

- T01/C19 ordinary implementation slim: `reconstitution_pending` imports
  `combo_basket_catalog` symbols directly (no getattr/missing-preview
  fallback). `catalog_compiler` dropped unused `catalog_active` re-exports
  and the persist/CLI writer that could rewrite frozen replay bytes;
  `compile_catalog` and `assert_legacy_catalog_artifact_frozen` remain
  read-only. Detect-only reconstitution CLI, unique_logic retired CLI stub,
  unknown dispatch, occupancy_audit wave-pack writer, unique_logic kernels,
  and Mass/driver refuse probes stay. Frozen digest
  `sha256:6ad5ba57dfa41ed9a97e5895d9238040fbb5539b310a2ea4aa349172b6cb8c69`
  is not regenerated. Not whole T01/C19.

The final release evidence records suite totals and runtime suites. Test count
is diagnostic only and is never a GO condition.
