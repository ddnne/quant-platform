# W102 / w0819e Track C — `xs_cs_dispersion_gate` quality (vs sticky)

**Wave:** W102 / `w0819e` · Track C  
**Main:** `xs_cs_dispersion_gate` (research-only; W100 daily_path_DD worst **−11.4%**)  
**Compare:** `xs_rank_ls_sticky` **STABLE_RESEARCH_ONLY** (worst **−14.4%**) — comparison only  
**Data path:** `local_real_mirrors` (same W99/W100 honest shards)  
**Method:** daily MTM after cost — `scripts/run_w100_peer_daily_dd.py` evaluators  
**Recipe:** `scripts/run_w102_dispersion_quality.py`  
**Logs:** [`.glm-logs/w0819e_w102_otc6_event_rate_dd/`](../../.glm-logs/w0819e_w102_otc6_event_rate_dd/) · `quality_summary.json`  
**Peer cite (not rerun as a grid):** [`w0819c_w100_peer_daily_dd_20260819.md`](w0819c_w100_peer_daily_dd_20260819.md)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| field | value |
|-------|-------|
| promote_as_main | **false** |
| go / go_eligible | **false** |
| hold/mom micro-grid | **not run** |
| full catalog grid | **not run** |
| cost over-tune | **false** (tx 5/10/20 bp + short L/M/H disclosure only) |
| extra leverage | **not applied** (gross=1.0 dollar-neutral L-S) |
| `xs_cs_dispersion_gate` worst daily_path_DD | **−11.4%** (`w2023_2025`) |
| `xs_rank_ls_sticky` worst daily_path_DD | **−14.4%** (`w2017_2019`) |
| sticky stance | **STABLE_RESEARCH_ONLY** (not re-promoted) |
| 3-default pins | **untouched** |
| Mass / READY / Phase7 / paper | NO-GO / 未宣言 / OFF / UNARMED |

Quality check, not a promotion. Gate is **not** uniformly safer than sticky. Research-only.

---

## Base daily path (tx 10 bp · same method as W100)

Required: **daily_path_DD** · **dd_duration** · **recovery** · **total_ret_net**.

| logic | window | n_days | daily_path_DD | dd_dur | recov | recovered | total_ret_net | stance |
|-------|--------|-------:|--------------:|-------:|------:|:---------:|--------------:|--------|
| `xs_cs_dispersion_gate` | w2017_2019 | 272 | −0.033574 | 10 | — | False | 0.088918 | RESEARCH_ONLY |
| `xs_cs_dispersion_gate` | w2020_2022 | 193 | −0.027298 | 24 | 1 | True | 0.186252 | RESEARCH_ONLY |
| `xs_cs_dispersion_gate` | w2023_2025 | 273 | −0.114227 | 68 | 52 | True | 0.128101 | RESEARCH_ONLY |
| `xs_rank_ls_sticky` | w2017_2019 | 272 | −0.143741 | 85 | — | False | 0.034975 | STABLE_RESEARCH_ONLY |
| `xs_rank_ls_sticky` | w2020_2022 | 193 | −0.037971 | 14 | 1 | True | 0.201923 | STABLE_RESEARCH_ONLY |
| `xs_rank_ls_sticky` | w2023_2025 | 273 | −0.108415 | 17 | 52 | True | 0.081073 | STABLE_RESEARCH_ONLY |

Numbers **match W100** (same shards / codes / 10 bp convention). Local mirrors ≠ CF SoT.

---

## Activity

Gate thesis: stay flat when PIT CS-momentum std is below its trailing median. That is visible in activity, not just in the headline DD.

| logic | window | n_active | active_frac | gate_on | gate_off | gate_on_frac |
|-------|--------|---------:|------------:|--------:|---------:|-------------:|
| `xs_cs_dispersion_gate` | w2017_2019 | 100 | 0.369 | 130 | 143 | 0.476 |
| `xs_cs_dispersion_gate` | w2020_2022 | 82 | 0.427 | 99 | 94 | 0.513 |
| `xs_cs_dispersion_gate` | w2023_2025 | 170 | 0.625 | 158 | 116 | 0.577 |
| `xs_rank_ls_sticky` | w2017_2019 | 251 | 0.926 | — | — | always-on |
| `xs_rank_ls_sticky` | w2020_2022 | 182 | 0.948 | — | — | always-on |
| `xs_rank_ls_sticky` | w2023_2025 | 252 | 0.926 | — | — | always-on |

Gate is on **~48–58%** of scored days and active **37–63%** of the calendar. Sticky is active **~93–95%**. The 2017–19 gap is the quality story: gate sat out most of the 2019 sticky drawdown (peak 2019-05-21 → trough 2019-09-20, 85 days, unrecovered) and printed only a 10-day −3.4% interval.

2023–25 is the opposite: gate is **more** active (62.5%) and its worst path DD **−11.4%** is **slightly worse** than sticky **−10.8%** (same trough date 2023-04-13; gate started the episode earlier, 2023-01-04 vs 2023-03-20).

---

## DD-interval character

Single max-DD is not the whole path. Episodes = stretches below the running peak.

