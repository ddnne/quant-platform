# Phase 6.2.1 test audit (honest)

## Retained (strong invariants)
- receipt eligibility: TRUSTED can COMPLETE; RECOVERED cannot
- READY publication policy / coherence
- PIT / snapshot publication
- JSDA corporate schema migration
- PaperExecutionService authorization
- ResearchBudgetCapability atomic consume
- ImmutableArtifactStore create-if-absent
- Ops projection status semantics
- StrategySpec / ResearchMemo / FeatureProposal / SelectionDecision strict decode

## Consolidated
- READY gate path uses ReadyPublicationPolicy wrapping coherence
- Ops projection metadata single module (`ops.projection_meta`)

## Removed
- None deleted en masse this wave (avoid churn)

## Added (minimal)
- `tests/test_receipt_eligibility.py`
- `tests/test_ops_projection_meta.py`
- `tests/test_ready_policy.py`
- `tests/test_immutable_artifact.py`
- `tests/test_selection_decision.py`
- `tests/test_research_budget_ledger.py`
- `tests/test_mass_research_gate.py`
- `tests/test_paper_execution_service.py`

## Mechanisms replacing test proliferation
- receipt eligibility field / evaluate_segment gate
- generated governed.js from coverage SoT
- PaperExecutionService sole authority
- ResearchBudgetCapability required for mass research assert
