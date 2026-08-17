# W84 / w0816s — Task C: parallel strategy explore (while A aligns)

**Wave status:** **Task C COMPLETE** (explore · metrics table · judgments · early paper · OTC tip) — **no commit/push**  
**Wave:** W84 / `w0816s` · 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Logs:** [`.glm-logs/w0816s_w84_realign/`](../../.glm-logs/w0816s_w84_realign/) · `explore_*`  
**Prior:** W83 default-path 2 candidates (xs hold=10 mom=5 · fund hold=10 mom=10) · event_post PIT demote · multi_day 10d demote

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
| default-path rewire | **not done in Task C** (A aligns; explore-only) |
| commit / push | **not done** (policy) |

---

## Policy (W84 Task C)

| rule | held |
|------|------|
| Parallel evaluate other classes/variants; do not wait for A | **yes** |
| PIT-safe only; no look-ahead event revival | **yes** |
| Stats always shown; flexible holistic judgment; no mean-bp-only | **yes** |
| No simple_daily_sign; no S1–S5 un-reject | **yes** |
| OTC tip-wait only (record 4499→?) | **yes** · **4499→4499** |
| Explore flow / macro / multi_day (real content) / event PIT / other CS+fund | **yes** |

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

Costs: **10bp one-way base** · **liquidity-linked** tx_mult · repo series disclosed.

Windows: W80/W81 style **full+Q4** (`y2015_full` · `y2017_q4` · `y2019_full` · `y2021_full` · `y2023_full` · `y2025_q4`) · 30 large-cap · liquidity one-way.

---

## Baseline (W83 default path reconfirm)

| class / block | mean net | t | Sharpe | win-rate | maxDD | hard RC | **holistic** |
|---------------|---------:|--:|-------:|---------:|------:|:------:|--------------|
| multi_day_hold 5d | +0.4bp | 0.03 | 0.01 | 0.50 | −59bp | False | **reject** |
| multi_day_hold 10d | +21.1bp | 0.62 | 0.25 | 0.67 | −132bp | False | **reject** (noisy; no force-revive) |
| event_post PIT | +5.9bp | 0.25 | 0.10 | 0.67 | −91bp | False | **reject** (no look-ahead revival) |
| macro_conditioned | −24.1bp | −3.16 | −1.29 | 0.00 | −145bp | False | **reject** |
| cross_section hold=5 | −10.9bp | −0.44 | −0.18 | 0.50 | −144bp | False | **reject** |
| **cross_section_hold_10 mom=5** | **+84.6bp** | **1.60** | **0.65** | **0.67** | **−47bp** | **True** | **W83 default_candidate** (held) |
| flow_demand hold=5 | +117.9bp* | 0.76 | 0.31 | 0.33 | −225bp | False | **reject** (*mean high, majority neg) |
| fundamentals hold=20 mom=20 | +70.9bp | 1.04 | 0.42 | 0.67 | −109bp | False | **conditional** / discussion |
| **fundamentals_hold_10 mom=10** | **+45.9bp** | **1.82** | **0.74** | **0.67** | **−10bp** | **True** | **W83 default_candidate** (held) |

---

## A. flow_demand (improved content)

| variant | mean net | t | Sharpe | win | maxDD | gate | econ | occ | stats | hard RC | **holistic** |
|---------|---------:|--:|-------:|----:|------:|:----:|:----:|:---:|:-----:|:------:|--------------|
| **hold=5 + short_confirm** | **+123.0bp** | **1.54** | **0.63** | 0.67 | −66bp | ✓ | ✓ | ✗ | ✓ | False | **conditional_near_miss** |
| hold=7 | −86.0bp | −0.78 | −0.32 | 0.67 | −712bp | ✗ | ✗ | ✓ | ✗ | False | **reject** |
| hold=7 + short_confirm | +37.1bp | 0.69 | 0.28 | 0.67 | −126bp | ✓ | ✓ | ✗ | ✗ | False | **reject** (stats+occ) |
| hold=15 | −606.7bp | −1.08 | −0.44 | 0.50 | −3760bp | ✗ | ✗ | ✗ | ✗ | False | **reject** |
| hold=15 + short_confirm | −112.3bp | −1.25 | −0.51 | 0.33 | −770bp | ✗ | ✗ | ✗ | ✗ | False | **reject** |
| hold=20 + short_confirm | −157.1bp | −0.82 | −0.34 | 0.67 | −1498bp | ✓ | ✗ | ✗ | ✗ | False | **reject** |

