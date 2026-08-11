# Phase 3.5 / 4 acceptance status (honest)

Status as of 2026-08-11: **the Phase 4 live smoke is green, but the overall
Phase 3.5/4 live ops acceptance is not green**. The weekly validation now
enforces multi-year depth under `QP_LIVE=1`; the synced DB does not yet meet
that gate.

## Current gates

| Gate | Status |
|------|--------|
| P0-1..5 | merged + deployed (previously recorded; not rerun here) |
| Phase 4 offline real-DB smoke | **exit 0** — 1 passed, 1 live deselected |
| Phase 4 live synced-DB smoke | **exit 0** — B0 strict pass; `return_1d` hit rate 0.92 on 50 codes; 333 trading days (floor 50) |
| B0 strict | **pass** — master 4,444; bar issuers 4,660; latest-day rows 4,444 |
| Chunked Premium-23 | **23/23** (previously recorded) |
| Watermarks | **23/23** (previously recorded) |
| Weekly `--require-implemented`, `QP_LIVE=1` | **exit 1** — 28 pass, 44 fail, 4 skip, 17 warn |
| Daily validation | **exit 0** (previous run; not rerun here) |

## 2026-08-11 validation evidence

The weekly command was run once:

```bash
QP_LIVE=1 .venv/bin/python scripts/run_phase35_validation.py \
  --db data/structured/ingestion.sqlite --tier weekly --require-implemented
```

It reported no `not_implemented` skips. All 44 failures were strict C6/C7
history-depth/fill-rate failures (22 datasets in each family). In particular,
`equities_bars_daily` spans 2025-04-01 through 2026-08-10, versus the Premium
history expectation beginning 2004-01-05. `markets_margin_interest` remained
empty and skipped its C6/C7 checks. The audit report was persisted under
`data/reports/` by the validator.

The Phase 4 smoke itself is complete. Full Phase 3.5/4 live ops acceptance
remains blocked on loading enough historical depth for strict C6/C7. The R2
timeseries partition path remains scaffolded in
`docs/phase35_storage_scale.md`.

## Phase 5

Not started by this work. Do not treat the current weekly strict result as a
green handoff.
