# W70 / w0816d — dataset_coverage aggregate follow-up (post-seal path)

**Wave status:** **COMPLETE** (tooling + checklist + tests; live COMPLETE **22** held)  
**Wave:** W70 / `w0816d` · Task A  
**Implementer:** GLM5.3 (Grok does not implement)  
**Live verified (local research DB dry-run):** `2026-08-16` · Dataset COMPLETE **22** · PARTIAL **4** · segs **3482** · fins **104/104** · empty COMPLETE **0**  
**READY 未宣言** · Mass **NO-GO** · Phase7 **OFF** · densify **none** · empty-raw COMPLETE **forbidden**  
**Commit/push:** **not done** (per wave instruction)

---

## Problem (W68 → W69 residue class)

W68 sealed `fins_earnings_date` tip so **`coverage_segments` = 104/104 COMPLETE**, but
`dataset_coverage.status` stayed **PARTIAL** with stale `coverage_v2.status_counts`
until W69 one-off surgical re-agg. That wave used a log-dir script
(`.glm-logs/w0816c_w69_ops_sync/surgical_reagg_fins.py`) — not a reusable path.

**Must prevent recurrence:** after segment COMPLETE seal, aggregate must update
(or a mandatory checklist + script must exist).

---

## Success criteria

| criterion | result |
|-----------|--------|
| Reusable surgical re-agg API | **`storage.sync_dataset_coverage_from_segments`** |
| CLI | **`scripts/sync_dataset_coverage_from_segments.py`** |
| Unit tests (pure + in-memory DB) | **15 passed** |
| Post-seal checklist documented | complete_segment + safe_complete_one_segment |
| Wire into restore path | `restore_local_complete_from_receipt.py` auto-syncs dataset |
| Do not roll back COMPLETE 22 / fins 104/104 | **held** (dry-run all = verify_only) |
| empty-raw COMPLETE forbidden | refuse promote on null/0 `receipt_run_id` |
| Mass / READY | **OFF** · not declared |
| Full `refresh_coverage_ledger` | **not required** for aggregate lag |
| Commit/push | **not done** |

---

## API

### Pure helpers (`packages/data_plane/storage/coverage_ledger.py`)

```python
from storage.coverage_ledger import (
    aggregate_status_from_segment_counts,  # Mapping[str,int] -> COMPLETE|PARTIAL|FAILED|UNKNOWN
    honest_status_counts,                  # drop zeros
    build_surgical_reagg_detail,           # merge coverage_v2.status_counts + audit
    sync_dataset_coverage_from_segments,   # conn-level surgical re-agg
)
```

#### `aggregate_status_from_segment_counts(status_counts) -> str`

| segment histogram | aggregate |
|-------------------|-----------|
| empty / all-zero | `UNKNOWN` (never invent COMPLETE) |
| any `FAILED` | `FAILED` |
| all `COMPLETE` (total > 0) | `COMPLETE` |
| else | `PARTIAL` |

#### `sync_dataset_coverage_from_segments(conn, *, datasets=None, policy_version=..., dry_run=False, require_no_failing_checks=True, refuse_empty_complete=True, wave=None) -> list[dict]`

Behavior:

1. Read `coverage_segments` status histogram per dataset (`policy_version` scoped).
2. Derive honest `status_counts` + aggregate status from segment SoT.
3. **Promote** `dataset_coverage` → COMPLETE only when all segs COMPLETE **and**
   (for PARTIAL→COMPLETE) no failing C* checks and no empty COMPLETE segs.
4. Update **only** `dataset_coverage.status` + `detail_json` + `evaluated_at`.
5. **Never** invent or rewrite `coverage_segments` (asserts platform COMPLETE count stable).
6. Already-COMPLETE datasets with historical C* fail noise are **held** (verify_only), not demoted.

Action values: `promoted` | `demoted` | `counts_refreshed` | `verify_only` |
`skip_missing_dataset_coverage` | `skip_empty_inventory` | `skip_failing_checks` |
`skip_empty_complete_segments`.

Also re-exported from `storage` package `__init__`.

### CLI

```bash
# Dry-run (all datasets)
.venv/bin/python scripts/sync_dataset_coverage_from_segments.py \
  --db data/structured/ingestion.sqlite --dry-run

# Surgical one-dataset promote (post-seal when segs all COMPLETE)
.venv/bin/python scripts/sync_dataset_coverage_from_segments.py \
  --db data/structured/ingestion.sqlite --datasets fins_earnings_date

# Machine JSON
.venv/bin/python scripts/sync_dataset_coverage_from_segments.py \
  --db data/structured/ingestion.sqlite --datasets fins_earnings_date --json
```

Flags: `--dry-run`, `--datasets …`, `--policy-version`, `--allow-failing-checks`,
`--allow-empty-complete` (not recommended), `--wave`, `--json`, `--summary`.

### Restore path wiring

`scripts/restore_local_complete_from_receipt.py` — after a successful segment
COMPLETE seal, automatically calls
`sync_dataset_coverage_from_segments(conn, datasets=[dataset])` so the last
PARTIAL segment promote also flips `dataset_coverage` without a full ledger
refresh.

---

