# W60 / w0815ba — close: long multi-signal + bridge expand

**Wave:** W60 / w0815ba  
**Phase name:** COMPLETE 21 長期窓マルチシグナル比較 + 橋拡張（宣言なし）  
**Mass / Phase7:** **NO-GO / OFF**  
**READY:** **not** declared  

## Deliverables

| lane | result |
|------|--------|
| A. Long multi-signal S1/S2/S3 | **PASS** · job `w0815ba-g1-long-multisignal` · 50d×30 · `history_source=r2` · report [`w0815ba_w60_long_multisignal_compare_20260815.md`](w0815ba_w60_long_multisignal_compare_20260815.md) |
| B. Bridge expand | **PASS** · margin/short/fins/alert loaders + aa policy · [`w0815ba_w60_bridge_expand_20260815.md`](w0815ba_w60_bridge_expand_20260815.md) |
| C. Quality | pytest (r2 + harness + complete21 + defer + mass) **pass** · FRESH `projgen-acdc868d174e4304ae93da453c01f057` · residual updated · **push required** |

## Live metrics (ops)

| metric | value |
|--------|------:|
| Dataset COMPLETE | **21** |
| PARTIAL (DEFER) | **5** |
| COMPLETE segs | **3478** |
| empty COMPLETE | **0** |
| OTC COMPLETE segs | **93** (`jsda_otc_bond_reference_prices`) |
| Projection | **FRESH** `projgen-acdc868d174e4304ae93da453c01f057` |
| actionable_gap | **0** (held) |

## Code surface

- `packages/product/research/r2_feature_context.py` — expand datasets · aa policy · allow_empty · repair  
- `packages/product/research/single_shot_job.py` — multi-signal `history_source=r2` · DiscDate aliases  
- `tests/test_r2_feature_context.py` — bridge expand · aa · multi-signal r2  

## Explicit non-declarations

READY / Mass / Phase7 GO / densify / COMPLETE 22 / `return_1d_c21` promote / look-ahead / significance / edge / orders — **all refused**.
