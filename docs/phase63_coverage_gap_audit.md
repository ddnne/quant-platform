# Phase 6.3 Coverage gap audit (4 PARTIAL)

Live quant-mcp 2026-08-23. **Do not invent COMPLETE.** Not GO.

Projection: **STALE** (`projgen-ef18b4f86ee946048161d25e2a30a2a8`, generated 2026-08-21).
Coverage aggregates below are last-known-good, not a fresh re-eval.

| Dataset | Status | Cause class | Contract change? | Human? |
|---------|--------|-------------|------------------|--------|
| `equities_bars_daily_am` | PARTIAL | **Stale coverage vs live ingest** + **session product entitlement/publication**. Target start 2024-01-04; projected observed 2026-08-01..11, 4444 rows. Inventory SLA `expected_after=11:30` `usable_by=12:30` JST. Sync watermark `last_event_date=2026-08-21` so ingest advanced after the 2026-08-14 coverage eval. 2024 target vs 2026 observed is a history-backfill/entitlement question, not a reason to shorten the target. | No (do not shorten 2024-01-04). Re-eval coverage after a fresh projection. | Confirm J-Quants AM session product window and whether empty AM responses are “not published yet” vs entitlement. |
| `equities_earnings_calendar` | PARTIAL | **Event data scored as monthly segments**. `coverage_mode=event_reconciled`, `expected_frequency=event_driven`, but inventory `coverage_segment_granularity=calendar_month`. Observed 2010-01-04..2026-08-14 with **333 rows**. Empty months / missing monthly receipts can stay PARTIAL even when events exist. | Yes, **event-grain contract** is justified; do not fabricate empty months as COMPLETE. | Approve event-reconciled segment identity (no monthly completeness fiction). |
| `equities_master` | PARTIAL | **History target 2006-08-13 vs observed_start 2008-05-01** (8,072,621 rows, SCD2). Current fetch gap is not proof the 2006 target is wrong. Do not shorten to 2008 because “we cannot fetch it today.” | Not without official J-Quants listed-info history start. | Official source spec for listed-info / master start; entitlement if 2006–2008 exists. |
| `jsda_otc_bond_reference_prices` | PARTIAL | **Receipt/segment incomplete, not only PARSE_ZERO**. COMPLETE 5886 / PARTIAL 2898 of 8784 required. Remaining official 2002 PARSE_ZERO days: `2002-08-02`, `2002-08-05` (2 days). 2898 PARTIAL ≫ 2 parse-zero days → deficit is **trusted receipt / segment completion**, not parse-zero. Raw acquired ≠ structured ≠ receipt-complete. | No. Do not mark PARSE_ZERO days COMPLETE. | None for inventing those two days. Receipt rebuild / segment identity for the 2898. |

## Raw vs Coverage

Hourly raw manifests often stamp `completeness=COMPLETE` with `row_count=0` / ~12 bytes. That is **EXPECTED_EMPTY_WITH_EVIDENCE** (or session-not-published), **not** dataset Coverage COMPLETE. MCP `raw_retention_status` now returns totals + `acquisition_state`.

## Sync

`applied_cursor` is null until a local apply pin is projected. Export lag 0 is **not** CURRENT.

## B0 / READY / SLA

- B0: UNKNOWN (no projected `ops_b0_status` row)
- READY: null
- SLA table empty; AM state projected as `PROJECTION_STALE` while ops projection is stale
