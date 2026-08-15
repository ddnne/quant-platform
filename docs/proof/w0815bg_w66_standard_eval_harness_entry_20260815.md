# W66 / w0815bg — Standard eval harness entry

**Phase:** 標準研究評価エントリ固定（READY 未宣言）  
**Wave:** W66 / w0815bg · 2026-08-15  
**Implementer:** GLM5.3 (Grok does not implement)  
**Function:** `research.eval_harness.run_standard_research_eval`  
**Alias:** `standard_research_eval_checklist_run`  
**Checklist proof:** [`w0815bg_w66_standard_research_eval_checklist_20260815.md`](w0815bg_w66_standard_research_eval_checklist_20260815.md)

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| `research_candidate` auto | **False** (never set by this entry) |
| edge / densify / orders | **none** |

## Delivered API

| symbol | role |
|--------|------|
| `CHECKLIST_VERSION` | `standard-research-eval-checklist/v1` |
| `standard_research_eval_checklist_document()` | public checklist surface + rejected baseline refs |
| `run_standard_research_eval(...)` | one-shot standard entry |
| `standard_research_eval_checklist_run` | alias of the above |

### Modes

| mode | behavior |
|------|----------|
| `wiring_only` (default) | design multi-year windows · cost · gap notes · gate surface · freezes; **no heavy R2** |
| `s1_rejected_baseline` | re-run `run_multi_year_s1_eval` (catalog rejected; not a new signal) |
| `s4_rejected_baseline` | re-run `run_multi_year_extra_hyp_eval` for S4 (rejected) |

### Return keys (minimum)

| key | meaning |
|-----|---------|
| `checklist_version` | checklist id |
| `steps_completed` | ordered procedure steps |
| `robustness_gate` | v2 cost-aware gate result or surface |
| `cost_assumption` | default 10bp one-way; change needs `cost_change_reason` |
| `data_gap_notes` | required disclosure (inventory + per-period) |
| `holding` | recommended annotation or full `holding_metrics_report` |
| `research_candidate` | always **False** |
| `ready_declared` / `mass_research` / `phase7` | always closed |
| `new_signals_registered` | always **False** |
| `gate_pass_implies_*` | always **False** |

### Defaults

- `dry_run=True` — validates wiring without heavy R2 when no executable fixtures
- `one_way_cost=0.001` (10bp); non-default requires `cost_change_reason`
- `require_net_sign_majority=True` (gate v2)
- `include_holding=True` (annotation if no panel records)
- Does **not** invent new signals; short-window-only remains **insufficient**

## Tests

`tests/test_standard_research_eval.py`

| test | assert |
|------|--------|
| dry_run wiring | ready_declared=False · mass NO-GO · phase7 OFF |
| gate pass | still not READY / not research_candidate |
| no new signals | `new_signals_registered=False` · catalog size unchanged |
| rejected baselines | S1–S5 still `research_baseline_rejected` after demo modes |
| cost change | reason required |
| holding optional | panel path + freeze closed |
| AST / modes | no mass import · modes closed set |

## Non-goals (held)

- no new daily sign signals  
- no S1–S5 un-reject  
- no READY / Mass / Phase7 ON  
- no densify / COMPLETE invent  
- no mass artifacts  
- no edge claims  

## Usage

```python
from research.eval_harness import run_standard_research_eval

out = run_standard_research_eval(dry_run=True)
assert out["checklist_version"] == "standard-research-eval-checklist/v1"
assert out["ready_declared"] is False
assert out["mass_research"] == "NO-GO"
assert out["phase7"] == "OFF"
assert out["research_candidate"] is False
```

Rejected-baseline dry demo (still rejected after):

```python
out = run_standard_research_eval(dry_run=True, mode="s1_rejected_baseline")
assert out["baseline_demo"]["still_rejected"] is True
```
