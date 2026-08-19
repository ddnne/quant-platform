# W103 / w0819f Track B — minimal repo-linked short cost wiring

**Wave:** W103 / `w0819f` · Track B  
**Goal:** Wire JSDA Tokyo overnight repo into bars-MTM daily path for short-leg cost  
**Candidates:** `xs_cs_dispersion_gate` (main research) + `xs_rank_ls_sticky` (compare only)  
**Recipe:** `scripts/run_w103_repo_gate_deepen.py`  
**Cost models:** `packages/product/research/cost_models.py` (`research-cost-models/v2`)  
**Logs:** [`.glm-logs/w0819f_w103_otc7_repo_gate/`](../../.glm-logs/w0819f_w103_otc7_repo_gate/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| field | value |
|-------|-------|
| repo series wired | **yes** (`jsda_tokyo_repo_rates` / `jsda_repo_rates`) |
| tenor | `overnight/翌日物/T+0` |
| n_obs (loaded window) | **2594** |
| gaps on required eval dates | **0** |
| ffill / invent | **false / false** |
| contrast vs fixed-bp | **yes** (mid spread 50bp) |
| ranking-by-cost-tune | **false** |
| over-tune | **false** |
| promote_as_main / go | **false / false** |
| Mass / READY / paper | NO-GO / 未宣言 / UNARMED |

Minimal wiring landed. Missing days would be gap-disclosed (none on required dates this wave).

---

## Wiring

```text
short_annual_bp[t] = repo_pct[t] * 100 + spread_bp(mid=50)
short_daily[t]     = (short_annual_bp[t] / 10000) / 245 * short_fraction(0.5)
```

* Applied as **extra daily drag on active days only** after base tx (10bp amortized) bars-MTM path.  
* Loader: `load_repo_rows_from_sqlite` → `load_repo_rate_series_from_rows` → `lookup_repo_rate` / `short_borrow_daily_cost_from_repo`.  
* Gap policy: if `lookup_repo_rate` is gap → **do not apply** short cost that day; disclose in `n_gaps` / `gap_dates_sample`. **No ffill.**

Artifacts: `repo_series_meta.json` · `repo_short_assumption.json` · `repo_short_contrast_table.json`

---

## Contrast table (gate + sticky · mid 50bp · vs fixed placeholder)

Base path = tx 10bp only. Overlay adds short borrow (repo-linked **or** fixed 50bp annual).

| logic | window | mode | daily_path_DD | total_ret_net | n_applied | n_gaps |
|-------|--------|------|--------------:|--------------:|----------:|-------:|
| gate | w2017_2019 | repo_linked | −0.033656 | 0.088013 | 100 | 0 |
| gate | w2017_2019 | fixed_bp | −0.033673 | 0.087808 | 100 | 0 |
| gate | w2020_2022 | repo_linked | −0.027412 | 0.185430 | 82 | 0 |
| gate | w2020_2022 | fixed_bp | −0.027437 | 0.185262 | 82 | 0 |
| gate | w2023_2025 | repo_linked | −0.114569 | 0.125973 | 170 | 0 |
| gate | w2023_2025 | fixed_bp | −0.114662 | 0.126147 | 170 | 0 |
| sticky | w2017_2019 | repo_linked | −0.144xxx | (see JSON) | — | 0 |
| sticky | … | fixed_bp | … | … | — | 0 |

Full rows: `repo_short_contrast_table.json`.

### Reading

* Repo-linked mid ≈ fixed 50bp while overnight repo ≈ 0 (2017–22).  
* 2023–25 repo rates leave mid slightly different from pure 50bp placeholder — **disclosed, not used to rank**.  
* ΔDD vs tx-only is small (bps-level path drag). **Not** a promotion signal.

---

## Explicit non-claims

* Not broker HTB / not live borrow.  
* Not a cost-tuned ranking of candidates.  
* Not GO / main / Mass / READY.  
* Gaps never invented (this wave: zero gaps on required dates).

GLM5.3 only. Grok did not implement.
