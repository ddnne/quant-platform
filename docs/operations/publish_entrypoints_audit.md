# Publish entrypoints audit (fail-closed guard)

**Live verified 2026-08-12.** Full apply uses `scripts/publish_ops_projection.py` which enforces
`enforce_complete_count_guard` (refuse if local COMPLETE < remote COMPLETE).
Remote apply also requires a dedicated signed Ops Projection envelope; Receipt
and READY signing keys are never fallback authorities.

| Entry | Path | apply-remote? | Guard applies? |
|-------|------|---------------|----------------|
| Manual / ops | `scripts/publish_ops_projection.py --apply-remote` | yes | **yes** (built-in) |
| Cron | `scripts/cron_publish_ops.sh` with `APPLY_REMOTE_OPS=1` | yes | **yes** (calls publish_ops_projection; refusal leaves prior generation active) |
| Sync | `scripts/sync_d1_to_sqlite.py --publish-ops --apply-remote-ops` | optional | **yes** (subprocess to publish_ops_projection) |

**Mass / READY:** NO-GO.

**No additional entry points found that write projection without the guard.**
