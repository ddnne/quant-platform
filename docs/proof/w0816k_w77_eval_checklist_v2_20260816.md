# W77 / w0816k — Evaluation checklist v2 (leverage/short costs + risk scenarios)

**Phase:** 標準研究評価チェックリスト v2（READY 未宣言）  
**Wave:** W77 / w0816k · 2026-08-16  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Harness entry:** `research.eval_harness.run_standard_research_eval`  
**Version:** `standard-research-eval-checklist/v2`  
**Prior (v1):** [`w0815bg_w66_standard_research_eval_checklist_20260815.md`](w0815bg_w66_standard_research_eval_checklist_20260815.md) · `standard-research-eval-checklist/v1`

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** (`ready_declared=False`) |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| edge / significance / operational GO | **none** |
| densify / COMPLETE invent | **none** |
| S1–S5 un-reject | **forbidden** (stay `research_baseline_rejected`) |
| incomplete checklist → `research_candidate` | **blocked** |
| Gate / checklist pass → READY/Mass/GO | **never auto-connects** |

---

## Old (v1) vs new (v2)

| item | v1 (`…/v1`) | v2 (`…/v2`) |
|------|-------------|-------------|
| Multi-year / non-overlapping long windows | **required** | **required** (kept) |
| Transaction cost (10bp one-way default) | **required** | **required** (kept; change needs reason) |
| Robustness gate v2 + `net_sign_majority` | **required** | **required** (kept) |
| Data-gap disclosure | **required** | **required** (kept) |
| Pass ≠ READY / Mass / GO | **required** | **required** (kept) |
| Holding / turnover | **recommended** | **near-required** for high-frequency hyps |
| Leverage / short related costs | — | **required** (explicit assumptions) |
| Risk scenario evaluation (min set) | — | **required** |
| Incomplete → not candidate | implied (always False) | **hard** via `checklist_completeness` / `research_candidate_allowed` |

### New required: leverage / short costs

| component | default / rule |
|-----------|----------------|
| Short borrow / lending fee | research model default **50bp annualized**; daily ≈ annual / 245 × short_fraction |
| Leverage financing / repo | research model default **25bp annualized** on max(gross_leverage−1, 0) |
| Long-only unlevered | **must still state** `position_style=long_only_unlevered` + short/financing **N/A** |
| Module | `packages/product/research/cost_models.py` |

### New required: risk scenarios (min set)

| scenario_id | rule |
|-------------|------|
| `crash` | large negative market-return regime — **required metrics** |
| `high_vol` | elevated vol regime — **required metrics** |
| `rate_up` / `rate_down` | if rate data usable; else **disclose N/A** with reason |
| `liquidity_stress` | if available; else **disclose N/A** with reason |
| Sign/stability break | **prefer fail candidate**; or explicit scenario-weakness disclosure (still not READY) |
| Module | `packages/product/research/risk_scenarios.py` |

---

## Delivered API

| symbol | module | role |
|--------|--------|------|
| `CHECKLIST_VERSION` | `eval_harness` | `standard-research-eval-checklist/v2` |
| `CHECKLIST_VERSION_V1` | `eval_harness` | prior id |
| `CHECKLIST_V2_REQUIRED` | `eval_harness` | required item ids |
| `standard_research_eval_checklist_document()` | `eval_harness` | public v2 surface |
| `evaluate_checklist_v2_completeness(...)` | `eval_harness` | completeness → candidate allowed? |
| `run_standard_research_eval(...)` | `eval_harness` | default entry (v2 wired) |
| `standard_research_eval_checklist_run` | `eval_harness` | alias |
| `COST_MODELS_VERSION` | `cost_models` | `research-cost-models/v1` |
| `cost_models_document()` | `cost_models` | public cost surface |
| `build_leverage_short_cost_assumption(...)` | `cost_models` | explicit lev/short block |
| `default_long_only_unlevered_cost_assumption(...)` | `cost_models` | long-only N/A disclosure |
| `short_borrow_daily_cost(...)` | `cost_models` | pure daily borrow |
| `leverage_financing_daily_cost(...)` | `cost_models` | pure daily financing |
| `research_net_with_extended_costs(...)` | `cost_models` | gross − tx − borrow − fin |
| `annotate_period_rows_with_extended_costs(...)` | `cost_models` | period row annotation |
| `RISK_SCENARIOS_VERSION` | `risk_scenarios` | `research-risk-scenarios/v1` |
| `risk_scenarios_document()` | `risk_scenarios` | public scenario surface |
| `evaluate_risk_scenarios(...)` | `risk_scenarios` | min-set eval + stability |
| `scenario_row(...)` | `risk_scenarios` | row builder |
| `default_na_scenario_bundle(...)` | `risk_scenarios` | wiring default (pending core) |

### `run_standard_research_eval` new kwargs (v2)

