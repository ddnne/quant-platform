# Phase 3.5 / 4 acceptance status (honest)

**Code P0s on `main`.** Ops advanced; Phase 5 still gated on weekly matrix.

## P0 code
| P0 | Status |
|----|--------|
| P0-1 available_at | merged + deployed |
| P0-2 validation honesty | merged |
| P0-3 watermarks | merged; D1 migrations applied |
| P0-4 parallel + retry | merged + deployed |
| P0-5 intended_role + accept | merged; live accept ok |

## Ops snapshot (2026-08-11 JST)
| Check | Result |
|-------|--------|
| Live phase4 accept | **`ok=true`** |
| B0 live gates | pass |
| **Chunked Premium-23** | **23/23 pass** (options fixed: stream D1 page-by-page + multi-stmt batch; was 1101/D1 lost) |
| Watermarks | 23/23 expected after options fix |
| Full single-shot `/v1/run` | still prefer chunked for wall-clock |
| Daily validation | exit 1 (data gaps) — not waived |
| Weekly validation | exit 1 — correct fail on ~39 `not_implemented` |

## Remaining before Phase 5
1. Weekly matrix: implement or explicitly waive remaining `not_implemented` IDs
2. Daily matrix green on fuller event_time coverage
3. Multi-year R2 partition path (scaffold only)
4. Optional: full single-shot 23-run under Worker limits

## Phase 5
Do **not** start until remaining list is green or waived in writing.
