# W100 / w0819c — daily_path_DD mandatory on the standard eval path

**Phase:** 標準研究評価チェックリストに daily_path_DD を必須化（READY 未宣言）  
**Wave:** W100 / w0819c · 2026-08-19  
**Implementer:** GLM5.3（Grok は統括のみ・未実装）  
**Harness entry:** `research.eval_harness.run_standard_research_eval`  
**Checklist:** `standard-research-eval-checklist/v2`（新フレームワークなし。既存 v2 経路に必須項目を追加）  
**Gate module:** `research.stats_metrics.evaluate_daily_path_dd_gate`  
**Reference example:** [`w0819b_w99_sticky_daily_dd_20260819.md`](w0819b_w99_sticky_daily_dd_20260819.md) · `xs_rank_ls_sticky` daily MTM

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** (`ready_declared=False`) |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| edge / significance / operational GO | **none** |
| `xs_rank_ls_sticky` | **STABLE_RESEARCH_ONLY** · `promote_as_main=false` · `go=false` |
| hold/mom micro-grid | **not run** |
| 3 default pins | **untouched** (not retuned) |
| Gate / checklist pass → READY/Mass/GO | **never auto-connects** |

## Why

W98 reported `max_dd_proxy=0` from **period-net cumsum** while every CF period
net was positive. That is an **aggregation artifact**, not “no risk”. W99 built
the true daily mark-to-market path for `xs_rank_ls_sticky` and showed:

| window | period_net_DD (W98 CF artifact) | daily_path_DD | dd_dur | recovery | total_ret_net |
|--------|--------------------------------:|--------------:|-------:|---------:|--------------:|
| w2017_2019 | 0.0000 | −0.143741 | 85 | — (not recovered) | 0.034975 |
| w2020_2022 | 0.0000 | −0.037971 | 14 | 1 (recovered) | 0.201923 |
| w2023_2025 | 0.0000 | −0.108415 | 17 | 52 (recovered) | 0.081073 |

Passing on `period_net_DD` alone is therefore **forbidden**. This wave wires
that rule into the **existing** standard eval checklist / scorecard.

## What changed (live code, not docs-only)

| surface | change |
|---------|--------|
| `CHECKLIST_V2_REQUIRED` | added **`daily_path_dd`** |
| `CHECKLIST_V2_INSUFFICIENT` | added `period_net_dd_only_pass`, `period_net_dd_zero_daily_unmeasured` |
| `evaluate_checklist_v2_completeness` | required item `daily_path_dd`; `period_net_dd_only=True` cannot pass the item |
| `run_standard_research_eval` | always runs `evaluate_daily_path_dd_gate`; return key `daily_path_dd`; step `daily_path_dd` |
| `research.stats_metrics` | `equity_path_drawdown` · `evaluate_daily_path_dd_gate` · W99 sticky reference table |

No new eval framework. No Mass/READY/GO wiring. No 3-default pin retune.
No hold/mom grid. Sticky stays research-only.

### Required scorecard fields

Every standard eval report must include:

| field | meaning |
|-------|---------|
| `daily_path_DD` | max peak-to-trough on the **daily after-cost equity level** |
| `dd_duration` | days from peak to trough |
| `recovery` | `recovered` (bool) + `recovery_days` (from trough; N/A if not recovered or no DD) |
| `total_ret_net` | after-cost total return on the same path |

`period_net_DD` may appear as **contrast only** (W99 style). It is not a
substitute for the four fields above.

### Fail / warn

| condition | verdict |
|-----------|---------|
| daily unmeasured (any required field missing) | **fail** → checklist item incomplete → `research_candidate_allowed=False` |
| `period_net_DD=0` **AND** daily unmeasured | **fail** → incomplete evaluation (`period_net_DD_zero_daily_unmeasured`) |
| period-net DD offered as the pass number (incl. `method=period_net_cumsum_proxy`) | **fail** → `period_net_DD_only_pass_forbidden` |
| `period_net_DD=0` but daily **is** measured | **warn** only (aggregation artifact; daily_path_DD is the risk number) |
| daily measured + all four fields present | item **complete** (measurement gate, **not** a DD-size floor) |

