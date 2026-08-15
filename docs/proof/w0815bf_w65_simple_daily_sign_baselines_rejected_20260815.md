# W65 / w0815bf — Simple daily sign baselines rejected (不合格ベースライン固定)

**Phase:** 不合格ベースライン固定（READY 未宣言）  
**Wave:** W65 / w0815bf  
**Generated:** 2026-08-15  
**Purpose:** Consolidate S1–S5 simple daily sign hypotheses as **research_baseline_rejected** after short-window → multi-period → multi-year gross → cost-after multi-year evaluation.  
**SoT references:** W61 multi-period · W62 gate+S4/S5 · W63 multi-year gross · W64 cost-aware multi-year  
**Code:** `features.minimal_signal` (S1–S5) · `research.robustness_gate` v2 · `research.baseline_catalog` (research-only)

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** (not declared) |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| edge / significance / operational GO | **none** |
| densify / COMPLETE 22 invent | **none** / COMPLETE remains **21** |
| return_1d_c21 promote | **forbidden** |
| Gate pass ≠ READY / Mass | **held** |

This wave **does not** claim edge. Failure after cost (or never multi-year-passing) is a **valid research outcome**. Catalog status `research_baseline_rejected` is documentation only — it does **not** arm Mass or mint READY.

## Holding-period convention (all S1–S5)

| field | value |
|-------|------:|
| signal clock | day **T** session close (feature as_of) |
| return | `R_{T→T+1} = close(T+1)/close(T) − 1` |
| holding | **1 trading day** (nextday close-to-close) |
| position | discrete **+1 / 0 / −1** daily sign (no multi-day hold logic) |
| research cost | one_way **10bp** · RT **20bp** · 仮定に依存・研究用・運用GOではない |

## Summary table (S1–S5)

| id | signal_id | short-window / multi-period | multi-year gross (W63) | cost-after multi-year (W64) | 結論 |
|----|-----------|----------------------------|------------------------|-----------------------------|------|
| **S1** | `c21_topix_relative_sign` | tip strong +; multi-period unstable (only w2023q4 mild +) | Q4 6y **PASS** soft (4+/2−) | Q4 **FAIL** (+3/−3 net); full~100d **FAIL** | **非候補** |
| **S2** | `c21_volume_change_sign` | tip gross −; fire rate period-dependent (0% in 22/23 Q4) | **not multi-year eval'd** | **not multi-year eval'd** | **非候補** |
| **S3** | `c21_topix_rel_disclosure_filter` | tracks S1 when dense; tip sparse; often fails after 10bp | **not multi-year eval'd** | **not multi-year eval'd** | **非候補** |
| **S4** | `c21_margin_change_sign` | multi-period soft − majority (weak) | Q4 6y **PASS** soft (6/6 −) | Q4 **PASS** net − all; **weak magnitudes** | **非候補** |
| **S5** | `c21_short_ratio_delta_sign` | multi-period **FAIL** (+/− split; coverage gaps) | **not multi-year eval'd** | **not multi-year eval'd** | **非候補** |

---

## S1 — `c21_topix_relative_sign`

| field | value |
|-------|-------|
| **signal_id** | `c21_topix_relative_sign` |
| **definition** | `sign(topix_relative_1d)` if `is_trading_day==1` (volume gate off by default) |
| **role** | primary / baseline daily sign |

### Short-window impression (W57–W61)

- **W58 tip-20d (30 codes):** mean R +1 **+0.00823** / −1 **−0.00202** · gross signed **+0.00528** (tip illusion).  
- **W61 multi-period (R2 · 4 windows):** only **w2023q4** mild same-direction (+0.00188 gross); **w2024q4** ~0; **w2025q1** both signs deeply negative (regime drag).  
- Tip separation **not** stable across long R2 periods.

### Multi-year gross (W63)

Q4 non-contiguous 6 years · 50d · 30 codes · `history_source=r2`:

| period | gross signed mean |
|--------|------------------:|
| y2015_q4 | **+0.002144** |
| y2017_q4 | **−0.000363** |
| y2019_q4 | **+0.001253** |
| y2021_q4 | **+0.000976** |
| y2023_q4 | **+0.001250** |
| y2025_q4 | **−0.000901** |

- Gross-only gate: **PASS** (majority + : 4+/2−) — research checklist only.  
- **Superseded for candidacy by W64 cost FAIL.**

### Cost-after multi-year (W64)

Net = gross − **10bp** one-way:

| period | gross | net_one_way | net_sign |
|--------|------:|------------:|---------:|
| y2015_q4 | +0.002144 | +0.001144 | + |
| y2017_q4 | −0.000363 | −0.001363 | − |
| y2019_q4 | +0.001253 | +0.000253 | + |
| y2021_q4 | +0.000976 | **−0.000024** | **−** |
| y2023_q4 | +0.001250 | +0.000250 | + |
| y2025_q4 | −0.000901 | −0.001901 | − |

