# W63 / w0815bd — Multi-year research evaluation window inventory

**Purpose:** Inventory multi-year R2 structured data availability so research evaluation windows are chosen from **observed coverage**, not tip illusion.  
**Wave:** W63 / w0815bd · inventory only  
**Mass / Phase7 / READY:** **NO-GO / OFF / not declared**  
**Densify:** **none** (this doc does not densify, invent COMPLETE, or claim Mass)

**SoT planes (held):**

| plane | role for multi-year eval |
|-------|--------------------------|
| R2 `quant-structured` JSONL + `archive/jquants_records` | **history SoT** for research windows |
| D1 `jquants_records` | **hot tip only** (`event ≥ 2026-07-01`, ~28 trading days bars/topix) |
| local mirrors under `.glm-logs/` | disposable research extracts · **not** SoT |

**Primary sources (already in-repo):**

| source | path |
|--------|------|
| W61 coverage inventory | [`w0815bb_w61_coverage_inventory_20260815.md`](w0815bb_w61_coverage_inventory_20260815.md) · [`.glm-logs/w0815bb_w61_multiperiod/coverage_inventory.json`](../../.glm-logs/w0815bb_w61_multiperiod/coverage_inventory.json) |
| W61 multi-period specs | [`.glm-logs/w0815bb_w61_multiperiod/period_specs.json`](../../.glm-logs/w0815bb_w61_multiperiod/period_specs.json) |
| W59 R2 bridge + long eval | [`w0815az_w59_r2_feature_context_bridge_20260815.md`](w0815az_w59_r2_feature_context_bridge_20260815.md) · [`w0815az_w59_long_window_signal_eval_20260815.md`](w0815az_w59_long_window_signal_eval_20260815.md) · [`.glm-logs/w0815az_g3b_long/`](../../.glm-logs/w0815az_g3b_long/) |
| W60 long multi-signal | [`w0815ba_w60_long_multisignal_compare_20260815.md`](w0815ba_w60_long_multisignal_compare_20260815.md) · [`.glm-logs/w0815ba_w60_long_multisignal/`](../../.glm-logs/w0815ba_w60_long_multisignal/) |
| W62 gaps (margin/short) | [`w0815bc_w62_extra_hyp_s4_s5_20260815.md`](w0815bc_w62_extra_hyp_s4_s5_20260815.md) · [`.glm-logs/w0815bc_w62_gate_hyp/`](../../.glm-logs/w0815bc_w62_gate_hyp/) |
| W57 code universe | [`w0815ax_w57_universe_expand_eval_20260815.md`](w0815ax_w57_universe_expand_eval_20260815.md) · [`.glm-logs/w0815ax_g1_universe/t1_code_universe.json`](../../.glm-logs/w0815ax_g1_universe/t1_code_universe.json) |
| Observed floors (COMPLETE plane) | [`observed_floor_catalog_20260815.md`](observed_floor_catalog_20260815.md) |

---

## 1. Dataset multi-year availability (research eval plane)

Research eval reads R2 JSONL and/or cold archive via `history_source="r2"` (W59 bridge). COMPLETE receipt status (observed floors) is **orthogonal**: a dataset can be COMPLETE yet have **JSONL year holes** that force archive or `allow_empty`.

| dataset | JSONL years (live inventory) | Archive / alternate | Usable for multi-year eval? | Honest gaps |
|---------|------------------------------|---------------------|-----------------------------|-------------|
| `equities_bars_daily` | **2008–2026 continuous-ish** | cold archive batches (sparse per code/day; ~1100 objects sampled in W59) | **YES** — primary multi-year bars plane | Pre-floor NO_RAW/EMPTY `2004-01…2008-04` (DEFER D7; **do not densify**). Usable research floor **2008-05-01** (observed). D1 tip only `2026-07-01…~2026-08-10` (~28d). |
| `indices_bars_daily_topix` | **2008–2023 + 2026** | **archive full history** **4440 days** · `2008-05-07…2026-06-30` (12 archive objects, W59) | **YES via archive** for all windows through 2026-06-30 | **JSONL gap 2024–2025** — long eval **must use archive** for those years (W61). Tip 2026 on D1 (~28d). |
| `markets_calendar` | **2026 tip shards only** (JSONL sample dt≈2026-08) | **archive** **6756 days** · `2008-01-01…2026-06-30` (17 objects) | **YES via archive + research PIT repair** | JSONL not a multi-year calendar SoT. Archive `available_at` often ≈ ingest wall-clock (~2026) → historical as_of fails unless research repair sets `available_at=event_time` when aa post-dates event (**documented W59/W61/W62**; does **not** rewrite R2 SoT). D1 tip `2026-07-01…2026-08-11`. |
| `markets_margin_interest` | **2013–2023 + 2025–2026** | archive samples exist but **not period-aligned** for 2024 in W61 multi-period runs | **Partial** — usable outside gap; **empty_allowed** when missing | **JSONL gap year 2024** (W61 inventory; W60 selected_keys empty for 2024q4; W62 S4 empty on w2024q4). COMPLETE floor 2013-01-04 (receipt plane). |
| `markets_short_ratio` | **2013–2023 + 2026** | same class as margin (JSONL primary for research mirrors) | **Partial** | **JSONL gap 2024–2025** (W61; W62 S5 empty on w2024q4 + w2025q1). COMPLETE floor 2013-01-04. |
| `markets_margin_alert` | present **including 2024** | — | optional O2 / not required for S1–S3 | not a blocker for primary multi-year S1 |
| `fins_summary` | **2008–2026 monthly-ish** (sparse) | — | sparse OK with code filter | code-filtered row counts small (W61: 50–77 per Q window) |

