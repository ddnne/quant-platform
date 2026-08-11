# Phase 3.5 / 4 acceptance status (honest)

**Code P0s on `main`.** Ops advanced 2026-08-11; Phase 5 still gated on weekly matrix honesty + multi-year scale.

## P0 code (merged)
| P0 | Status |
|----|--------|
| P0-1 available_at policy | merged + deployed |
| P0-2 validation honesty | merged (weekly `not_implemented` → exit 1) |
| P0-3 watermarks + incremental sync | merged; D1 `0001`+`0002` applied remote |
| P0-4 parallel + retry | merged + deployed (`concurrency=4`, `rateLimitMs=125`) |
| P0-5 intended_role + accept report | merged; live helpers fall back to `jquants_records` |

## Ops snapshot (2026-08-11 JST, this session)
| Check | Result |
|-------|--------|
| Worker deploy from main tip | Version after redeploy; watermarks export allowed |
| D1 migrations | `0001_init` + `0002_watermarks` ✅ |
| Sync (premium URL) | `jquants_records` incremental OK; default proxy URL pointed at *secrets* worker (404) — use `--url` premium |
| Bars backfill (partial) | weeks pass (e.g. +39k rows); some ranges D1 network fail / curl timeout |
| Calendar range ingest | `markets_calendar` 2026-01..08 pass (+217 rows) |
| Full `/v1/run` 23 datasets | client timeout 600s (incomplete single-shot); health still ok; use per-dataset / cron |
| B0 live gates | **pass** master/bars ≥3000 |
| Offline phase4 accept | `ok=true` |
| **Live** phase4 accept (`QP_LIVE=1`) | **`ok=true`** all sections (registry, hit rates ~0.9, BT 147 days ≥50, B0) |
| Daily validation local | exit 1 (data/event_time gaps) — not waived |
| Weekly validation | exit 1 — correct fail on 39 `not_implemented` |

## Remaining before Phase 5
1. Reliable full Premium-23 run (worker wall-clock / chunked run) with failed=0
2. Deeper multi-month bars without D1 connection drops; watermarks populated for all 23
3. Weekly matrix: implement or explicitly waive remaining `not_implemented` IDs
4. Fix default `ingestion_proxy_url` to premium worker (ops config; not in git)
5. Multi-year R2 partition path still scaffold-only

## Phase 5
Do **not** start until remaining list is green or explicitly waived in writing.
