# W61 / w0815bb — Evaluation data coverage inventory & gaps

**Purpose:** Make holes explicit so multi-period signal reads are not over-interpreted.  
**SoT:** R2 `quant-structured` history · D1 tip not used as long-history SoT · local mirrors disposable.  
**Log:** [`.glm-logs/w0815bb_w61_multiperiod/coverage_inventory.json`](../../.glm-logs/w0815bb_w61_multiperiod/coverage_inventory.json)

## JSONL inventory (live list, W61)

| dataset | years present (JSONL) | notes |
|---------|----------------------|-------|
| `equities_bars_daily` | 2008–2026 | usable multi-period bars |
| `indices_bars_daily_topix` | 2008–2023 + **2026** | **gap 2024–2025 JSONL** → long eval uses **archive** (2008-05-07…2026-06-30) |
| `markets_calendar` | **2026 tip only** | history uses **archive** + research PIT repair |
| `fins_summary` | 2008–2026 monthly-ish | sparse; code-filtered for 30-universe |
| `markets_margin_interest` | 2013–2023 + 2025–2026 | **gap year 2024** |
| `markets_short_ratio` | 2013–2023 + 2026 | **gap 2024–2025 JSONL** |
| `markets_margin_alert` | present including 2024 | not required for S1–S3 primary formulas |

## Per-window bars after 30-code filter

| window | bars n_days | day_span | fins rows (code-filtered) |
|--------|------------:|----------|--------------------------:|
| w2022q4 | 81 | 2022-09-01…2022-12-29 | 50 |
| w2023q4 | 81 | 2023-09-04…2023-12-29 | 52 |
| w2024q4 | 74 (W60 mirror) | 2024-09-02…2024-12-18 | 77 |
| w2025q1 | 61 | 2025-01-06…2025-04-04 | 61 |

Eval max_days may be lower than available days (40/50/25).

## Features empty-by-policy this wave

| feature / dataset | when empty | handling |
|-------------------|------------|----------|
| `markets_margin_interest` | multi-period S1–S3 runs | `allow_empty` — **not invented** |
| S2 volume gate | 2022/2023 long windows | **non_null=0** reported honestly |
| S3 disclosure | sparse fins | non_null rate reported; no densify |

## Forbidden responses to gaps

- densify DEFER / invent COMPLETE 22  
- silent look-ahead fill of `available_at`  
- treat empty feature as zero edge  
- claim readiness because one window looks good  

## Residual pointer

Coverage baseline remains COMPLETE **21** / DEFER **5** / actionable_gap **0**. This inventory is **research evaluation plane**, not coverage densify work.
