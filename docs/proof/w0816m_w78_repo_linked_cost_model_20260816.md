# W78 / w0816m — Repo-linked research cost model (date-matched Tokyo repo rates)

**Phase:** 研究用コストモデル v2（レバ調達 / 空売り借入を `jsda_tokyo_repo_rates` 連動）  
**Wave:** W78 / w0816m · 2026-08-16  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Module:** `packages/product/research/cost_models.py`  
**Harness:** `research.eval_harness.run_standard_research_eval` (checklist v2)  
**Version:** `research-cost-models/v2` (prior: `…/v1`)  
**Prior cost/checklist:** [`w0816k_w77_eval_checklist_v2_20260816.md`](w0816k_w77_eval_checklist_v2_20260816.md)

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** (`ready_declared=False`) |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| edge / significance / operational GO | **none** |
| densify / COMPLETE invent | **none** |
| repo gap fill (ffill / invent) | **forbidden** — gaps disclosed only |
| Mass/READY auto-declare | **never** |
| push | **not this task** (Lane E) |

---

## Policy

| rule | held |
|------|------|
| Prefer date-matched `jsda_tokyo_repo_rates` over fixed bp | **yes** (`prefer_repo_linked=True`) |
| Hard-require repo series for checklist complete | **no** (`require_repo_linked=False` default) |
| Missing repo dates | **gap flags**; cost = `None` for that day; **no ffill invent** |
| Long-only unlevered | tx (10bp default) + short/financing **N/A** explicit |
| Fixed bp fallback | disclosed when no series (`rate_source=fixed_bp_placeholder`) |

---

## Models

### 1. Leverage financing = f(repo_rate[t], leverage excess)

```text
financing_daily[t] = (repo_pct[t] / 100) * max(gross_leverage - 1, 0) / trading_days
```

* `repo_pct` is JSDA schema unit (**percent**; see `docs/data_sources.md`).
* Preferred rate source: `jsda_tokyo_repo_rates` / table `jsda_repo_rates`.
* Fallback when no series: fixed **25bp** annual placeholder (v1 default).

### 2. Short cost = f(repo[t] + spread, short_frac) **or** borrow proxy

**Preferred (repo + explicit spread):**

```text
short_annual_bp[t] = repo_pct[t] * 100 + spread_bp
short_borrow_daily[t] = (short_annual_bp[t] / 10000) / trading_days * short_fraction
```

| sensitivity | spread_bp | note |
|-------------|-----------|------|
| **low** | 25 | liquid large-cap research band |
| **mid** (default) | 50 | matches prior fixed 50bp when repo≈0 |
| **high** | 150 | harder-to-borrow research band |

**Alternatives:**

* pure `borrow_proxy` annual bp (no repo)
* fixed 50bp annual placeholder when no series

### 3. Long-only unlevered

* Transaction: default 10bp one-way (change needs reason)
* Short borrow: **N/A** (explicit)
* Leverage financing: **N/A** (explicit)
* Repo series may still be attached for inventory/disclosure but does not apply cost

### 4. Gap policy

* `load_repo_rate_series*` with `required_dates` lists missing keys in `gap_dates`
* `lookup_repo_rate` → `is_gap=True`, `rate=None`, `ffill_applied=False`
* Date-matched daily costs on gap days → `financing_daily` / `short_borrow_daily` = `None`
* Mean summary uses **observed rates only** (gaps excluded, never invented)

---

## Load paths (D1 / R2 / local)

| API | path | note |
|-----|------|------|
| `load_repo_rate_series_from_mapping` | pure mapping | unit-test / synthetic |
| `load_repo_rate_series_from_rows` | JSDA/PIT-shaped rows | no network |
| `load_repo_rate_series` | unified (mapping / rows / series) | preferred entry |
| `load_repo_rate_series_from_pit` | `pit.get_jsda_repo_rates` | D1 tip / local SQLite; inject fn in tests |
| `load_repo_rate_series_from_r2_rows` | caller-supplied R2 extract | history SoT = R2 `quant-structured`; helper does not fetch |

Dataset id: **`jsda_tokyo_repo_rates`** · fact table: **`jsda_repo_rates`** · default tenor prefer: **隔日物**.

---

## Delivered API names

