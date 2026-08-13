# T12 receipts wave — fins_details + fins_summary raw seal **+45** (2026-08-14)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**cf_premium_backfill:** **not** launched (peer `t5_fins_paced` + `t6_options_near` left running)  
**empty-raw ban:** held (`_is_usable_raw`; only non-empty R2 page combines)

## Summary

| Metric | PRE | POST |
|--------|----:|-----:|
| Local segment COMPLETE | **538** | **585** (**+47** total delta) |
| Remote segment COMPLETE | **538** | **585** |
| This T12 wave (fins) | | **+45** |
| Peer concurrent (T9 options Jun/Jul) | | **+2** (receipts `900586–900587`; already documented) |
| Projection | — | **FRESH** `projgen-134169e74fda4429bb2ea8b2e69ab36a` age=0 |

Fail-closed publish: `complete_count_guard ok local=585 remote=560 force=False` → remote applied to **585**.

## Path (raw-required only; no new acq)

1. Remote `raw_retention_manifests` COMPLETE + `row_count>0` for peer-acq months.
2. `wrangler r2 object get quant-raw/raw/{dataset}/{run_id}/page-*.json` → combine non-empty pages →  
   `data/raw/jquants/2026/08/14/{dataset}_from=_to=_from_r2_run*.json`
3. `normalize_generic` + `SqliteStore.upsert(jquants_records)` (empty envelopes rejected).
4. `scripts/issue_receipts_parallel.py --struct-hint` → signed SUCCESS.
5. `scripts/publish_ops_projection.py --refresh-coverage --apply-remote` (no `--force-apply-remote`).

## Sealed this T12 wave (**+45**)

### `fins_details` **+20** — receipt run_id **900566–900585**

| segment_ids | structured range (ex.) | R2 acq runs (ex.) |
|-------------|-----------------------:|-------------------|
| **2018-01 … 2019-08** (20 months) | 236 … 2703 | 6347 … 6375 |

PRE COMPLETE segs: `2024-01`, `2024-02`, `2026-08` only.  
POST COMPLETE segs: **23** = prior 3 + **2018-01…2019-08**.

### `fins_summary` **+25** — receipt run_id **900588–900612**

| segment_ids | structured range (ex.) | R2 acq runs (ex.) |
|-------------|-----------------------:|-------------------|
| **2008-07 … 2010-07** (25 months) | 303 … 3853 | 5961 … 6215 |

PRE COMPLETE segs: `2024-01/02`, `2026-06/07/08` (5).  
POST COMPLETE segs: **30** = prior 5 + **2008-07…2010-07**.

Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`.  
Reconciliation: `raw_row_count == structured_row_count` (script policy).

## Explicit non-claims / DEFER

| Item | Why |
|------|-----|
| `cf_premium_backfill` this pass | **Not started** (avoid fins/options acq contention) |
| Remaining fins_summary months (2010-08… beyond wave cap 25) | **DEFER** — more R2 raw exists; next T12 wave |
| Remaining fins_details (2019-09… beyond 2019-08) | **DEFER** — peer acq still writing |
| COMPLETE without raw / empty `{"data":[]}` | **Forbidden** / empty-raw ban |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| Dataset-level COMPLETE beyond calendar + tokyo-repo | still **2** |

## Publish (fail-closed)

```text
coverage ledger refresh ok
complete_count_guard ok local=585 remote=560 force=False
remote projection applied
ops_reeval_freshness → projgen-134169e74fda4429bb2ea8b2e69ab36a FRESH age=0
```

Verified live remote D1: `coverage_segments status=COMPLETE` count **585**.

## Operator repro

```bash
# dry (after R2 mirror + local struct upsert)
.venv/bin/python scripts/issue_receipts_parallel.py \
  --datasets fins_details,fins_summary \
  --struct-hint --limit 40 --workers 6 --order asc --dry-run --json-summary

# issue
.venv/bin/python scripts/issue_receipts_parallel.py \
  --datasets fins_details,fins_summary \
  --struct-hint --limit 40 --workers 6 --order asc --json-summary

.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite --refresh-coverage --apply-remote
```