## How to run after seal (operator checklist)

When a tip seal / issue path leaves segs all-COMPLETE but ops Dataset COMPLETE
lags (or after any path that does not go through restore):

```bash
# 1) Surgical re-agg (local research DB; segs untouched)
.venv/bin/python scripts/sync_dataset_coverage_from_segments.py \
  --db data/structured/ingestion.sqlite --datasets <DATASET>

# 2) Fail-closed publish (local COMPLETE segs >= remote)
.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite --apply-remote
# Do NOT use --force-apply-remote unless deliberately overriding the guard.

# 3) FRESH reclock (segments untouched)
.venv/bin/python scripts/ops_reeval_freshness.py

# 4) Regression: COMPLETE count matches segment SoT
.venv/bin/python scripts/refresh_coverage_ledger.py \
  --db data/structured/ingestion.sqlite --summary-only
.venv/bin/python scripts/refresh_coverage_ledger.py \
  --db data/structured/ingestion.sqlite --gaps-only
```

Prefer **one-dataset** surgical re-agg over full `refresh_coverage_ledger`
when the segment plane is already correct (W69 class).

Documented also in:

- [`docs/complete_segment_checklist.md`](../complete_segment_checklist.md) step 9
- [`docs/operations/safe_complete_one_segment.md`](../operations/safe_complete_one_segment.md) step 5b

---

## Regression: COMPLETE count matches segment SoT

### Dry-run on live research DB (this wave)

```text
dataset_coverage PRE {'COMPLETE': 22, 'PARTIAL': 4} -> POST {'COMPLETE': 22, 'PARTIAL': 4}
platform COMPLETE segs 3482 -> 3482 (untouched=True)
actions: verify_only × 26
fins_earnings_date: verify_only COMPLETE segs={'COMPLETE': 104} complete=104/104
```

| surface | value |
|---------|------:|
| Dataset COMPLETE | **22** (held) |
| Dataset PARTIAL | **4** (held) |
| platform COMPLETE segs | **3482** (untouched) |
| fins segs | **104/104 COMPLETE** |
| fins `dataset_coverage` | **COMPLETE** |
| empty COMPLETE | **0** |

PARTIAL set (unchanged DEFER residual):

1. `equities_bars_daily_am`
2. `equities_earnings_calendar`
3. `equities_master`
4. `jsda_otc_bond_reference_prices`

### Unit tests

```bash
.venv/bin/python -m pytest tests/test_sync_dataset_coverage_from_segments.py -v
# 15 passed
```

Coverage:

| test | asserts |
|------|---------|
| all COMPLETE → COMPLETE | pure + DB promote |
| any PARTIAL → PARTIAL | pure + DB stay/refresh |
| any FAILED → FAILED | pure |
| empty inventory → UNKNOWN | never invent COMPLETE |
| empty-raw COMPLETE segs | skip promote |
| failing C* on PARTIAL | skip promote |
| already COMPLETE + failing C* | hold COMPLETE (verify_only) |
| dry-run | no write |
| missing `dataset_coverage` row | skip (no invent aggregate) |
| stale COMPLETE vs PARTIAL segs | honest demote |
| segments untouched | COMPLETE seg count stable |

---

## What this wave did **not** do

| non-goal | held |
|----------|------|
| Roll back COMPLETE 22 / fins 104/104 | yes |
| Full `refresh_coverage_ledger` | not run |
| Remote D1 publish / force-apply | not run (tooling only) |
| Mass / READY / Phase7 ON | no |
| densify / invent segs | no |
| commit/push | deferred |
| Change S1–S5 / residual DEFER 4 | untouched |

---

## Artifacts

| path | role |
|------|------|
| [`packages/data_plane/storage/coverage_ledger.py`](../../packages/data_plane/storage/coverage_ledger.py) | pure + `sync_dataset_coverage_from_segments` |
| [`packages/data_plane/storage/__init__.py`](../../packages/data_plane/storage/__init__.py) | re-exports |
| [`scripts/sync_dataset_coverage_from_segments.py`](../../scripts/sync_dataset_coverage_from_segments.py) | CLI |
| [`scripts/restore_local_complete_from_receipt.py`](../../scripts/restore_local_complete_from_receipt.py) | post-seal auto-sync |
| [`tests/test_sync_dataset_coverage_from_segments.py`](../../tests/test_sync_dataset_coverage_from_segments.py) | unit tests |
| [`docs/complete_segment_checklist.md`](../complete_segment_checklist.md) | mandatory step 9 |
| [`docs/operations/safe_complete_one_segment.md`](../operations/safe_complete_one_segment.md) | step 5b |
| W69 prior | [`w0816c_w69_ops_aggregate_sync_20260816.md`](w0816c_w69_ops_aggregate_sync_20260816.md) |
| this file | proof |

---

## Result

**Reusable surgical re-aggregate path exists.** After any future segment seal that
fills the last PARTIAL for a dataset, operators (or restore) run
`sync_dataset_coverage_from_segments` → publish → freshness so ops Dataset
COMPLETE tracks segment SoT without a risky full ledger refresh.
**COMPLETE 22 / fins 104/104 / segs 3482 held.**
