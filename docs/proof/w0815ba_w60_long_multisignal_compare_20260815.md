# W60 / w0815ba — Long-window multi-signal compare (S1/S2/S3) via R2

**Wave:** W60 / w0815ba · long multi-signal + bridge expand  
**Label:** **小サンプル / 研究用・未宣言**  
**Cost label:** **仮定に依存・研究用・運用GOではない**  
**Mass / Phase7:** **NO-GO / OFF**  
**READY:** **not** declared  
**Order execution:** **none**  
**densify / tip collect as primary:** **none**  
**Invent COMPLETE / Dataset COMPLETE 22:** **forbidden** (held **21**)  
**Significance / edge claim:** **none**  
**Operational GO:** **none**

**Primary:** Re-run W58 S1/S2/S3 multi-signal compare on the **same long R2 window** as W59 S1 (`history_source="r2"`, 50 days × 30 codes) and place results next to tip-20d (W58) for research-only delta reading.

**Job:** `w0815ba-g1-long-multisignal`  
**Logs:** [`.glm-logs/w0815ba_w60_long_multisignal/`](../../.glm-logs/w0815ba_w60_long_multisignal/)  
**R2:** `research/single_shot/job=w0815ba-g1-long-multisignal/batch_summary.json`

---

## Verdict

| gate | result |
|------|--------|
| Long multi-signal `history_source=r2` | **PASS** · n_days=**50** · n_codes=**30** |
| S1/S2/S3 compare table | **written** (mean/median R · non_null · 10bp net) |
| tip-20d vs long-50d delta | **documented** (this file) |
| Look-ahead ban | **held** |
| Mass / READY / densify | **OFF / not declared / none** |

**Honesty:** Research metrics only. Short tip-window separation does **not** automatically transfer to the long R2 window. No significance, edge, or operational GO.

---

## Window / universe

| field | value |
|-------|------:|
| **period** | `2024-09-02` … `2024-12-18` |
| **n_days** | **50** |
| **n_codes** | **30** (same W57 list as W58/W59) |
| **history_source** | `r2` |
| **tip_plane** | `R2_history` |
| **datasets** | bars · topix · calendar · fins_summary · markets_margin_interest (archive sample; sparse in window) |
| **local SoT** | **false** (disposable mirrors of live R2 GET) |

---

## Signal definitions (same as W58)

| id | formula |
|----|---------|
| **S1** `c21_topix_relative_sign` | `sign(topix_relative_1d)` if trading day (volume gate off) |
| **S2** `c21_volume_change_sign` | `sign(volume_change_1d)` if trading day and `|volume_change| ≥ 0.10` |
| **S3** `c21_topix_rel_disclosure_filter` | `sign(topix_relative_1d)` if trading day and `disclosure_flag_fins==1` |

All legs **approved** · signal status **candidate** · `candidate_only=False` · **not READY**.

---

## Long-window compare (50d × 30 · R2)

**Label: 小サンプル / 研究用・未宣言**

| signal | non_null | rate | +1 / −1 | mean R +1 | median R +1 | mean R −1 | median R −1 | gross signed mean | net 10bp one-way |
|--------|---------:|-----:|--------:|----------:|------------:|----------:|------------:|------------------:|-----------------:|
| S1 topix_rel | **1500** | **1.000** | 767 / 733 | **−0.000182** | −0.001168 | **−0.000245** | −0.001977 | **+0.000027** | **−0.000973** |
| S2 volume_sign | **70** | **0.047** | 22 / 48 | −0.003813 | −0.002322 | −0.001655 | −0.003441 | **−0.000275** | **−0.001275** |
| S3 topix+disc | **954** | **0.636** | 455 / 499 | **+0.000369** | −0.000185 | **−0.000977** | −0.002908 | **+0.000688** | **−0.000312** |

Shared overall mean/median R ≈ **−0.000213** / **−0.001440** · null_return_rate **0.02**.

---

## tip-20d (W58) vs long-50d (this wave)

| signal | tip-20d non_null rate | long-50d non_null rate | tip mean R +1 | long mean R +1 | tip mean R −1 | long mean R −1 | tip gross signed | long gross signed |
|--------|----------------------:|-----------------------:|--------------:|---------------:|--------------:|---------------:|-----------------:|------------------:|
| S1 | 1.000 | 1.000 | **+0.00823** | **−0.000182** | **−0.00202** | **−0.000245** | **+0.00528** | **~0** |
| S2 | 0.752 | **0.047** | +0.00165 | −0.00381 | +0.00298 | −0.00165 | **−0.00078** | **−0.00028** |
| S3 | 0.295 | **0.636** | +0.00718 | +0.00037 | +0.00055 | −0.00098 | **+0.00345** | **+0.00069** |

### Research read (not significance)

1. **S1 sign separation seen on tip-20d collapses on long-50d** — both signs near zero mean next-day R (reconfirms W59 S1-only finding).  
2. **S2 volume 10% gate is far rarer on the long window** (non_null ~5% vs ~75% tip) — tip densify window may over-sample active volume days; gross signed remains non-positive.  
3. **S3 disclosure filter is denser on long history** (fins R2 JSONL; non_null ~64% vs ~30% tip) but sign means remain small; gross signed slightly positive before 10bp cost, **negative after** one-way cost.  
4. **Do not promote tip-20d results to long-window claims.** All figures remain **研究用・未宣言**.

---

## Freeze

| switch | value |
|--------|------:|
| Mass | **NO-GO** |
| Phase7 | **OFF** |
| READY | **not declared** |
| densify | **false** |
| order_execution | **false** |
| significance_claimed | **false** |
| edge_claimed | **false** |
| operational_go | **false** |