### 1.1 Proven per-window bars density (W61, 30-code filter)

| window | period | bars n_days (filtered span) | eval max_days used | topix/calendar source | margin |
|--------|--------|----------------------------:|-------------------:|----------------------|--------|
| w2022q4 | 2022-09-01…2022-12-29 | **81** | 40 | archive + PIT repair | empty_allowed |
| w2023q4 | 2023-09-01…2023-12-29 | **81** | 40 | archive + PIT repair | empty_allowed |
| w2024q4 | 2024-09-02…2024-12-18 | **74** (W60 mirror) | 50 | archive + PIT repair | **empty** (2024 gap) |
| w2025q1 | 2025-01-06…2025-04-30 | **61** (span ends ~2025-04-04) | 25 | archive + PIT repair | empty_allowed (short empty 2025) |

Eval `max_days` may be lower than available trading days; inventory span is the upper bound before min_days/max_days clamps.

### 1.2 Plane summary (research)

```
bars      JSONL 2008..2026  ── usable continuous multi-year
topix     JSONL 2008..2023,2026  | ARCHIVE fills 2024-2025 + full 2008-05-07..2026-06-30
calendar  JSONL tip-2026 only    | ARCHIVE 2008-01-01..2026-06-30 + aa research repair
margin    JSONL 2013..2023,2025..2026  | GAP 2024
short     JSONL 2013..2023,2026        | GAP 2024-2025
D1 tip    2026-07-01..~2026-08-14 only (~20–28 as_of days)
```

---

## 2. W57 / W61 code list (n_codes = 30)

Reuse the W57 liquid/diverse tip universe (all 28 tip days present at selection). Prefer **n_codes = 20–30** for W63 multi-year; default **30** to match W59–W62.

```
13010 72030 67580 99840 83060 68610 65010 40630 80350 94320
45020 63670 60980 79740 69810 45680 80010 80020 80580 94330
29140 33820 46610 49010 51080 54010 57130 62730 63010 65030
```

Log: `.glm-logs/w0815ax_g1_universe/t1_code_universe.json`  
Proof: `docs/proof/w0815ax_w57_universe_expand_eval_20260815.md`

**Note:** Codes are tip-selected (2026). Historical windows may have listing/liquidity changes; report non_null honestly; do **not** invent bars.

---

## 3. Recommended multi-year window list (W63 proposal)

Design goals:

* Spread **biennial** anchors **2015 → 2025** (plus optional tip 2026)
* `max_days` in **60–120** where inventory allows; fall back honestly when span is shorter
* `n_codes` **20–30** (default **30**, W57 list)
* Primary signals S1–S3 need **bars + topix + calendar** → all listed years OK **if archive+PIT repair used for topix/calendar**
* S4 margin: mark **gap 2024** (`allow_empty` or skip S4 that year)
* S5 short: mark **gap 2024–2025**
* No densify · no READY · no Mass

### 3.1 Primary recommended set

| period_id | year anchor | period_start | period_end | max_days | min_days | n_codes | expected bars span (≈) | S1–S3 (bars/topix/cal) | S4 margin | S5 short | notes |
|-----------|------------:|-------------:|-----------:|---------:|---------:|--------:|------------------------|------------------------|-----------|----------|-------|
| **w2015q4** | 2015 | **2015-09-01** | **2015-12-30** | **80** | 40 | **30** | ~80–85 trading days | **OK** (archive topix/cal) | OK if JSONL present | OK if JSONL present | first biennial; bars JSONL expected continuous |
| **w2017q4** | 2017 | **2017-09-01** | **2017-12-29** | **80** | 40 | **30** | ~80–85 | **OK** | OK | OK | |
| **w2019q4** | 2019 | **2019-09-02** | **2019-12-30** | **80** | 40 | **30** | ~80–85 | **OK** | OK | OK | |
| **w2021q4** | 2021 | **2021-09-01** | **2021-12-30** | **80** | 40 | **30** | ~80–85 | **OK** | OK | OK | |
| **w2023q4** | 2023 | **2023-09-01** | **2023-12-29** | **80** | 40 | **30** | **81** proven (W61) | **OK** (proven) | OK (W62 S4/S5 yes) | OK (W62 yes) | reuse W61 extract pattern |
| **w2025q1** | 2025 | **2025-01-06** | **2025-04-30** | **60** | 25 | **30** | **61** proven (ends ~04-04) | **OK** (archive topix) | OK (W62 yes) | **empty / gap** | short_ratio JSONL gap; max_days≤60 honest |

### 3.2 Optional extensions

