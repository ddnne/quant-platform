# W86 / w0816u — Task A: sign flip + non-zero testing (default / main explore)

**Wave status:** **Task A COMPLETE** (helper · class_hyp wire · default reps · tests · selection table) — closed with residual W86  
**Wave:** W86 / `w0816u` · 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Logs:** [`.glm-logs/w0816u_w86_go_pre/`](../../.glm-logs/w0816u_w86_go_pre/)  
**Prior:** W85 multi-window paper · 3 default candidates (xs mom5 KEEP · xs mom3 PROMOTE · fund mom10 KEEP) · paper xs **−0.49%** · fund **−1.77%** · mom3 **+0.66%**

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| operational GO | **closed** |
| continuous / unlimited paper arm | **OFF / UNARMED** |
| live orders | **OFF** |
| simple_daily_sign | **not used** |
| S1–S5 un-reject | **forbidden** |
| look-ahead / event revival | **forbidden** |
| mean-bp-only promotion | **forbidden** |
| Mass/READY/ops GO from sign selection | **forbidden** |
| commit / push | residual W86 |

---

## Policy (W86 Task A) — held

| rule | held |
|------|------|
| Evaluate **both** original (+1) and inverted (−1) **after costs** | **yes** |
| Prefer side with **positive mean net** supported by **non-zero evidence** | **yes** |
| `t` is a **guideline**, not a hard one-strike reject | **yes** |
| Both fail non-zero / near-zero after cost → reject / explore demote | **yes** |
| Record **`chosen_sign`** for reproducibility | **yes** |
| Do not over-invest mom3 vs mom5 — compress to representative few after selection | **yes** · both survive → keep both |
| Fund with multi-window paper mean negative **must evaluate flip first** | **yes** |
| No simple_daily_sign / look-ahead / S1–S5 un-reject | **yes** |
| Mass/READY/ops GO/live OFF | **yes** |

### Cost model (disclosed)

| side | formula |
|------|---------|
| original | `net = gross − amortized_one_way_cost` |
| inverted | `net = −gross − amortized_one_way_cost` |

Symmetric one-way cost assumption. Short-borrow remeasure (W85 mid) remains an upstream research residual; sign-selection uses amortized one-way from period rows (or gross−net).

### Non-zero evidence (soft)

| check | default |
|-------|--------:|
| near-zero \|mean\| floor | **5bp** (research) / **0.1%** (paper windows) |
| t guideline | **\|t\| ≥ 1.0** (not hard fail if mean clear) |
| economic floor (soft on selection) | **20bp** research mean |

---

## Implementation landings

| item | path / note |
|------|-------------|
| Shared helper | [`packages/product/research/sign_selection.py`](../../packages/product/research/sign_selection.py) · `evaluate_sign_both_sides` · `choose_sign` · `sign_selection_from_period_rows` |
| class_hyp_eval | [`packages/product/research/class_hyp_eval.py`](../../packages/product/research/class_hyp_eval.py) · **v7** / W86 · emits `sign_selection` · `chosen_sign` · `default_path_representatives` |
| StrategySpec `signal_sign` | [`packages/research_runtime/strategies/spec/schema.py`](../../packages/research_runtime/strategies/spec/schema.py) · optional +1/−1 on CS rank + value×mom · omitted from `to_dict` when +1 |
| Interpreter | [`packages/research_runtime/strategies/spec/interpreter.py`](../../packages/research_runtime/strategies/spec/interpreter.py) · multiplies signed positions by `signal_sign` |
| Paper adapter | [`packages/product/research/paper_candidate_adapter.py`](../../packages/product/research/paper_candidate_adapter.py) · builders accept `signal_sign` · adapt reads `chosen_sign` |
| Tests | [`tests/test_sign_selection.py`](../../tests/test_sign_selection.py) · flip / near-zero reject / t guideline / StrategySpec round-trip |
| Runner + table | [`.glm-logs/w0816u_w86_go_pre/run_w86_sign_flip.py`](../../.glm-logs/w0816u_w86_go_pre/run_w86_sign_flip.py) · `selection_table.md` |

