# W61 / w0815bb — Research walk-forward (fixed S1/S2/S3)

**Label:** **小サンプル / 研究用ウォークフォワード・未宣言**  
**Mass / Phase7 / READY:** **NO-GO / OFF / not declared**  
**Threshold tuning:** **false** (definitions fixed on both folds)  
**API:** `research.eval_harness.split_asof_days_walk_forward` · `run_research_walk_forward_multisignal`  
**Job:** `w0815bb-g1-wf-w2024q4`  
**Log:** [`.glm-logs/w0815bb_w61_multiperiod/walk_forward_w2024q4.json`](../../.glm-logs/w0815bb_w61_multiperiod/walk_forward_w2024q4.json)

## Procedure (research-only)

1. Load one long window (`w2024q4`, 50 as_of days via `history_source=r2`).  
2. Chronological split: first ~50% **train**, remainder **test** (`train_fraction=0.5`).  
3. Evaluate **the same** S1/S2/S3 definitions (volume abs min **0.10** fixed) on each fold.  
4. **Do not** search thresholds on train.  
5. Record mean/median / non_null / 10bp net per fold.  
6. **Not** connected to READY, Mass, or orders.

## Split

| fold | as_of span | n_days |
|------|------------|-------:|
| train | 2024-10-08 … 2024-11-13 | **25** |
| test | 2024-11-14 … 2024-12-18 | **25** |
| full | 2024-10-08 … 2024-12-18 | **50** |

## Results (研究用・未宣言)

### S1

| fold | mean R +1 | mean R −1 | gross signed | net 10bp |
|------|----------:|----------:|-------------:|---------:|
| train | −0.00089 | +0.00041 | −0.00068 | (cost worse) |
| test | +0.00072 | −0.00080 | +0.00076 | (see log) |
| full | −0.00018 | −0.00024 | ~0 | −0.00097 |

### S2

| fold | non_null | gross signed |
|------|---------:|-------------:|
| train | **0.000** | — |
| test | 0.093 | −0.00028 |
| full | 0.047 | −0.00028 |

### S3

| fold | non_null | gross signed |
|------|---------:|-------------:|
| train | 0.273 | +0.00049 |
| test | 0.999 | +0.00074 |
| full | 0.636 | +0.00069 |

## Research read (未宣言)

- Within a single 50d window, **train vs test S1 sign pattern is unstable** (train gross negative; test mildly positive).  
- This supports **not** promoting a single tip-window or single long-window print to a strategy default.  
- Procedure is a **research holdout scaffold** only — not production walk-forward, not GO.

## Non-declarations

READY **not** declared · Mass **NO-GO** · Phase7 **OFF** · no edge / significance / operational GO.
