# W106 / w0820c Track C — funding/surprise L/S min variants (not a kill)

**Wave:** W106 / `w0820c` · Track C  
**Parents:** `event_funding_stress_skip` · `surprise_xs_rank_hold`  
**Variants (3, not a farm):** `event_funding_easy_short` · `event_funding_stress_ls` · `surprise_xs_rank_flip`  
**Scope:** sign flip / short side · conditional L/S (opposite only under stress) · occupancy must not collapse · daily_path_DD  
**Not run:** threshold / hold / mom grid farm · extra `xs_cs_dispersion_gate` grid · pick-best cost  
**Data path:** `local_real_mirrors` + `ingestion.sqlite` (same W99/W104/W105 honest shards)  
**Method:** daily MTM after cost — `scripts/run_w104_new_hyps_daily_dd.py` + `scripts/run_w106_funding_surprise_ls.py`  
**Recipe:** `scripts/run_w106_funding_surprise_ls.py`  
**Artifacts:** [`.glm-logs/w0820c_w106_otc10_ls_hyps/`](../../.glm-logs/w0820c_w106_otc10_ls_hyps/) · `ls_daily_dd_table.json` · `ls_side_preference_table.json` · `w106_c_summary.json`  
**Parent cited (not remapped):** [`w0820b_w105_funding_surprise_deepdive_20260820.md`](w0820b_w105_funding_surprise_deepdive_20260820.md)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

**Do not conclude “sign flipped so kill”.** Window sign-flip of the parents is a **side table**, not a discard. Three min variants were measured. Occupancy did **not** collapse. Survivors research-only.

| field | value |
|-------|-------|
| n_variants | **3** (at most 2–3; not a grid farm) |
| n_daily_path_DD complete | **3 / 3** |
| occupancy collapsed | **false** |
| sign_flip_is_not_a_kill | **true** |
| did_not_kill_funding_surprise | **true** |
| promote_as_main | **false** |
| go / go_eligible | **false** |
| hold/mom micro-grid | **not run** |
| threshold grid | **not run** |
| extra dispersion_gate grid | **not run** |
| ffill / invent | **false** |
| `event_funding_easy_short` worst daily_path_DD | **−9.1%** (`w2023_2025`) |
| `event_funding_stress_ls` worst daily_path_DD | **−18.6%** (`w2017_2019`, unrecovered) |
| `surprise_xs_rank_flip` worst daily_path_DD | **−11.9%** (`w2017_2019`, unrecovered) |
| parent skip worst (cited) | **−11.4%** (`w2017_2019`) |
| parent surprise worst (cited) | **−8.7%** (`w2023_2025`) |
| stance | **RESEARCH_ONLY** |
| 3-default pins | **untouched** |
| Mass / READY / Phase7 / paper | NO-GO / 未宣言 / OFF / UNARMED |

Complete measurement **≠** GO. Sign-flip of a window is **not** a kill of funding or surprise.

---

## Variants (min-impl, not a farm)

| logic_id | parent | kind | occupancy vs parent |
|----------|--------|------|---------------------|
| `event_funding_easy_short` | `event_funding_stress_skip` | sign-flip / short side | **same** (easy-funding entries only; −surprise) |
| `event_funding_stress_ls` | `event_funding_stress_skip` | conditional L/S | **expanded** (easy = original; stress = opposite) |
| `surprise_xs_rank_flip` | `surprise_xs_rank_hold` | sign-flip / short side | **same** ranked days (long low-surprise / short high) |

Missing overnight still skip (no ffill). `<2` surprise names still flat (no invent). No threshold/hold grid.

---

## Occupancy (must not collapse)

### Funding book

| window | n_events | skip entered | easy_short entered | stress_ls entered (easy+stress) | skip/easy active | L/S active |
|--------|---------:|-------------:|-------------------:|--------------------------------:|-----------------:|-----------:|
| w2017_2019 | 57 | **26** | **26** | **50** (26+24) | 15.5% | 24.7% |
| w2020_2022 | 39 | **6** | **6** | **38** (6+32) | 5.2% | 25.5% |
| w2023_2025 | 52 | **36** | **36** | **48** (36+12) | 16.9% | 22.8% |

easy_short occupancy **=** skip. stress_ls occupancy **>** skip (2020–22 6→38; 2025-q4 0→12 stress entries). Occupancy did **not** collapse.

### Surprise rank book

