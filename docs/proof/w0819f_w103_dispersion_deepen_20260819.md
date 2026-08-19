# W103 / w0819f Track C — `xs_cs_dispersion_gate` deepen (vs sticky · no GO)

**Wave:** W103 / `w0819f` · Track C  
**Main:** `xs_cs_dispersion_gate` (research-only; W100/W102 daily_path_DD worst **−11.4%**)  
**Compare:** `xs_rank_ls_sticky` **STABLE_RESEARCH_ONLY** (worst **−14.4%**) — comparison only  
**Data path:** `local_real_mirrors` (same W99/W100 honest shards)  
**Method:** daily MTM after cost — `scripts/run_w100_peer_daily_dd.py` evaluators  
**Recipe:** `scripts/run_w103_dispersion_deepen.py` (extends `scripts/run_w102_dispersion_quality.py`)  
**Complementary (Track B / parallel deepen):** `scripts/run_w103_repo_gate_deepen.py` · [`w0819f_w103_dispersion_gate_deepen_20260819.md`](w0819f_w103_dispersion_gate_deepen_20260819.md) · [`w0819f_w103_repo_short_wiring_20260819.md`](w0819f_w103_repo_short_wiring_20260819.md)  
**Prior quality (cited):** [`w0819e_w102_dispersion_quality_20260819.md`](w0819e_w102_dispersion_quality_20260819.md)  
**Logs:** [`.glm-logs/w0819f_w103_otc7_repo_gate/`](../../.glm-logs/w0819f_w103_otc7_repo_gate/) · `deepen_summary.json` · `deepen_gate_onoff_returns.json` · `deepen_activity_explain_w2023_2025.json` · `deepen_thresh_sensitivity.json` · `deepen_repo_short_contrast.json`  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| field | value |
|-------|-------|
| promote_as_main | **false** |
| go / go_eligible | **false** |
| uniformly safer than sticky | **false** (check=false · **never claimed**) |
| hold/mom micro-grid | **not run** |
| full catalog grid | **not run** |
| thresh sensitivity | **3 coarse pts only** (×0.9 / ×1.0 / ×1.1 on PIT trailing median) |
| thresh grid mass | **false** |
| repo short contrast | **yes** (local `jsda_repo_rates`; overnight; 0 gaps on required) |
| gate worst daily_path_DD | **−11.4%** (`w2023_2025`) |
| sticky worst daily_path_DD | **−14.4%** (`w2017_2019`) |
| sticky stance | **STABLE_RESEARCH_ONLY** (not re-promoted) |
| 3-default pins | **untouched** |
| Mass / READY / Phase7 / paper | NO-GO / 未宣言 / OFF / UNARMED |

Deepen only. Gate is **not** uniformly safer than sticky. Better-in-some-windows ≠ main candidate.

---

## Base daily path (tx 10 bp · thresh×1.0 · W100/W102 method)

| logic | window | n_days | daily_path_DD | dd_dur | recov | recovered | total_ret_net | active_frac | gate_on_frac | stance |
|-------|--------|-------:|--------------:|-------:|------:|:---------:|--------------:|------------:|-------------:|--------|
| gate | w2017_2019 | 272 | −0.033574 | 10 | — | False | 0.088918 | 0.369 | 0.476 | RESEARCH_ONLY |
| gate | w2020_2022 | 193 | −0.027298 | 24 | 1 | True | 0.186252 | 0.427 | 0.513 | RESEARCH_ONLY |
| gate | w2023_2025 | 273 | −0.114227 | 68 | 52 | True | 0.128101 | **0.625** | **0.577** | RESEARCH_ONLY |
| sticky | w2017_2019 | 272 | −0.143741 | 85 | — | False | 0.034975 | 0.926 | — | STABLE_RESEARCH_ONLY |
| sticky | w2020_2022 | 193 | −0.037971 | 14 | 1 | True | 0.201923 | 0.948 | — | STABLE_RESEARCH_ONLY |
| sticky | w2023_2025 | 273 | −0.108415 | 17 | 52 | True | 0.081073 | 0.926 | — | STABLE_RESEARCH_ONLY |

