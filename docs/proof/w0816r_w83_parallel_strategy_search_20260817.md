# W83 / w0816r — parallel multi-strategy research candidate search

**Wave status:** **COMPLETE** — residual FRESH close + commit/push (see close proof)  
**Wave:** W83 / `w0816r` · 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Logs:** [`.glm-logs/w0816r_w83_parallel/`](../../.glm-logs/w0816r_w83_parallel/)  
**Close:** [`w0816r_w83_parallel_close_20260817.md`](w0816r_w83_parallel_close_20260817.md)  
**Prior:** W82 event_post PIT demote · optional xs hold=10 KEEP (not default-wired) · multi_day 10d demoted · 0 production default candidates

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| operational GO | **未宣言** |
| continuous paper | **UNARMED** |
| live orders | **OFF** |
| simple_daily_sign | **not used** |
| S1–S5 un-reject | **forbidden** |
| mean-bp-only promotion | **forbidden** |
| event_post look-ahead revival | **forbidden** (W82 PIT only) |
| multi_day 10d force-revive | **forbidden** (no real content improve) |
| OTC bulk archive re-scan | **not run** (light tip only) |
| commit / push | **done** (residual close) |

---

## Policy (W83)

| rule | held |
|------|------|
| PIT-safe only | **yes** |
| Always compute t / Sharpe / win-rate / yearly stability / activation | **yes** |
| Flexible holistic judgment with written reasons (not one-strike auto-fail) | **yes** |
| Hard production bar still reported; holistic may KEEP/CONDITIONAL/REJECT with reasons | **yes** |
| Explore **all** families in parallel (not xs alone) | **yes** |
| Wire true default candidates into default eval path if justified | **yes** (2 wired) |
| candidate 0 is OK but keep exploring | N/A — found 2 |

### Statistical / production floors (reported; holistic can soften only with written reasons)

| metric | floor |
|--------|------:|
| mean net (economic) | ≥ 20bp |
| \|t\| (period nets) | ≥ 1.5 |
| Sharpe (period) | ≥ 0.50 |
| period win-rate | ≥ 0.60 |
| positive periods | ≥ 4 |
| multi-year | ≥ 4 ok periods |
| activation / occurrence | rate-based (W80) |

Costs: **10bp one-way base** · **liquidity-linked** tx_mult · repo series disclosed for L/S context (no invent fill).

---

## Delivered code

| artifact | path | role |
|----------|------|------|
| Class signals **v6** | `packages/research_runtime/features/class_signals.py` | wave **W83 / w0816r** |
| Offline multi-year eval **v6** | `packages/product/research/class_hyp_eval.py` | default-path **xs hold=10** + **fund hold=10** blocks · explore params |
| Tests | `tests/test_class_signals.py` | +W83 wave/default params · xs sticky · **17 passed** |
| Explore runner | `.glm-logs/w0816r_w83_parallel/run_w83_parallel_search.py` | parallel multi-family matrix |

### Default-path wiring (justified)

| block | params | why |
|-------|--------|-----|
| `cross_section_hold_10` | hold=**10** · momentum_n=**5** (W82 pin) | Hard bar pass · **research_candidate=True** · mom=10 content-match **fails** |
| `fundamentals_hold_10` | hold=**10** · momentum_n=**10** · value×mom agree | Hard bar pass · content improve vs hold=20/mom=20 (occ+stats fail) |

Primary defaults unchanged: xs hold=5 · fund hold=20/mom=20 · multi_day 5 + 10 reported · event PIT · flow hold=5.

---

## Parallel explore matrix (all families)

Windows: W80/W81 style **full+Q4** (`y2015_full` · `y2017_q4` · `y2019_full` · `y2021_full` · `y2023_full` · `y2025_q4`) · 30 large-cap codes · liquidity one-way.

### A. Default multi-year path (rewired)

