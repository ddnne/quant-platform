# W103 / w0819f Track B — repo-linked short cost (bars-MTM)

**Wave:** W103 / w0819f · Track B  
**Applied to:** `xs_cs_dispersion_gate` · `xs_rank_ls_sticky` (small set only)  
**Data path:** `local_real_mirrors` + local sqlite `jsda_repo_rates`  
**Method:** daily MTM after cost — `scripts/run_w100_peer_daily_dd.py` evaluators; short drag date-matched on that path  
**Recipe:** `scripts/run_w103_repo_short_cost.py`  
**Logs:** [`.glm-logs/w0819f_w103_otc7_repo_gate`](../../.glm-logs/w0819f_w103_otc7_repo_gate/) · `w103b_summary.json`  
**HEAD (pre-commit):** `2e0511ad64b439317624ab50241f3d1955be8bb8`  
**Peer cite:** [`w0819e_w102_dispersion_quality_20260819.md`](w0819e_w102_dispersion_quality_20260819.md) (W102 mid 50 bp placeholder)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| field | value |
|-------|-------|
| repo-linked short wired | **yes** |
| tenor | `overnight/翌日物/T+0` |
| gaps invented / ffilled | **false** |
| applied logics | `xs_cs_dispersion_gate`, `xs_rank_ls_sticky` |
| cost over-tune / ranking-by-cost | **false** |
| ranking unchanged vs tx-only | **True** |
| W102 50 bp placeholder reproduced (fixed_bp mode) | **True** |
| promote_as_main | **false** |
| go / go_eligible | **false** |
| Complete measurement = GO/main | **no** |
| 3-default pins untouched | **True** |
| hold/mom micro-grid | **not run** |
| Mass / READY / Phase7 / paper | NO-GO / 未宣言 / OFF / UNARMED |

Minimum wiring of an already-available funding series (`jsda_tokyo_repo_rates` in local sqlite, same table W102 event/rate used for the curve book). Short overlay is **date-matched repo + mid 50 bp spread**. Missing dates charge **0** that day. Not a GO.

## 1. Wiring

| need | path |
|------|------|
| bars (close panel) | local `real_mirrors` shards (same W99/W100 windows) |
| funding series | `jsda_tokyo_repo_rates` via `data/structured/ingestion.sqlite` → `jsda_repo_rates` |
| tenor (observed only) | `overnight/翌日物/T+0` |
| short formula | `daily = (repo_pct/100 + 50bp/10000) / 245 × short_frac=0.5` on **active** bars-MTM days |
| gap policy | missing `as_of_date` → extra=0, counted in `n_gaps` (no ffill / no invent) |
| loader | `load_repo_rows_from_sqlite` + `load_repo_rate_series_from_rows` + `lookup_repo_rate` + `short_borrow_daily_cost_from_repo` |

Local status: **ok** · n_obs=2594 · n_required_bar_dates=738 · present_required=738 · gaps_on_required=0 · span 2016-01-04→2026-08-14 · ffill=False invent=False.

CS L-S is already dollar-neutral (`long_frac=short_frac=0.3`). **No extra leverage** (`gross_leverage=1.0` → financing daily = 0). Short borrow lives only on the short share (`short_frac=0.5` of the active book).

## 2. Contrast table (tx 10 bp + short overlay)

Required: **daily_path_DD** · **dd_duration** · **recovery** · **total_ret_net**.
Modes: `repo_linked` (this wave) vs `fixed_bp` (W102 mid 50 bp placeholder).

| logic | window | mode | n_days | daily_path_DD | dd_dur | recov | recovered | total_ret_net | tx-only DD | mean repo % | n_applied | n_gaps |
|-------|--------|------|-------:|--------------:|-------:|------:|:---------:|--------------:|-----------:|------------:|----------:|-------:|
| `xs_cs_dispersion_gate` | w2017_2019 | `repo_linked` | 272 | -0.033656 | 10 | — | False | 0.088013 | -0.033574 | -0.092 | 100 | 0 |
| `xs_cs_dispersion_gate` | w2017_2019 | `fixed_bp` | 272 | -0.033673 | 10 | — | False | 0.087808 | -0.033574 | — | 100 | 0 |
| `xs_cs_dispersion_gate` | w2020_2022 | `repo_linked` | 193 | -0.027412 | 24 | 1 | True | 0.185430 | -0.027298 | -0.085 | 82 | 0 |
| `xs_cs_dispersion_gate` | w2020_2022 | `fixed_bp` | 193 | -0.027437 | 24 | 1 | True | 0.185262 | -0.027298 | — | 82 | 0 |
| `xs_cs_dispersion_gate` | w2023_2025 | `repo_linked` | 273 | -0.114569 | 68 | 52 | True | 0.125973 | -0.114227 | 0.045 | 170 | 0 |
| `xs_cs_dispersion_gate` | w2023_2025 | `fixed_bp` | 273 | -0.114662 | 68 | 52 | True | 0.126147 | -0.114227 | — | 170 | 0 |
| `xs_rank_ls_sticky` | w2017_2019 | `repo_linked` | 272 | -0.144363 | 85 | — | False | 0.032789 | -0.143741 | -0.087 | 251 | 0 |
| `xs_rank_ls_sticky` | w2017_2019 | `fixed_bp` | 272 | -0.144485 | 85 | — | False | 0.032328 | -0.143741 | — | 251 | 0 |
| `xs_rank_ls_sticky` | w2020_2022 | `repo_linked` | 193 | -0.038086 | 14 | 1 | True | 0.200072 | -0.037971 | -0.085 | 182 | 0 |
| `xs_rank_ls_sticky` | w2020_2022 | `fixed_bp` | 193 | -0.038109 | 14 | 1 | True | 0.199696 | -0.037971 | — | 182 | 0 |
| `xs_rank_ls_sticky` | w2023_2025 | `repo_linked` | 273 | -0.108529 | 17 | 52 | True | 0.077942 | -0.108415 | 0.064 | 252 | 0 |
| `xs_rank_ls_sticky` | w2023_2025 | `fixed_bp` | 273 | -0.108570 | 17 | 52 | True | 0.078297 | -0.108415 | — | 252 | 0 |