| kwarg | default | meaning |
|-------|---------|---------|
| `position_style` | `long_only_unlevered` | style for cost model |
| `gross_leverage` | `1.0` | leverage for financing |
| `short_fraction` | `0.0` | short side fraction |
| `short_borrow_annual_bp` / `financing_annual_bp` | model defaults | override rates |
| `leverage_short_cost_assumption` | `None` | prebuilt assumption dict |
| `scenario_rows` | wiring pending bundle | risk scenario metrics |
| `rate_data_usable` / `liquidity_data_available` | `False` | data-dependent required |
| `prefer_fail_on_sign_break` | `True` | stability break → not candidate |
| `scenario_weakness_disclosed` / `notes` | off | disclosure path |
| `high_frequency_hyp` | `False` | makes holding near-required hard |
| `require_holding_for_hf` | `True` | HF holding enforcement |

### Return keys (v2 additions)

| key | meaning |
|-----|---------|
| `checklist_version` | `standard-research-eval-checklist/v2` |
| `leverage_short_costs` | explicit lev/short assumption block |
| `risk_scenarios` | min-set evaluation result |
| `checklist_completeness` | item-level completeness |
| `checklist_complete` | bool |
| `research_candidate_allowed` | bool (False if incomplete) |
| `research_candidate` | **always False** (no auto-promotion) |
| freeze keys | always closed |

---

## Wiring rule: incomplete → not candidate

```text
checklist_complete == False
  → research_candidate_allowed = False
  → research_candidate = False   (harness never sets True)

checklist_complete == True
  → research_candidate_allowed = True (discussion only)
  → research_candidate still False from harness (no auto-promote)
  → ready_declared / mass / phase7 still closed
```

S1–S5 remain `research_baseline_rejected` in `baseline_catalog.py` (not un-rejected by v2).

---

## Tests

`tests/test_standard_research_eval.py`

| test | assert |
|------|--------|
| dry_run wiring | v2 version · Mass NO-GO · READY false · lev/short + risk surfaces |
| incomplete checklist | `research_candidate_allowed=False` |
| complete scenarios | complete allowed, still not auto-candidate; freezes closed |
| sign break prefer fail | not candidate |
| HF holding near-required | missing holding → incomplete |
| S1–S5 rejected | still rejected after demo modes |
| AST | no mass import · v2 string present |

Also: `tests/test_w73_research_guards.py` (S1–S5 + freeze maintain).

---

## Usage

```python
from research.eval_harness import run_standard_research_eval
from research.risk_scenarios import scenario_row, SCENARIO_CRASH, SCENARIO_HIGH_VOL
from research.risk_scenarios import SCENARIO_RATE_UP, SCENARIO_RATE_DOWN, SCENARIO_LIQUIDITY_STRESS

# Wiring-only: incomplete risk metrics → not candidate
out = run_standard_research_eval(dry_run=True)
assert out["checklist_version"] == "standard-research-eval-checklist/v2"
assert out["research_candidate"] is False
assert out["research_candidate_allowed"] is False
assert out["ready_declared"] is False
assert out["mass_research"] == "NO-GO"

# With scenario metrics (still no auto-candidate / no READY)
scen = [
    scenario_row(SCENARIO_CRASH, gross_signed_mean=-0.001, net_one_way_mean=-0.002),
    scenario_row(SCENARIO_HIGH_VOL, gross_signed_mean=-0.0008, net_one_way_mean=-0.0018),
    scenario_row(SCENARIO_RATE_UP, not_applicable=True, na_reason="no rate data"),
    scenario_row(SCENARIO_RATE_DOWN, not_applicable=True, na_reason="no rate data"),
    scenario_row(SCENARIO_LIQUIDITY_STRESS, not_applicable=True, na_reason="no liq data"),
]
out2 = run_standard_research_eval(dry_run=True, scenario_rows=scen)
assert out2["checklist_complete"] is True
assert out2["research_candidate"] is False  # harness never auto-promotes
```

---

## Non-goals (held)

- no Mass / READY auto-connect  
- no S1–S5 un-reject / revive  
- no empty invent COMPLETE  
- no push / no commit required by this wave doc  
- no edge / significance claims  

---

## Related

| artifact | path |
|----------|------|
| Checklist v1 | [`w0815bg_w66_standard_research_eval_checklist_20260815.md`](w0815bg_w66_standard_research_eval_checklist_20260815.md) |
| Gate v2 | `packages/product/research/robustness_gate.py` |
| Cost models | `packages/product/research/cost_models.py` |
| Risk scenarios | `packages/product/research/risk_scenarios.py` |
| Holding metrics | `packages/product/research/holding_metrics.py` |
| Rejected catalog | `packages/product/research/baseline_catalog.py` |
| Standard entry | `run_standard_research_eval` in `eval_harness.py` |