| class / block | mean net | t | Sharpe | win-rate | maxDD | gate | econ | occ | stats | hard RC | **holistic** |
|---------------|---------:|--:|-------:|---------:|------:|:----:|:----:|:---:|:-----:|:------:|--------------|
| multi_day_hold 5d | +0.4bp | 0.03 | 0.01 | 0.50 | −59bp | ✗ | ✗ | ✓ | ✗ | False | **reject** |
| multi_day_hold **10d** | +21.1bp | 0.62 | 0.25 | 0.67 | −132bp | ✓ | ✓ | ✓ | ✗ | False | **reject** (noisy; no force-revive) |
| **event_post PIT** | +5.9bp | 0.25 | 0.10 | 0.67 | −91bp | ✓ | ✗ | ✓ | ✗ | False | **reject** (no look-ahead revival) |
| macro_conditioned | −24.1bp | −3.16 | −1.29 | 0.00 | −145bp | ✓ | ✗ | ✓ | ✗ | False | **reject** (weak −) |
| cross_section hold=5 | −10.9bp | −0.44 | −0.18 | 0.50 | −144bp | ✗ | ✗ | ✓ | ✗ | False | **reject** |
| **cross_section hold=10 mom=5** | **+84.6bp** | **1.60** | **0.65** | **0.67** | **−47bp** | ✓ | ✓ | ✓ | ✓ | **True** | **default_candidate** |
| flow_demand hold=5 | +117.9bp* | 0.76 | 0.31 | 0.33 | −225bp | ✗ | ✗ | ✓ | ✗ | False | **reject** (*mean high, majority neg) |
| fundamentals hold=20 mom=20 | +70.9bp | 1.04 | 0.42 | 0.67 | −109bp | ✓ | ✓ | ✗ | ✗ | False | **conditional** (discussion_only; see hold=10) |
| **fundamentals hold=10 mom=10** | **+45.9bp** | **1.82** | **0.74** | **0.67** | **−10bp** | ✓ | ✓ | ✓ | ✓ | **True** | **default_candidate** |

### B. Cross-section variants (explore)

| variant | mean net | t | Sharpe | win-rate | hard RC | holistic |
|---------|---------:|--:|-------:|---------:|:------:|----------|
| hold=10 mom=**5** (W82 pin) | **+84.6bp** | **1.60** | **0.65** | 0.67 | **True** | **default_candidate** |
| hold=10 mom=**10** (content-matched) | +6.6bp | 0.24 | 0.10 | 0.50 | False | **reject** (edge collapses) |
| hold=20 mom=20 | −29.5bp | −0.22 | −0.09 | 0.83 | False | **reject** |
| hold=10 frac=0.2 | +19.8bp | 0.51 | 0.21 | 0.83 | False | **reject** (econ/occ) |
| hold=5 mom=5 | −10.9bp | −0.44 | −0.18 | 0.50 | False | **reject** |

**Look-ahead check (xs):** same-day close momentum ranks → sticky fixed-horizon hold → multi-day forward return from rebalance bar. No future disc times. Rank construction uses only bars ≤ t.

### C. flow_demand (improved attempts)

| variant | mean net | t | Sharpe | win-rate | hard RC | holistic |
|---------|---------:|--:|-------:|---------:|:------:|----------|
| hold=5 | +117.9bp | 0.76 | 0.31 | 0.33 | False | **reject** |
| hold=10 | −322bp | −0.99 | −0.40 | 0.50 | False | **reject** |
| hold=10 + short_confirm | −47.6bp | −1.19 | −0.48 | 0.33 | False | **reject** |
| hold=20 | −618bp | −1.13 | −0.46 | 0.33 | False | **reject** |

Not S4 rehash. Short-confirm does not salvage. **No default wire.**

### D. fundamentals_price

| variant | mean net | t | Sharpe | win-rate | occ | hard RC | holistic |
|---------|---------:|--:|-------:|---------:|:---:|:------:|----------|
| hold=20 mom=20 agree | +70.9bp | 1.04 | 0.42 | 0.67 | ✗ | False | conditional / discussion |
| **hold=10 mom=10 agree** | **+45.9bp** | **1.82** | **0.74** | **0.67** | ✓ | **True** | **default_candidate** |
| hold=20 value_only | −16.7bp | −0.22 | −0.09 | 0.33 | ✗ | False | **reject** |
| hold=40 mom=20 | −157bp | −2.24 | −1.12 | 0.00 | ✗ | False | **reject** |