**Look-ahead:** margin change on observation date only; sticky min_hold; short_confirm same-sign optional. Not S4 daily rehash.

**Holistic — flow hold=5 short_confirm:** real content improve vs bare hold=5 (t 0.76→1.54, win 0.33→0.67, maxDD shrinks). Gate+econ+stats clear. **Occurrence rate fails** (sparse short-confirmed margin entries) → **not** hard RC / **not** default-wire. Discussion-only near-miss.

---

## B. macro_conditioned (horizon content; mom tied to `hold_days`)

| variant | mean net | t | Sharpe | win | hard RC | **holistic** |
|---------|---------:|--:|-------:|----:|:------:|--------------|
| hold=5 rate_change (baseline) | −24.1bp | −3.16 | −1.29 | 0.00 | False | **reject** |
| hold=10 rate_change | −18.1bp | −2.29 | −0.93 | 0.17 | False | **reject** |
| hold=20 rate_change | −13.2bp | −1.94 | −0.79 | 0.17 | False | **reject** |
| hold=5 rate_level | −6.2bp | −1.43 | −0.58 | 0.17 | False | **reject** |
| hold=10 rate_level | −2.4bp | −0.46 | −0.19 | 0.33 | False | **reject** |
| hold=20 rate_level | −8.7bp | −2.12 | −0.86 | 0.17 | False | **reject** |

All negative residual after costs. No candidate. Repo series local SQLite keyed by as_of_date (disclosed bulk available_at).

---

## C. multi_day (real content only — new horizons; no 10d force-revive)

| variant | mean net | t | Sharpe | win | gate | econ | occ | stats | hard RC | **holistic** |
|---------|---------:|--:|-------:|----:|:----:|:----:|:---:|:-----:|:------:|--------------|
| hold=5 (baseline) | +0.4bp | 0.03 | 0.01 | 0.50 | ✗ | ✗ | ✓ | ✗ | False | **reject** |
| **hold=7** (new horizon) | **+23.0bp** | **0.92** | **0.37** | 0.67 | ✓ | ✓ | ✓ | ✗ | False | **reject_noisy_stats** |
| hold=10 reconfirm | +21.1bp | 0.62 | 0.25 | 0.67 | ✓ | ✓ | ✓ | ✗ | False | **reject_noisy_stats** (no force-revive) |
| hold=15 (new horizon) | +6.0bp | 0.11 | 0.04 | 0.67 | ✓ | ✗ | ✓ | ✗ | False | **reject** |
| hold=20 (W83) | +18.5bp | 0.20 | 0.08 | 0.83 | ✓ | ✗ | ✗ | ✗ | False | **reject** |

**Content note:** hold=7 is a real different horizon (entry mom_n=7, sticky 7d) — better than 5/15/20 mean residual but **stats bar fails** (t=0.92 · Sharpe=0.37). Same construction family as demoted 10d → **no force-revive**. No production candidate.

---

## D. event_post PIT-only (W82 entry; no look-ahead revival)

| variant | mean net | t | Sharpe | win | hard RC | **holistic** |
|---------|---------:|--:|-------:|----:|:------:|--------------|
| PIT hold=5 (baseline) | +5.9bp | 0.25 | 0.10 | 0.67 | False | **reject** |
| PIT hold=3 | +1.4bp | 0.07 | 0.03 | 0.50 | False | **reject** |
| PIT hold=10 (W83) | +0.9bp | 0.02 | 0.01 | 0.67 | False | **reject** |
| PIT hold=15 | +17.3bp | 0.45 | 0.19 | 0.67 | False | **reject** (econ fail) |
| PIT hold=20 | +49.7bp | 0.96 | 0.39 | 0.50 | False | **reject** (mean high, stats/econ fail) |
| PIT hold=5 no earnings_date thicken | +3.5bp | 0.16 | 0.06 | 0.67 | False | **reject** |
| PIT hold=10 no thicken | −4.2bp | −0.08 | −0.03 | 0.67 | False | **reject** |