### Repo-linked vs W102 placeholder (mid 50 bp) vs tx-only

| logic | window | DD tx-only | DD +short placeholder | DD +short repo | net placeholder | net repo | ΔDD (repo−ph) |
|-------|--------|-----------:|----------------------:|---------------:|----------------:|---------:|--------------:|
| `xs_cs_dispersion_gate` | w2017_2019 | -0.033574 | -0.033673 | -0.033656 | 0.087808 | 0.088013 | 0.00001728 |
| `xs_cs_dispersion_gate` | w2020_2022 | -0.027298 | -0.027437 | -0.027412 | 0.185262 | 0.185430 | 0.00002478 |
| `xs_cs_dispersion_gate` | w2023_2025 | -0.114227 | -0.114662 | -0.114569 | 0.126147 | 0.125973 | 0.00009270 |
| `xs_rank_ls_sticky` | w2017_2019 | -0.143741 | -0.144485 | -0.144363 | 0.032328 | 0.032789 | 0.00012228 |
| `xs_rank_ls_sticky` | w2020_2022 | -0.037971 | -0.038109 | -0.038086 | 0.199696 | 0.200072 | 0.00002258 |
| `xs_rank_ls_sticky` | w2023_2025 | -0.108415 | -0.108570 | -0.108529 | 0.078297 | 0.077942 | 0.00004143 |

### W102 placeholder reproduction (fixed_bp mode)

| logic | window | W102 DD | this-wave fixed_bp DD | match |
|-------|--------|--------:|----------------------:|:-----:|
| `xs_cs_dispersion_gate` | w2017_2019 | -0.033673 | -0.033673 | yes |
| `xs_cs_dispersion_gate` | w2020_2022 | -0.027437 | -0.027437 | yes |
| `xs_cs_dispersion_gate` | w2023_2025 | -0.114662 | -0.114662 | yes |
| `xs_rank_ls_sticky` | w2017_2019 | -0.144485 | -0.144485 | yes |
| `xs_rank_ls_sticky` | w2020_2022 | -0.038109 | -0.038109 | yes |
| `xs_rank_ls_sticky` | w2023_2025 | -0.108570 | -0.108570 | yes |

## Headline (research-only · not GO)

- JSDA Tokyo overnight repo **wired** into the bars-MTM short-leg daily drag for `xs_cs_dispersion_gate` and `xs_rank_ls_sticky` only. n_obs=2594 · gaps_on_required=0 · ffill=false · invent=false.
- Gate worst repo-linked daily_path_DD **-0.114569** (w2023_2025). Sticky worst **-0.144363** (w2017_2019).
- Negative overnight repo (2017–23 NIRP) makes repo+50 bp **slightly cheaper** than the W102 50 bp placeholder; 2025-Q4 positive repo makes it **slightly dearer**. Ranking vs sticky does **not** flip.
- Cost was **not** tuned to manufacture ranking. Mid spread is the single overlay (W102 convention).
- **promote_as_main=false · go=false.** Complete measurement is **not** a production candidate.

> **Warning:** period-net DD = 0 when all period nets are positive is an
> **aggregation artifact**. It does **not** mean the strategy is riskless.
> Use **daily_path_DD** (duration / recovery / total_ret_net).
>
> **Complete measurement ≠ GO / main.** These rows remain research-only.

## Method (same as W100/W102)

1. Load W99/W100 honest `real_mirrors` shards (max_codes=15, max_days/shard=200).
2. Build the equal-weight held book (gate / sticky catalog params; **not** a hold/mom retune).
3. Mark to market **daily**; subtract amortized one-way 10 bp while active.
4. Load `jsda_repo_rates` overnight T+0 from local sqlite. Key by `as_of_date`. **Do not** ffill.
5. On each **active** bars-MTM day, extra short drag = `f(repo[t] + 50 bp, short_frac=0.5)` when the date is present; else extra=0 and count a gap.
6. Replay the same path with constant 50 bp annual (W102 placeholder) for the contrast table.
7. `evaluate_daily_path_dd_gate` must complete; period-net-only is forbidden.

## Freezes held

- promote_as_main = **false** · go = **false**
- no hold/mom micro-grid · no 3-default pin retune
- no cost over-tune ranking
- Mass NO-GO · READY 未宣言 · Phase7 OFF · continuous paper UNARMED
- period_net_DD-only **cannot pass**
- no repo ffill / no invent

## Non-claims

- No READY / Mass / GO / live / pin retune / hold-mom grid / full catalog grid.
- Repo-linked short cost is a **research overlay** on two logics, not a production borrow model and not a liquidity-linked HTB scale.
- Local mirrors + local sqlite ≠ CF SoT.
- Period-net DD=0 **must not** be read as riskless.
- Complete daily_path_DD is **not** a production candidate / GO.

GLM implementer only. Grok did not implement.
