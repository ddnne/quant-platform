# コアエンジン（Phase 3 最小）

`core/` は **ブラックボックス** のバックテストエンジン。エージェント・研究コードは
[`run_backtest`](#entry-api) を呼び出し [`BacktestResult`](#結果) を消費するだけで、
内部には触らない。Phase 3 は **最小** 実装: 日足・1〜2 執行モード・標準/ストレス費用・
再現性メタデータを備える。features registry / agents / FoF / Risk / optimizer / broker /
分足・Tick 執行は対象外。

## データ境界（構造で強制）

- **fact は `pit.get_*` 経由のみ。** `core/` は `sqlite3` / `storage` / HTTP クライアントを
  import しない（`tests/test_core_data_boundary.py` が静的に検査）。
- 戦略には [`BarContext`](#戦略プロトコル) 経由で **意思決定 `as_of` 時点で既に PIT 読み出し済み**
  のデータだけを渡す。戦略は `pit` / SQLite に触るハンドルを一切持たない。
- これにより look-ahead は **2 重** に防がれる:
  1. PIT が `available_at <= as_of` で未来行を隠す。
  2. 執行定義が「D のシグナルは D に約定しない（next_close）」を保証する。

## 戦略プロトコル（narrow）

```python
class Strategy(Protocol):
    def on_bar(self, ctx: BarContext) -> list[OrderIntent]: ...
```

`BarContext` は以下のみを持つ（DB/PIT ハンドルなし）:

| フィールド | 内容 |
|-----------|------|
| `as_of` | 意思決定の PIT インスタント（JST ISO）|
| `date` | 意思決定の営業日 `YYYY-MM-DD` |
| `universe` | `as_of` 時点の取引可能銘柄（PIT マスター由来・生き残りバイアス排除の第一歩）|
| `positions` | 現ポジション（code -> `Position`）|
| `cash` / `equity` | 現金 / 含み益評価額 |
| `prices` | universe 各銘柄の最終可視終値（`None` 値あり）|
| `bars` | universe 各銘柄の直近 PIT 可視日足（古い順）|
| `master` | 各銘柄の `as_of` 時点の最新マスター |

`OrderIntent(code, target_weight)` はポートフォリオ評価額に対する **目標ウェイト**。
- 戦略が `on_bar` で **返さなかった** 銘柄は維持（売却強制しない）→ 買い持ち戦略は初日のみ
  オーダを出し翌日以降 `[]` でホールドできる。
- 目標ウェイト → 目標株数 → 現ポジとの差分（delta）を執行。同じ目標なら取引ゼロ・費用ゼロ。
- ショートはフラットにクリップ（最小エンジンの対象外）。正の可視価格が無い銘柄はスキップ。

## ユニバース（anti-survivorship 第一步）

- 既定では各意思決定日の `as_of` で `pit.get_equity_master` を読み、**その時点で存在した**
  最新の全銘柄Snapshotだけからユニバースを作る。後から上場/廃止された銘柄は、その
  Snapshotが可視になった日に自動的に出入りし、古い銘柄別行は残存させない。
- `run_backtest(..., universe=["1332","8697"])` で固定ユニバースも指定可能（高速化・テスト用）。
- より細かいフィルタ（業種/規模/流動性/上場状態フラグ）は最小エンジンの対象外。

## 執行モード（1〜2）

| モード | 意思決定 `as_of` | 約定 | look-ahead 備考 |
|--------|------------------|------|-----------------|
| `next_close`（既定）| D の引け（15:30、2024-11-04 以前は 15:00 JST）| **翌営業日** の引け | D のシグナルは D に約定しない。D の引けが可視でも安全。|
| `same_day_close` | D の寄引 **09:00 JST**（引け前）| D の引け | 意思決定情報集合は D の引けを **含まない**。寄付決定・大引約定。|

- 注文は約定対象セッション当日の日足が可視でなければ古い終値では約定せず、
  `next_close` では翌営業日に持ち越す（`same_day_close` ではスキップ）。
- 最終営業日に決定した注文は約定機会が無い（文書化された挙動）。

株式分割・併合で保有評価に架空損益を入れないため、`adjustment_close` がある日足は
目標株数・約定・評価のすべてに調整後価格を一貫して用いる。

## 費用

[`CostModel`](../core/costs.py) は **片道固定 bps**（買い/売り対称）。

- `standard_cost(bps=5.0)` — 既定 5bps 片道。
- `stress_cost(multiple=5.0, base_bps=5.0)` — 標準の `multiple` 倍（感度/ロバスト性）。

費用は約定時に現金から即時控除。pre-cost 指標は「費用が無かったはずの終了時評価額」を
（ポジション同一を仮定して）復元するため、コスト設定を変えても pre-cost リターンは不変・
post-cost リターンのみ変化する（`tests/test_core_engine.py::test_costs_change_post_cost_not_pre_cost`）。

## 指標（metrics subset）

- `total_return_pre_cost` / `total_return_post_cost`
- `max_drawdown`（post-cost 評価額曲線のピークtoトラフ）
- `cost_drag`（累積費用）
- `num_trades`, `turnover_notional`（片道売買代金の絶対値累計＝ターンオーバー代理）, `num_trading_days`

## カレンダー

- 営業日は `pit.get_market_calendar` から `holiday_division == "1"`（立会あり）で構築。
  非営業日はスキップ。カレンダーは `as_of = close_as_of(end)`（既定; `calendar_as_of=` で上書き可）で読む。
- 引け時刻は 2024-11-05 以降 15:30、それより前 15:00 JST（`core.execution` が日付で切替）。

## Entry API

```python
from core import run_backtest, standard_cost, stress_cost
from core.strategies.buy_hold import BuyHold

result = run_backtest(
    BuyHold(),
    start="2025-04-01",
    end="2025-05-31",
    *,
    db_path="data/structured/ingestion.sqlite",
    execution_mode="next_close",      # or "same_day_close"
    cost_model=standard_cost(),       # default; stress_cost() も可
    universe=None,                    # None=マスターから日次構築, 固定 list 可
    starting_capital=1_000_000.0,
    lookback_days=30,
    calendar_as_of=None,
)
```

日次ループ: 各営業日 D について、D の **意思決定 `as_of`** で `pit.get_*` を読み
`BarContext` を組み、`strategy.on_bar(ctx)` を呼び、執行モードに従って約定させる。

## 結果

`BacktestResult`:

- `equity_curve`: 各営業日の `{date, cash, positions_value, equity}`（post-cost、引け評価）。
- `trades`: `{decision_date, fill_date, code, side, shares, price, notional, cost}`。
- `metrics`: 上記指標 subset。
- `metadata`: **再現性ブロック**。`core_engine_version` / `pit_api_version` / `start` / `end` /
  `execution_mode` / `as_of_rule` / `cost_model` / `universe_rule` / `lookback_days` /
  `starting_capital` / `strategy_id` / `strategy_params` / `strategy_params_hash` / `db_path` /
  `trading_days`。ウォールクロック時刻・乱数に依存しないため、同一入力 → 同一メタデータ
  （`tests/test_core_engine.py::test_reproducibility_same_config_same_result`）。

## 制限（今後の Phase）

- 整数株・ロット丸めなし（浮動小数株）。ショート未対応（フラットにクリップ）。
- 指値/不成/VWAP 等の執行厚み・分足・Tick は対象外。
- ユニバースの流動性/業種/規模フィルタ、明示的な上場状態フラグ、決算・開示イベントの
  特徴量化は features registry（Phase 4）以降。
- pre-cost 指標は費用解放cashの再投資リターンを無視する近似。
