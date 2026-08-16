# W79 / w0816n — Liquidity-linked research cost model

**Phase:** 研究用コストモデル v2 に流動性連動を追加（tx cost / short spread）  
**Wave:** W79 / w0816n · 2026-08-16  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Module:** `packages/product/research/cost_models.py`  
**Harness:** `research.eval_harness.run_standard_research_eval` (checklist v2)  
**Version:** `research-cost-models/v2` (kept; prior wave W78 repo-linked)  
**Prior cost proofs:**  
* [`w0816m_w78_repo_linked_cost_model_20260816.md`](w0816m_w78_repo_linked_cost_model_20260816.md)  
* [`w0816k_w77_eval_checklist_v2_20260816.md`](w0816k_w77_eval_checklist_v2_20260816.md)

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** (`ready_declared=False`) |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| edge / significance / operational GO | **none** |
| densify / COMPLETE invent | **none** |
| repo gap fill (ffill / invent) | **forbidden** |
| liquidity invent | **forbidden** — missing → gap + mult=1.0 |
| Mass/READY auto-declare | **never** |
| push | **not this task** |

---

## Policy

| rule | held |
|------|------|
| Keep repo-linked cost_models **v2** | **yes** |
| Short low/mid/high spreads remain as sensitivity | **yes** (25 / 50 / 150 bp) |
| ADD liquidity modulation of tx cost and/or short spread | **yes** |
| No invent on missing liquidity → gap disclose | **yes** |
| Mass/READY not auto-connect | **yes** |
| Prefer liquidity-linked when proxy available | **yes** (`prefer_liquidity_linked=True`) |
| Hard-require liquidity for checklist complete | **no** (`require_liquidity_linked=False` default) |

---

## Liquidity proxy formula

### Per-bar yen turnover

Dataset: **`equities_bars_daily`** (fields from JQuants normalize).

```text
yen_turnover[t] =
    turnover_value[t]                                      # 売買代金 (prefer)
    else close[t] * volume[t]
    else adjustment_close[t] * adjustment_volume[t]
    else MISSING  → gap (never invent)
```

### ADV (average daily yen volume)

```text
ADV = mean_t( yen_turnover[t] for observed bars )
```

Optional membership (soft only when ADV is observed):

* `is_topix=True` or `scale_category` matching large-cap tokens  
  (`large`, `core30`, `large70`, `topix100`)  
  → upgrade bucket one step (low→mid, mid→high)
* Membership **alone never invents** ADV or a bucket when bars are missing

### Bucket thresholds (research placeholders, JPY/day · 仮定に依存)

| bucket | rule (default) |
|--------|----------------|
| **high** | `ADV >= 1e9` (¥1bn/day) |
| **mid** | `ADV >= 1e8` (¥100m/day) |
| **low** | ADV observed and `< 1e8` |
| **missing** | no observed yen turnover → gap |

Constants: `LIQUIDITY_ADV_HIGH_JPY`, `LIQUIDITY_ADV_MID_JPY`.

---

## Cost modulation formula

### Transaction (one-way)

```text
one_way_cost_eff = one_way_cost_base * LIQUIDITY_TX_MULT[bucket]
```

| bucket | `LIQUIDITY_TX_MULT` | effect on default 10bp |
|--------|---------------------|-------------------------|
| high | 1.0 | 10 bp |
| mid | 1.5 | 15 bp |
| low | 2.5 | 25 bp |
| missing | 1.0 (unmodulated) | 10 bp + gap disclosed |

### Short borrow spread (combined with sensitivity)

Short low/mid/high sensitivity is applied **first**, then liquidity mult:

```text
spread_base_bp = SHORT_BORROW_SPREAD_SENSITIVITY[low|mid|high]
                 # 25 / 50 / 150
spread_eff_bp  = spread_base_bp * LIQUIDITY_SHORT_SPREAD_MULT[bucket]

# Preferred repo-linked short:
short_annual_bp = repo_annual_bp + spread_eff_bp
short_borrow_daily = (short_annual_bp / 10000) / trading_days * short_fraction
```

| bucket | `LIQUIDITY_SHORT_SPREAD_MULT` |
|--------|-------------------------------|
| high | 1.0 |
| mid | 1.5 |
| low | 2.0 |
| missing | 1.0 (unmodulated) + gap |

**Example (mid sensitivity × low liquidity):**  
`50 * 2.0 = 100bp` effective spread over repo.

**Fixed-bp / borrow_proxy path when liquidity applied:**  
annual borrow is scaled by `short_spread_mult` so low-liquidity shorts cost more even without a repo series.

### Leverage financing

Unchanged by liquidity in this wave (still repo-linked preferred / fixed-bp fallback).

---

## Delivered API

