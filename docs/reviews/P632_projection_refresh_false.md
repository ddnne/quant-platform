# P632 — live `refresh_success=false` write path

**This fetch (live `quant-mcp` `projection_status`, not invented):**

| Field | Value |
|-------|--------|
| `projection_status` | `STALE` |
| `stale` | `true` |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | **181073** (~50.3 h) |
| `stages.refresh_attempt` | **`true`** |
| `stages.refresh_success` | **`false`** |
| `last_known_good.not_fresh` | **`true`** |
| `last_known_good.generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_version` | `ops_projection/v3` |
| B0 / READY / Mass / GO | **not claimed** |

Companion root-cause note: [`P632_projection_stale.md`](P632_projection_stale.md) (`2f0024d`). This file pins the **write** of `refresh_success=false` for the live pair `refresh_attempt=true` / `refresh_success=false` / `last_known_good.not_fresh=true`. No wrangler apply. No live coverage refresh. Not a FRESH / GO event.

---

## File:line of the write

`refresh_success` is **not** a D1 column. MCP computes it on read and writes it into the tool payload.

### 1. Live MCP payload (what this fetch returned)

Deployed `quant-ops-mcp` is still the **pre-`2f0024d`** worker. That path:

| Step | File:line (parent of `2f0024d`) | What it does |
|------|----------------------------------|--------------|
| Age demotion | `platform/workers/quant-ops-mcp/src/domain.js:617` (pre-fix) | stored `FRESH` → `STALE` when request age `> 86400` |
| Boolean | **same file:625** | `const refreshSuccess = status === "FRESH" && !stale;` |
| Payload write | **same file:644** | `stages.refresh_success: refreshSuccess` |
| Attempt flag | same file:643 | **hardcodes** `refresh_attempt: true` |
| Last-known-good | same file:637–640 | `last_known_good.not_fresh: true` whenever `stale` |

Live age **181073 > 86400**, so `status` is `STALE`, `stale` is `true`, and line 625 writes **`refresh_success=false`**. `refresh_attempt=true` is the hardcoded flag, **not** evidence that `refresh_coverage_ledger` ran for this generation.

Last applied SQL still on disk (`data/ops/projection.d1.sql:26`, 2026-08-21 export-only):

```text
status='FRESH', age_seconds=0,
detail_json.refresh_status=null,
projection_generation_id=projgen-ef18b4f86ee946048161d25e2a30a2a8
```

That stored `FRESH` + null refresh is what the worker demotes.

### 2. This tree (honesty already landed in `2f0024d`; not yet the live Worker)

| Step | File:line | What it does |
|------|-----------|--------------|
| Honest demotion | `platform/workers/quant-ops-mcp/src/domain.js:88-90` | stored `FRESH` without `detail_json.refresh_status === "success"` → `STALE` (or `DEGRADED_REFRESH_FAILED` if `"failed"`) |
| Attempt flag | `domain.js:82-84` | `refresh_attempt` true only when refresh_status is present and not `"skipped"` |
| Boolean | **`domain.js:696`** | `const refreshSuccess = status === "FRESH" && honest.refreshOk && !stale;` |
| Payload write | **`domain.js:715`** | `stages.refresh_success: refreshSuccess` |
| Last-known-good | `domain.js:708-712` | `last_known_good.not_fresh: true` when `stale` |

After Worker deploy **without** a new D1 apply, this live row (`refresh_status: null`, age ~50 h) stays `STALE` with `refresh_success=false`. Tree would report `refresh_attempt=false` (null/skipped is not an attempt). Live `refresh_attempt=true` is the undeployed hardcoded flag.

### 3. Ops projection refresh pipeline (how `refresh_status` gets written)

This is the out-of-band publisher. Remote MCP has no write tool.

| Step | File:line | What it does |
|------|-----------|--------------|
| Default | `scripts/publish_ops_projection.py:209` | `refresh_status = "skipped"` (export-only; **this live generation**) |
| Attempt | `publish_ops_projection.py:213-217` | `--refresh-coverage` sets `last_refresh_attempt_at` |
| Success write | `publish_ops_projection.py:222` | `refresh_status = "success"` after `refresh_coverage_ledger` |
| **Failure write** | **`publish_ops_projection.py:226`** | `refresh_status = "failed"` in the `except` |
| Status map | `packages/data_plane/ops/projection_meta.py:117-122` | `"failed"` → `DEGRADED_REFRESH_FAILED`; any `FRESH` without `"success"` → `STALE` |
| D1 SQL INSERT | `scripts/export_ops_projection.py:455-457` via `_insert_sql` **`:206`** | writes `ops_projection_metadata.status` + `detail_json.refresh_status` |
| Refuse apply | `publish_ops_projection.py:299-305` | `--apply-remote` after `"failed"` → exit 4 (no FRESH-looking remote apply) |

Live generation is **skipped**, not `"failed"`. `refresh_success=false` is therefore **age + missing success**, not a recorded ledger exception.

---

## Why STALE is honest

