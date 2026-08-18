# W98 / w0819a Track C — `xs_rank_ls_sticky` deep-dive

**Wave:** W98 / `w0819a` · Track C  
**Logic:** `xs_rank_ls_sticky`  
**CF job:** `w98-sticky-20260818T223015Z` · mode `r2_panels` · status `ok`  
**Gates:** multi-year + cost + PIT + sign + low-var  
**Artifacts:** [`.glm-logs/w0819a_w98_otc_master_xs/sticky_deep_table.md`](../../.glm-logs/w0819a_w98_otc_master_xs/sticky_deep_table.md)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Explicit stance (frozen)

| field | value |
|-------|-------|
| stance | **STABLE_RESEARCH_ONLY** |
| relatively_better | **True** (recorded) |
| promote_as_main | **False** |
| go_eligible | **False** |
| research_only | **True** |
| hold/mom micro-grid | **not run** |
| 3-default pin retune | **not done** (`pins_untouched=True`) |

**Policy:** relatively better may be noted; **promote/GO remain false**. No Mass / READY / live.

---

## Window table (cost + PIT + sign + low-var)

| window | mean_net | t | act | sharpe | max_dd_proxy | sign | survived | low_var |
|--------|---------:|--:|----:|-------:|-------------:|-----:|:--------:|:-------:|
| w2017_2019 | 0.012700 | 1.2662 | 0.0463 | 0.895 | 0.0000 | 1 | True | False |
| w2020_2022 | 0.003867 | — | 0.0455 | — | 0.0000 | 1 | True | False |
| w2023_2025 | 0.022339 | 3.6041 | 0.0463 | 2.548 | 0.0000 | 1 | True | False |

Cross-window: survived **3/3** · sign_flip **False** · signs `[1,1,1]` · mean_net_avg **0.012969** · t_avg **2.4352** · act_avg **0.0460**.

---

## Subperiod stability

| period_id | net | act | sign |
|-----------|----:|----:|-----:|
| y2017_q4 | 0.022731 | 0.0471 | + |
| y2019_full | 0.002670 | 0.0455 | + |
| y2021_full | 0.003867 | 0.0455 | + |
| y2023_full | 0.028537 | 0.0455 | + |
| y2025_q4 | 0.016140 | 0.0471 | + |

- sign_flip_across_subperiods: **False**  
- all_positive_net: **True**  
- mean/min/max net: 0.014789 / 0.002670 / 0.028537  

---

## Drawdown (period-net cumulative proxy)

| scope | n | max_dd | note |
|-------|--:|-------:|------|
| all subperiods | 5 | **0.0** | period_net_cumsum_proxy (not daily equity curve) |
| per window | 1–2 | **0.0** | all-positive nets → no trough |

See also `sticky_drawdown_preferred.json` / `sticky_subperiod_stability.json`.

---

## Activation table

| period_id | year | act | n_active | net | cost | hold |
|-----------|-----:|----:|---------:|----:|-----:|-----:|
| y2017_q4 | 2017 | 0.0471 | 42 | 0.022731 | 0.0002 | 10 |
| y2019_full | 2019 | 0.0455 | 60 | 0.002670 | 0.0002 | 10 |
| y2021_full | 2021 | 0.0455 | 60 | 0.003867 | 0.0002 | 10 |
| y2023_full | 2023 | 0.0455 | 60 | 0.028537 | 0.0002 | 10 |
| y2025_q4 | 2025 | 0.0471 | 42 | 0.016140 | 0.0002 | 10 |

Activation stable ~4.5–4.7% across shards — low-but-consistent book (not a low-var t artifact; `low_variance_artifact=False`).

---

## Freezes held

- Mass = NO-GO · READY = false · ops GO = false · continuous paper = UNARMED  
- 3 default-path pins **untouched / not retuned**  
- No hold/mom micro-grid · no main promote · no GO