W81 pre-PIT KEEP remains **look-ahead contaminated** — **not revived**. Entry mode: `same_day_close_if_pre_close` (DiscDate+DiscTime SoT).

---

## E. cross_section — other CS specs (around W82 pin)

| variant | mean net | t | Sharpe | win | maxDD | occ | stats | hard RC | **holistic** |
|---------|---------:|--:|-------:|----:|------:|:---:|:-----:|:------:|--------------|
| hold=10 mom=5 frac=0.3 (W83 pin) | +84.6bp | 1.60 | 0.65 | 0.67 | −47bp | ✓ | ✓ | **True** | **W83 default** |
| hold=10 mom=5 **frac=0.2** | +125.3bp | 1.65 | 0.68 | 0.83 | −88bp | ✗ | ✓ | False | **conditional_near_miss** |
| hold=10 mom=5 **frac=0.4** | **+62.9bp** | **1.69** | **0.69** | 0.67 | −36bp | ✓ | ✓ | **True** | **NEW hard passer** |
| hold=10 **mom=3** | **+120.1bp** | **3.04** | **1.24** | **1.00** | 0bp* | ✓ | ✓ | **True** | **NEW hard passer** (standout) |
| hold=10 mom=7 | +78.2bp | 1.47 | 0.60 | 0.67 | −52bp | ✓ | ✗ | False | **reject_noisy_stats** (t just below 1.5) |
| hold=7 mom=5 | −31.9bp | −0.74 | −0.30 | 0.33 | −298bp | ✓ | ✗ | False | **reject** |
| hold=15 mom=5 | +49.7bp | 1.07 | 0.44 | 0.67 | −104bp | ✗ | ✗ | False | **reject** |
| hold=20 mom=5 | −100.2bp | −0.86 | −0.35 | 0.50 | −646bp | ✗ | ✗ | False | **reject** |

\*maxDD=0: all 6 period nets positive (weakest y2023 +6.2bp).

**Look-ahead check (xs):** same-day close momentum ranks → sticky fixed-horizon hold → multi-day forward from rebalance bar. Ranks use only bars ≤ t.

**Holistic — xs hold=10 mom=3:** strongest stats in matrix (t=3.04 · Sharpe=1.24 · win=6/6). Hard bar full pass. Content is real (shorter mom lookback on sticky 10d hold — same pattern as W82 pin that mom must stay short). **Task C does not default-wire** (A aligns). Paper proxy only.

**Holistic — xs hold=10 mom=5 frac=0.4:** broader book than pin frac=0.3; hard bar pass with lower mean than pin but cleaner maxDD. Eligible research candidate (not default-wired here).

**Holistic — xs hold=10 mom=5 frac=0.2:** higher mean/t than pin but **occ fails** (narrower book → activation rate below floor) → near-miss, not wire.

---

## F. fundamentals_price — other fund specs

