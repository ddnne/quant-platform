# G7 = T11 + T12 — JSDA OTC DEFER + parallel signed receipts **+10** (2026-08-13)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**cf_premium_backfill:** **not** launched (peers t6/t7/t8/t5 own acq; receipt priority only)  
**empty-raw ban:** held (`_is_usable_raw`; only non-empty R2 page combines)

## Summary

| Metric | PRE | POST |
|--------|----:|-----:|
| Remote segment COMPLETE | **510** | **520** (**+10**) |
| Local segment COMPLETE | **510** | **520** |
| JSDA OTC COMPLETE segs | **5** | **5** (**+0**) |
| JSDA corporate COMPLETE segs | **1** (`2026`) | **1** (**+0**) |
| Remote `raw_retention_manifests` | ~6477 | **7130** total / **6241** COMPLETE completeness (peer acq continuing) |
| Projection | — | **FRESH** `projgen-3ac496d26f2d45c78ae849e06b988974` age=0 |

## T11 — JSDA OTC / corporate (raw-required only)

### OTC probe

| check | result |
|-------|--------|
| Official site `market.jsda.or.jp:443` | **connect timeout** (~9.3s, curl 28) on S260805… and peer days |
| R2 keys for unsealed days (`S260805/04/03/731/730`, corporate 2024/2025) | **MISS** (key does not exist) |
| Local raw beyond sealed 5 days | none usable for new seal |
| Existing COMPLETE days | `2026-08-06/07/10/12/13` retained |

**OTC +0.** Honest **DEFER** — no receipt/seal without raw. Site timeout recorded; not treated as empty-success.

### Corporate bond

| check | result |
|-------|--------|
| COMPLETE year | `2026` only |
| R2 probe prior years (`TORIHIKI2025`, `2024`, …) | **MISS** |
| Seal prior years | **DEFER** (raw-required; no invent) |

## T12 — Parallel signed receipts (new raw)

Upstream peer **t6** mirrored R2 pages → local `data/raw/jquants/2026/08/13/*_from=_to=_from_r2_run*.json` + structured upsert (empty pages dropped).  
This pass issued via `scripts/issue_receipts_parallel.py --struct-hint` (empty-raw ban).

### Sealed segments (+10) — receipt run_id **900530–900539**

| dataset | segment_id | structured | receipt run_id | R2 acq run |
|---------|------------|----------:|---------------:|-----------:|
| `edinet_major_shareholders` | 2026-02 | 71 | **900530** | 5613 |
| `edinet_cross_shareholdings` | 2026-06 | 2194 | **900531** | 5665 |
| `edinet_large_volume_shareholders` | 2026-06 | 1696 | **900532** | 5929 |
| `edinet_large_volume_shareholders` | 2026-05 | 1206 | **900533** | 5922 |
| `edinet_large_volume_shareholders` | 2026-04 | 1230 | **900534** | 5908 |
| `edinet_large_volume_shareholders` | 2026-03 | 1397 | **900535** | 5870 |
| `edinet_large_volume_shareholders` | 2026-02 | 1018 | **900536** | 5810 |
| `edinet_large_volume_shareholders` | 2026-01 | 1023 | **900537** | 5738 |
| `derivatives_bars_daily_futures` | 2026-02 | 2016 | **900538** | 5948 |
| `derivatives_bars_daily_futures` | 2026-01 | 2128 | **900539** | 5941 |

Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`.  
Reconciliation: `raw_row_count == structured_row_count` (script policy).

### POST COMPLETE months (remote)

| dataset | COMPLETE segment_ids |
|---------|----------------------|
| `edinet_major_shareholders` | 2026-01, **2026-02**, 2026-07, 2026-08 |
| `edinet_cross_shareholdings` | 2026-02/03/04, **2026-06**, 2026-07/08 |
| `edinet_large_volume_shareholders` | **2026-01…06**, 2026-07, 2026-08 |
| `derivatives_bars_daily_futures` | **2026-01**, **2026-02**, 2026-08 |

## Publish (fail-closed)

```text
complete_count_guard ok local=520 remote=510 force=False
remote projection applied
ops_reeval_freshness → projgen-3ac496d26f2d45c78ae849e06b988974 FRESH age=0
```

No `--force-apply-remote`. Mass / READY / Phase7 untouched.

## Fail / DEFER reasons

| Item | Why |
|------|-----|
| OTC additional trading days | site **timeout** + R2 **MISS** → no raw → **DEFER** |
| Corporate years 2015–2025 | no local/R2 raw → **DEFER** |
| `cf_premium_backfill` this pass | **not started** (avoid acq contention) |
| COMPLETE without raw / empty `{"data":[]}` | **Forbidden** / rejected by empty-raw ban |
| Dataset-level COMPLETE beyond calendar + tokyo-repo | still **2** |

## Operator repro

```bash
# dry (after R2 mirror + local struct upsert)
.venv/bin/python scripts/issue_receipts_parallel.py \
  --datasets edinet_major_shareholders,edinet_cross_shareholdings,edinet_large_volume_shareholders,derivatives_bars_daily_futures \
  --struct-hint --limit 20 --workers 6 --order asc --dry-run --json-summary

# issue
.venv/bin/python scripts/issue_receipts_parallel.py \
  --datasets edinet_major_shareholders,edinet_cross_shareholdings,edinet_large_volume_shareholders,derivatives_bars_daily_futures \
  --struct-hint --limit 20 --workers 6 --order asc --json-summary

.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite --refresh-coverage --apply-remote
```
