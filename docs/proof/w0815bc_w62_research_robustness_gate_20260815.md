# W62 / w0815bc — Research robustness gate (合格 ≠ 運用GO)

**Label:** **研究用頑健性ゲート・未宣言**  
**Mass / Phase7 / READY:** **NO-GO / OFF / not declared**  
**Gate pass ⇒ READY/Mass/GO:** **forbidden** (constants + tests)  
**Module:** `packages/product/research/robustness_gate.py`  
**Logs:** [`.glm-logs/w0815bc_w62_gate_hyp/`](../../.glm-logs/w0815bc_w62_gate_hyp/)

## Definition

A hypothesis **passes** only if **all required** criteria hold:

| id | rule | required |
|----|------|----------|
| `multi_period` | ≥ **2** periods with `n_active ≥ 20` and non-null gross signed mean | yes |
| `sign_majority` | strict majority of those periods share the same gross-sign (+ or −) | yes |
| `not_catastrophic` | no eligible period with `|gross_signed_mean| > 0.05` | yes |
| `wf_not_full_flip` | train/test gross signs do not fully reverse (when supplied) | optional (`require_wf_check`) |

**Always attached:** `ready_declared=false` · `operational_go=false` · `connected_to_ready=false` · `connected_to_mass=false` · `mass_research=NO-GO` · no significance/edge claim.

Fail is a **valid research outcome** (record and continue). No force-pass path.

## S1 / S2 / S3 as gate examples (W61 multi-period + WF)

Source metrics: W61 multi-period cross table + w2024q4 walk-forward.

| signal | soft gate (WF advisory) | hard WF check | note |
|--------|-------------------------|---------------|------|
| **S1** topix_rel | **PASS** (majority + gross across 4 windows) | **FAIL** (train/test full sign flip) | Short-window illusion risk; WF flip documented |
| **S2** volume_sign | **PASS** (eligible windows share − gross; sparse fire) | PASS | Pass ≠ useful; fire-rate unstable historically |
| **S3** topix+disc | **PASS** (majority + gross) | PASS | Still **not** READY; cost often kills net |

**Research reading (未宣言):**  
Even when the soft multi-period sign majority holds, **S1 fails the optional hard WF check**. Treat soft pass as a weak checklist only — **never** as GO. Tip-20d S1 win remains non-generalizable.

## API

```text
evaluate_research_robustness_gate(period_rows, signal_id=..., walk_forward=..., require_wf_check=False)
→ {passed, reasons, criteria, ready_declared: false, operational_go: false, ...}
```

Harness re-exports: `research.eval_harness.evaluate_research_robustness_gate`.
