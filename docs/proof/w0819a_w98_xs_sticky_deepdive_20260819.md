# W98 / w0819a — Track C `xs_rank_ls_sticky` deep-dive (NO GO / NO main)

**Wave:** W98 / `w0819a` · Track C  
**Policy:** multi-year + cost + PIT + sign + low-var · CF `r2_panels` preferred · **no** hold/mom micro-grid · **3-default pins untouched** · explicit **`promote_as_main=false`** · **`go=false`**  
**Recipe:** `scripts/run_w98_xs_sticky_deepdive.py`  
**Logs:** [`.glm-logs/w0819a_w98_otc_master_xs/`](../../.glm-logs/w0819a_w98_otc_master_xs/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## CF deep job

| field | value |
|-------|-------|
| job_id | `w98-sticky-20260818T222820Z` |
| status | `ok` |
| mode | `r2_panels` (preferred) |
| logic | `xs_rank_ls_sticky` |
| params | hold=10 · mom=5 · long/short_frac=0.3 · book_mode=balanced_ls (**catalog base; not a retune**) |
| window survivor cells | **3/3** |
| stance | **STABLE_RESEARCH_ONLY** |
| sign_flip | **False** (all +1) |
| low_var | **False** |
| promote_as_main | **false** |
| go | **false** |
| hold/mom micro-grid | **not run** |
| 3-default pins | **unchanged / not retuned** |

Corroborating CF job (parallel): `w98-sticky-20260818T223015Z` · same stance · promote/GO false.

## Window table (cost + PIT + sign + low-var)

| window | logic | mean_net | t | act | sharpe | max_dd | sign | surv | low_var | rejects |
|---|---|---:|---:|---:|---:|---:|---|:---:|:---:|---|
| w2017_2019 | `xs_rank_ls_sticky` | 0.010942 | 1.3363 | 0.0392 | 0.945 | 0.000000 | 1 | True | False | — |
| w2020_2022 | `xs_rank_ls_sticky` | 0.010171 | — | 0.0385 | — | 0.000000 | 1 | True | False | — |
| w2023_2025 | `xs_rank_ls_sticky` | 0.018085 | 3.6995 | 0.0392 | 2.616 | 0.000000 | 1 | True | False | — |

## Classification

| logic | stance | surv_win | sign_flip | low_var | mean_net_avg | t_avg | act_avg | main? | GO? |
|---|---|---:|:---:|:---:|---:|---:|---:|:---:|:---:|
| `xs_rank_ls_sticky` | STABLE_RESEARCH_ONLY | 3/3 | False | False | 0.013066 | 2.5179 | 0.0389 | **false** | **false** |

## Subperiod stability

chosen_sign=original · all 5 shards **ok** · all signed nets **positive** · no subperiod sign flip

| window | period | status | gross | net | signed_net | cost | act | hold | n_pos |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| w2017_2019 | `y2017_q4` | ok | 0.019330 | 0.019130 | 0.019130 | 0.000200 | 0.039886 | 10 | 42 |
| w2017_2019 | `y2019_full` | ok | 0.002954 | 0.002754 | 0.002754 | 0.000200 | 0.038462 | 10 | 60 |
| w2020_2022 | `y2021_full` | ok | 0.010371 | 0.010171 | 0.010171 | 0.000200 | 0.038462 | 10 | 60 |
| w2023_2025 | `y2023_full` | ok | 0.023173 | 0.022973 | 0.022973 | 0.000200 | 0.038462 | 10 | 60 |
| w2023_2025 | `y2025_q4` | ok | 0.013396 | 0.013196 | 0.013196 | 0.000200 | 0.039886 | 10 | 42 |

## Activation table

| window | period | act | min_act | below_min | n_active_pos | status |
|---|---|---:|---:|:---:|---:|---|
| w2017_2019 | `y2017_q4` | 0.0399 | 0.0100 | False | 42 | ok |
| w2017_2019 | `y2019_full` | 0.0385 | 0.0100 | False | 60 | ok |
| w2020_2022 | `y2021_full` | 0.0385 | 0.0100 | False | 60 | ok |
| w2023_2025 | `y2023_full` | 0.0385 | 0.0100 | False | 60 | ok |
| w2023_2025 | `y2025_q4` | 0.0399 | 0.0100 | False | 42 | ok |

mean_activation ≈ **0.0389** · **0** periods below min_activation gate.

## Drawdown table (period-net cumulative)

| scope | n | max_dd | abs_max_dd | note |
|---|---:|---:|---:|---|
| all_subperiods | 5 | 0.0 | 0.0 | cumulative signed period-nets |
| `w2017_2019` | 2 | 0.0 | 0.0 | window shards |
| `w2020_2022` | 1 | 0.0 | 0.0 | window shards |
| `w2023_2025` | 2 | 0.0 | 0.0 | window shards |

Note: DD on cumulative sum of signed **period nets** (research period-level; not intraday equity curve). All-positive signed nets → max_dd=0 at this grain.

## Explicit non-declarations (held)

- `promote_as_main` = **false** · `go` = **false** · research-only
- hold/mom micro-grid = **forbidden / not run**
- 3-default pins = **untouched** (`cross_section_hold_10` KEEP · `cross_section_hold_10_mom3` PROMOTE · `fundamentals_hold_10` KEEP)
- Mass NO-GO · READY 未宣言 · Phase7 OFF · ops GO 未宣言 · continuous paper UNARMED · no live

## Artifacts

| artifact | role |
|----------|------|
| `sticky_deep_cf.json` / `sticky_deep_cf_table.md` | CF preferred deep pack |
| `sticky_deep_table.json` / `.md` | preferred C table + classification |
| `sticky_subperiod_*.json` | subperiod stability |
| `sticky_activation_*.json` | activation table |
| `sticky_drawdown_*.json` | period-net DD |
| `frozen_pins_assert(_after).json` | pins_untouched=True |
| `w98_cd_summary.json` | C+D combined |
