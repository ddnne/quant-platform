# Architecture（概要）

詳細設計は後続 Phase。ここでは方針と境界のみを固定する。

## 目的

日本株・開示・債券データを用いた **研究／Paper／FoF** 基盤を構築する。

## 正本と実験・CI

| 項目 | 方針 |
|------|------|
| 正本 | **GitHub リポジトリ 1 本（公開・非公開は運用で変更可）**（本リポジトリ） |
| 実験の枝分かれ | Cloudflare **Artifacts**（後続） |
| CI/CD | **Cloudflare**（後続）。**GitHub Actions には載せない** |

## データ取得と境界

- 外部データ取得は **Ingestion のみ**。エージェントや戦略コードから外部 API へ直接は出ない。
- **Secrets** は Cloudflare Secrets／環境変数。コード・リポジトリに埋め込まない。
- データは **`event_time`**（事象の時刻）と **`available_at`**（利用可能になった時刻）を持つ（**PIT** 前提）。
- 構造化保存では `available_at` は必須（空は拒否）。
- **構造化データの読み出しは PIT Data API（`pit/`）のみ。** 研究・特徴量・戦略コードは
  直接 SQLite を開かず、必ず `as_of` を取る `pit.get_*` 経由で読む。これが **fact の
  唯一の読み出し経路（sole read path for facts）** であり、look-ahead を構造で防ぐ。
  詳細は [pit_api.md](pit_api.md) を参照。

## 必須データ源（Phase 1 実装）

- **J-Quants**（API V2）
- **JSDA** 公社債取引統計

> 開示系データは独立した EDINET DB を介さず、**J-Quants の EDINET 系 API**（`/v2/edinet/major-shareholders`, `/v2/edinet/cross-shareholdings`, `/v2/edinet/large-volume-shareholders`, および `/v2/fins/...`）で統合する（カタログ実体: `ingestion/jquants/catalog.py`）。

Phase 1 は **ローカルランタイム主系**。ランタイムの切替（local / cloudflare）、Fetcher vs Registrar 分離（Pattern B）、`available_at` 検証、冪等 upsert、raw/structured 保存の詳細は [data_sources.md](data_sources.md) 参照。

## コアエンジンとエージェント

- **コアエンジン（Phase 3 最小実装）**はブラックボックス。エージェント・研究コードは
  `core.run_backtest` を呼び出して結果を消費するだけで、内部を改変しない。
- **fact は `pit.get_*` 経由のみ**（`core/` は SQLite/HTTP を直接開かない。`tests/test_core_data_boundary.py`
  が静的に強制）。戦略には意思決定 `as_of` 時点で既に PIT 読出し済みの狭い `BarContext` のみ渡す。
  look-ahead は PIT の `available_at <= as_of` と執行定義（`next_close` では D のシグナルは
  D に約定しない）の 2 重構造で防ぐ。詳細は [core_engine.md](core_engine.md)。
- 役割エージェント（後続）の例：
  - マクロ / ファンダ / クオンツ / コンポーザー
  - ストラテジスト / PM / トレーダー / Risk

## 選抜と規制

- **選抜優先**（戦略・実験の採用・淘汰を中心に回す）。
- 規制は最小限にとどめ、**PIT** と **境界**（Ingestion のみ外部通信、Secrets 非埋め込み等）は **構造で強制**する。
