# Phase 3.5 / 4 acceptance status (honest)

**Code P0s landed on `main` @ `da60d8b`.** Phase 5 still blocked until ops evidence is green.

## P0 merge status
| P0 | Status | Notes |
|----|--------|-------|
| P0-1 available_at policy | **merged + deployed** | `availability.ts` + Python mirror; live bars use session_close |
| P0-2 validation honesty | **merged** | C1/C2 honesty; weekly `--require-implemented` exits 1 on stubs |
| P0-3 watermarks + incremental sync | **merged + D1 applied** | `0001`+`0002` applied remote `quant-ingest` |
| P0-4 CF parallel + retry | **merged + deployed** | concurrency=4, rateLimitMs=125 in `/health` |
| P0-5 intended_role + accept report | **merged** | offline accept report `ok=true` |

Offline `pytest`: green. Worker `tsc --noEmit`: green. Pushed to `origin/main`.

## Ops snapshot (2026-08-11 JST)
| Check | Result |
|-------|--------|
| `/health` | `ok=true`, datasets=23, last_run shows `concurrency=4 rateLimitMs=125` |
| D1 migrations remote | `0001_init` + `0002_watermarks` ✅ |
| Offline phase4 accept | `ok=true` (fixture; hit_rate=1.0; BT 30 days) |
| Daily validation on local sync DB | exit 1 — many C8/K3 fails (sparse local data / missing event_time) |
| Weekly validation | exit 1 — **correct**: 39 `not_implemented` treated as fail |
| Live phase4 accept / multi-year history | **not yet** |

## Remaining before Phase 5 (honest)
1. Live full `/v1/run` after main tip (worker deployed mid-P0; confirm post-merge tip)
2. Sync D1→local with watermarks; re-run daily matrix with fuller data
3. Live `scripts/run_phase4_accept.py` with `QP_LIVE=1` + report artifact
4. Weekly matrix: implement or explicitly defer remaining not_implemented IDs (currently correctly fail completion)
5. Multi-year / R2 partition migration remains scale path (scaffolded)

## Phase 5
Do **not** start until the remaining ops list is honestly green or explicitly waived.