| symbol | role |
|--------|------|
| `COST_MODELS_VERSION` | `research-cost-models/v2` (kept) |
| `COST_MODELS_WAVE` | `W79 / w0816n` |
| `COST_MODELS_PROOF` | this proof path |
| `COST_MODELS_PROOF_REPO_LINKED` | W78 proof pin |
| `LIQUIDITY_DATASET_ID` | `equities_bars_daily` |
| `LIQUIDITY_PROXY_UNIT` | `jpy_adv` |
| `LIQUIDITY_BUCKET_{HIGH,MID,LOW,MISSING}` | bucket ids |
| `LIQUIDITY_ADV_{HIGH,MID}_JPY` | thresholds |
| `LIQUIDITY_TX_MULT` | tx mult map |
| `LIQUIDITY_SHORT_SPREAD_MULT` | short-spread mult map |
| `yen_turnover_from_bar` | single-bar yen turnover (gap-safe) |
| `compute_liquidity_proxy_from_bars` | ADV from bar rows |
| `compute_liquidity_proxy_from_adv` | ADV scalar envelope |
| `liquidity_bucket_from_proxy` | ADV → bucket |
| `liquidity_cost_multipliers` | bucket → mults |
| `resolve_liquidity_modulation` | unified proxy→bucket→mult |
| `apply_liquidity_to_one_way_cost` | `tx * tx_mult` |
| `apply_liquidity_to_short_spread_bp` | `spread * short_spread_mult` |
| `build_leverage_short_cost_assumption` | checklist block (liq-aware) |
| `default_long_only_unlevered_cost_assumption` | tx (+ optional liq) + N/A |
| `cost_models_document` | public surface (+ liquidity) |

### `build_leverage_short_cost_assumption` liquidity kwargs

| kwarg | default | meaning |
|-------|---------|---------|
| `liquidity_proxy` | `None` | prebuilt proxy envelope or ADV float |
| `liquidity_bars` | `None` | equities_bars-like rows |
| `liquidity_bucket` | `None` | explicit `high`/`mid`/`low`/`missing` |
| `liquidity_adv_jpy` | `None` | scalar ADV |
| `is_topix` | `None` | soft membership |
| `scale_category` | `None` | soft membership (master field) |
| `prefer_liquidity_linked` | `True` | apply mults when bucket known |
| `require_liquidity_linked` | `False` | if True + gap → incomplete |
| `liquidity_required_dates` | `None` | gap checklist for bars |

### Harness (checklist v2) wiring

| symbol / kwarg | default | meaning |
|----------------|---------|---------|
| `COST_MODEL_PREFER_LIQUIDITY_LINKED` | `True` | prefer liq path |
| `COST_MODEL_REQUIRE_LIQUIDITY_LINKED` | `False` | not hard-required |
| `STANDARD_EVAL_COST_MODEL_PROOF` | this file | proof pin |
| `run_standard_research_eval(... liquidity_*)` | — | same kwargs as builder |
| return `liquidity` / `prefer_liquidity_linked` | — | disclosure |

`standard_research_eval_checklist_document()` adds:

* `cost_model_defaults.prefer_liquidity_linked` / `require_liquidity_linked`
* `recommended` includes `liquidity_linked_cost_model`
* `cost_models_surface.liquidity` block

---

## Gap policy (liquidity)

* Empty bars / missing fields → `is_gap=True`, `adv_jpy=None`
* Required dates without turnover → `gap_dates` listed
* `ffill_applied=False`, `invent_fill=False` always
* Missing liquidity → `tx_mult=1.0`, `short_spread_mult=1.0`, costs unmodulated, gap disclosed
* TOPIX/scale without ADV → still missing (no invent)

---

## Tests

```text
.venv/bin/python -m pytest \
  tests/test_cost_models_liquidity_linked.py \
  tests/test_cost_models_repo_linked.py \
  tests/test_standard_research_eval.py -q
```

Coverage highlights:

* yen turnover priority + gap
* ADV from bars / scalar
* high/mid/low thresholds + TOPIX soft upgrade
* mult ordering; missing → 1.0
* short sensitivity × liquidity combined
* long-only tx scaled by low liquidity
* repo+spread + liquidity
* require_liquidity_linked blocks completeness
* harness wiring + Mass/READY freeze

---

## Defaults summary

| situation | tx | short spread | checklist complete? |
|-----------|----|--------------|---------------------|
| no liquidity inputs | base 10bp (mult=1) | base sensitivity / fixed | **yes** (gap disclosed) |
| high ADV bars | 10bp | spread × 1.0 | **yes** |
| low ADV bars | 25bp | spread × 2.0 | **yes** |
| `require_liquidity_linked=True`, no data | — | — | **no** (`liquidity_proxy` missing) |

---

## Non-goals (this wave)

* No Mass / READY declare  
* No Phase7 ON  
* No push / no commit by implementer instruction  
* No invent densify of bars or repo history  
* No broker borrow / live spread quote integration  
* No claim of edge / significance  
* Financing not liquidity-scaled (repo path only)

---

## Files touched

| path | change |
|------|--------|
| `packages/product/research/cost_models.py` | liquidity proxy + mult + builder wiring (v2 kept) |
| `packages/product/research/eval_harness.py` | prefer/require + kwargs + checklist surface |
| `tests/test_cost_models_liquidity_linked.py` | unit + harness tests |
| `docs/proof/w0816n_w79_liquidity_linked_cost_20260816.md` | this proof |