| gate view | result |
|-----------|--------|
| gross_only (W63) | PASS (+ maj) |
| **cost-aware v2** | **FAIL** (net +3 / −3 — no strict majority) |

Full bar-span ~100d (2015/19/21/23): gross majority **FAIL** (+2/−2); cost-aware **FAIL**. Longer windows do **not** rescue S1.

### Holding-period note

1-day nextday close-to-close only. Residual after 10bp on “winning” Q4 years is ~0–11bp — not strategy-scale.

### 結論

**非候補 (`research_baseline_rejected`)**  
**Reason:** cost-after multi-year destroys soft gross majority; full-span also fails; tip-window win was overstated.  
**Freeze:** READY未宣言 / Mass NO-GO / Phase7 OFF / no edge.

---

## S2 — `c21_volume_change_sign`

| field | value |
|-------|-------|
| **signal_id** | `c21_volume_change_sign` |
| **definition** | `sign(volume_change_1d)` if trading day and `|volume_change_1d| ≥ 0.10` |
| **role** | volume-sign abs-threshold (not topix rehash of form, but still daily sign) |

### Short-window impression (W57–W61)

- **W58 tip-20d:** non_null ~0.75 · gross signed **−0.00078** (negative on tip).  
- **W61 multi-period:** fire rate **0%** in w2022q4 / w2023q4; sparse (0.047) in w2024q4; higher (0.64) in w2025q1 with deeply negative print.  
- Period-dependent sparsity → tip fire rate must not be generalized.

### Multi-year gross (W63)

**not multi-year eval'd** — W63 focused S1 + S4 only.

### Cost-after multi-year (W64)

**not multi-year eval'd.**  
Where short-window net is available (W61): after 10bp, residual further negative (e.g. w2024q4 net −0.00128).

### Holding-period note

1-day nextday. Abs-threshold gate makes active set highly regime-dependent.

### 結論

**非候補 (`research_baseline_rejected`)**  
**Reason:** tip already gross-negative; multi-period fire rate unstable / often empty; never established multi-year cost-robust majority. Rejected as simple daily sign baseline without promoting to multi-year cost campaign (not worth it on short evidence).  
**Freeze:** READY未宣言 / Mass NO-GO / Phase7 OFF / no edge.

---

## S3 — `c21_topix_rel_disclosure_filter`

| field | value |
|-------|-------|
| **signal_id** | `c21_topix_rel_disclosure_filter` |
| **definition** | `sign(topix_relative_1d)` if trading day and `disclosure_flag_fins==1` |
| **role** | S1 + disclosure binary filter |

### Short-window impression (W57–W61)

- **W58 tip-20d:** non_null **~29.5%** (sparse fins tip) · gross **+0.00345** (below S1, fewer actives).  
- **W61 multi-period:** denser on long history; tracks S1 sign pattern (mild + on w2023q4, ~0/+ small on w2024q4, − on w2025q1).  
- Often fails after 10bp on multi-period nets.

### Multi-year gross (W63)

**not multi-year eval'd** — filter of S1; S1 itself cost-failed multi-year so S3 is not an independent rescue path.

### Cost-after multi-year (W64)

**not multi-year eval'd.**  
Research logic: same primary sign as S1 with a denser/sparser mask — cannot outrun S1 cost collapse without a different return driver.

### Holding-period note

1-day nextday. Disclosure mask changes activity, not holding.

### 結論

**非候補 (`research_baseline_rejected`)**  
**Reason:** S1-dependent sign; multi-period not stable after cost; primary leg S1 already cost-FAIL on multi-year. No independent multi-year campaign justified.  
**Freeze:** READY未宣言 / Mass NO-GO / Phase7 OFF / no edge.

---

## S4 — `c21_margin_change_sign`

| field | value |
|-------|-------|
| **signal_id** | `c21_margin_change_sign` |
| **definition** | `sign(margin_interest_change_1d)` if `is_trading_day==1` |
| **role** | extra hyp (W62) — not S1 rehash |

### Short-window impression (W62 multi-period)

| period | S4 gross |
|--------|---------:|
| w2022q4 | **−0.00014** |
| w2023q4 | **−0.00099** |
| w2024q4 | empty (margin JSONL gap — not invented) |
| w2025q1 | **+0.00145** (regime: both signs deeply negative levels) |

Soft multi-period gate **PASS** (majority −) — weak magnitudes. **Pass ≠ GO.**

### Multi-year gross (W63)

Q4 6y · all **negative** gross:

| period | gross |
|--------|------:|
| y2015_q4 | −0.000697 |
| y2017_q4 | −0.000153 |
| y2019_q4 | −0.000971 |
| y2021_q4 | −0.000514 |
| y2023_q4 | −0.000104 |
| y2025_q4 | −0.000792 |

Gross-only gate **PASS** (6/6 −).

### Cost-after multi-year (W64)

