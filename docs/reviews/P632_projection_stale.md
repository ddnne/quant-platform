# P632 — projection STALE / `refresh_success=false` root cause

**Live MCP `projection_status` (this turn, not invented):**

| Field | Value |
|-------|--------|
| `projection_status` | `STALE` |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | ~177k (~49 h) |
| `stages.refresh_attempt` | `true` (deployed worker hardcodes this) |
| `stages.refresh_success` | `false` |
| `stages.projection_generated` | `true` |
| `stages.d1_applied` | `true` |
| `stages.mcp_visible` | `true` |

B0 / READY / Mass / GO: **unchanged, not claimed.** No wrangler apply was run.

Last applied SQL on disk (`data/ops/projection.d1.sql` line 26, written 2026-08-21):

```
status='FRESH', age_seconds=0,
detail_json.refresh_status=null,
projection_generation_id=projgen-ef18b4f86ee946048161d25e2a30a2a8
```

Local sidecar `data/ops/projection_meta.json` is a **different** generation
(`projgen-73bb0c3f…`) with `last_refresh_status=skipped` and frozen
`status=FRESH` / `age_seconds=0`. MCP reads D1, not this file.

## Why `refresh_success` is false

Deployed `quant-ops-mcp` derives it from stored status after an age demotion,
not from a live refresh:

1. `platform/workers/quant-ops-mcp/src/domain.js` (pre-fix) computed
   `refreshSuccess = status === "FRESH" && !stale` and hardcoded
   `refresh_attempt: true`.
2. Same file demotes stored `FRESH` to `STALE` when request age `> 86400`.
   Live age ~177k s, so MCP returns `STALE` and `refresh_success=false`.
3. Last remote apply was the 2026-08-21 export-only publish (`refresh_status`
   null in D1 SQL). Coverage ledger was **not** run (`skipped` in local JSON).
4. Repo cron logs under `.glm-logs/ops-cron/` stop at `2026-08-12`. Ingestion
   still runs (`ops_status.last_run` 2026-08-23) but the projection was not
   republished.

This is **not** a Coverage COMPLETE / B0 / READY event. It is a stale ops
projection clock.

## Hypotheses checked

### Missing applied pin — not the FRESH/STALE cause

Live `sync_status.applied_feed_cursor` is **null**. Every dataset is
`LAGGING_APPLY_UNPINNED` or `EXPORT_CURRENT_APPLY_UNPINNED`. That blocks
**CURRENT**, not projection FRESH.

Projector always emits an explicit unpinned `jquants_records` row when local
`sync_change_state` has no pin (`scripts/export_ops_projection.py:266-272`).
MCP never coerces null to CURRENT (`domain.js` `syncDatasetState` +
`first()` on `ops_applied_pins`).

### `0007_ops_applied_pins` “not remote” — schema likely present; pin still NULL

Migration comment (`migrations/0007_ops_applied_pins.sql:1-3`) says do not
apply that file remotely from the change set (schema-only). The **projection
SQL** still does `CREATE TABLE IF NOT EXISTS ops_applied_pins`
(`export_ops_projection.py:48-54`) and `DELETE FROM ops_applied_pins` then
insert. Live `sync_status` returns a structured null pin rather than a tool
error, so the table is readable (or missing-table is swallowed).

`first()` / `all()` swallow `no such table` (`domain.js:209-226`) and return
`null` / `[]`. A missing 0007 table would look like an unpinned feed, **not**
like `refresh_success=false`.

### Exception swallowed — latent fail-open; not this live generation

`scripts/publish_ops_projection.py` catches coverage-ledger errors, prints,
and (before this fix) continued to export + `--apply-remote`. Export did
**not** receive `refresh_status`, so D1 SQL could still say `FRESH`
(`refresh_status: null`) while local JSON said `DEGRADED_REFRESH_FAILED`.

This live generation was `skipped`, not `failed`. The swallow is a real
honesty hole for the next `--refresh-coverage` failure.

### Clock-stamper — local FRESH without refresh_success

`scripts/ops_reeval_freshness.py` (cron fallback on publish rc=3,
`scripts/cron_publish_ops.sh:30-35`) rotated `ops_projection_metadata.status`
to `FRESH` with `refresh_status=ops_reeval_freshness`. That is not coverage
refresh success. Live generation is the 2026-08-21 full export, not that
stamper.

D1 `ops_projection_metadata.status` CHECK only allows
`FRESH|STALE|FAILED|UNKNOWN` (`migrations/0003_endpoint_inventory_sla.sql:35`).
`DEGRADED_*` cannot be stored; MCP must compute it.

## Fail-close in this change (honesty, not a live FRESH)

- `packages/data_plane/ops/projection_meta.py`: `FRESH` only when
  `refresh_status == "success"`. Skipped/null → `STALE`. Failed →
  `DEGRADED_REFRESH_FAILED`.
- `scripts/export_ops_projection.py`: thread `refresh_status` into the SQL
  metadata row; coerce CHECK-illegal statuses (`DEGRADED_REFRESH_FAILED` →
  `FAILED`).
- `scripts/publish_ops_projection.py`: pass refresh fields into export;
  **refuse `--apply-remote` after a failed refresh** (exit 4); do not default
  applied sidecar status to FRESH.
- `platform/workers/quant-ops-mcp/src/domain.js`: `honestProjectionStatus()`
  demotes stored FRESH unless `detail_json.refresh_status === "success"` and
  age ≤ 86400. `refresh_attempt` is no longer hardcoded `true`.
  `refresh_success` requires FRESH **and** that refresh.
- `scripts/ops_reeval_freshness.py`: no longer writes `status='FRESH'`.

This commit does **not** refresh live D1. After worker deploy, the current
row (`refresh_status: null`, age ~49h) remains STALE with
`refresh_attempt=false`, `refresh_success=false`. A FRESH projection still
requires a successful `publish_ops_projection.py --refresh-coverage` apply,
not a clock stamp.

Human residuals unchanged: pin CURRENT (`0007` apply + non-null seq),
Coverage V3 PARTIAL four, B0 UNKNOWN, READY null.