| variant | mean net | t | Sharpe | win | maxDD | hard RC | **holistic** |
|---------|---------:|--:|-------:|----:|------:|:------:|--------------|
| hold=20 mom=20 agree (default) | +70.9bp | 1.04 | 0.42 | 0.67 | −109bp | False | discussion / conditional |
| hold=10 mom=10 agree (W83) | +45.9bp | 1.82 | 0.74 | 0.67 | −10bp | **True** | **W83 default** |
| hold=5 mom=5 agree | +15.0bp | 0.82 | 0.33 | 0.67 | −52bp | False | **reject** (econ) |
| hold=10 mom=5 agree | +21.3bp | 0.66 | 0.27 | 0.67 | −102bp | False | **reject_noisy_stats** |
| hold=10 mom=20 agree | +47.5bp | 1.28 | 0.52 | 0.67 | −37bp | False | **reject_noisy_stats** |
| **hold=15 mom=10 agree** | **+91.5bp** | **1.80** | **0.73** | **0.83** | **−22bp** | **True** | **NEW hard passer** |
| **hold=5 mom=10 agree** | **+24.4bp** | **1.92** | **0.78** | **0.83** | **−9bp** | **True** | **NEW hard passer** (econ borderline) |
| hold=20 mom=10 agree | +45.4bp | 0.62 | 0.25 | 0.50 | −206bp | False | **reject** |
| hold=10 value_only | +2.3bp | 0.06 | 0.03 | 0.50 | −155bp | False | **reject** |
| hold=5 value_only | +4.2bp | 0.22 | 0.09 | 0.33 | −77bp | False | **reject** |

**Look-ahead (fund):** PIT `fins_asof` on disc calendar; value score vs global median; sticky hold. No invent EPS/FEPS. value_only fails; value×mom agree required.

**Holistic — fund hold=15 mom=10:** stronger mean than W83 hold=10 with solid t/Sharpe/win; hard pass. Real content (longer sticky hold, matched mom lookback). Not default-wired in Task C.

**Holistic — fund hold=5 mom=10:** best fund stats (t=1.92 · Sharpe=0.78 · win=0.83) but mean **+24.4bp** only barely above 20bp econ floor. Hard pass; fragile economically. Paper proxy identical to hold=15 when only mom_n expressible.

---

## NEW hard-bar passers (Task C explore)

| # | class | variant | mean | t | Sharpe | win | hard RC | default-wired |
|---|-------|---------|-----:|--:|-------:|----:|:------:|:-------------:|
| 1 | **cross_section_relative** | sticky hold=10 · **mom=3** | +120.1bp | **3.04** | **1.24** | **1.00** | **True** | **no** (explore) |
| 2 | **cross_section_relative** | sticky hold=10 · mom=5 · **frac=0.4** | +62.9bp | 1.69 | 0.69 | 0.67 | **True** | **no** (explore) |
| 3 | **fundamentals_price** | hold=**15** · mom=**10** agree | +91.5bp | 1.80 | 0.73 | 0.83 | **True** | **no** (explore) |
| 4 | **fundamentals_price** | hold=**5** · mom=**10** agree | +24.4bp | 1.92 | 0.78 | 0.83 | **True** | **no** (explore) |

**W83 defaults still on path (reconfirmed):** xs hold=10 mom=5 · fund hold=10 mom=10.  
**Mass / READY / operational GO / live: still closed.**

### Near-misses (not hard RC)

| variant | mean | t | Sharpe | why not hard |
|---------|-----:|--:|-------:|--------------|
| flow hold=5 short_confirm | +123bp | 1.54 | 0.63 | occurrence rate fail |
| xs hold=10 mom=5 frac=0.2 | +125bp | 1.65 | 0.68 | occurrence rate fail |

---

## Paper (new passers only)

Continuous scheduler **UNARMED**. Live **OFF**. Fidelity = **MomentumFeatureStrategy / StrategySpec v2 proxy** (momentum_n top_k). Sticky CS L-S ranks and fund value leg **not expressible**.

| trial | class | window | post-cost | maxDD | trades | note |
|-------|-------|--------|----------:|------:|-------:|------|
| single-shot | xs hold10 mom3 proxy | 5d Draft | **+1.46%** | −0.21% | 26 | dry healthy |
| **limited** | xs hold10 mom3 proxy | 30d Paper | **−18.87%** | −22.2% | 191 | **honest negative** |
| single-shot | xs hold10 mom5 frac40 proxy | 5d Draft | **+2.14%** | −0.10% | 56 | dry healthy |
| **limited** | xs hold10 mom5 frac40 proxy | 30d Paper | **−0.72%** | −5.77% | 315 | **honest negative** |
| single-shot | fund hold15 mom10 proxy | 5d Draft | **+2.17%** | −0.27% | 23 | dry healthy |
| **limited** | fund hold15 mom10 proxy | 30d Paper | **−4.06%** | −10.35% | 152 | **honest negative** |
| single-shot | fund hold5 mom10 proxy | 5d Draft | **+2.17%** | −0.27% | 23 | same proxy as hold15 (mom only) |
| **limited** | fund hold5 mom10 proxy | 30d Paper | **−4.06%** | −10.35% | 152 | **honest negative** |