| symbol | role |
|--------|------|
| `COST_MODELS_VERSION` | `research-cost-models/v2` |
| `COST_MODELS_VERSION_V1` | prior id |
| `COST_MODELS_WAVE` | `W78 / w0816m` |
| `COST_MODELS_PROOF` | this proof path |
| `REPO_DATASET_ID` / `REPO_TABLE` | `jsda_tokyo_repo_rates` / `jsda_repo_rates` |
| `RATE_SOURCE_REPO_SERIES` | financing preferred |
| `RATE_SOURCE_REPO_PLUS_SPREAD` | short preferred |
| `RATE_SOURCE_FIXED_BP` | disclosed fallback |
| `RATE_SOURCE_BORROW_PROXY` | short alt |
| `RATE_SOURCE_NOT_APPLICABLE` | long-only N/A |
| `SHORT_BORROW_SPREAD_LOW_BP` / `MID` / `HIGH` | 25 / 50 / 150 |
| `SHORT_BORROW_SPREAD_SENSITIVITY` | band map |
| `repo_rate_pct_to_annual_fraction` | % → fraction |
| `repo_rate_pct_to_annual_bp` | % → bp |
| `load_repo_rate_series` | unified loader |
| `load_repo_rate_series_from_mapping` | date→rate |
| `load_repo_rate_series_from_rows` | JSDA rows |
| `load_repo_rate_series_from_pit` | PIT/D1/local |
| `load_repo_rate_series_from_r2_rows` | R2 rows (no fetch) |
| `lookup_repo_rate` | single-date + gap flag |
| `mean_repo_rate_pct` | observed-only mean |
| `leverage_financing_daily_cost` | fixed/annual helper (kept) |
| `leverage_financing_daily_cost_from_repo` | f(repo, excess) |
| `short_borrow_daily_cost` | fixed/annual helper (kept) |
| `short_borrow_daily_cost_from_repo` | f(repo+spread, frac) |
| `short_borrow_daily_cost_from_proxy` | borrow_proxy path |
| `date_matched_leverage_financing_costs` | per-date financing + gaps |
| `date_matched_short_borrow_costs` | per-date short + gaps |
| `build_leverage_short_cost_assumption` | checklist block (repo-aware) |
| `default_long_only_unlevered_cost_assumption` | tx + N/A |
| `annotate_period_rows_with_extended_costs` | date-matched annotate |
| `cost_models_document` | public surface |
| `research_net_with_extended_costs` | gross − tx − short − fin |

### Harness (checklist v2) wiring

| symbol / kwarg | default | meaning |
|----------------|---------|---------|
| `COST_MODEL_PREFER_REPO_LINKED` | `True` | prefer repo path |
| `COST_MODEL_REQUIRE_REPO_LINKED` | `False` | not hard-required |
| `STANDARD_EVAL_COST_MODEL_PROOF` | this file | proof pin |
| `run_standard_research_eval(repo_rate_series=…)` | `None` | mapping/rows/series |
| `prefer_repo_linked` | `True` | use series when usable |
| `require_repo_linked` | `False` | if True + lev/short without series → incomplete |
| `short_borrow_spread_bp` / `short_borrow_sensitivity` | mid 50bp | short spread |
| `borrow_proxy_annual_bp` | `None` | short alt |
| `repo_required_dates` | `None` | gap checklist for series |
| return `repo_rate_series` / `prefer_repo_linked` / `cost_model_proof` | — | disclosure |

`standard_research_eval_checklist_document()` adds:

* `cost_model_defaults` (prefer/require + gap policy)
* `recommended` includes `repo_linked_cost_model`
* `cost_model_proof` pin

---

## Tests

```text
.venv/bin/python -m pytest tests/test_cost_models_repo_linked.py tests/test_standard_research_eval.py tests/test_eval_harness.py -q
# 57 passed
```

Coverage highlights:

* synthetic series + gap day `2024-01-04`
* no ffill invent on gaps
* financing/short date-matched costs
* low/mid/high short sensitivity ordering
* long-only N/A
* harness prefer path + optional require path
* Mass/READY freeze on all paths

---

## Defaults summary (document for checklist callers)

| situation | financing | short | checklist complete? |
|-----------|-----------|-------|---------------------|
| long-only unlevered, no series | N/A | N/A | **yes** (N/A explicit) |
| levered / short, **with** series | repo mean / date-matched | repo+spread | **yes** (gaps disclosed) |
| levered / short, **no** series | fixed 25bp | fixed 50bp | **yes** (fallback disclosed) |
| levered / short, `require_repo_linked=True`, no series | — | — | **no** (`repo_rate_series` missing) |

---

## Non-goals (this wave)

* No Mass / READY declare  
* No Phase7 ON  
* No push / no commit by implementer instruction  
* No invent densify of JSDA history  
* No broker borrow quote integration  
* No claim of edge / significance  

---

## Files touched

| path | change |
|------|--------|
| `packages/product/research/cost_models.py` | v2 repo-linked model + load API |
| `packages/product/research/eval_harness.py` | prefer/require wiring + kwargs |
| `tests/test_cost_models_repo_linked.py` | unit + harness tests |
| `docs/proof/w0816m_w78_repo_linked_cost_model_20260816.md` | this proof |
