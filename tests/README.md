# tests

Offline pytest suite for quant-platform. **No live credentials** required for the
default path. Live API paths (if any) are opt-in via env flags and are not part
of the guard packs below.

```bash
# Mandatory local CI (6 active workers in parallel; no VERIFY_* skips)
scripts/verify_ci.sh

# Skippable helper only (optional VERIFY_* skips; may skip missing node_modules)
scripts/verify_all.sh

# Full offline suite (G2)
.venv/bin/python -m pytest tests/ -q

# Guard pack only (G0 — architecture invariants)
.venv/bin/python -m pytest tests/ -q \
  -k "plane_import or mass_research or gateway_fail or publish_guard or sticky or issue_receipts or data_boundary or strategies_static"

# Smoke = G0 architecture guards (no tests.test_smoke module)
.venv/bin/python -m pytest tests/ -q \
  -k "plane_import or mass_research or gateway_fail or publish_guard"
```

Live residual COMPLETE / Mass status is **not** decided by tests — see
[`docs/phase62_residual_status.md`](../docs/phase62_residual_status.md).
Live review findings: [`docs/phase633_finding_ledger.md`](../docs/phase633_finding_ledger.md) (sole). Historical review waves remain in Git history, not the active tree.
Mandatory local CI: [`scripts/verify_ci.sh`](../scripts/verify_ci.sh) (6 active workers, no `VERIFY_*` skips; pinned `uv sync --frozen`). [`scripts/verify_all.sh`](../scripts/verify_all.sh) is a skippable helper only. The merge gate is the live native Cloudflare GitHub App check for the repo-root `verify_ci.sh` Build. The legacy receipt aggregator has been removed. Do not add `.github/workflows`. See [`docs/ci/workers_builds.md`](../docs/ci/workers_builds.md).

---

## Tiers (B1-d navigation)

| Tier | Intent | What to run | Typical contents |
|------|--------|-------------|------------------|
| **G0** | Architecture guards — stop the batch if red | named `-k` pack or explicit paths | plane import boundaries, Mass fail-closed, gateway fail-closed, publish guard, sticky COMPLETE, empty-raw ban, core/features/strategies data boundaries |
| **G1** | Contract / behavior | modules for the change you made | PIT look-ahead, StrategySpec reject, receipt signature, JSDA parse, J-Quants catalog, coverage ledger |
| **G2** | Full offline | `pytest tests/ -q` | everything under `tests/` that does not need live network |

### G0 named guards (prefer these names in PR bodies)

| Invariant | Test module / focus |
|-----------|---------------------|
| Plane import direction | `test_plane_import_boundaries.py` |
| Mass fail-closed | `test_mass_research_gate.py` |
| Gateway fail-closed | `test_gateway_fail_closed.py` |
| Publish COMPLETE fail-closed | `test_ops_projection_publish_guard.py` |
| Core no direct SQLite facts | `test_core_data_boundary.py` |
| Features no direct SQLite facts | `test_features_data_boundary.py` |
| Strategies static boundaries | `test_strategies_static_boundaries.py` |
| Empty-raw ban / A3 prepare | `test_issue_receipts_parallel.py` |
| Sticky COMPLETE segment_id fallback | `test_sticky_complete_segment_id_fallback.py` |
| Receipt Ed25519 eligibility | `test_receipt_eligibility.py`, `test_phase623_receipt_signature.py` |

### G1 clusters (by task)

| Task | Start here |
|------|------------|
| Coverage / receipts | `test_issue_receipts_parallel.py`, `test_coherence_with_receipts.py`, `test_receipt_eligibility.py` |
| PIT / as-of | `test_pit_*.py`, `test_available_at.py`, `test_pipeline_pit_timestamps.py` |
| J-Quants ingest | `test_jquants_*.py`, `test_parallel_date_jobs.py` |
| JSDA | `test_jsda_*.py` |
| Paper / agents | `test_paper_*.py`, `test_agents_*.py`, `test_strategy_spec_schema.py` |
| Phase 3.5 / CF | `test_phase35_*.py`, `test_phase6_*.py` |
| Ops projection | `test_ops_projection_*.py`, `test_phase35_sync_script.py` (`--publish-ops`) |

---

## Fixtures

Synthetic data under `tests/fixtures/` (CSV/HTML). Prefer fixtures over network.
Do **not** commit `data/**/*.sqlite` or secrets.

---

## What tests must **not** claim

```text
✗ Mass ON / production READY / Phase 7 GO
✗ Live COMPLETE counts (residual SoT only)
✗ That worker pass == Coverage COMPLETE
✗ That projection FRESH == Research READY
✗ That a historical Git review snapshot is the live finding SoT (use phase633_finding_ledger.md)
```

Agent nav: [`docs/architecture/llm_nav_map.md`](../docs/architecture/llm_nav_map.md).  
ADR: [`docs/architecture/adr_llm_friendly_refactor.md`](../docs/architecture/adr_llm_friendly_refactor.md).