| period_id | period_start | period_end | max_days | n_codes | role |
|-----------|-------------:|-----------:|---------:|--------:|------|
| **w2024q4** | 2024-09-02 | 2024-12-18 | **70** (≤74 inventory) | 30 | Already proven W59–W61; **margin empty · short empty** — use for S1–S3 only |
| **w2022q4** | 2022-09-01 | 2022-12-29 | **80** (≤81) | 30 | Proven W61; optional denser biennial mid-point |
| **w2026tip** | 2026-07-01 | 2026-08-14 | **20–28** | 30 | D1 tip compare only · **not** multi-year R2 history |
| **w2015h1** (alt long) | 2015-01-05 | 2015-06-30 | **100–120** | 20–30 | longer stress if JSONL bars + archive topix/cal load OK |
| **w2019h1** (alt long) | 2019-01-04 | 2019-06-28 | **100–120** | 20–30 | same |

**Longer 100–120d windows:** bars JSONL + topix archive + calendar archive support multi-month spans in principle (topix archive day count 4440). Prefer **single half-year** anchors rather than inventing continuous multi-year single-shot jobs. Cap `n_codes` at **20** if extract size becomes the bottleneck.

### 3.3 Suggested default W63 eval matrix (concrete)

```text
codes   = W57_30 (section 2)
history = r2  (JSONL bars + archive topix + archive calendar PIT-repaired)
windows = w2015q4, w2017q4, w2019q4, w2021q4, w2023q4, w2025q1
max_days = 80, 80, 80, 80, 80, 60
min_days = 40, 40, 40, 40, 40, 25
signals  = S1 (required) · S2/S3 optional · S4 skip/empty on 2024 · S5 skip/empty on 2024–2025
label    = 小サンプル / 研究用・未宣言
```

### 3.4 Loader policy (held from W59–W62)

| rule | action |
|------|--------|
| topix 2024–2025 | load **archive**, not JSONL year shards |
| calendar history | load **archive**; research `available_at=event_time` when envelope aa is ingest-polluted (~2026) |
| margin 2024 | `r2_allow_empty_datasets=["markets_margin_interest"]` or omit S4 |
| short 2024–2025 | same for `markets_short_ratio` / omit S5 |
| DEFER permanent | hard reject as history (master, earn_cal, bars_am, fins_earn tip, jsda otc) |
| densify | **forbidden** response to gaps |
| READY / Mass / edge | **not declared** |

---

## 4. Inventory table (copy-ready)

### 4.1 Dataset years usable

| dataset | years usable (research) | primary plane | blocker for multi-year |
|---------|-------------------------|---------------|------------------------|
| `equities_bars_daily` | **2008-05 … 2026** | JSONL (+ archive supplement) | none post-2008-05 for biennial Q4 windows |
| `indices_bars_daily_topix` | **2008-05-07 … 2026-06-30** | **archive** (JSONL missing 2024–2025) | use archive always for long eval |
| `markets_calendar` | **2008-01-01 … 2026-06-30** (+ tip 2026-07+) | **archive** + PIT repair | JSONL tip-only |
| `markets_margin_interest` | **2013–2023, 2025–2026** | JSONL | **2024 gap** |
| `markets_short_ratio` | **2013–2023, 2026** | JSONL | **2024–2025 gap** |

### 4.2 Recommended windows (summary)

| period_id | period_start | period_end | max_days | n_codes |
|-----------|--------------|------------|----------|---------|
| w2015q4 | 2015-09-01 | 2015-12-30 | 80 | 30 |
| w2017q4 | 2017-09-01 | 2017-12-29 | 80 | 30 |
| w2019q4 | 2019-09-02 | 2019-12-30 | 80 | 30 |
| w2021q4 | 2021-09-01 | 2021-12-30 | 80 | 30 |
| w2023q4 | 2023-09-01 | 2023-12-29 | 80 | 30 |
| w2025q1 | 2025-01-06 | 2025-04-30 | 60 | 30 |

Optional proven / tip: `w2024q4` (50–70d, S1–S3 only) · `w2022q4` · `w2026tip` (D1, ≤28d).

---

## 5. Explicit non-declarations

| claim | status |
|-------|--------|
| READY publication | **not declared** |
| Mass Autonomous Research | **NO-GO** |
| Phase7 | **OFF** |
| Densify / invent COMPLETE 22 | **forbidden** |
| Statistical significance / edge / operational GO | **refused** |
| 2015–2021 windows live-executed this wave | **proposal only** (2022–2025 proven W59–W62; earlier years inventory-supported, not re-run here) |

---

## 6. Residual pointer

Coverage baseline remains COMPLETE **21** / permanent DEFER **5** / actionable densify gap **0**.  
This inventory is the **research evaluation plane** (multi-year window design).  
JSONL year holes (topix 2024–2025, calendar tip-only JSONL, margin 2024, short 2024–2025) are **loader/routing facts**, not densify tickets.

**Next (out of scope for this inventory doc):** execute proposed 2015/2017/2019/2021 windows with the same R2 mirror + gate pattern as W61/W62; report skips/empty honestly.

---

*End of W63 / w0815bd multi-year window inventory. No densify · no Mass · no READY.*
