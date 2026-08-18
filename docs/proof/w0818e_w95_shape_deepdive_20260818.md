# W95 / w0818e — track A: skew / CM-term / Δ deep-dive

**Wave status:** **COMPLETE** (track A) — coarse sens + shape×CS combos + windows · **WEAK → not main candidate**  
**Wave:** W95 / `w0818e` · 2026-08-18  
**Driver:** [`scripts/run_w95_shape_deepdive.py`](../../scripts/run_w95_shape_deepdive.py)  
**Logs:** [`.glm-logs/w0818e_w95_shape_factor_decomp/`](../../.glm-logs/w0818e_w95_shape_factor_decomp/)  
**Series:** `research-options-225-vol-series/v1.2` (skew 2452 / cm_term 2452 / Δ 2451)  
**Prior:** W94 windows already showed shape ≠ level (`w94-skew-20260818T130829Z`)

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| operational GO | **未宣言** |
| continuous paper | **UNARMED** |
| 3 defaults retune | **forbidden / not done** |
| grid mass | **no** (2–4 pts/series only) |
| smile ≡ BaseVol level | **forbidden / not claimed** |
| **promote as main candidate** | **false** · **WEAK** |

---

## 1. Chosen coarse sens / lookback points (not a grid)

Fullspan anchors (v1.2): skew p10/p50/p90 ≈ 2.54 / 4.35 / 6.99 · cm_term ≈ −1.52 / −0.24 / 1.83 · Δ ≈ −1.78 / −0.14 / 2.00.

| logic | tag | high | low | why |
|-------|-----|-----:|----:|-----|
| `opt225_skew_abs_level` | default | 3.0 | 0.5 | W94 pin; hi below p50 |
| `opt225_skew_abs_level` | looser | 2.0 | 1.0 | near-p10 high-band; more act |
| `opt225_skew_abs_level` | tighter | 4.5 | 0.0 | hi≈p50; only elevated reverse |
| `opt225_cm_term_abs_level` | default | 2.0 | −1.0 | W94 pin; hi≈p90 / lo≈p10 |
| `opt225_cm_term_abs_level` | narrow | 1.0 | −0.5 | more mid→flat |
| `opt225_cm_term_abs_level` | wide | 3.0 | −2.0 | extreme-only stress |
| `opt225_basevol_delta_abs` | default | 1.0 | −1.0 | W94 pin; ≈0.5σ daily Δ |
| `opt225_basevol_delta_abs` | tight | 0.5 | −0.5 | higher activation |
| `opt225_basevol_delta_abs` | wide | 1.5 | −1.5 | near p10/p90 moves |

**Lookback axis:** CS mom ∈ {5, 3} at default hi/lo (`bind_mom3`). **Not** a frozen-default retune.

Artifact: [`chosen_points.md`](../../.glm-logs/w0818e_w95_shape_factor_decomp/chosen_points.md)

---

## 2. Shape×CS combo logics (thesis / signal / position)

### `high_skew_reverse_cs` → `opt225_skew_abs_level`

- **thesis:** Elevated 95% put skew = crash-premium / risk-off → reverse CS mom; calm skew → keep CS.
- **signal:** `put_iv(~0.95*S) − atm_mid`; hi≥3.0 / lo≤0.5; CS rank mom L-S (mom=5).
- **position:** high → −CS; low → +CS; mid → flat; hold=10 sticky.

### `steep_cm_term_keep_cs` → `opt225_cm_term_abs_level`

- **thesis:** Steep CM term (near ≪ next → cm_term low/neg) = risk-on / contango-like → **keep** CS; front-rich (high) → reverse.
- **signal:** `near_atm − next_atm` (min_dte≥6); hi≥2.0 / lo≤−1.0; CS mom=5.
- **position:** steep/low → +CS; front-rich/high → −CS; mid → flat; hold=10 sticky.

Artifact: [`combo_logics.md`](../../.glm-logs/w0818e_w95_shape_factor_decomp/combo_logics.md)

### Combo window table

| window | combo | mean_net | t | act | sign | surv |
|--------|-------|---------:|--:|----:|-----:|:----:|
| w2017_2019 | high_skew_reverse | 0.005043 | 0.6857 | 0.0565 | −1 | T |
| w2017_2019 | steep_term_keep | 0.004438 | 18.5813† | 0.0274 | +1 | T |
| w2020_2022 | high_skew_reverse | 0.010885 | — | 0.0622 | −1 | T |
| w2020_2022 | steep_term_keep | 0.009068 | — | 0.0332 | +1 | T |
| w2023_2025 | high_skew_reverse | 0.005845 | 1.4256 | 0.0562 | −1 | T |
| w2023_2025 | steep_term_keep | 0.006024 | 0.8916 | 0.0356 | **−1** | T |

† n=2 window giant-t = low-variance artifact class (W95 gate elsewhere); **not** an edge claim.  
**Sign flip** on steep_term_keep (+1 → +1 → −1) across windows → unstable / weak.

---

## 3. Window tables (default sens + level compare + mom3 lookback)

Honest shards: w2017_2019 = y2017_q4+y2019_full · w2020_2022 = y2021_full · w2023_2025 = y2023_full+y2025_q4.

