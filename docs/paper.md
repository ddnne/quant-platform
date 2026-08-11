# Paper pipeline（Phase 5 / 5.5）

Phase 5 は、アイデア／戦略パラメータを **仮想執行（Paper）** の結果として保存するまでを
縦に接続する。入口は `PaperRunConfig` と `run_paper`、計算本体は `features` と
`core.run_backtest`、出力は `PaperRunResult` である。実注文や broker API は扱わない。

```text
idea / strategy params
  -> features (PIT + required as_of)
  -> core.run_backtest (next_close by default)
  -> PaperRunResult + reproducibility metadata
  -> data/paper/<strategy_id>/<experiment_id>/<run_id>.json
  -> data/paper/index.jsonl
  -> optional simple report
```

## 境界と look-ahead 防止

- fact の読み出しは必ず `pit` を通り、すべての読み出しに明示的な `as_of` が必要。
- 戦略が利用する派生値は `BarContext.feature(...)`（`ctx.feature(...)`）で要求する。
  trusted runtime が `ctx.as_of` と DB path を自動的に束縛して `features` を呼び出すため、
  戦略は `as_of` や DB path を差し替えられない。
- 戦略モジュールは `pit`、`storage`、`sqlite3`、HTTP クライアント、J-Quants、secrets を
  import／利用しない。戦略の data interface は狭い `BarContext` だけとし、DB path、
  raw handle、SQL、PIT handle を戦略の constructor や `on_bar` に渡さない。
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
    price_basis="RAW",
)
strategy = MomentumFeatureStrategy(
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
戦略インスタンスが `strategy_id` と戦略パラメータを公開する。DB path は
trusted runtime configuration に限定され、戦略には公開されない。`run_paper` は設定を
`core.run_backtest` に渡し、各 bar で PIT-scoped feature accessor を含む `BarContext` を構築する。
その結果を Paper 固有の識別子・lifecycle・再現性情報とともに `PaperRunResult` にまとめる。
`price_basis` は Core/Features と同じ `RAW` を既定かつ唯一の有効値とし、provenance が未証明の
vendor adjusted history を要求する `PIT_ADJUSTED` は fail-closed とする。

## Result と保存

`PaperRunResult` は少なくとも次を保持する。

- `experiment_id`, `run_id`, `strategy_id`, lifecycle（`Draft` または `Paper`）
- `metrics`（pre/post-cost return、drawdown、cost drag、trade count など）
- `trades` と `equity_curve`
- 実行条件を再現する `reproducibility`

`reproducibility` には `core_engine_version`、`pit_api_version`、feature id/version と
feature definition hash、features runtime version、期間、execution mode、`as_of` rule、cost model、
strategy id/params/hash、strategy definition hash、universe、starting capital、lookback、
`price_basis`、`data_snapshot_id`、取得できる場合は `git_commit` を含める。API key、proxy token などの
secret は結果に保存しない。

### Data snapshot ID

`data_snapshot_id` は SQLite 全体の payload hash ではなく、軽量な control-plane state の
決定論的 hash である。schema version/marker、ソート済み ingestion watermark
（dataset、last event date、last ingested time）、利用できる validation state や key table の
count / `MAX(ingested_at)` などから生成する。watermark が無い DB のみ、main DB の file
size / mtime を weak fallback として使う。これは完全な payload 同一性の証明ではなく、
Phase 6 の multi-experiment で安価に入力状態を区別するための ID である。

runtime は run 前に一度 snapshot ID を決定して result に保存し、run 後に再計算する。
両者が異なる場合は実行中に入力状態が変更されたとみなし、fail closed とする。

Production research は mutable な sync/staging DB を直接使わず、content-addressed な
READY artifact を `paper_runtime.latest_ready_snapshot` /
`open_ready_snapshot` で解決する。READY manifest の `snapshot_id` がそのまま
`data_snapshot_id` になる。publication lifecycle、coverage ledger、strict quality gate は
[`phase6_snapshot_publication.md`](phase6_snapshot_publication.md) を参照。

### Experiment, run, lifecycle

- `experiment_id` は strategy id/params、feature version／定義 hash、`data_snapshot_id`、期間、
  execution/cost/universe などの engine configuration の決定論的 hash である。
  lifecycle、promotion state、wall-clock 時刻は含めない。
- `run_id` は 1 回の実行結果の識別子である。Phase 5.5 の pure backtest では
  `run_id = experiment_id` とする決定論的 policy を採用し、同じ入力とコードの再実行は
  同じ ID になる。wall-clock 時刻や lifecycle は混ぜない。
- lifecycle は `Draft` / `Paper` の可変 label であり、experiment の同一性とは分離する。

`JsonPaperStore` の既定保存先は次のとおり。

```text
data/paper/<strategy_id>/<experiment_id>/<run_id>.json
```

JSON は result schema v2 として結果全体を自己完結に保持する。既存の v1 result は
互換 load の対象とする。軽量な `data/paper/index.jsonl` に experiment/run、lifecycle、
snapshot、期間、主要 metrics、feature IDs、result path を索引し、`experiment_id` から
run を検索できる。simple report は保存済み result の要約であり、計算の正本は
JSON とする。

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

両者は `BarContext` の `ctx.feature(...)` だけを介して feature を利用する。戦略は
`db_path` を constructor で受け取らず、`features.compute` や SQL を直接呼び出さない。サンプルは予測力の
主張ではなく、Paper pipeline の境界と再現性を示す用途である。

## Phase 6 への境界

Phase 6 では versioned `StrategySpec` / 宣言的 DSL を、生成側と trusted interpreter の間の
契約として導入する予定である。LLM の出力は schema validation、許可済み feature / operator、
制約検査を通し、ここで定めた `BarContext` 境界の上で実行する。LLM が生成した
任意の Python、`eval` / `exec`、shell command を実行してはならない。Phase 5.5 はその
ための境界・再現性・識別子・索引の foundation hardening であり、LLM agent の
実装自体は対象外である。

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

Phase 5 / 5.5 の対象外は、実注文／broker API、FoF と Risk agent の本実装、
LLM による戦略生成、StrategySpec interpreter の本実装、addon dataset、指値・VWAP・
分足／Tick 執行である。次の Phase 6 では、ここで固定した Paper 境界と保存結果を
利用する役割エージェントへ進む。
