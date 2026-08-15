# W60 / w0815ba — R2 bridge expand (margin / short / fins / alert)

**Wave:** W60 / w0815ba  
**Label:** **研究用・未宣言**  
**Mass / Phase7:** **NO-GO / OFF**  
**READY:** **not** declared  
**DEFER 5:** **hard reject** (unchanged)  
**local SoT:** **false**

## What landed

| item | status |
|------|--------|
| `BRIDGE_EXPAND_DATASETS` | `markets_margin_interest` · `markets_short_ratio` · `fins_summary` · `markets_margin_alert` |
| Schema map (`bridge_expand_column_map`) | documented in `schema_mapping_document()` |
| Loader path | existing `normalize_r2_history_row` + catalog normalizer; DiscDate/PublishedDate date aliases |
| available_at policy | `AVAILABLE_AT_REPAIR_POLICY` / `repair_available_at_research` **explicit** |
| DEFER hard reject | held |
| Unit tests | `tests/test_r2_feature_context.py` bridge expand + aa repair + multi-signal r2 |

## available_at policy (no silent look-ahead)

| repair | datasets | action |
|--------|----------|--------|
| `calendar_ingest_pollution` | `markets_calendar` | if `available_at` day > event day → set `available_at = event_time` (research-only) |
| `missing_available_at_drop` | all | null/empty → **drop** (never invent) |
| `post_date_preserve` | bars/topix/fins/margin/short/alert | keep real post-event publish times |

**Forbidden:** `available_at = as_of` / `now()` / evaluation clock.

Document: `research.r2_feature_context.AVAILABLE_AT_REPAIR_POLICY`  
Log: [`.glm-logs/w0815ba_w60_long_multisignal/available_at_policy.json`](../../.glm-logs/w0815ba_w60_long_multisignal/available_at_policy.json)

## Live extract counts (disposable mirrors of R2 GET)

| dataset | extracted rows (no code filter) | channel |
|---------|--------------------------------:|---------|
| `markets_margin_interest` | **1200** | archive batch NDJSON sample |
| `markets_short_ratio` | **790** | archive batch NDJSON sample |
| `fins_summary` | **77** | JSONL 2024-08…2024-12 filtered to 30-code universe |
| `markets_margin_alert` | **500** | JSONL sample (cap) |

Log: [`bridge_expand_extract.json`](../../.glm-logs/w0815ba_w60_long_multisignal/bridge_expand_extract.json)

**Note:** margin/short JSONL has **no 2024-calendar-year shards** in live inventory (years present: 2013–2023 + 2025–2026 for margin; short similar gap). Long multi-signal S1/S2/S3 window used fins for S3; margin interest optional/empty-allowed when out of period. Bridge loaders themselves are COMPLETE-21 capable and PIT-gated.

## Multi-signal R2 path

`execute_multiday_multisignal_compare(..., history_source="r2")` wired (default remains `d1_tip`).

## Non-declarations

- READY **not** declared  
- Mass **NO-GO** · Phase7 **OFF**  
- No densify · no COMPLETE 22 · no DEFER load  
- No significance / edge / operational GO  
