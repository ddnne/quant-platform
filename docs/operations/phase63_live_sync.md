> **Historical snapshot** — not current residual SoT.
> Current residual: [phase62_residual_status.md](../phase62_residual_status.md).
> Mass / READY / Phase7: **NO-GO / OFF** unless residual says otherwise.
> Counts below are dated (2026-08-12) and may be stale.

# Phase 6.3 live vs code (2026-08-12)

| Commit | Role |
|--------|------|
| `4aaf424` | sticky COMPLETE; dataset_coverage resynced from segments |
| `fe6aafc` | full projection publish fail-closed guard |
| `b86b93b` | ops_reeval_freshness + restore_local_complete_from_receipt |
| `1f175a3` | master coverage_mode scd2_event_sourcing |
| `1f66821` | storage_plane_status MCP tool |

## Live checks
- markets_calendar: 224/224 COMPLETE (dataset COMPLETE)
- jsda_tokyo_repo_rates: COMPLETE
- segment COMPLETE: 400
- sticky: prevents demotion of COMPLETE when SUCCESS receipt still eligible
- Mass / READY: NO-GO