Numbers **match W100/W102**. Gate shallower in 2017–19; **slightly worse** than sticky in 2023–25 (−11.4% vs −10.8%). Local mirrors ≠ CF SoT.

---

## Gate on/off interval returns & daily DD

Sticky CS L-S daily nets are **partitioned** by the prior-day dispersion gate (ON vs OFF). Conditional books are flat when the mask excludes the day — disclosure of interval character, **not** a continuous alternate strategy.

| window | sticky\|ON net | sticky\|ON DD | sticky\|OFF net | sticky\|OFF DD | gate book DD | note |
|--------|---------------:|--------------:|----------------:|---------------:|-------------:|------|
| w2017_2019 | +0.0926 | −0.0497 | **−0.0528** | **−0.1109** | −0.0336 | OFF-regime sticky bled; gate sat out → edge |
| w2020_2022 | +0.1442 | −0.0383 | +0.0505 | −0.0209 | −0.0273 | ON carries most of the net |
| w2023_2025 | +0.0722 | −0.1081 | +0.0083 | −0.1414 | **−0.1142** | ON carries the −11% episode; OFF still ugly |

### Contiguous interval summaries (sticky nets inside gate runs)

| window | on n_iv | on mean_cum | on worst_cum | on worst_iv_DD | off n_iv | off mean_cum | off worst_cum |
|--------|--------:|------------:|-------------:|---------------:|---------:|-------------:|--------------:|
| w2017_2019 | 25 | +0.0036 | −0.0173 | −0.0480 | 25 | −0.0020 | −0.0640 |
| w2020_2022 | 18 | +0.0078 | −0.0144 | −0.0913 | 18 | +0.0028 | −0.0069 |
| w2023_2025 | 32 | +0.0025 | −0.0552 | −0.1165 | 32 | +0.0006 | −0.0890 |

2017–19 quality story = **avoiding negative OFF intervals**. 2023–25 risk lives **inside ON intervals** (worst on-interval DD ≈ −11.7%). Do **not** read this as uniformly safer.

Artifacts: `deepen_gate_onoff_returns.json` · `deepen_gate_intervals.json`.

---

## Why w2023_2025 activity is higher

| window | disp_mean | disp_median | disp_p90 | excess_mean vs thresh | frac_disp≥thresh | gate_on_frac | active_frac | max_on_run |
|--------|----------:|------------:|---------:|----------------------:|-----------------:|-------------:|------------:|-----------:|
| w2017_2019 | 0.0299 | 0.0260 | 0.0441 | +0.0029 | 0.435 | 0.476 | 0.369 | 16 |
| w2020_2022 | 0.0344 | 0.0301 | 0.0457 | +0.0056 | 0.486 | 0.513 | 0.427 | 16 |
| w2023_2025 | **0.0397** | 0.0276 | **0.0570** | **+0.0124** | **0.543** | **0.577** | **0.625** | **19** |

**Driver:** CS mom-std spends more calendar time at/above its PIT trailing median (higher `frac_excess_pos` / `gate_on_frac`), with a fatter right tail (`disp_p90`) and longer max on-runs — **not** a hold/mom retune. Elevated dispersion keeps the gate open → book looks more like sticky → inherits sticky-like path DD. **Not uniformly safer.**

Artifact: `deepen_activity_explain_w2023_2025.json` · `deepen_activity_drivers.json`.

---

## Coarse thresh sensitivity (3 points only · no grid mass)

`on = disp >= trailing_median × thresh_mult`. Mult ∈ {**0.9, 1.0, 1.1**}. Catalog hold=10 mom=5 **frozen**. Complementary parallel deepen also probed ×0.85/1.15 — same conclusion.