**Targets applied:**

1. `cross_section_hold_10` (xs hold10 **mom5**) — paper-neg flag → flip-first eval  
2. `cross_section_hold_10_mom3` (xs hold10 **mom3**)  
3. `fundamentals_hold_10` (fund hold10 **mom10**) — paper-neg flag → flip-first eval  
4. stay_explore (cheap): xs frac0.4 · fund hold15 · fund hold5  

---

## Selection table (research multi-year — primary)

Sources: W84 `class_hyp_multi_year_bundle` (xs mom5 · fund mom10) + W84 explore period rows (mom3 · stay_explore).  
Full machine log: [`.glm-logs/w0816u_w86_go_pre/sign_flip_selection.json`](../../.glm-logs/w0816u_w86_go_pre/sign_flip_selection.json)

| strategy | orig mean bp | orig t | orig Sh | inv mean bp | inv t | inv Sh | **chosen_sign** | decision | default-wire |
|----------|-------------:|-------:|--------:|------------:|------:|-------:|:---------------:|----------|:------------:|
| **xs_hold10_mom5** | **+84.6** | **1.60** | **0.65** | −86.6 | −1.64 | −0.67 | **+1** | keep_original | **yes** |
| **xs_hold10_mom3** | **+120.0** | **3.04** | **1.24** | −122.0 | −3.10 | −1.26 | **+1** | keep_original | **yes** |
| **fund_hold10_mom10** | **+45.9** | **1.82** | **0.74** | −47.9 | −1.90 | −0.77 | **+1** | keep_original | **yes** |
| xs_hold10_mom5_frac40 | +62.9 | 1.69 | 0.69 | −64.9 | −1.74 | −0.71 | **+1** | keep_original | **no** (stay_explore) |
| fund_hold15_mom10 | +91.5 | 1.80 | 0.73 | −92.9 | −1.83 | −0.75 | **+1** | keep_original | **no** (stay_explore) |
| fund_hold5_mom10 | +24.4 | 1.92 | 0.78 | −28.4 | −2.23 | −0.91 | **+1** | keep_original | **no** (stay_explore) |

**Reading:** After cost, inverted sides are the near-mirror negative of originals (symmetric cost). Research original remains the only side with positive mean + non-zero evidence for all six. Flip was **evaluated** (required for paper-negative fund/xs) but **not selected** on the multi-year research residual.

---

## Paper multi-window (W85 honesty — secondary)

| strategy | W85 paper mean % | paper orig t | paper inv mean % | paper inv t | paper **chosen_sign** | paper decision |
|----------|-----------------:|-------------:|-----------------:|------------:|:---------------------:|----------------|
| xs_hold10_mom5 | **−0.49** | −0.26 | −1.23 | −0.67 | **none** | reject_both_non_positive |
| xs_hold10_mom3 | **+0.66** | 0.39 | −2.40 | −1.43 | **+1** | keep_original |
| fund_hold10_mom10 | **−1.77** | −1.22 | **+0.19** | 0.13 | **−1** | flip_to_inverted (weak) |
| xs_hold10_mom5_frac40 | −1.56 | — | — | — | none | reject / incomplete pre_cost |
| fund_hold15_mom10 | −1.13 | — | — | — | none | reject / incomplete pre_cost |
| fund_hold5_mom10 | −1.40 | — | — | — | none | reject_both_non_positive |

### Paper vs research tension (disclosed, not hidden)

| candidate | research chosen | paper chosen | resolution (W86) |
|-----------|:---------------:|:------------:|------------------|
| xs mom5 | **+1** | both fail | **keep research +1** · paper residual weak both sides · continuous **UNARMED** · not auto-reject KEEP solely on paper (W85 policy held) · flip eval recorded |
| xs mom3 | **+1** | **+1** | **aligned** · both keep original |
| fund mom10 | **+1** | **−1** (weak +0.19% · t=0.13) | **research +1 remains default** · paper invert is **weak** (near floor, t≪1) → **not** enough non-zero evidence to rewire research default · logged as paper_flip_weak residual · continuous **UNARMED** |

