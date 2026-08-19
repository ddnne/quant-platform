# W103 / w0819f Track C — `xs_cs_dispersion_gate` extra deep-dive (vs sticky)

**Wave:** W103 / `w0819f` · Track C  
**Main:** `xs_cs_dispersion_gate` (research-only; W100/W102 daily_path_DD worst **−11.4%**)  
**Compare:** `xs_rank_ls_sticky` **STABLE_RESEARCH_ONLY** (worst **−14.4%**) — comparison only  
**Data path:** `local_real_mirrors` (same W99/W100 honest shards)  
**Method:** daily MTM after cost — `scripts/run_w100_peer_daily_dd.py` evaluators  
**Recipe:** `scripts/run_w103_repo_gate_deepen.py` · `scripts/run_w103_dispersion_deepen.py`  
**Logs:** [`.glm-logs/w0819f_w103_otc7_repo_gate/`](../../.glm-logs/w0819f_w103_otc7_repo_gate/) · `deepen_summary.json` · `w103_cd_summary.json`  
**Prior quality (cited, not a grid):** [`w0819e_w102_dispersion_quality_20260819.md`](w0819e_w102_dispersion_quality_20260819.md)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

This wave is an **extra** deep-dive, not a promotion. Allowed: gate on vs off interval returns/DD; what drives 2023–25 higher activity; coarse threshold sensitivity **2–3 points max**; repo-linked short overlay because Track B landed. **No** hold/mom micro-grid. **promote_as_main=false · go=false.**

---

## Verdict

| field | value |
|-------|-------|
| promote_as_main | **false** |
| go / go_eligible | **false** |
| hold/mom micro-grid | **not run** |
| full catalog grid | **not run** |
| uniformly safer than sticky | **false** (do not claim) |
| better-in-some-windows ≠ main | **held** |
| thresh sensitivity | **3 pts only** (×0.9 / 1.0 / 1.1 on PIT trailing median; first pass ×0.85/1.15 agrees) |
| `xs_cs_dispersion_gate` worst daily_path_DD | **−11.4%** (`w2023_2025`) |
| `xs_rank_ls_sticky` worst daily_path_DD | **−14.4%** (`w2017_2019`) |
| 2023–25 gate vs sticky | gate **−11.4%** is **slightly worse** than sticky **−10.8%** |
| sticky stance | **STABLE_RESEARCH_ONLY** (not re-promoted) |
| repo-linked short overlay | **wired** (Track B; overnight Tokyo repo; 0 gaps on required dates) |
| 3-default pins | **untouched** |
| Mass / READY / Phase7 / paper | NO-GO / 未宣言 / OFF / UNARMED |

Gate is **not** uniformly safer. 2017–19 inactivity is the quality story; 2023–25 is more often **on**, and the worst path lives **inside** the on-segment. Catalog hold=10 mom=5 left frozen.

---

## Base daily path (tx 10 bp · thresh×1.0 · same method as W100/W102)

Required: **daily_path_DD** · **dd_duration** · **recovery** · **total_ret_net**. Numbers **match W102**.

| logic | window | n_days | daily_path_DD | dd_dur | recov | recovered | total_ret_net | stance |
|-------|--------|-------:|--------------:|-------:|------:|:---------:|--------------:|--------|
| `xs_cs_dispersion_gate` | w2017_2019 | 272 | −0.033574 | 10 | — | False | 0.088918 | RESEARCH_ONLY |
| `xs_cs_dispersion_gate` | w2020_2022 | 193 | −0.027298 | 24 | 1 | True | 0.186252 | RESEARCH_ONLY |
| `xs_cs_dispersion_gate` | w2023_2025 | 273 | −0.114227 | 68 | 52 | True | 0.128101 | RESEARCH_ONLY |
| `xs_rank_ls_sticky` | w2017_2019 | 272 | −0.143741 | 85 | — | False | 0.034975 | STABLE_RESEARCH_ONLY |
| `xs_rank_ls_sticky` | w2020_2022 | 193 | −0.037971 | 14 | 1 | True | 0.201923 | STABLE_RESEARCH_ONLY |
| `xs_rank_ls_sticky` | w2023_2025 | 273 | −0.108415 | 17 | 52 | True | 0.081073 | STABLE_RESEARCH_ONLY |

Local mirrors ≠ CF SoT. Period-net DD=0 **must not** be read as riskless.

---

## Gate on vs off interval returns / DD

Gate state = today's CS-momentum std ≥ PIT trailing median (warmup days count as on). Segment equity **stitches selected days only** — disclosure of conditional path character, **not** a continuous book.

