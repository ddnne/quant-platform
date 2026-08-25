# Safe +1 COMPLETE Procedure (Single Segment)

Use this runbook when raw files for **exactly one** segment arrive and you want
to advance the local coverage ledger by **+1 COMPLETE** row. This procedure
deliberately forbids mass operations.

## 0. Guardrails (NEVER violate)

- **NEVER invent, fabricate, or guess** required items. Every item must come
  from a verifiable source: a SUCCESS signed `collection_receipt` or an R2
  object that was actually fetched.
- **NEVER touch remote D1** during a single-segment restore. This procedure is
  **local-only** until `publish_ops_projection` runs as a separate step.
- **NEVER bulk-restore.** One `--dataset` + one `--segment-id` per run.
- **NEVER promote a segment to COMPLETE without a SUCCESS receipt.**
- **R2 before ledger.** Confirm the raw object exists in R2 before touching the
  ledger.

## 1. Inputs you must collect

| Item | Source | Example |
| --- | --- | --- |
| `DATASET` | receipt / scope | `jsda_corporate_bond_transactions` |
| `SEGMENT_ID` | receipt / scope | `2024-01-15::tokyo` |
| `POLICY_VERSION` | receipt header | `collection-coverage/v2` |
| `RECEIPT_ID` | `collection_receipts.receipt_id` | `rcpt_0192ab...` |
| `R2_KEY` | receipt `expected_scope.items[*].r2_key` | `raw/jsda/2024/01/15/...parquet` |

## 2. Confirm raw is in R2 first

```bash
# Use whichever R2 helper the platform exposes; this is illustrative.
wrangler r2 object get ingestion-raw \
    --remote \
    --key "${R2_KEY}" \
    --file /tmp/_r2_probe >/dev/null \
&& echo "R2_OK" || { echo "R2_MISSING"; exit 2; }
```

If `R2_MISSING`: **stop**. Do not modify the ledger. Re-run ingestion for the
missing item.

## 3. Verify a SUCCESS signed receipt exists locally

```bash
sqlite3 "${LOCAL_DB}" <<SQL
SELECT receipt_id, status, policy_version, created_at
FROM collection_receipts
WHERE dataset        = '${DATASET}'
  AND segment_id     = '${SEGMENT_ID}'
  AND status         = 'SUCCESS'
  AND policy_version = '${POLICY_VERSION}'
ORDER BY created_at DESC
LIMIT 1;
SQL
```

If no row returns: **stop**. There is nothing safe to promote.

## 4. Run the single-segment restore (local only)

```bash
python scripts/restore_local_complete_from_receipt.py \
    --db            "${LOCAL_DB}" \
    --dataset       "${DATASET}" \
    --segment-id    "${SEGMENT_ID}" \
    --policy-version "${POLICY_VERSION}"
```

Expected stdout:

```
[restore] BEFORE: dataset=... segment_id=... status=INCOMPLETE ...
[restore] AFTER:  dataset=... segment_id=... status=COMPLETE ...
[restore] OK
```

Exit code must be `0`. Exit `1` means not eligible (do not retry with hacks;
re-check the receipt or R2).

## 5. Cross-check the ledger delta is exactly +1

```bash
sqlite3 "${LOCAL_DB}" <<SQL
SELECT status, COUNT(*) FROM coverage_segments
WHERE dataset='${DATASET}'
GROUP BY status;
SQL
```

The `COMPLETE` bucket must increase by **exactly 1** versus the prior state.

## 5b. Dataset aggregate follow-up (mandatory; W70)

If this seal was the **last** PARTIAL segment for `${DATASET}`, segment SoT is
now all-COMPLETE but `dataset_coverage` may still show PARTIAL (W68/W69 class).

`restore_local_complete_from_receipt.py` already calls
`sync_dataset_coverage_from_segments` for the sealed dataset. For tip seals /
issue paths that do **not** go through restore, run explicitly:

```bash
.venv/bin/python scripts/sync_dataset_coverage_from_segments.py \
  --db "${LOCAL_DB}" --datasets "${DATASET}"
# dry-run first if unsure:
# .venv/bin/python scripts/sync_dataset_coverage_from_segments.py \
#   --db "${LOCAL_DB}" --datasets "${DATASET}" --dry-run
```

Rules (fail-closed):

- Promotes `dataset_coverage` → COMPLETE **only** when all segs COMPLETE
- Writes honest `coverage_v2.status_counts` from segment histogram
- **Never** invents segments; **never** rewrites `coverage_segments`
- Refuses empty COMPLETE (null/0 `receipt_run_id`)
- Prefer this surgical path over full `refresh_coverage_ledger`

Verify:

```bash
sqlite3 "${LOCAL_DB}" <<SQL
SELECT status FROM dataset_coverage WHERE dataset='${DATASET}';
SELECT status, COUNT(*) FROM coverage_segments
WHERE dataset='${DATASET}' GROUP BY status;
SQL
```

Dataset COMPLETE count must match segment SoT (all COMPLETE → dataset COMPLETE).

## 6. Publish the ops projection (separate, controlled step)

Only after Step 5 confirms a single +1 delta **and** Step 5b aggregate is honest:

```bash
python scripts/publish_ops_projection.py --db "${LOCAL_DB}" --apply-remote
```

Notes:

- `publish_ops_projection` is the only sanctioned path that writes remote D1
  projection tables.
- Projection freshness is never refreshed by mutating an active row. Publish a
  newly reconciled immutable generation or keep the prior generation stale.

## 7. Publish guard

Before the publish step, the publish guard verifies:

1. `coverage_segments` delta is `+1 COMPLETE` for the targeted dataset.
2. No segments moved from `COMPLETE` to a non-COMPLETE state.
3. `ops_projection_generation` is append-only and permits only immutable
   `SEALED` rows; activation state lives exclusively in
   `ops_projection_active`.
4. `collection_receipts.status` for the segment is `SUCCESS`.

If any check fails, the publish is aborted and **no remote mutation occurs**.

## 8. Audit log entry

Record an entry in the operations audit log:

```
YYYY-MM-DDTHH:MM:SSZ  operator=<you>  dataset=<DATASET>  segment_id=<SEGMENT_ID>
                      receipt_id=<RECEIPT_ID>  r2_key=<R2_KEY>  delta=+1COMPLETE
                      publish_generation_id=<gen_...>
```
