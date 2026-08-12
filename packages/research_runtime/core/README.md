# core

**コアエンジン**（Phase 3 最小実装）— ブラックボックスのバックテスト基盤。

エージェント・研究コードは `core.run_backtest` を呼び出して `BacktestResult` を消費するだけで、
コアを改変しない。入力となる構造化データは **PIT Data API（`pit/`・`as_of` 必須）経由でのみ**
読み出す（`core/` は SQLite/HTTP を直接開かない・`tests/test_core_data_boundary.py` が静的に強制。
look-ahead は PIT の `available_at <= as_of` と執行定義の 2 重構造で防止）。

## 主な API

- `core.run_backtest(strategy, start, end, *, db_path, execution_mode, cost_model, ...)` — エントリポイント。
- `core.Strategy` / `BarContext` / `OrderIntent` — 戦略プロトコル（narrow）。
- `core.NEXT_CLOSE` / `core.SAME_DAY_CLOSE` — 執行モード。
- `core.standard_cost` / `core.stress_cost` — 費用モデル。
- `core.BacktestResult` — equity_curve / trades / metrics / 再現性 metadata。
- price basis は `RAW` のみ有効。`PIT_ADJUSTED` は adjustment provenance が
  PIT-safe と証明されるまで fail-closed。
- signal の `lookback_days` と valuation mark は独立。当日 bar が無い保有銘柄は
  最後の PIT-safe mark を繰り越すが、当日 bar 無しでは約定しない。

詳細は [../docs/core_engine.md](../docs/core_engine.md)。

## 構成

| ファイル | 役割 |
|---------|------|
| `engine.py` | 日次バックテストループ・`run_backtest` |
| `strategy_protocol.py` | narrow な `BarContext`/`OrderIntent`/`Strategy` |
| `universe.py` | PIT マスター由来の as-of ユニバース（anti-survivorship） |
| `execution.py` | 執行モード定義（next_close / same_day_close）・as_of ヘルパ |
| `costs.py` | 費用モデル（標準 / ストレス） |
| `metrics.py` | 指標 subset（pre/post return・MaxDD・trade count・turnover） |
| `result.py` | `BacktestResult` + 再現性 metadata |
| `strategies/buy_hold.py` | テスト用ダミー戦略（買い持ち）|