### Gate book's own net, split by gate mask

| window | on n | on mean_net | on total | on DD | off n | off mean_net | off total | off DD |
|--------|-----:|------------:|---------:|------:|------:|-------------:|----------:|-------:|
| w2017_2019 | 128 | +0.000680 | +0.0897 | −0.0251 (4d) | 143 | ≈0 | −0.0007 | −0.0283 (40d) |
| w2020_2022 | 98 | +0.001788 | +0.1847 | −0.0352 (14d, rec) | 94 | ≈0 | +0.0013 | −0.0196 (77d) |
| w2023_2025 | 156 | +0.001047 | +0.1571 | **−0.1084** (36d, rec) | 116 | −0.000206 | −0.0250 | −0.0438 (23d) |

2017–19 / 2020–22: almost all of the gate book's net is earned **on**; off-days are near-flat (sticky-carry leftover, not a second thesis).

2023–25 is the opposite quality story: the **on-segment itself** prints **−10.8%** path DD (36d). That is essentially the headline worst interval (−11.4% on the continuous book, 68 calendar days including off-days between peak and trough). Sitting out the off-days does **not** remove 2023–25 risk.

### Sticky book, **conditional on the same gate mask** (compare only)

| window | sticky ON total / DD | sticky OFF total / DD |
|--------|----------------------|------------------------|
| w2017_2019 | +0.0893 / **−10.5%** (26d) | **−0.0499 / −7.9%** (92d) |
| w2020_2022 | +0.2280 / −4.8% (14d, rec) | −0.0213 / −5.7% (32d) |
| w2023_2025 | +0.0953 / **−10.8%** (36d, rec) | −0.0130 / −3.9% (2d, rec) |

This is the 2017–19 quality edge: sticky's 2019 drawdown (peak 2019-05-21 → trough 2019-09-20, 85d, unrecovered, **−14.4%**) has a large **off-mask** contribution. The gate sat that stretch out. That is **not** a 2023–25 result — in 2023–25 sticky's worst interval is **on-mask** (same trough 2023-04-13), and the gate is on for it.

---

## What drives higher activity in 2023–25

| window | gate_on_frac | active_frac | disp_mean | disp_median | disp_p75 | n_on / n_off |
|--------|-------------:|------------:|----------:|------------:|---------:|-------------:|
| w2017_2019 | 0.476 | 0.369 | 0.0300 | 0.0260 | 0.0341 | 130 / 143 |
| w2020_2022 | 0.513 | 0.427 | 0.0344 | 0.0301 | 0.0381 | 99 / 94 |
| w2023_2025 | **0.577** | **0.625** | **0.0399** | 0.0276 | **0.0404** | 158 / 116 |

Mean CS-momentum std **rises** (0.030 → 0.040). Median does **not** (0.026 → 0.028). The 2023–25 panel has a **fatter right tail** of dispersion, so more days clear the PIT trailing median. That is a **regime-frequency** shift, not a safer book.

### Shard split (honest mirrors; not contiguous 3y)

| shard | n_cal | n_active | active_frac | n_gate_on | n_gate_off | shard DD |
|-------|------:|---------:|------------:|----------:|-----------:|---------:|
| y2017_q4 | 80 | 50 | 0.625 | 44 | 37 | −1.9% |
| y2019_full | 191 | **50** | **0.262** | 86 | 106 | −3.4% |
| y2021_full | 192 | 82 | 0.427 | 99 | 94 | −2.7% |
| **y2023_full** | 192 | **130** | **0.677** | **113** | 80 | **−11.4%** |
| y2025_q4 | 80 | 40 | 0.500 | 45 | 36 | −8.5% |

The 2023–25 activity jump is **the 2023 shard** (68% active), not 2025-q4 (50%). 2017–19 quietness is **the 2019 shard** (26% active) — the same shard that contains sticky's unrecovered −14.4% path.

Sticky-carry vs gate-on:

- 2017–19: active **37%** < gate_on **48%** (gate-on days before sticky fill / warmup).
- 2023–25: active **63%** > gate_on **58%** (sticky hold keeps the book on after the gate drops).

Higher 2023–25 activity = (1) more days above the trailing median because of a fatter CS-disp tail, **plus** (2) sticky-hold carry. Neither is a safety claim.

---

## Coarse threshold sensitivity (3 points MAX · no grid farm)

`on = disp ≥ (PIT trailing median × thresh_mult)`. Catalog hold=10 mom=5 **frozen**. On-disk 3-pt set: **×0.9 / ×1.0 / ×1.1**. A first pass at ×0.85 / ×1.15 told the same story (2023–25 DD invariant). Not a grid farm.

