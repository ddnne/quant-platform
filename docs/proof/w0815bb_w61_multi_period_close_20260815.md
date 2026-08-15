# W61 / w0815bb — close: multi-period + research walk-forward

**Phase name:** COMPLETE 21 複数期間シグナル再評価 + 研究用 WF（宣言なし）  
**Wave:** W61 / w0815bb  
**Mass / Phase7 / READY:** **NO-GO / OFF / not declared**

## Deliverables

| lane | result |
|------|--------|
| A multi-period S1/S2/S3 | **PASS** · 4 windows · [`w0815bb_w61_multi_period_multisignal_20260815.md`](w0815bb_w61_multi_period_multisignal_20260815.md) |
| B research walk-forward | **PASS** · API + w2024q4 train/test · [`w0815bb_w61_walk_forward_research_20260815.md`](w0815bb_w61_walk_forward_research_20260815.md) |
| C coverage inventory | **PASS** · [`w0815bb_w61_coverage_inventory_20260815.md`](w0815bb_w61_coverage_inventory_20260815.md) |
| D quality | tests + FRESH + residual + push |

## Code

- `packages/product/research/eval_harness.py` — `split_asof_days_walk_forward` · `run_multisignal_compare` · `run_research_walk_forward_multisignal` · `run_multi_period_multisignal_compare`
- `tests/test_eval_harness.py` — WF + multi-period fixtures

## Explicit non-declarations

READY / Mass / Phase7 GO / densify invent / look-ahead / edge / significance / orders — **refused**.
