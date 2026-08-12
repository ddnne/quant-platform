# COMPLETE +3 proof — parallel signed receipts continuation (Track A3)

**Date:** 2026-08-12  
**Operator path:** `scripts/issue_receipts_parallel.py` (ThreadPool prepare + serial sign/write)  
**Mass / READY / Phase7:** still **NO-GO**  
**cf_premium_backfill:** **not** launched (bars lane ownership)

## PRE / POST

| Metric | PRE | POST |
|--------|----:|-----:|
| Local segment COMPLETE | **479** | **481** |
| Remote segment COMPLETE | **479** | **481** |
| Net this batch | | **+3 sealed**, remote lag closed; concurrent bars ledger −1 observed locally before publish (see note) |

> Honest net arithmetic: started local **479**, issued **+3** SUCCESS receipts
> (`equities_earnings_calendar/2026-08`, `fins_details/2024-02`, `fins_details/2024-01`).
> Concurrent `equities_bars_daily` COMPLETE **12→11** (not this track) made the
> observed ledger total **481** (= 479 + 3 − 1) at publish time. Fail-closed
> guard compared **local=481 ≥ remote=479** and applied without `--force`.

## Segments sealed this batch

| dataset | segment_id | structured_row_count | run_id | raw |
|---------|------------|---------------------:|-------:|-----|
| `equities_earnings_calendar` | 2026-08 | 137 | 900492 | usable date= day payload (non-`[]`) |
| `fins_details` | 2024-02 | 2705 | 900493 | largest non-empty date= day in window |
| `fins_details` | 2024-01 | 990 | 900494 | largest non-empty date= day in window |

Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`.  
Empty-raw ban: `fins_details/2026-08` has structured rows but only empty/`no_raw`
evidence → **skipped** (never COMPLETE without raw).

## Script improvement

`--struct-hint`: SQL `EXISTS (jquants_records in-window)` so `--limit` is spent
on months that already hold structured rows. Without it, `fins_details` desc
scan of limit=20 only saw empty 2025–2026 months and missed 2024-01/02.

Also tightened empty-raw rejection for pretty-printed `[\n]` / `{\n}`.

```bash
.venv/bin/python scripts/issue_receipts_parallel.py \
  --datasets fins_details,equities_earnings_calendar \
  --struct-hint --limit 20 --workers 6 --order desc --dry-run --json-summary
```

## Publish (fail-closed)

| Guard | Value |
|-------|-------|
| `complete_count_guard` | `local=481 remote=479 force=False` → ok |
| Generation | `projgen-b6d1dd3f25d048c5acb0520fa3660a2b` |
| Applied | remote D1 projection; verified **local COMPLETE = remote COMPLETE = 481** |

## Explicit non-claims / DEFER

| Item | Status |
|------|--------|
| COMPLETE without raw | **Forbidden** — remaining struct-only months skipped |
| Empty `[]` raw | **Rejected** |
| Mass / READY / Phase7 | **NO-GO** |
| `cf_premium_backfill` / dual rebuild | **Not** started |
| Remaining struct+no_raw (e.g. `fins_dividend/2026-08`, `markets_short_sale_report/2026-08`, investor_types 2019-12/2026-08) | **DEFER** until usable raw lands |
| Dataset-level COMPLETE for sealed series | Still **PARTIAL** history |
