# Sticky COMPLETE verification (2026-08-12)

## Code (origin includes `4aaf424`+)
In `storage/coverage_ledger.py` refresh path:
- If prior segment status is COMPLETE
- And receipt is SUCCESS + COMPLETE-eligible (Ed25519 TRUSTED)
- Then demotion to PARTIAL is **blocked** (`sticky_complete: true`)

## Live quant-mcp / wrangler (same day)
| Metric | Value |
|--------|--------|
| markets_calendar segments | **224 COMPLETE / 0 PARTIAL** |
| dataset COMPLETE | **markets_calendar**, **jsda_tokyo_repo_rates** |
| segment COMPLETE total | **400** |
| master | scd2_event_sourcing / 128811 |
| projection | FRESH age≈0 |

## Conclusion
Sticky COMPLETE is present on origin and live calendar is fully COMPLETE (no regression).
Mass / READY remain NO-GO.