**Look-ahead check (fund):** PIT `fins_asof` on disc calendar; value score vs global median; sticky hold. No invent EPS/FEPS.

### E. macro_conditioned

| variant | mean net | t | Sharpe | win-rate | hard RC | holistic |
|---------|---------:|--:|-------:|---------:|:------:|----------|
| rate_change (default) | −24.1bp | −3.16 | −1.29 | 0.00 | False | **reject** |
| rate_level | −6.2bp | −1.43 | −0.58 | 0.17 | False | **reject** |

### F. multi_day (no force-revive)

| variant | mean net | t | Sharpe | win-rate | hard RC | holistic |
|---------|---------:|--:|-------:|---------:|:------:|----------|
| hold=5 | +0.4bp | 0.03 | 0.01 | 0.50 | False | **reject** |
| hold=10 | +21.1bp | 0.62 | 0.25 | 0.67 | False | **reject** (noisy stats demote held) |
| hold=20 | +18.5bp | 0.20 | 0.08 | 0.83 | False | **reject** (no real content improve) |

### G. event-family (W82 PIT only)

| variant | mean net | t | Sharpe | win-rate | hard RC | holistic |
|---------|---------:|--:|-------:|---------:|:------:|----------|
| PIT hold=5 | +5.9bp | 0.25 | 0.10 | 0.67 | False | **reject** |
| PIT hold=10 | +0.9bp | 0.02 | 0.01 | 0.67 | False | **reject** |

W81 pre-PIT KEEP (+53bp · t=2.83) remains **look-ahead contaminated** — not revived.

---

## Candidate list (W83)

| # | class | variant | mean | t | Sharpe | win | hard RC | holistic | default-wired |
|---|-------|---------|-----:|--:|-------:|----:|:------:|----------|:-------------:|
| 1 | **cross_section_relative** | sticky hold=10 · **mom=5** | +84.6bp | 1.60 | 0.65 | 0.67 | **True** | **default_candidate** | **yes** (`cross_section_hold_10`) |
| 2 | **fundamentals_price** | hold=10 · **mom=10** agree | +45.9bp | 1.82 | 0.74 | 0.67 | **True** | **default_candidate** | **yes** (`fundamentals_hold_10`) |

**Production research candidates on default path after W83: 2.**  
**Mass / READY / operational GO / live: still closed.**

### Holistic reasons (written)

**cross_section_hold_10**

* Hard bar fully met (not mean-bp-only).  
* t=1.60 is **barely** above 1.5 and win-rate is 4/6 — borderline, but gate + risk + occ + skew + multi-year all clear; payoff 3.6 and maxDD small support KEEP.  
* Critical content detail: **momentum_n must stay 5** (W82 pin). Aligning mom to hold=10 **destroys** residual → do not “content-match” blindly.  
* Research-only; StrategySpec v2 cannot express sticky L-S ranks (paper is proxy).

**fundamentals_hold_10**

* Stronger stats than xs (t=1.82 · Sharpe=0.74) with tiny period maxDD.  
* Real content improve vs default hold=20/mom=20 (which fails occ rate + stats).  
* PIT fins path held; value×mom agree (not value_only — that fails).  
* Research-only; paper proxy uses momentum_n top_k (value leg not in StrategySpec v2).

---

## Paper (passers only)

Continuous scheduler **UNARMED**. Live **OFF**. Fidelity = **StrategySpec v2 proxy** (momentum_n top_k).

| trial | class | window | post-cost | maxDD | trades | note |
|-------|-------|--------|----------:|------:|-------:|------|
| single-shot | xs hold10 proxy | 5d Draft | **+1.16%** | −0.13% | 27 | dry healthy |
| **limited** | xs hold10 proxy | 30d Paper | **−1.96%** | −5.14% | 175 | **honest negative** |
| single-shot | fund hold10 proxy | 5d Draft | **+2.17%** | −0.27% | 23 | dry healthy |
| **limited** | fund hold10 proxy | 30d Paper | **−4.06%** | −10.35% | 152 | **honest negative** |

