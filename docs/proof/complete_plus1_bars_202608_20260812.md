# COMPLETE +1 proof — equities_bars_daily/2026-08 re-seal (Track A3)

**Date:** 2026-08-12  
**Operator path:** `scripts/issue_receipts_parallel.py`  
**Mass / READY / Phase7:** still **NO-GO**  
**cf_premium_backfill:** **not** launched

## Context

After concurrent A3 +3 (`docs/proof/complete_plus3_struct_hint_20260812.md`) closed
remote at **481**, local `equities_bars_daily/2026-08` had fallen to **PARTIAL**
(`missing collection receipt`) while usable local raw + structured rows still
existed (structured_row_count **26671**, non-empty raw payload ~3MB). Empty-raw
ban held; no backfill.

## PRE / POST

| Metric | PRE (this batch) | POST |
|--------|-----------------:|-----:|
| Local segment COMPLETE | **481** | **482** |
| Remote segment COMPLETE | **481** | **482** |
| `equities_bars_daily` COMPLETE segs | 11 (remote) / 12 after local issue | **12 / 12** |

## Segment sealed

| dataset | segment_id | structured_row_count | run_id | raw |
|---------|------------|---------------------:|-------:|-----|
| `equities_bars_daily` | 2026-08 | 26671 | 900495 | usable local jquants raw (non-`[]`) |

Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`.  
Reconciliation: `raw_row_count == structured_row_count == 26671`.

## Publish (fail-closed)

```text
complete_count_guard ok local=482 remote=481 force=False
active_generation: projgen-eb0412ea86f34c6ab51b5f312d3ebcbc
```

Verified after apply: **local COMPLETE = remote COMPLETE = 482**.

## Explicit non-claims

| Item | Status |
|------|--------|
| COMPLETE without raw | **Forbidden** — not used |
| Empty `[]` raw | **Rejected** by `_is_usable_raw` |
| `cf_premium_backfill` / Mass / READY / Phase7 | **Not** started |
| Dataset-level COMPLETE for bars | Still **PARTIAL** |

## Command

```bash
.venv/bin/python scripts/issue_receipts_parallel.py \
  --datasets equities_bars_daily --segment-id 2026-08 --limit 1 --workers 1
.venv/bin/python scripts/publish_ops_projection.py --apply-remote
```