| logic | window | n_ep | time underwater | max ep dur | median ep | worst peak → trough | recovered |
|-------|--------|-----:|----------------:|-----------:|----------:|---------------------|:---------:|
| gate | w2017_2019 | 14 | 84.1% | 103 | 6.5 | 2019-05-21 → 2019-06-04 (10d) | False |
| gate | w2020_2022 | 11 | 83.3% | 77 | 9.0 | 2021-08-23 → 2021-09-28 (24d) | True (1d) |
| gate | w2023_2025 | 6 | 90.4% | 120 | 27.0 | 2023-01-04 → 2023-04-13 (68d) | True (52d) |
| sticky | w2017_2019 | 20 | 82.7% | 103 | 4.5 | 2019-05-21 → 2019-09-20 (85d) | False |
| sticky | w2020_2022 | 13 | 81.3% | 84 | 8.0 | 2021-09-06 → 2021-09-28 (14d) | True (1d) |
| sticky | w2023_2025 | 7 | 92.3% | 84 | 45.0 | 2023-03-20 → 2023-04-13 (17d) | True (52d) |

Both books spend most of the window underwater of *some* peak (80–92%). Gate’s advantage is **shallower / shorter worst interval in 2017–19**, not a smoother equity curve. 2023–25 gate has the **longest single episode** (120d) and a deeper worst interval than sticky.

> **Warning:** period-net DD = 0 when all period nets are positive is an
> **aggregation artifact**. It does **not** mean the strategy is riskless.
> Use **daily_path_DD** (duration / recovery / total_ret_net).

---

## Cost sensitivity (tx only · params frozen)

One-way 5 / 10 / 20 bp. **Not** a hold/mom/frac grid. Catalog hold=10 mom=5 left untouched.

| logic | window | DD @5bp | DD @10bp | DD @20bp | net @5bp | net @10bp | net @20bp |
|-------|--------|--------:|---------:|---------:|---------:|----------:|----------:|
| gate | w2017_2019 | −0.033526 | −0.033574 | −0.033671 | 0.089462 | 0.088918 | 0.087830 |
| gate | w2020_2022 | −0.027230 | −0.027298 | −0.027434 | 0.186738 | 0.186252 | 0.185282 |
| gate | w2023_2025 | −0.114014 | −0.114227 | −0.114653 | 0.129060 | 0.128101 | 0.126186 |
| sticky | w2017_2019 | −0.143377 | −0.143741 | −0.144470 | 0.036275 | 0.034975 | 0.032381 |
| sticky | w2020_2022 | −0.037903 | −0.037971 | −0.038106 | 0.203017 | 0.201923 | 0.199740 |
| sticky | w2023_2025 | −0.108338 | −0.108415 | −0.108567 | 0.082435 | 0.081073 | 0.078352 |

Gate worst path moves **−11.40% → −11.42% → −11.47%** across 5/10/20 bp. Sticky worst **−14.34% → −14.37% → −14.45%**. Ranking and recovery flags do not flip. Gate is less cost-sensitive because it is off ~half the days.

---

## Leverage / short overlay (disclosure · not a retune)

CS L-S is already dollar-neutral (`long_frac=short_frac=0.3`). **No extra leverage** (`gross_leverage=1` → financing daily = 0).

Short borrow is a **placeholder overlay**: 25 / 50 / 150 bp annual × short_frac=0.5 / 245 days, applied only while the book is active. **Repo series not wired into this bars-MTM path** — gaps not invented (`rate_source=fixed_bp_placeholder`). Mid=50 bp is the single overlay; L/H are disclosure bands, **not** pick-best.

| logic | window | DD tx-only | DD +short mid | DD +short high | net +short mid |
|-------|--------|-----------:|--------------:|---------------:|---------------:|
| gate | w2017_2019 | −0.033574 | −0.033673 | −0.033871 | 0.087808 |
| gate | w2020_2022 | −0.027298 | −0.027437 | −0.027715 | 0.185262 |
| gate | w2023_2025 | −0.114227 | −0.114662 | −0.115531 | 0.126147 |
| sticky | w2017_2019 | −0.143741 | −0.144485 | −0.145971 | 0.032328 |
| sticky | w2020_2022 | −0.037971 | −0.038109 | −0.038384 | 0.199696 |
| sticky | w2023_2025 | −0.108415 | −0.108570 | −0.108882 | 0.078297 |

Mid overlay adds ~1.0 bp/day while active. Gate worst becomes **−11.47%** (mid) / **−11.55%** (high). Does **not** change the research-only stance. Checklist v2 still wants a **repo-linked** short series before any `research_candidate` discussion — not claimed here.

---

## Headline (research-only · not GO)

- Gate’s W100 headline (worst **−11.4%** vs sticky **−14.4%**) **reproduces**. The edge is **2017–19 inactivity**, not a uniformly calmer book.
- 2023–25 gate worst interval is **longer and slightly deeper** than sticky. Activity rose (gate_on 58%). Do not read “dispersion gate = safer sticky”.
- Cost (tx 5–20 bp) and short placeholder (25–150 bp annual) **do not reorder** the two books. No over-tune.
- **promote_as_main=false · go=false.** Sticky stays **STABLE_RESEARCH_ONLY**. Gate stays **RESEARCH_ONLY**. Neither is a production `research_candidate`.

## Non-claims

- No READY / Mass / GO / live / pin retune / hold-mom grid / full catalog grid.
- No extra leverage. Short overlay is a **fixed-bp placeholder**, not repo-linked.
- Local mirrors ≠ CF SoT. Period-net DD=0 **must not** be read as riskless.
- Leverage/short + risk-scenario checklist items still required before any candidate discussion.

GLM implementer only. Grok did not implement.