Limited-window proxy PnL is **not** alpha / significance. Logs: `.glm-logs/w0816r_w83_parallel/paper_*` · `paper_trial_card.json` · `paper_results.json`.

---

## OTC light tip FULL_OK

| metric | value |
|--------|------:|
| dataset | `jsda_otc_bond_reference_prices` |
| dataset status | **PARTIAL** (held) |
| COMPLETE segments | **4499** |
| span | **2008-03-25 … 2026-08-17** |
| W82 pin | 4499 |
| **4499 → ?** | **4499 → 4499 (Δ0)** |
| bulk archive re-scan | **not run** |

COMPLETE 22 health (local): **pass** · COMPLETE **22** · PARTIAL **4** · fins **104** · empty **0** · OTC **4499** · bars_am **1** · segs **7888**.

---

## Pytest / freezes

| suite | n |
|-------|--:|
| `tests/test_class_signals.py` | **17** |
| `tests/test_hypothesis_classes.py` | 12 |
| `tests/test_standard_research_eval.py` | 17 |
| `tests/test_paper_candidate_adapter.py` | 12 |
| **key total** | **58 green** |

Standard eval `wiring_only` dry_run: `ready_declared=False` · mass=**NO-GO** · phase7=**OFF** · `research_candidate=False` (harness) · gate≠READY/Mass.

---

## Log index

| file | content |
|------|---------|
| `.glm-logs/w0816r_w83_parallel/run_w83_parallel_search.py` | explore matrix runner |
| `.glm-logs/w0816r_w83_parallel/explore_table.json` | flat comparison rows |
| `.glm-logs/w0816r_w83_parallel/explore_*.json` | per-variant summaries |
| `.glm-logs/w0816r_w83_parallel/class_hyp_multi_year_bundle.json` | full default-path bundle v6 |
| `.glm-logs/w0816r_w83_parallel/candidate_summary.json` | default path candidate table |
| `.glm-logs/w0816r_w83_parallel/holistic_judgments.json` | flexible judgments + reasons |
| `.glm-logs/w0816r_w83_parallel/candidate_list.json` | final passers |
| `.glm-logs/w0816r_w83_parallel/detail_cross_section_hold_10.json` | xs10 detail |
| `.glm-logs/w0816r_w83_parallel/detail_fundamentals_hold_10.json` | fund10 detail |
| `.glm-logs/w0816r_w83_parallel/paper_results.json` | paper trials |
| `.glm-logs/w0816r_w83_parallel/otc_tip_full_ok.json` | OTC light tip |
| `.glm-logs/w0816r_w83_parallel/health_local.json` | COMPLETE 22 health |
| `.glm-logs/w0816r_w83_parallel/pytest_w83.log` | 58 green |

---

## Explicit non-declarations (held)

- **READY / Mass / Phase7 / operational GO / live orders** — closed  
- **continuous paper arm** — **False**  
- **mean-bp-only promotion** — forbidden  
- **event_post look-ahead revival** — forbidden  
- **multi_day_hold 10d production candidate** — still demoted  
- **xs mom=10 as default** — **rejected** (explore collapse)  
- **S1–S5 un-reject / simple_daily_sign** — not done  
- **OTC dataset COMPLETE / bulk densify** — not forced  
- **limited paper PnL as edge** — **not claimed**  
- **commit / push** — residual close (this wave)  

---

## Residual TOP (W83)

1. **2 default research candidates wired** — `cross_section_hold_10` (mom=5) · `fundamentals_hold_10` (mom=10)  
2. **xs content caveat** — mom lookback **must remain 5**; mom=10 not a “better” content match  
3. **Paper proxy gap** — StrategySpec v2 irreducible; limited trials **negative** honestly  
4. **event_post / multi_day_10 / flow / macro** — still not candidates under PIT + stats bar  
5. **OTC** — **4499→4499** tip held · dataset PARTIAL · no bulk re-scan  
6. **Mass/READY/ops GO** — still **未宣言 / NO-GO**
