# Paper pipeline（Phase 5）

Phase 5 は、アイデア／戦略パラメータを **仮想執行（Paper）** の結果として保存するまでを
縦に接続する。入口は `PaperRunConfig` と `run_paper`、計算本体は `features` と
`core.run_backtest`、出力は `PaperRunResult` である。実注文や broker API は扱わない。

```text
idea / strategy params
  -> features (PIT + required as_of)
  -> core.run_backtest (next_close by default)
  -> PaperRunResult + reproducibility metadata
  -> data/paper/<strategy_id>/<run_id>.json
  -> optional simple report
```

## 境界と look-ahead 防止

- fact の読み出しは必ず `pit` を通り、すべての読み出しに明示的な `as_of` が必要。
- 戦略が利用する派生値は `features` で計算し、シミュレーションは `core` をブラックボックス
  として利用する。
- 戦略モジュールは `pit`、`storage`、`sqlite3`、HTTP クライアント、J-Quants、secrets を
  import／利用しない。DB の raw handle や SQL を戦略に渡さない。
- 既定の `next_close` は D 日の引け時点で意思決定し、翌営業日の引けで約定する。
  PIT の `available_at <= as_of` と執行時点の分離で look-ahead を防ぐ。
- J-Quants を含む外部 API は ingestion-only。Paper 実行中にネットワーク取得しない。

## Entry API

```python
from strategies.examples import MomentumFeatureStrategy
from strategies.paper import JsonPaperStore, PaperRunConfig, run_paper

config = PaperRunConfig(
    start="2025-04-01",
    end="2025-05-31",
    db_path="data/structured/ingestion.sqlite",
    execution_mode="next_close",
    universe=("8697",),
)
strategy = MomentumFeatureStrategy(
    db_path=config.db_path,
    n=20,
    top_k=1,
    min_momentum=0.0,
)
result = run_paper(
    strategy=strategy,
    config=config,
    store=JsonPaperStore(),
)
print(result.run_id, result.metrics["total_return_post_cost"])
```

`PaperRunConfig` が期間、費用、執行、資本、ユニバース、特徴量／PIT の DB path を固定し、
戦略インスタンスが `strategy_id` と戦略パラメータを公開する。`run_paper` は設定を
`core.run_backtest` に渡し、その結果を Paper 固有の識別子・lifecycle・再現性情報とともに
`PaperRunResult` にまとめる。

## Result と保存

`PaperRunResult` は少なくとも次を保持する。

- `run_id`, `strategy_id`, lifecycle（`Draft` または `Paper`）
- `metrics`（pre/post-cost return、drawdown、cost drag、trade count など）
- `trades` と `equity_curve`
- 実行条件を再現する `reproducibility`

`reproducibility` には `core_engine_version`、`pit_api_version`、feature id/version と
features runtime version、期間、execution mode、`as_of` rule、cost model、strategy id、
strategy params と hash、universe、starting capital、lookback、DB path を含める。実 DB を使う
live smoke では DB fingerprint も記録し、同じコードだけでなく同じ入力 snapshot を識別できる
ようにする。API key、proxy token などの secret は結果に保存しない。

`JsonPaperStore` の既定保存先は次のとおり。

```text
data/paper/<strategy_id>/<run_id>.json
```

JSON は結果全体を自己完結に保持する。`run_id` は再現性情報とバックテスト結果から決定論的に
生成するため、内容が異なる run は別の保存先になる。wall-clock 生成時刻は決定論的な結果／
再現性 hash に混ぜない。simple report は保存済み result の要約であり、計算の正本は JSON とする。

## Lifecycle

Phase 5 の最小 lifecycle は 2 段階だけである。

| label | 意味 |
|-------|------|
| `Draft` | 設定作成中、または Paper として採用前の研究 run |
| `Paper` | 仮想執行結果として保存・比較する run。live order を意味しない |

label は研究結果の分類であり、broker 接続や注文権限を付与しない。Phase 6 以降の役割
エージェントも、この境界を越えて live order を生成しない。

## Sample strategies

- `Return1dFeatureStrategy`: `return_1d` が閾値を上回る銘柄を等ウェイトで保有する rule。
- `MomentumFeatureStrategy`: `momentum_n` が閾値以上の上位 `top_k` 銘柄を等ウェイトで
  保有する rule。

両者は `features` の公開 API だけを利用する。注入された `db_path` は `features.compute` に
渡すためだけの値であり、戦略自身が開いたり SQL を実行したりしない。サンプルは予測力の
主張ではなく、Paper pipeline の境界と再現性を示す用途である。

## CLI

fixture DB など既存の structured DB に対して 1 run を実行する。

```bash
.venv/bin/python scripts/run_paper_once.py --help
.venv/bin/python scripts/run_paper_once.py \
  --strategy return-1d \
  --start 2025-04-01 \
  --end 2025-05-31 \
  --db data/structured/ingestion.sqlite \
  --universe 8697
```

CLI は ingestion を起動せず、指定 DB を PIT 経由で読むだけである。結果は既定で
`data/paper/` 以下へ保存する。具体的な引数と既定値は `--help` を正本とする。

## Verify

通常の検証は API key・ネットワーク不要で完結する。

```bash
.venv/bin/python -m pytest tests/test_paper*.py tests/test_phase4*.py -q
.venv/bin/python -m pytest -q
.venv/bin/python scripts/run_paper_once.py --help
```

本番同期済み DB の任意 smoke は、先に Phase 3.5 の B0 strict pass を確認してから明示的に
有効化する。

```bash
QP_LIVE=1 .venv/bin/python scripts/run_paper_once.py \
  --strategy return-1d --start 2026-04-01 --end 2026-06-30 \
  --db data/structured/ingestion.sqlite --universe 7203,6758,9984
```

`QP_LIVE=1` は live broker を意味せず、local fixture ではなく実データ snapshot を使う
Paper smoke の opt-in である。

## Scope

Phase 5 の対象外は、実注文／broker API、FoF と Risk agent の本実装、戦略の大量生成、addon
dataset、指値・VWAP・分足／Tick 執行である。次の Phase 6 では、ここで固定した Paper 境界と
保存結果を利用する役割エージェントへ進む。
