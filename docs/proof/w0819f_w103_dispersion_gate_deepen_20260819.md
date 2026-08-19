# W103 / w0819f Track C — `xs_cs_dispersion_gate` deepen (vs sticky)

**Wave:** W103 / `w0819f` · Track C  
**Main:** `xs_cs_dispersion_gate` (research-only)  
**Compare:** `xs_rank_ls_sticky` **STABLE_RESEARCH_ONLY**  
**Recipe:** `scripts/run_w103_repo_gate_deepen.py` (+ complementary `scripts/run_w103_dispersion_deepen.py` artifacts)  
**Prior quality:** [`w0819e_w102_dispersion_quality_20260819.md`](w0819e_w102_dispersion_quality_20260819.md)  
**Logs:** [`.glm-logs/w0819f_w103_otc7_repo_gate/`](../../.glm-logs/w0819f_w103_otc7_repo_gate/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| field | value |
|-------|-------|
| promote_as_main | **false** |
| go / go_eligible | **false** |
| uniformly safer than sticky | **false** |
| hold/mom micro-grid | **not run** |
| thresh sensitivity | **3 coarse pts only** (×0.85 / ×1.00 / ×1.15 on trailing median) |
| repo short contrast | **wired** (Track B) — disclosure, not ranking |
| gate worst daily_path_DD | **−11.4%** (`w2023_2025`) |
| sticky worst daily_path_DD | **−14.4%** (`w2017_2019`) |
| sticky stance | **STABLE_RESEARCH_ONLY** |
| Mass / READY / paper | NO-GO / 未宣言 / UNARMED |

Deepen = monitor + understand. **Better in some windows ≠ main candidate.**

---

## Base daily path (tx 10 bp · reproduced)

| logic | window | n_days | daily_path_DD | active_frac | gate_on_frac | total_ret_net |
|-------|--------|-------:|--------------:|------------:|-------------:|--------------:|
| gate | w2017_2019 | 272 | −0.033574 | 0.369 | 0.476 | 0.088918 |
| gate | w2020_2022 | 193 | −0.027298 | 0.427 | 0.513 | 0.186252 |
| gate | w2023_2025 | 273 | −0.114227 | **0.625** | **0.577** | 0.128101 |
| sticky | w2017_2019 | 272 | −0.143741 | 0.926 | — | 0.034975 |
| sticky | w2020_2022 | 193 | −0.037971 | 0.948 | — | 0.201923 |
| sticky | w2023_2025 | 273 | −0.108415 | 0.926 | — | 0.081073 |

Matches W100/W102 method (local_real_mirrors). Gate **not** uniformly safer: 2017–19 shallower; 2023–25 slightly worse than sticky.

---

## Why 2023–25 activity is higher

| window | disp_mean | disp_median | gate_on_frac | active_frac |
|--------|----------:|------------:|-------------:|------------:|
| w2017_2019 | 0.0300 | 0.0260 | 0.476 | 0.369 |
| w2020_2022 | 0.0344 | 0.0301 | 0.513 | 0.427 |
| w2023_2025 | **0.0399** | 0.0276 | **0.577** | **0.625** |

CS mom dispersion spends more calendar time **at/above** its PIT trailing median → gate_on_frac↑ → active_frac↑.  
**2023–25 is not “safer”** — the book is simply **on more often**, and its worst daily_path_DD (−11.4%) is the wave’s gate headline risk.

Artifact: `deepen_activity_why.json`.

---

## Gate on/off segments (disclosure)

Segment equity stitches selected days only — conditional path character, **not** a continuous tradable book.

| window | sticky mean_net \| gate_on | sticky mean_net \| gate_off | gate book on-seg DD | note |
|--------|---------------------------:|----------------------------:|--------------------:|------|
| w2017_2019 | +0.00070 | **−0.00035** | −0.025 | sticky bled on off-days; gate sat flat-ish |
| w2020_2022 | +0.00216 | −0.00022 | −0.035 | same pattern |
| w2023_2025 | +0.00070 | −0.00009 | −0.108 | on-days carry the −11% episode |

Sticky conditional on the gate mask shows **why** the gate helped in 2017–19 (avoided negative off-regime days) and **why** 2023–25 does not look uniformly safer (risk concentrated on on-days).

Artifacts: `deepen_gate_on_off.json` · `deepen_gate_onoff_returns.json`.

---

## Coarse thresh sensitivity (2–3 pts only)

`on = disp >= trailing_median × mult`. Mult ∈ {0.85, 1.00, 1.15}. **Not** a hold/mom/frac grid.

| window | ×0.85 DD | ×1.00 DD | ×1.15 DD | ×0.85 on_frac | ×1.00 on_frac | ×1.15 on_frac |
|--------|---------:|---------:|---------:|--------------:|--------------:|--------------:|
| w2017_2019 | −0.0466 | −0.0336 | −0.0233 | 0.634 | 0.476 | 0.374 |
| w2020_2022 | −0.0302 | −0.0273 | −0.0299 | 0.674 | 0.513 | 0.409 |
| w2023_2025 | −0.1142 | −0.1142 | −0.1142 | 0.734 | 0.577 | 0.442 |

Looser thresh → more activity; 2017–19 DD deepens toward sticky. Tighter thresh → less activity / shallower 2017–19 DD. **2023–25 worst DD stays ≈ −11.4% across all three** — not rescued by coarse thresh. No promotion.

Artifact: `deepen_thresh_sensitivity.json`.

---

## With / without repo short (Track B)

| window | tx-only DD | +repo mid DD | +fixed 50bp DD |
|--------|-----------:|-------------:|---------------:|
| w2017_2019 | −0.033574 | −0.033656 | −0.033673 |
| w2020_2022 | −0.027298 | −0.027412 | −0.027437 |
| w2023_2025 | −0.114227 | −0.114569 | −0.114662 |

Repo short drag is real but **small** vs path DD. Contrast only — **no ranking-by-cost-tune**.

---

## Explicit non-declarations

* promote_as_main / go = **false**  
* “uniformly safe” = **false**  
* hold/mom grid / full catalog = **not run**  
* sticky not re-promoted  
* cost over-tune = **false**

GLM5.3 only. Grok did not implement.
