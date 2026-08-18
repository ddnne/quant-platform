# W99 / w0819b Track B — `xs_rank_ls_sticky` true daily drawdown

**Logic:** `xs_rank_ls_sticky`  
**Data path:** `local_real_mirrors` (CF mass-eval cannot emit daily equity path)  
**HEAD:** `5f514978e8b27b89d57564fc57ee0feca16df7be`  
**Policy:** `promote_as_main=false` · `go=false` · no pin retune · no hold/mom grid  

## Why this wave

W98 reported `max_dd_proxy=0` from **period-net cumsum** while all CF period
nets were positive. That is an **aggregation artifact**, **not** “no risk”.
This wave builds a **daily mark-to-market** equity curve after costs and
computes true path DD / duration / recovery.

## Explicit stance (frozen)

| field | value |
|-------|-------|
| promote_as_main | **False** |
| go / go_eligible | **False** |
| research_only | **True** |
| hold/mom micro-grid | **not run** |
| 3-default pins untouched | **True** |
| Mass / READY / Phase7 / paper | NO-GO / 未宣言 / OFF / UNARMED |

## Window table — daily path (after cost)

| window | n_days | total_ret_net | total_ret_gross | mean_net_daily | max_dd | abs_dd | dd_dur | recovery | recovered | period_ref_nets |
|--------|-------:|--------------:|----------------:|---------------:|-------:|-------:|-------:|---------:|:---------:|-----------------|
| w2017_2019 | 272 | 0.034975 | 0.037576 | 0.000146 | -0.143741 | 0.143741 | 85 | — | False | `0.011785, -0.002311` |
| w2020_2022 | 193 | 0.201923 | 0.204111 | 0.000998 | -0.037971 | 0.037971 | 14 | 1 | True | `0.010885` |
| w2023_2025 | 273 | 0.081073 | 0.083800 | 0.000363 | -0.108415 | 0.108415 | 17 | 52 | True | `0.002610, 0.009944` |

### Per-shard daily path

| window | period_id | n_days | total_ret_net | max_dd | dd_dur | recovery | period_net_ref |
|--------|-----------|-------:|--------------:|-------:|-------:|---------:|---------------:|
| w2017_2019 | y2017_q4 | 81 | 0.081566 | -0.018864 | 9 | 7 | 0.011785 |
| w2017_2019 | y2019_full | 192 | -0.043077 | -0.143741 | 85 | — | -0.002311 |
| w2020_2022 | y2021_full | 193 | 0.201923 | -0.037971 | 14 | 1 | 0.010885 |
| w2023_2025 | y2023_full | 193 | 0.022049 | -0.108415 | 17 | 52 | 0.002610 |
| w2023_2025 | y2025_q4 | 81 | 0.057750 | -0.098810 | 35 | 29 | 0.009944 |

## Contrast — period_net_DD (=0 artifact) vs daily_path_DD

| window | period_net_DD (W98 CF artifact) | period_net_DD (local proxy) | daily_path_DD | dd_dur | recovery | total_ret_net |
|--------|--------------------------------:|----------------------------:|--------------:|-------:|---------:|--------------:|
| w2017_2019 | 0.0000 | -0.0023 | -0.143741 | 85 | — | 0.034975 |
| w2020_2022 | 0.0000 | 0.0000 | -0.037971 | 14 | 1 | 0.201923 |
| w2023_2025 | 0.0000 | 0.0000 | -0.108415 | 17 | 52 | 0.081073 |

> **Warning:** period-net DD = 0 when all period nets are positive is an
> **aggregation artifact**. It does **not** mean the strategy is riskless.
> Use **daily_path_DD** (and duration / recovery) for path risk.

## Method

1. Load local `real_mirrors` bars for W98/W99 honest shards.
2. Build CS momentum ranks → sticky `fixed_horizon` hold (hold=10, mom=5).
3. Mark held L/S book to market **daily** (equal-weight active names).
4. Subtract Python amortized daily cost drag while active.
5. Equity curve peak-to-trough → max DD, duration, recovery.
6. Contrast vs W98 CF period-net cumsum proxy (artifact = 0).

Params (catalog base, **not** a retune): `{'hold_days': 10, 'momentum_n': 5, 'long_frac': 0.3, 'short_frac': 0.3, 'book_mode': 'balanced_ls'}`.
Codes: first 15 of `DEFAULT_EVAL_CODES`; max_days/shard=200.

## Freezes held

- promote_as_main = **false** · go = **false**
- no hold/mom micro-grid · no 3-default pin retune
- Mass NO-GO · READY 未宣言 · Phase7 OFF · continuous paper UNARMED


## Artifacts

- Logs: [`.glm-logs/w0819b_w99_otc_sticky_dd`](../../.glm-logs/w0819b_w99_otc_sticky_dd)
- Contrast JSON: `contrast_period_vs_daily.json`
- Window daily packs: `window_w*_daily.json`

## Non-claims

- No READY / Mass / GO / live / pin retune / hold-mom grid.
- Local mirrors are **not** CF SoT; labeled `local_real_mirrors`.
- Period-net DD=0 **must not** be read as riskless.