This is a **measurement gate**, not a “DD must be smaller than X” bar.
`passed` / `complete` on the daily-path item means the path was measured.
It still does **not** mint `research_candidate`, READY, Mass, or GO.

Default `run_standard_research_eval(dry_run=True)` leaves daily unmeasured
→ incomplete (same as pending risk scenarios).

### New kwargs on `run_standard_research_eval`

| kwarg | meaning |
|-------|---------|
| `daily_path_dd` | scalar max DD **or** a pack |
| `dd_duration` / `recovered` / `recovery_days` / `total_ret_net` | scorecard fields |
| `period_net_dd` | contrast only; cannot pass alone |
| `daily_path_pack` | W99-style mapping (`daily_path_DD`, `dd_duration`, …) |
| `daily_equities` / `daily_dates` | compute the path via `equity_path_drawdown` |
| `daily_path_method` | `period_net_cumsum_proxy` is rejected as not daily |

## Reference example (kept)

`w99_sticky_daily_path_dd_reference()` and
`W99_STICKY_DAILY_PATH_DD_REFERENCE` freeze the W99 sticky window table as
the documented example. Stance remains:

* `STABLE_RESEARCH_ONLY`
* `promote_as_main=false`
* `go=false`
* no hold/mom grid
* 3 default pins untouched

## Tests

`tests/test_standard_research_eval.py`

| test | assert |
|------|--------|
| wiring_only | `daily_path_dd` unmeasured → incomplete; step present |
| scenarios without daily path | still incomplete (`daily_path_dd` missing) |
| `period_net_DD=0` + daily unmeasured | fail + incomplete reason |
| period-net only (nonzero) | `period_net_DD_only_pass_forbidden` |
| period-net method relabeled as daily | fail |
| W99 sticky pack | item complete + artifact **warn**; still not auto-candidate |
| equity-curve helper | duration / recovery / `total_ret_net` from level path |
| complete scenarios **+** daily pack | checklist complete allowed, still `research_candidate=False` |

## Usage

```python
from research.eval_harness import run_standard_research_eval
from research.stats_metrics import W99_STICKY_DAILY_PATH_DD_REFERENCE

# Unmeasured daily path → incomplete (cannot pass on period_net_DD=0)
out = run_standard_research_eval(dry_run=True, period_net_dd=0.0)
assert out["daily_path_dd"]["period_net_dd_zero_daily_unmeasured"] is True
assert out["checklist_complete"] is False
assert out["research_candidate"] is False

# Measured daily path (W99 sticky reference; still not auto-candidate / not GO)
pack = {
    "daily_path_DD": W99_STICKY_DAILY_PATH_DD_REFERENCE[0]["daily_path_DD"],
    "dd_duration": 85,
    "recovered": False,
    "recovery_days": None,
    "total_ret_net": 0.034975,
    "period_net_DD": 0.0,  # contrast only
    "method": "daily_equity_level_peak_to_trough",
}
out2 = run_standard_research_eval(dry_run=True, daily_path_pack=pack, scenario_rows=...)
assert out2["daily_path_dd"]["complete"] is True
assert out2["research_candidate"] is False
assert out2["ready_declared"] is False
```

## Non-goals (held)

- no Mass / READY / Phase7 / operational GO / live
- no `xs_rank_ls_sticky` promote_as_main / GO
- no hold/mom micro-grid
- no 3-default pin retune
- no new eval framework
- no claim that period_net_DD=0 is riskless
- no S1–S5 un-reject

## Related

| artifact | path |
|----------|------|
| This gate | `packages/product/research/stats_metrics.py` · `evaluate_daily_path_dd_gate` |
| Checklist wiring | `packages/product/research/eval_harness.py` |
| Checklist v2 (prior) | [`w0816k_w77_eval_checklist_v2_20260816.md`](w0816k_w77_eval_checklist_v2_20260816.md) |
| Checklist v1 | [`w0815bg_w66_standard_research_eval_checklist_20260815.md`](w0815bg_w66_standard_research_eval_checklist_20260815.md) |
| W99 sticky daily DD (reference) | [`w0819b_w99_sticky_daily_dd_20260819.md`](w0819b_w99_sticky_daily_dd_20260819.md) |
| W99 recipe | `scripts/run_w99_sticky_daily_dd.py` |
