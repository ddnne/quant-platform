# W80 / w0816o — Task D: paper receptacle for candidates (UNARMED)

**Phase:** research candidate → paper-readable StrategySpec receptacle  
**Wave:** W80 / `w0816o` · 2026-08-16  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Task:** **D** paper receptacle adapter · example specs · unarmed tests  
**Logs / examples:** [`.glm-logs/w0816o_w80_candidate/paper_specs/`](../../.glm-logs/w0816o_w80_candidate/paper_specs/)  
**Prior:** W79 class_hyp candidates (`multi_day_hold_10` · `event_post` discussion_only) · W78 multi_day_hold · StrategySpec v2 paper runner

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| **paper_scheduler_armed** | **False** (not continuous) |
| **live_orders / live_order_path** | **False** |
| **READY** | **未宣言** (`ready_declared=False`) |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| **operational GO** | **closed** |
| edge / significance | **none** |
| auto `research_candidate` promote | **none** (adapter always False) |
| S1–S5 un-reject | **forbidden** |
| push / commit | **not this task** |

Paper = **pseudo ops between research and live**. This wave only adds an **UNARMED receptacle** — it does **not** schedule paper continuously, does **not** call `run_paper` / `PaperExecutionService`, and does **not** touch the live order path.

---

## Task D — Delivered

### Code

| artifact | path | role |
|----------|------|------|
| **Paper candidate adapter** | [`packages/product/research/paper_candidate_adapter.py`](../../packages/product/research/paper_candidate_adapter.py) | class_hyp / research candidate → paper-readable envelope + nested StrategySpec |
| Research exports | [`packages/product/research/__init__.py`](../../packages/product/research/__init__.py) | `adapt_class_hyp_candidate` · `emit_example_paper_specs` · … |
| Unit tests | [`tests/test_paper_candidate_adapter.py`](../../tests/test_paper_candidate_adapter.py) | unarmed surface · hostile input strip · StrategySpec interpret · no runner import |
| Example specs | [`.glm-logs/w0816o_w80_candidate/paper_specs/`](../../.glm-logs/w0816o_w80_candidate/paper_specs/) | multi_day_hold 10d + event_post (+ bare StrategySpec JSON) |

### Adapter path (return value for orchestrator)

```text
packages/product/research/paper_candidate_adapter.py
```

Public entry:

```python
from research.paper_candidate_adapter import (
    adapt_class_hyp_candidate,
    adapt_from_class_hyp_bundle,
    emit_example_paper_specs,
    assert_unarmed,
)
```

---

## Mapping contract

### Input (research)

* class_hyp multi-year class blocks (`multi_day_hold_10`, `event_post`, …)
* free-form candidate payloads with `hypothesis_class` / `signal_id` / `candidate`
* optional hostile arm/live/go keys (must be stripped)

### Output (paper-readable receptacle)

Schema version: **`paper-candidate-spec/v1`**

Aligned fields (task contract):

| field | meaning |
|-------|---------|
| `horizon` | research horizon string (e.g. `10d_hold`, `1d_to_5d_post_event`) |
| `costs` | one_way / bp / amortized / `cost_bps` for PaperRunConfig alignment |
| `universe` | class registry universe (or payload codes) |
| `rebalance` | research rebalance intent (e.g. `every_10d_fixed_horizon`) |
| `strategy_spec` | closed **StrategySpec v2** (`rebalance` remains `"daily"` per schema) |

Nested StrategySpec is interpreter-valid (approved features only). Research multi-day / event rebalance lives on the **envelope**, not by extending StrategySpec schema.

### Class → StrategySpec

| class | fidelity | StrategySpec rule |
|-------|----------|-------------------|
| `multi_day_hold` (10d) | **aligned** | `top_k` · `momentum_n` `n=10` |
| `event_post` | **proxy** (discussion_only) | `threshold` · `disclosure_flag_fins` ≥ 0.5 |

**event_post note:** full surprise-proxy sticky hold is **not** expressible in StrategySpec v2 rule language. The receptacle is still emitted for paper readiness discussion; fidelity=`proxy`.

### Always forced closed (even if input says otherwise)

```text
paper_scheduler_armed = False
paper_continuous = False
live_orders = False
live_order_path_enabled = False
ready_declared = False
operational_go = False
mass_research = NO-GO
phase7 = OFF
research_candidate = False   # never auto-promote
paper_run_hints.scheduler_armed / run_now / continuous = False
```

---

## Example specs emitted

Directory: `.glm-logs/w0816o_w80_candidate/paper_specs/`

| file | content |
|------|---------|
| `multi_day_hold_10d.json` | full unarmed receptacle (prefer W79 bundle when present) |
| `multi_day_hold_10d_strategy_spec.json` | bare StrategySpec for paper consumers |
| `event_post.json` | full unarmed receptacle (discussion_only proxy) |
| `event_post_strategy_spec.json` | bare StrategySpec |
| `index.json` | inventory + freeze surface |

Source preference: W79  
`.glm-logs/w0816n_w79_go_final/class_hyp_multi_year_bundle.json`  
when available; otherwise synthetic discussion_only payloads (still unarmed).

---

## Tests (proof)

```bash
.venv/bin/python -m pytest tests/test_paper_candidate_adapter.py -q
```

Coverage:

1. Module constants unarmed  
2. multi_day_hold 10d StrategySpec interpretable (approved `momentum_n`)  
3. event_post StrategySpec interpretable (approved `disclosure_flag_fins`)  
4. horizon / costs / universe / rebalance alignment  
5. **Hostile input** (`paper_scheduler_armed=True`, `live_orders=True`, `mass_research=GO`, …) → output closed  
6. `assert_unarmed` rejects arm/live/go/ready/mass/phase7  
7. never auto-promotes `research_candidate`  
8. bundle adapter keys  
9. `emit_example_paper_specs` writes unarmed files  
10. **Static AST:** no `run_paper` / `PaperExecutionService` / `execution` import; constants not True  

---

## Non-goals (explicit)

* Continuous paper scheduler arming  
* Live orders / broker / trader prepare  
* Mass / READY / Phase7 / operational GO  
* Auto-promote research_candidate  
* Extending StrategySpec closed schema  
* Commit / push  

---

## Adapter path (summary)

```text
/Users/taku/GitHub/quant-platform/packages/product/research/paper_candidate_adapter.py
```

Paper runner (existing, **not called** by adapter):

```text
packages/research_runtime/strategies/paper/runner.py
packages/research_runtime/strategies/spec/schema.py   # StrategySpec
packages/product/execution/paper_service.py           # authority gate (untouched)
```
