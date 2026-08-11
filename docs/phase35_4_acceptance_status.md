# Phase 3.5 / 4 acceptance status (honest)

**Code P0s landed on `main` this session.** Phase 5 still blocked until ops evidence below is green.

## P0 merge status
| P0 | Status | Notes |
|----|--------|-------|
| P0-1 available_at policy | **merged** | `availability.ts` + Python mirror + unit tests |
| P0-2 validation honesty | **merged** | C1/C2 run-log honesty; weekly `--require-implemented` |
| P0-3 watermarks + incremental sync | **merged** | `0002_watermarks.sql` + sync `--incremental` + scale doc |
| P0-4 CF parallel + retry | **merged** | concurrency 4 / 125ms floor / 429-5xx retry |
| P0-5 intended_role + accept report | **merged** | FeatureDefinition roles + `scripts/run_phase4_accept.py` |

Offline `pytest` after all three merges: green. Worker `tsc --noEmit`: green.

## Ops still required (not “complete” yet)
1. Apply D1 migration `0002_watermarks.sql` on production (if not auto-applied by deploy)
2. Confirm live `/health` + full `/v1/run` **failed=0** after final main deploy (worker branch already deployed mid-P0)
3. Produce live artifacts: `data/reports/phase4_accept_*.json`, weekly validation report
4. Multi-year history / R2 partition migration remains a scale path (scaffolded, not full rewrite)

## What is solid
- Phase 0–3 design (PIT sole path, core black-box, as_of gate)
- Phase 3.5 Worker/R2/D1/Cron/Secrets/Export + Premium 23
- Feature Registry pit-only offline + live B0 path
- available_at session_close for bars (historical PIT usable at close, not only at ingest)

## Phase 5
Do **not** start until ops checklist above is honestly green.
