# Historical Phase 3.5 ingestion design

This page is retained as a link target, not a second runbook. The original D1
body mirror, local HTTP synchronization and phase-specific completion claims
are recoverable in Git before this retirement.

Current sources of truth:

- [Premium Worker](../platform/workers/ingestion-premium/README.md): acquisition,
  existing endpoints and scheduling.
- [Cloud storage architecture](architecture/cf_native_storage_plane.md):
  R2 market bodies, small indexed D1 metadata and bounded cloud scratch.
- [Operational runbook](operations/current_production_runbook.md): deployment
  and explicit execution holds.
- [Whole-repository simplification](architecture/personal_simplification.md).

The local HTTP client and Worker D1/change-feed export routes are retired.
The current receipt-product metadata API remains. Synthetic SQLite fixture
imports are not authority to download real market history locally or publish
READY. Neither source delivery nor ingestion PASS establishes research GO.
