# strategies

feature-driven 戦略と Paper（仮想執行）実験の入口。Phase 5–6 では次を提供する。

- `paper/`: `PaperRunConfig`、`run_paper`、`PaperRunResult`、`JsonPaperStore`
- `examples/`: `Return1dFeatureStrategy`、`MomentumFeatureStrategy`
- `spec/`: closed `StrategySpec` schema と approved-feature whitelist interpreter

```text
strategy params -> features -> core.run_backtest -> PaperRunResult -> JsonPaperStore
```

戦略モジュールは `pit`、`storage`、`sqlite3`、HTTP、J-Quants、secrets を直接利用しない。
fact は必須 `as_of` 付きの PIT、派生値は `features`、執行は `core` にそれぞれ閉じ込める。
Paper は live broker／real order を含まない。

使い方、保存規約、reproducibility metadata、offline／optional live smoke は
[Paper pipeline](../docs/paper.md) を参照。