| window | n_days | parent ranked | flip ranked | ranked_frac |
|--------|-------:|--------------:|------------:|------------:|
| w2017_2019 | 272 | **51** | **51** | 18.8% |
| w2020_2022 | 193 | **41** | **41** | 21.4% |
| w2023_2025 | 273 | **49** | **49** | 18.0% |

Flip occupancy **=** parent. Not filled.

---

## Window side table (which window prefers which side)

Required: **daily_path_DD** · **total_ret_net** · occupancy. Base tx **10 bp**. Preferred = highest `total_ret_net` in that window (research table, **not** a pass / **not** pick-best GO).

### Funding (`event_funding_stress_skip` family)

| window | skip net (orig) | skip DD | easy_short net (flip) | easy_short DD | stress_ls net (cond) | stress_ls DD | **preferred side** |
|--------|----------------:|--------:|----------------------:|--------------:|---------------------:|-------------:|--------------------|
| w2017_2019 | **+0.0099** | −11.4% | −0.0195 | −8.3% | −0.1036 | −18.6% | **original skip** |
| w2020_2022 | −0.0422 | −7.0% | **+0.0410** | −2.6% | −0.1170 | −17.4% | **short side (easy_short)** |
| w2023_2025 | +0.0894 | −4.8% | −0.0913 | −9.1% | **+0.2217** | −4.8% | **conditional L/S** |

2020–22 (the parent’s negative window) prefers the **short side** of the same easy-funding book. 2017–19 prefers original. 2023–25 prefers staying in under stress (conditional L/S), driven by the 2025-q4 stress book that skip emptied (0/12 → 12/12). That is the opposite of “sign flipped so kill”.

### Surprise (`surprise_xs_rank_hold` family)

| window | orig net | orig DD | flip net | flip DD | **preferred side** |
|--------|---------:|--------:|---------:|--------:|--------------------|
| w2017_2019 | **+0.1028** | −2.7% | −0.1011 | −11.9% | **original** (long high-surprise) |
| w2020_2022 | **−0.0024** | −6.2% | −0.0044 | −4.1% | **original** (both near-zero; orig less bad) |
| w2023_2025 | −0.0262 | −8.7% | **+0.0155** | −7.2% | **flip** (long low-surprise) |

2023–25 (the parent’s worst path) prefers the **flipped** rank book. 2017–19 prefers original. Window sign-flip is the story; it is **not** a kill.

---

## daily_path_DD (variants)

| logic | window | n_days | daily_path_DD | total_ret_net | sign | n_entered / n_ranked | complete |
|-------|--------|-------:|--------------:|--------------:|-----:|---------------------:|:--------:|
| `event_funding_easy_short` | w2017_2019 | 272 | −0.083159 | −0.019455 | − | 26 | True |
| `event_funding_easy_short` | w2020_2022 | 193 | −0.025584 | +0.041033 | + | 6 | True |
| `event_funding_easy_short` | w2023_2025 | 273 | −0.091339 | −0.091339 | − | 36 | True |
| `event_funding_stress_ls` | w2017_2019 | 272 | −0.185968 | −0.103644 | − | 50 | True |
| `event_funding_stress_ls` | w2020_2022 | 193 | −0.174420 | −0.117009 | − | 38 | True |
| `event_funding_stress_ls` | w2023_2025 | 273 | −0.048347 | +0.221736 | + | 48 | True |
| `surprise_xs_rank_flip` | w2017_2019 | 272 | −0.119226 | −0.101100 | − | 51 ranked | True |
| `surprise_xs_rank_flip` | w2020_2022 | 193 | −0.040790 | −0.004445 | − | 41 ranked | True |
| `surprise_xs_rank_flip` | w2023_2025 | 273 | −0.072155 | +0.015536 | + | 49 ranked | True |

Conditional L/S worst path **−18.6%** (2017–19) is **worse** than skip’s **−11.4%** — staying in under stress is not free. 2023–25 L/S net is a small-universe research path (15 codes, two shards) — **not** a pass.

---

## Explicit non-declarations

- Sign-flip of a window **is not** a kill of `event_funding_stress_skip` / `surprise_xs_rank_hold`
- Preferred-side table **is not** pick-best / **not** GO
- Survivors **not** main / **not** GO
- No threshold / hold farm
- Family append of these logics is **recognition, not promotion**
- Grok did **not** implement

GLM implementer only. Grok did not implement.