| period | gross | net_one_way |
|--------|------:|------------:|
| y2015_q4 | −0.000697 | −0.001697 |
| y2017_q4 | −0.000153 | −0.001153 |
| y2019_q4 | −0.000971 | −0.001971 |
| y2021_q4 | −0.000514 | −0.001514 |
| y2023_q4 | −0.000104 | −0.001104 |
| y2025_q4 | −0.000792 | −0.001792 |

| gate view | result |
|-----------|--------|
| gross_only | PASS (all −) |
| **cost-aware v2** | **PASS** (all net −) |

**But:** magnitudes tiny (~1–10bp gross; after cost more negative). Consistent **weak negative print**, not an edge and **not** a Mass/READY candidate. Cost-aware pass still ≠ GO.

### Holding-period note

1-day nextday. Margin 2024 empty held as inventory gap.

### 結論

**非候補 (`research_baseline_rejected`)**  
**Reason:** multi-year cost majority holds only as weak all-negative residual; size is not strategy-candidate material; no edge claim. Explicitly rejected as baseline (pass without edge).  
**Freeze:** READY未宣言 / Mass NO-GO / Phase7 OFF / no edge.

---

## S5 — `c21_short_ratio_delta_sign`

| field | value |
|-------|-------|
| **signal_id** | `c21_short_ratio_delta_sign` |
| **definition** | `sign(Δ short_ratio_level[section=0050])` broadcast to codes if trading day |
| **role** | extra hyp (W62) — sector Δ short ratio |

### Short-window impression (W62)

| period | S5 gross | note |
|--------|---------:|------|
| w2022q4 | **−0.00005** | near zero |
| w2023q4 | **+0.00056** | opposite sign |
| w2024q4 | empty | short JSONL gap |
| w2025q1 | empty | short JSONL gap 2024–2025 |

Robustness gate: **FAIL** (2 eligible periods; +/− split — no majority).

### Multi-year gross (W63)

**not multi-year eval'd** (gate already failed on available multi-period; coverage gaps for short ratio).

### Cost-after multi-year (W64)

**not multi-year eval'd.**

### Holding-period note

1-day nextday; sector-level Δ broadcast is research convenience, not stock-level short interest timing.

### 結論

**非候補 (`research_baseline_rejected`)**  
**Reason:** multi-period sign majority FAIL; inventory gaps (2024–25 short); never multi-year / cost-robust.  
**Freeze:** READY未宣言 / Mass NO-GO / Phase7 OFF / no edge.

---

## Cross-cutting research status

| item | value |
|------|-------|
| catalog module | `packages/product/research/baseline_catalog.py` |
| status enum value | `research_baseline_rejected` |
| auto-connect READY | **false** |
| auto-connect Mass | **false** |
| mass-generate signals | **false** |
| proof close stub | [`w0815bf_w65_baseline_close_20260815.md`](w0815bf_w65_baseline_close_20260815.md) |

### Prior proofs (sources of numbers)

| wave | doc |
|------|-----|
| W61 multi-period | [`w0815bb_w61_multi_period_multisignal_20260815.md`](w0815bb_w61_multi_period_multisignal_20260815.md) |
| W62 S4/S5 | [`w0815bc_w62_extra_hyp_s4_s5_20260815.md`](w0815bc_w62_extra_hyp_s4_s5_20260815.md) |
| W63 multi-year gross | [`w0815bd_w63_multi_year_eval_20260815.md`](w0815bd_w63_multi_year_eval_20260815.md) |
| W64 cost multi-year | [`w0815be_w64_cost_multi_year_eval_20260815.md`](w0815be_w64_cost_multi_year_eval_20260815.md) · [`w0815be_w64_cost_multi_year_close_20260815.md`](w0815be_w64_cost_multi_year_close_20260815.md) |

## Gaps held (honest)

| gap | handling |
|-----|----------|
| S2 / S3 / S5 multi-year + cost | **not run** — rejected on short/multi-period + S1 parent cost FAIL (S3) / empty-or-negative evidence (S2/S5) |
| topix JSONL 2024–2025 | archive (W59+) |
| margin 2024 empty | empty_allowed |
| short 2024–2025 gaps | empty_allowed |
| full-year bars sample ends ~Oct | period bound to bar span (W64); no invent Dec |

## Non-goals (held)

- no Mass arm · no Phase7 · no READY · no densify · no COMPLETE 22 invent  
- no promote `return_1d_c21` · no Artifacts mass gen · no orders  
- no invent of multi-year numbers for S2/S3/S5  
- **no edge claim** even where cost gate soft-PASS (S4)

## Wave purpose outcome

「単純日次 sign ベースライン」を **不合格として固定**する。

- S1: cost-after multi-year **FAIL** → soft gross PASS 過大評価を確定  
- S2/S3/S5: multi-year 未実施でも short/multi-period で候補外が十分確定  
- S4: cost majority 残るが **弱すぎて候補にしない**（PASS ≠ GO）  
- **残らなくても成功**（不合格確定）· **Mass / READY に進まない**
