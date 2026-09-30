# Historical Phase 3.5 storage split

The D1-current-row/local-mirror plan on this page is superseded by the
[cloud storage architecture](architecture/cf_native_storage_plane.md).
Its original design remains in Git; do not restore old readers from it.

Current market bodies belong in R2. D1 holds small indexed mutable metadata;
cloud scratch supplies SQL/PIT/feature processing without a local price DB.
The legacy local HTTP client and D1/change-feed export endpoints are retired.

Existing D1 tables and evidence are not deleted by this source retirement.
Schema or data deletion requires its own consumer/recovery assessment.
Use the [current runbook](operations/current_production_runbook.md) and
[whole-repository worklist](architecture/personal_simplification.md), not the
former full-table download, COUNT, mirror or speculative Parquet recipes.