| tag | mult | window | daily_path_DD | total_ret_net | active_frac | gate_on_frac |
|-----|-----:|--------|--------------:|--------------:|------------:|-------------:|
| looser_0p9 | 0.9 | w2017_2019 | −0.045608 | 0.085926 | 0.483 | 0.597 |
| looser_0p9 | 0.9 | w2020_2022 | −0.030168 | 0.176333 | 0.583 | 0.648 |
| looser_0p9 | 0.9 | w2023_2025 | **−0.114227** | 0.152010 | 0.699 | 0.682 |
| base_1p0 | 1.0 | w2017_2019 | −0.033574 | 0.088918 | 0.369 | 0.476 |
| base_1p0 | 1.0 | w2020_2022 | −0.027298 | 0.186252 | 0.427 | 0.513 |
| base_1p0 | 1.0 | w2023_2025 | **−0.114227** | 0.128101 | 0.625 | 0.577 |
| tighter_1p1 | 1.1 | w2017_2019 | −0.023261 | 0.111650 | 0.332 | 0.403 |
| tighter_1p1 | 1.1 | w2020_2022 | −0.027298 | 0.132887 | 0.312 | 0.440 |
| tighter_1p1 | 1.1 | w2023_2025 | **−0.114227** | 0.116983 | 0.515 | 0.478 |
| sticky_ref | — | w2017_2019 | −0.143741 | 0.034975 | 0.926 | — |
| sticky_ref | — | w2020_2022 | −0.037971 | 0.201923 | 0.948 | — |
| sticky_ref | — | w2023_2025 | −0.108415 | 0.081073 | 0.926 | — |

**Read:** looser → more activity (as expected). Tighter → less activity and better 2017–19 DD, but **2023–25 worst path stays −11.4%** across all three mults (episode sits inside high-dispersion days). No mult makes the gate uniformly safer than sticky. **Not a retune / not pick-best.**

Artifact: `deepen_thresh_sensitivity.json`.

---

## Repo-linked short contrast (with / without)

Parallel Track B landed: date-matched `jsda_tokyo_repo_rates` (prefer `overnight/翌日物/T+0`) + mid spread 50 bp on short_frac=0.5. Gaps **disclosed / not invent-filled**. Contrast only — **not** cost ranking.

| logic | window | tx-only DD | fixed mid DD | repo+spread DD | tx-only net | repo net | n_gaps |
|-------|--------|-----------:|-------------:|---------------:|------------:|---------:|-------:|
| gate | w2017_2019 | −0.033574 | −0.033673 | −0.033656 | 0.088918 | 0.088012 | 0 |
| gate | w2020_2022 | −0.027298 | −0.027437 | −0.027413 | 0.186252 | 0.185429 | 0 |
| gate | w2023_2025 | −0.114227 | −0.114662 | −0.114570 | 0.128101 | 0.125975 | 0 |
| sticky | w2017_2019 | −0.143741 | −0.144485 | −0.144363 | 0.034975 | 0.032790 | 0 |
| sticky | w2020_2022 | −0.037971 | −0.038109 | −0.038087 | 0.201923 | 0.200072 | 0 |
| sticky | w2023_2025 | −0.108415 | −0.108570 | −0.108529 | 0.081073 | 0.077947 | 0 |

Repo overlay ≈ fixed mid (repo ≈ −9 bp annual in these windows → slightly cheaper than pure 50 bp). **Does not reorder** gate vs sticky. Gate worst remains **−11.4% / −11.46% / −11.46%** (tx / fixed / repo). **promote_as_main=false · go=false.**

Artifact: `deepen_repo_short_contrast.json` · `deepen_repo_series_meta.json`.

---

## Headline (research-only · not GO)

- Gate on/off split confirms W102: **2017–19 edge = sitting out negative OFF sticky days**; **2023–25 risk = ON-regime path**.
- Higher 2023–25 activity is **dispersion-regime persistence**, not a param retune.
- Coarse thresh ×0.9/1.0/1.1 does **not** clear the −11.4% 2023–25 worst path; no uniformly-safer claim.
- Repo-linked short (Track B) vs placeholder: disclosure only; no ranking-by-cost.
- **promote_as_main=false · go=false.** Sticky stays **STABLE_RESEARCH_ONLY**. Gate stays **RESEARCH_ONLY**.

## Non-claims

- No READY / Mass / GO / live / pin retune / hold-mom grid / thresh grid mass.
- Never claim uniformly safer. Better-in-some-windows ≠ main.
- Local mirrors ≠ CF SoT. Period-net DD=0 **must not** be read as riskless.

GLM implementer only. Grok did not implement.