**Flip-first for paper-negative fund:** evaluated. Inverted paper mean only +0.19% with t=0.13 — policy allows selection on positive mean + soft evidence, but this is **not** strategy-scale and does **not** override the research multi-year original (+45.9bp · t=1.82). No Mass/READY/ops GO.

---

## Default representatives after sign selection

| # | representative | params | chosen_sign | research mean bp / t / Sh | default-wired |
|---|----------------|--------|:-----------:|--------------------------:|:-------------:|
| 1 | **cross_section_hold_10** | hold=10 · **mom=5** · frac=0.3 | **+1** | +84.6 / 1.60 / 0.65 | **yes** |
| 2 | **cross_section_hold_10_mom3** | hold=10 · **mom=3** | **+1** | +120.0 / 3.04 / 1.24 | **yes** |
| 3 | **fundamentals_hold_10** | hold=10 · **mom=10** | **+1** | +45.9 / 1.82 / 0.74 | **yes** |

### mom3 vs mom5 compression

Both survive sign selection with original side → **keep both** as parallel default representatives (W85 already promoted mom3). No merge / no over-invest in extra mom lookbacks. Primary pin remains mom=5 (W82); mom=3 is parallel.

### stay_explore (not default-wired)

| variant | research chosen_sign | paper | default-wire |
|---------|:--------------------:|-------|:------------:|
| xs frac0.4 | +1 | weak / reject | **no** |
| fund hold15 | +1 | weak / reject | **no** |
| fund hold5 | +1 | reject both | **no** |

---

## StrategySpec wiring (reproducibility)

Emitted unarmed specs with `signal_sign` (= `chosen_sign`) in  
[`.glm-logs/w0816u_w86_go_pre/emitted_specs.json`](../../.glm-logs/w0816u_w86_go_pre/emitted_specs.json):

| strategy_id | signal_sign |
|-------------|:-----------:|
| `w86_xs_hold10_mom5_sign1` | **+1** |
| `w86_xs_hold10_mom3_sign1` | **+1** |
| `w86_fund_hold10_mom10_sign1` | **+1** |

`signal_sign=-1` path is schema-valid and interpreter-applied for future flips; not selected on research primary for these three.

---

## Tests

```text
tests/test_sign_selection.py + related schema/version tests
...........................  (27 passed)
```

Log: [`.glm-logs/w0816u_w86_go_pre/pytest_sign_flip.log`](../../.glm-logs/w0816u_w86_go_pre/pytest_sign_flip.log)

Coverage:

* invert net math (gross − cost)  
* original preferred when positive  
* flip when original negative / inverted positive  
* both near-zero → reject  
* t is guideline (not hard one-strike)  
* paper_mean_negative flip-first path  
* period-row helper  
* StrategySpec `signal_sign=-1` round-trip  
* paper adapter builders  
* class_hyp_eval v7 / W86 tag  

---

## What was **not** done

| item | status |
|------|--------|
| commit / push | **not done** |
| Mass / READY / ops GO / live | **still closed** |
| continuous paper arm | **UNARMED** |
| re-run full multi-year bar mirrors (optional reconfirm) | **not required** — used prior W84 period nets |
| re-run multi-window paper with inverted StrategySpec | **not run** (paper flip estimated from pre/post cost; fund paper invert weak) |
| simple_daily_sign / S1–S5 un-reject | **not done** |
| demote research defaults solely on paper negatives | **not done** (W85 honesty policy held) |

---

## Bottom line

1. **Shared helper landed** — `evaluate_sign_both_sides` / `choose_sign` with period nets, mean, t, Sharpe.  
2. **Applied** to xs mom5 / mom3 / fund mom10 + stay_explore (cheap).  
3. **class_hyp_eval v7** emits `chosen_sign` + both-side metrics + `default_path_representatives`.  
4. **Default reps after selection: still 3** — all `chosen_sign=+1` (original). mom3+mom5 both kept.  
5. **Fund paper-negative flip evaluated first** — paper invert only weakly positive; research original retained.  
6. **Tests green · proof + logs written · no commit/push.**

**Mass / READY / operational GO / live: still OFF.**