### Default sens (mom=5) + BaseVol level compare

| window | logic | mean_net | t | act | sign | surv |
|--------|-------|---------:|--:|----:|-----:|:----:|
| w2017_2019 | `opt225_basevol_abs_level` | 0.007213 | 16.2881† | 0.0207 | +1 | T |
| w2017_2019 | `opt225_skew_abs_level` | 0.005043 | 0.6857 | 0.0565 | −1 | T |
| w2017_2019 | `opt225_cm_term_abs_level` | 0.004438 | 18.5813† | 0.0274 | +1 | T |
| w2017_2019 | `opt225_basevol_delta_abs` | 0.003102 | 0.4532 | 0.0326 | −1 | T |
| w2020_2022 | `opt225_basevol_abs_level` | — | — | **0.0000** | — | **F** |
| w2020_2022 | `opt225_skew_abs_level` | 0.010885 | — | 0.0622 | −1 | T |
| w2020_2022 | `opt225_cm_term_abs_level` | 0.009068 | — | 0.0332 | +1 | T |
| w2020_2022 | `opt225_basevol_delta_abs` | 0.005073 | — | 0.0462 | +1 | T |
| w2023_2025 | `opt225_basevol_abs_level` | 0.025480 | — | 0.0201 | −1 | T |
| w2023_2025 | `opt225_skew_abs_level` | 0.005845 | 1.4256 | 0.0562 | −1 | T |
| w2023_2025 | `opt225_cm_term_abs_level` | 0.006024 | 0.8916 | 0.0356 | −1 | T |
| w2023_2025 | `opt225_basevol_delta_abs` | 0.015655 | 1.6523 | 0.0415 | −1 | T |

### Lookback bind mom=3 (default thresholds)

| window | logic | mean_net | t | act | sign | surv |
|--------|-------|---------:|--:|----:|-----:|:----:|
| w2017_2019 | skew | 0.000955 | 0.4174 | 0.0575 | −1 | T |
| w2017_2019 | cm_term | 0.001731 | 1.0163 | 0.0269 | −1 | T |
| w2017_2019 | ΔBaseVol | 0.003900 | 0.5155 | 0.0318 | −1 | T |
| w2020_2022 | skew | 0.015184 | — | 0.0622 | −1 | T |
| w2020_2022 | cm_term | 0.016737 | — | 0.0384 | +1 | T |
| w2020_2022 | ΔBaseVol | 0.007912 | — | 0.0466 | +1 | T |
| w2023_2025 | skew | 0.013547 | 2.4163 | 0.0562 | −1 | T |
| w2023_2025 | cm_term | 0.010267 | 5.8430 | 0.0338 | +1 | T |
| w2023_2025 | ΔBaseVol | 0.024085 | 16.3744† | 0.0407 | −1 | T |

Full sens grid (3 threshold tags × 3 series + binds + combos):  
[`shape_window_table.md`](../../.glm-logs/w0818e_w95_shape_factor_decomp/shape_window_table.md) ·  
[`shape_sens_bind_table.md`](../../.glm-logs/w0818e_w95_shape_factor_decomp/shape_sens_bind_table.md)

**Sens takeaways (coarse only):**
- Skew sign stable (−1) across windows / threshold tags; nets thin (~0.5–1.1%).
- CM-term sign **flips** (esp. 2023 default −1 vs earlier +1; mom3 stays +1 in 2023) → mapping unstable.
- ΔBaseVol sign flips 2017(−) → 2020(+) → 2023(−); wide tag dies in 2017 (near-zero).
- Activation stays ~3–6% for shape vs ~0–2% for BaseVol level.

---

## 4. `note_2020_22_vs_level`

See [`note_2020_22_vs_level.md`](../../.glm-logs/w0818e_w95_shape_factor_decomp/note_2020_22_vs_level.md).

| item | value |
|------|-------|
| BaseVol abs level | **dead** (act=0 / reject) |
| skew / cm_term / Δ | **alive** (act≈0.03–0.06) |
| divergence | **True** |
| claim smile ≡ level | **forbidden** |

W94 already showed this; W95 coarse sens **confirms** — shape/change is not a restate of level regime.

---

## 5. Explicit stance — WEAK → not main candidate

| item | value |
|------|-------|
| promote_as_main_candidate | **false** |
| strength | `weak_to_moderate_research` |
| reason | Survive some windows but signs flip / nets thin / n=2 t artifacts; research-only |
| 3 defaults | untouched |

**Do not** select human main candidate from this track. **Do not** arm Mass / READY / GO / continuous paper / live.

---

## Artifacts

| file | role |
|------|------|
| `chosen_points.md` | coarse sens / lookback points + why |
| `combo_logics.md` | thesis / signal / position |
| `shape_window_table.md` | sens + lookback windows |
| `shape_combo_window_table.md` | combo windows |
| `note_2020_22_vs_level.md` | 2020–22 vs level note |
| `shape_deepdive_SUMMARY.md` | track A summary |

Sister track B (rate/flow/fund decomp): [`w0818e_w95_shape_factor_decomp_20260818.md`](w0818e_w95_shape_factor_decomp_20260818.md)
