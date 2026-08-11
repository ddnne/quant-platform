# Phase 3.5 / 4 acceptance status (honest)

**Code P0s on `main`.** Ops advanced; Phase 5 still gated.

## P0 code
| P0 | Status |
|----|--------|
| P0-1 available_at | merged + deployed |
| P0-2 validation honesty | merged (weekly not_implemented → exit 1) |
| P0-3 watermarks | merged; D1 migrations applied |
| P0-4 parallel + retry | merged + deployed |
| P0-5 intended_role + accept | merged; live `jquants_records` fallback |

## Ops snapshot (2026-08-11 JST)
| Check | Result |
|-------|--------|
| Live phase4 accept | **`ok=true`** (B0, hit≈0.9, BT≥50 days) |
| B0 live gates | pass (≥3000 master/bars) |
| Proxy URL | local config → **premium** worker |
| **Chunked Premium-23** | **22/23 pass** same-day; `derivatives_bars_daily_options` flaky (timeout / D1_ERROR network lost) |
| Watermarks | **22/23** after chunked run |
| Full single-shot `/v1/run` | unreliable — use chunked |
| Daily validation | exit 1 (data gaps) — not waived |
| Weekly validation | exit 1 — correct fail on ~39 `not_implemented` |

Local artifact: `.glm-logs/ops-chunked-23-summary.json` (not in git).

## Remaining before Phase 5
1. Stabilize `derivatives_bars_daily_options` (large payload D1 writes)
2. Weekly matrix: implement or explicitly waive remaining `not_implemented` IDs
3. Daily matrix green on fuller event_time coverage
4. Multi-year R2 partition path (scaffold only)

## Phase 5
Do **not** start until remaining list is green or waived in writing.
