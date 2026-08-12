# Track A dry-run proof (historical raw acceleration)

**Date:** 2026-08-12  
**Mode:** dry-run only (`--execute` **not** used)  
**ADR:** [`docs/architecture/adr_historical_raw_acceleration.md`](../architecture/adr_historical_raw_acceleration.md)

## Absolute bans respected

- No Mass ON / READY
- No COMPLETE without raw (no COMPLETE claimed)
- Local sqlite treated as research mirror, not CF SoT
- No secrets / tokens in logs or proof artifacts
- No sqlite DB commit

## PRE metrics (local research mirror)

Source: `docs/proof/raw_throughput_PRE_20260812.json`

| Metric | Value |
|--------|------:|
| raw_retention_manifests | **0** (remote ~1488; local not synced) |
| complete_segments | **404** |
| complete_datasets | **2** (`markets_calendar`, `jsda_tokyo_repo_rates`) |
| stale_datasets | **1** (`markets_margin_interest`) |
| projection | **FRESH** |

### Track A focus (local)

| dataset | status | complete/total segs | local records | event_time max (local) |
|---------|--------|--------------------:|--------------:|------------------------|
| equities_bars_daily | PARTIAL | 12/272 | 803862 | 2026-08-10 (local starts ~2024) |
| indices_bars_daily_topix | PARTIAL | 32/224 | 635 | 2026-08-10 |
| markets_breakdown | PARTIAL | 8/164 | 2669153 | 2026-08-10 |
| fins_summary | PARTIAL | 5/224 | 6121 | 2026-08-10 |
| equities_master | PARTIAL | 94/314 | 7679458 | 2026-08-12 |
| markets_margin_interest | **STALE** | 14/164 | 251470 | 2025-02-28 |

Honest residual: **margin interest remains STALE** until C8 freshness + history close; dry-run does not claim otherwise.

## Dry-run command

```bash
python scripts/ops/cf_premium_backfill.py \
  --track-a \
  --datasets equities_bars_daily,indices_bars_daily_topix,markets_breakdown,fins_summary,equities_master,markets_margin_interest \
  --from-date 2004-01-01 \
  --to-date 2023-12-31
```

## Queue result

| Field | Value |
|-------|------:|
| mode | dry-run |
| queued jobs | **1066** |
| executed | **0** |
| general pool | 874 |
| fins pool | 192 |

### By dataset

| dataset | jobs | pool |
|---------|-----:|------|
| equities_bars_daily | 240 | general |
| equities_master | 178 | general |
| indices_bars_daily_topix | 192 | general |
| markets_breakdown | 132 | general |
| markets_margin_interest | 132 | general |
| fins_summary | 192 | **fins** |

### Throughput design envelope (host dispatch only)

| Parameter | Value |
|-----------|------:|
| general RPM | 480 (under ~500/min) |
| fins RPM | 480 (isolated) |
| host dispatch floor (parallel pools) | ~1.82 min |
| host dispatch floor (serial all) | ~2.22 min |

**Note:** Worker pagination dominates wall-clock. This envelope is **not** a COMPLETE/SLA estimate.

### Sample range jobs (date-range batch standard)

| dataset | from | to | segment | pool |
|---------|------|----|---------|------|
| equities_bars_daily | 2004-01-05 | 2004-01-31 | 2004-01 | general |
| indices_bars_daily_topix | 2008-01-01 | 2008-01-31 | 2008-01 | general |
| fins_summary | 2008-01-08 | 2008-01-31 | 2008-01 | fins |
| markets_breakdown | 2013-01-04 | 2013-01-31 | 2013-01 | general |
| markets_margin_interest | 2013-01-04 | 2013-01-31 | 2013-01 | general |
| equities_master | 2004-01-01 | 2004-01-31 | 2004-01 | general |

## Margin latest-only dry-run

```bash
python scripts/ops/cf_premium_backfill.py \
  --datasets markets_margin_interest --latest-only --max-jobs 1
```

→ queued **1** job (latest incomplete month). Execute intentionally deferred in this proof (STALE root causes are multi-plane; see `p1_markets_margin_interest_stale_defer_20260812.md`).

## POST

No live execute in this Track A commit → POST metrics **unchanged** vs PRE for raw/COMPLETE. Re-measure after controlled `--execute` windows with:

```bash
python scripts/report_raw_throughput.py --label POST \
  --baseline docs/proof/raw_throughput_PRE_20260812.json \
  --format both --out-dir docs/proof
```

## Artifacts

- `docs/proof/raw_throughput_PRE_20260812.json` / `.md`
- `docs/proof/track_a_dryrun_20260812.json` (slim queue summary)
- Full plan/queue under `.glm-logs/cf-backfill/` (local only, not committed)
