# W61 / w0815bb — Multi-period S1/S2/S3 compare (R2)

**Wave:** W61 / w0815bb  
**Label:** **小サンプル / 研究用・未宣言**  
**Mass / Phase7:** **NO-GO / OFF**  
**READY:** **not** declared  
**Significance / edge / operational GO:** **none**  
**history_source:** `r2`  
**Codes:** 30 (same W57/W58/W60 list)  
**Logs:** [`.glm-logs/w0815bb_w61_multiperiod/`](../../.glm-logs/w0815bb_w61_multiperiod/)

## Purpose

Re-run fixed S1/S2/S3 on **multiple non-overlapping** historical windows so that tip-20d / single-50d findings are not window-selection artifacts. Not operational GO.

## Windows (non-overlapping)

| period_id | period | n_days eval | status |
|-----------|--------|------------:|--------|
| **w2022q4** | 2022-09-01 … 2022-12-29 | **40** | ok |
| **w2023q4** | 2023-09-01 … 2023-12-29 | **40** | ok |
| **w2024q4** | 2024-09-02 … 2024-12-18 | **50** | ok (W60 baseline reconfirm) |
| **w2025q1** | 2025-01-06 … 2025-04-30 | **25** | ok (shorter inventory span) |

## Cross-period compare (fixed definitions)

**All figures: 小サンプル / 研究用・未宣言 — no significance claim.**

### S1 `c21_topix_relative_sign`

| period | non_null | mean R +1 | mean R −1 | gross signed | net 10bp |
|--------|---------:|----------:|----------:|-------------:|---------:|
| w2022q4 | 1.000 | −0.00010 | −0.00105 | +0.00043 | −0.00057 |
| w2023q4 | 1.000 | **+0.00243** | **−0.00141** | **+0.00188** | **+0.00088** |
| w2024q4 | 1.000 | −0.00018 | −0.00024 | ~0 | −0.00097 |
| w2025q1 | 1.000 | −0.02026 | −0.01888 | −0.00032 | −0.00132 |

### S2 `c21_volume_change_sign` (|Δvol|≥0.10)

| period | non_null | mean R +1 | mean R −1 | gross signed | net 10bp |
|--------|---------:|----------:|----------:|-------------:|---------:|
| w2022q4 | **0.000** | — | — | — | — |
| w2023q4 | **0.000** | — | — | — | — |
| w2024q4 | 0.047 | −0.00381 | −0.00165 | −0.00028 | −0.00128 |
| w2025q1 | 0.636 | −0.03039 | — | −0.03039 | −0.03139 |

### S3 `c21_topix_rel_disclosure_filter`

| period | non_null | mean R +1 | mean R −1 | gross signed | net 10bp |
|--------|---------:|----------:|----------:|-------------:|---------:|
| w2022q4 | 0.950 | −0.00063 | −0.00122 | +0.00021 | −0.00079 |
| w2023q4 | 0.958 | +0.00248 | −0.00174 | +0.00209 | +0.00109 |
| w2024q4 | 0.636 | +0.00037 | −0.00098 | +0.00069 | −0.00031 |
| w2025q1 | 1.000 | −0.02026 | −0.01888 | −0.00032 | −0.00132 |

## tip-20d (W58) reference (not same period)

| signal | tip non_null | tip mean R +1 | tip mean R −1 | tip gross |
|--------|-------------:|--------------:|--------------:|----------:|
| S1 | 1.000 | +0.00823 | −0.00202 | +0.00528 |
| S2 | 0.752 | +0.00165 | +0.00298 | −0.00078 |
| S3 | 0.295 | +0.00718 | +0.00055 | +0.00345 |

## Research read (未宣言)

1. **S1 tip separation is not stable across long R2 windows.** Only **w2023q4** shows a mild same-direction separation; **w2024q4** near zero; **w2025q1** both signs deeply negative (regime drag, not sign edge).  
2. **S2 10% volume gate is highly period-dependent** (0% fire in 2022/2023 long windows vs tip 75% and 2025q1 64%). Tip fire rate must not be generalized.  
3. **S3 tracks S1 sign pattern** when disclosures fire; denser on long history than tip, still **not** a GO claim (often fails after 10bp).  
4. **Window choice matters** — single 50d slice is insufficient for research conclusions.

## Coverage gaps (honest)

See [`coverage_inventory.json`](../../.glm-logs/w0815bb_w61_multiperiod/coverage_inventory.json) and [`w0815bb_w61_coverage_inventory_20260815.md`](w0815bb_w61_coverage_inventory_20260815.md).

- topix JSONL missing 2024–2025 shards → used **archive**  
- calendar JSONL tip-only → used **archive PIT repair**  
- margin/short JSONL year gaps → **empty_allowed** this wave (not invented)  
- w2025q1 bars span ends ~2025-04-04 in filtered mirror → n_days=25  

## Freeze

Mass **NO-GO** · Phase7 **OFF** · READY **not declared** · densify **false** · look-ahead **held**
