# P0 CF-native storage plane evidence

**As of:** 2026-08-12 (orchestrator live verify + deploy)  
**Mass research:** NO-GO  
**READY claim:** none

## Code (main lineage)

| Commit | Content |
|--------|---------|
| `0e1f880` | R2 structured write path, cold archive, change_log prune |
| `4993bca` | master SCD2 + artifacts plan + parquet-manifest |
| `0cd09a7` | JSDA fact tables + bounded acquisition |
| (this change) | `storage_plane_status` Ops tool + surplus D1 cleanup |

## Live D1 (quant-ingest remote)

| Metric | Value |
|--------|-------|
| D1 size | ~652 MB (was ~10 GB pre-archive) |
| `jquants_records` cold bars (`event_time < 2026-07-01`) | **0** |
| bars hot | ~124k |
| master (hot window only) | ~129k |
| tables after surplus cleanup | 31 (empty legacy jquants_* fact tables dropped; nk_v2 stages cleared) |
| COMPLETE segments | **400** |
| JSDA OTC rows / COMPLETE | 12403 / 1 (`2026-08-12`) |
| JSDA corporate rows / COMPLETE | 89 / 1 (`2026`) |
| JSDA tokyo repo COMPLETE | 1 |

## Ops visibility

- MCP tool: **`storage_plane_status`** (deployed on quant-platform-ops-read-mcp)
- Worker routes: `/v1/ops/archive-cold`, `/v1/ops/prune-changelog`, R2-only write path via `write_path_config.ts`

## Explicit non-claims

- Not READY / not B0 green for production research
- Not full history COMPLETE for bars/master
- Not true Arrow Parquet materialization complete
- Mass Autonomous Research remains **OFF**