| window | ×0.9 DD / net / on_frac / act | ×1.0 DD / net / on_frac / act | ×1.1 DD / net / on_frac / act |
|--------|-------------------------------|-------------------------------|-------------------------------|
| w2017_2019 | −4.56% / +8.6% / 60% / 48% | −3.36% / +8.9% / 48% / 37% | −2.33% / +11.2% / 40% / 33% |
| w2020_2022 | −3.02% / +17.6% / 65% / 58% | −2.73% / +18.6% / 51% / 43% | −2.73% / +13.3% / 44% / 31% |
| w2023_2025 | **−11.42%** / +15.2% / 68% / 70% | **−11.42%** / +12.8% / 58% / 63% | **−11.42%** / +11.7% / 48% / 51% |

**2023–25 worst path DD is −11.42% at all three points.** The Jan–Apr 2023 episode is a high-dispersion regime that still clears ×1.1 (and ×1.15 on the first pass). Tightening the gate does **not** delete the worst interval; it only cuts later activity and some net. Loosening (×0.9) **worsens 2017–19** (−3.4% → −4.6%, 77d unrecovered) by turning the book back on during the 2019 stretch the base gate sat out.

This is a **disclosure**, not a retune. Do not pick ×1.1 because 2017–19 looks calmer. Do not pick ×0.9 because 2023–25 net is higher. **promote_as_main=false.**

---

## Repo-linked short overlay (Track B landed)

JSDA Tokyo overnight (`overnight/翌日物/T+0`) loaded from local `jsda_repo_rates`. **n_obs=2594**, required window dates **738/738 present**, **n_gaps=0**, **no ffill / no invent**. Short daily = f(repo[t] + mid 50 bp spread, short_frac=0.5) on **active** days only. Contrast vs the W102 fixed-50 bp placeholder. **Not** a ranking-by-cost-tune.

| logic | window | tx-only DD | +repo mid DD | +fixed-50bp DD | tx-only net | +repo mid net |
|-------|--------|-----------:|-------------:|---------------:|------------:|--------------:|
| gate | w2017_2019 | −0.033574 | −0.033656 | −0.033673 | 0.088918 | 0.088013 |
| gate | w2020_2022 | −0.027298 | −0.027412 | −0.027437 | 0.186252 | 0.185430 |
| gate | w2023_2025 | −0.114227 | −0.114569 | −0.114662 | 0.128101 | 0.125973 |
| sticky | w2017_2019 | −0.143741 | −0.144363 | −0.144485 | 0.034975 | 0.032789 |
| sticky | w2020_2022 | −0.037971 | −0.038086 | −0.038109 | 0.201923 | 0.200072 |
| sticky | w2023_2025 | −0.108415 | −0.108529 | −0.108570 | 0.081073 | 0.077942 |

Gate worst becomes **−11.46%** (repo mid) vs **−11.47%** (fixed placeholder). Recovery flags and ranking vs sticky **do not flip**. Overlay is a disclosure. **No extra leverage** (gross=1.0 dollar-neutral L-S).

---

## Headline (research-only · not GO)

- W102 headline reproduces: gate worst **−11.4%** (2023–25) vs sticky **−14.4%** (2017–19).
- The 2017–19 edge is **inactivity on the off-mask**, where sticky lost ~5% / −7.9% DD. That is **not** a 2023–25 result.
- 2023–25 higher activity is a **fatter CS-disp right tail** (mean 0.040 vs 0.030; median not higher) concentrated in the **2023 shard** (68% active), plus sticky-hold carry. The on-segment itself is **−10.8%**. More often on ≠ safer.
- Coarse thresh ×0.9/1.0/1.1 (and ×0.85/1.15) does **not** move 2023–25 worst DD off −11.4%. Do not retune the threshold.
- Repo-linked short (Track B) is a small extra drag; **not** a ranking lever.
- **promote_as_main=false · go=false.** Sticky stays **STABLE_RESEARCH_ONLY**. Gate stays **RESEARCH_ONLY**. Neither is a production `research_candidate`. Better-in-some-windows is **not** a main candidate.

## Non-claims

- No READY / Mass / GO / live / pin retune / hold-mom grid / full catalog grid.
- No “uniformly safer”. No pick-best thresh. No cost over-tune ranking.
- Segment on/off equity is **disclosure**, not a tradable continuous book.
- Local mirrors ≠ CF SoT. Period-net DD=0 **must not** be read as riskless.

GLM implementer only. Grok did not implement.