1. **Clock.** `generated_at` 2026-08-21T12:30:49Z, request age **181073 s** (> 86400). Stored `age_seconds=0` is not trusted.
2. **No coverage-refresh success.** `detail_json.refresh_status` is **null** on the last apply. `FRESH` requires `refresh_status === "success"` (`projection_meta.py:50`, `domain.js:67-68,88-90,696`). Skipped / null / failed / `ops_reeval_freshness` never count.
3. **Last-known-good is not current.** `last_known_good.not_fresh=true` is the same 2026-08-21 row. Coverage 22/4 under this generation is a frozen last-known snapshot, not a new publication.
4. **`refresh_attempt=true` is not success.** Live Worker hardcodes the attempt flag. Local sidecar `data/ops/projection_meta.json` (untracked, different gen `projgen-73bb0c3f…`) still says `status=FRESH` / `last_refresh_status=skipped`. MCP reads D1, not that file. Do not treat the sidecar as FRESH.
5. **Tree does not invent FRESH.** `honestProjectionStatus` never promotes stored `STALE` to `FRESH`. Mixed generations become `DEGRADED_MIXED_GENERATION`. Targeted `scripts/ops_reeval_freshness.py:110` writes `status='STALE'`.

STALE + `refresh_success=false` + `not_fresh=true` is the honest tuple for this generation.

---

## What HUMAN / ops must do

Do **not** run live `--refresh-coverage --apply-remote` from an agent session: it mutates production D1 (`quant-ingest`) and can replace remote COMPLETE evidence. This commit does not deploy, apply, or stamp FRESH.

Operator sequence (HUMAN; record the reason):

1. **Read-only confirm.** Re-fetch `projection_status` + `sync_status`. Expect STALE until a successful apply. `applied_feed_cursor` null is a **different** gate (CURRENT), not projection FRESH.
2. **Optional honesty deploy.** Ship `quant-ops-mcp` containing `2f0024d` / this SHA. After deploy, live `refresh_attempt` becomes `false` for this row; `refresh_success` stays `false`; status stays `STALE`. Deploy is not a publish.
3. **Coverage ledger + publish (mutates D1).** After `local COMPLETE ≥ remote COMPLETE` (or documented `--force-apply-remote`):
   ```bash
   python scripts/publish_ops_projection.py \
     --db data/structured/ingestion.sqlite \
     --refresh-coverage --apply-remote
   ```
   Guard: `scripts/publish_ops_projection.py:233-250`, `docs/operations/projection_publish_guard.md`. Failed refresh must **not** apply (`exit 4`). Cron fallback `scripts/cron_publish_ops.sh:30-35` → `ops_reeval_freshness.py` is **not** FRESH.
4. **Accept FRESH only on a new MCP fetch** that shows **all** of:
   - `projection_status=FRESH`
   - `stages.refresh_success=true`
   - `stages.refresh_attempt=true`
   - `stale=false` / `last_known_good=null`
   - `projection_age_seconds ≤ 86400`
   - a **new** `active_generation` (not `projgen-ef18b4f86ee946048161d25e2a30a2a8` unless that generation is genuinely re-applied with `refresh_status=success`)
5. **CURRENT is separate.** Pin `ops_applied_pins.feed=jquants_records` to a non-null `last_applied_change_seq` (`0007_ops_applied_pins.sql` schema is HUMAN-remote). Null pin stays unpinned after a FRESH projection.

Do not flip Phase 6.3.2 COMPLETE, Phase 7 GO, B0 PASS, READY, or Coverage COMPLETE from this file.

---

## `applied_cursor` null never CURRENT

Live `sync_status` this fetch: `applied_feed_cursor=null`, `latest_change_seq=2890659`, CURRENT datasets **0**. Lag-0 `indices_bars_daily_topix` is `EXPORT_CURRENT_APPLY_UNPINNED`. Typical others: `LAGGING_APPLY_UNPINNED`.

| Guard | File:line |
|-------|-----------|
| `applied == null` → `EXPORT_CURRENT_APPLY_UNPINNED` / `LAGGING_APPLY_UNPINNED` / `APPLY_UNPINNED` | `platform/workers/quant-ops-mcp/src/domain.js:124-136` |
| Pin SELECT; missing/null stays null | `domain.js:814-825` |
| Research note: null pin never CURRENT | `domain.js:865-868` |
| Export always emits explicit unpinned `jquants_records` row when local pin is absent | `scripts/export_ops_projection.py:266-272` |

`CURRENT` requires `applied != null` **and** `lag === 0` **and** `applied === exported`. Export lag 0 with a null pin is never CURRENT. Projection FRESH does not fill the pin.

---

## Fail-closed in tree vs live Worker

`2f0024d` already stopped advertising FRESH when `refresh_success` is false (`domain.js:88-90,696` + tests in `platform/workers/quant-ops-mcp/test/domain-d1.test.mjs`). No additional producer lie found on this SHA: sidecar FRESH+skipped is an untracked 2026-08-21 leftover, not MCP.

This commit does **not** refresh live D1, does **not** deploy the Worker, and does **not** flip GO.
