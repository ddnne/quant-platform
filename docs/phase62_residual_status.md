# Phase 6.2 / 6.3 residual status (2026-08-12)

| Area | Status | Notes |
|------|--------|-------|
| D1 cold prune | **DONE** | cold rows before hot cutoff = 0 |
| R2-first write path | **DONE** | write_path_config / r2_structured_writer |
| master SCD2 | **DONE** | scd2_event_sourcing / D1 hot 128811 |
| Full publish guard | **DONE** | fe6aafc |
| Local COMPLETE heal | **DONE** | local 400 = remote 400 |
| Target freshness | **DONE** | ops_reeval_freshness |
| JSDA min COMPLETE | **DONE** | OTC / corporate / tokyo 1 each |
| Segment COMPLETE total | **400** | not invent more without raw |
| Dataset-level COMPLETE | ~2 full-dataset | calendar + tokyo aggregate COMPLETE; others PARTIAL |
| Mass / READY / B0 | **NO-GO** | |
| applied_cursor materialization | **DEFER** | READY path |
| Extra COMPLETE without raw | **DEFER** | correct |

## Unpushed commits (ahead of origin/main)
- 1f66821 storage_plane_status
- 1f175a3 master scd2 contract + reeval evidence
- fe6aafc publish guard
- b86b93b reeval + restore tooling
- c4505b1 heal evidence