Limited-window proxy PnL is **not** alpha / significance / edge claim.  
Logs: `.glm-logs/w0816s_w84_realign/paper_*` · `paper_trial_card.json` · `paper_results.json`.

---

## OTC light tip FULL_OK

| metric | value |
|--------|------:|
| dataset | `jsda_otc_bond_reference_prices` |
| dataset status | **PARTIAL** (held) |
| COMPLETE segments | **4499** |
| span | **2008-03-25 … 2026-08-17** |
| W83 pin | 4499 |
| **4499 → ?** | **4499 → 4499 (Δ0)** |
| bulk archive re-scan | **not run** |

Log: `.glm-logs/w0816s_w84_realign/otc_tip_full_ok.json`

---

## Log index

| file | content |
|------|---------|
| `.glm-logs/w0816s_w84_realign/run_w84_parallel_explore.py` | explore matrix runner |
| `.glm-logs/w0816s_w84_realign/run_all.log` | full stdout |
| `.glm-logs/w0816s_w84_realign/explore_*.json` | per-variant summaries |
| `.glm-logs/w0816s_w84_realign/explore_table.json` | flat comparison rows |
| `.glm-logs/w0816s_w84_realign/explore_table.md` | markdown metrics table |
| `.glm-logs/w0816s_w84_realign/explore_strong.json` | hard RC + near-miss rows |
| `.glm-logs/w0816s_w84_realign/explore_focus_table.json` | primary-class focus rows |
| `.glm-logs/w0816s_w84_realign/holistic_judgments.json` | flexible judgments |
| `.glm-logs/w0816s_w84_realign/candidate_list.json` | NEW passers + near-misses |
| `.glm-logs/w0816s_w84_realign/bundle_baseline_default_path.json` | full default-path bundle |
| `.glm-logs/w0816s_w84_realign/run_w84_paper_passers.py` | paper trials |
| `.glm-logs/w0816s_w84_realign/paper_results.json` | paper metrics |
| `.glm-logs/w0816s_w84_realign/paper_trial_card.json` | paper card |
| `.glm-logs/w0816s_w84_realign/otc_tip_full_ok.json` | OTC 4499→4499 |

---

## Explicit non-declarations (held)

- **READY / Mass / Phase7 / operational GO / live orders** — closed  
- **continuous paper arm** — **False**  
- **mean-bp-only promotion** — forbidden  
- **event_post look-ahead revival** — forbidden  
- **multi_day force-revive** (7/10/15) — demoted (stats/econ)  
- **default-path rewire of NEW passers** — **not done** in Task C (A aligns)  
- **S1–S5 un-reject / simple_daily_sign** — not done  
- **OTC dataset COMPLETE / bulk densify** — not forced  
- **limited paper PnL as edge** — **not claimed**  
- **commit / push** — **not done**

---

## Residual for Task A / later

1. **4 NEW hard-bar research candidates** found in parallel explore — decide whether to wire any into default path (mom=3 standout; fund hold=15 stronger mean; fund hold=5 borderline econ).  
2. **W83 defaults** still valid on path (xs hold=10 mom=5 · fund hold=10 mom=10).  
3. **flow short_confirm hold=5** near-miss — occurrence rate is the blocker; not S4.  
4. **macro / multi_day / event PIT** remain rejects under full bar.  
5. **Paper proxy gap** irreducible under StrategySpec v2; limited trials mostly **negative** honestly.  
6. **OTC** — **4499→4499** tip-wait · dataset PARTIAL.  
7. **Mass/READY/ops GO** — still **未宣言 / NO-GO**.  
8. **No commit/push** from this Task C landing.
