# quant-platform

日本株・開示・債券データを用いた量化研究／Paper／FoF 基盤。  
正本は GitHub リポジトリ 1 本（公開・非公開は運用で変更可）。

## 現状（Phase 4）

**Phase 1（Ingestion）＋ Phase 2（PIT Data API）＋ Phase 3（コアエンジン最小）＋
Phase 3.5（CF J-Quants Premium 閉路の実装）＋ Phase 4（特徴量 Registry）が完了した状態です。**

Phase 1 — 2 データソースの取得・正規化・格納が動きます:

- **J-Quants** API V2 — カタログ全量（`ingestion/jquants/catalog.py` の `DATASETS`）:
  銘柄マスター・日足（含む AM）・財務（summary / details / dividend / earnings-date）・
  決算カレンダー・市場カレンダー・投資部門・指数（TOPIX / 一般）・デリバティブ
  （日経225オプション / 先物 / オプション）・市場系（信用・空売り・ブレイクダウン）・
  **EDINET 系**（大株主・持ち合い・大量保有）・分足・Tick（trades）・TDnet 系（list / files / bulk）。
- **JSDA** 公社債取引統計（CSV/XLSX）

Phase 2 — 構造化データの **読み出し経路として PIT Data API（`pit/`）** を実装。
全読み出しは `as_of` 必須・`available_at <= as_of` で look-ahead を防止・読み取り専用
（`mode=ro`）。**直接 SQLite での研究読み出しは禁止**（[docs/pit_api.md](docs/pit_api.md)）。

Phase 3 — **コアエンジン最小（`core/`）**。ブラックボックスのバックテストエンジン。
fact は `pit.get_*` 経由のみ（`core/` は SQLite/HTTP を直接開かない）、戦略には意思決定 `as_of`
時点の狭い `BarContext` のみを渡す。`next_close`/`same_day_close` 執行・標準/ストレス費用・
再現性メタデータ付き。詳細は [docs/core_engine.md](docs/core_engine.md)。

Phase 3.5 — **Cloudflare 上の J-Quants Premium core 閉路の実装**。Worker
`quant-platform-ingestion-premium` は、デプロイ後に cron で 23 データセットを取得し、R2 raw + D1
structured に保存・per-dataset の pass/fail 検証を行う。**閉路の対象は Premium core 23 だけ**:
addon（分足・Tick・TDnet）は Phase 1 でカタログされているが Phase 3.5 のスケジュール対象外。
ローカルはページネーション付き `/v1/export/d1` から同期して `pit.get_*` で読む。
検証は per-job の pass/fail に加えて、
[docs/phase35_validation_matrix.md](docs/phase35_validation_matrix.md) のカタログ
（C1–C12, M*, B*, A*, K*, E*, F*, I*, D*, S*, N*, X*）を daily / weekly の 2 階層で実行する。
Cloudflare リソース作成・migration・同一 secret 値の binding・deploy が完了して初めて本番閉路が有効になる。
2026-08-11 JST 時点で `quant-ingest`、`quant-raw`、`quant-structured` を作成し、migration、
既存の 2 secret binding、Worker + Cron deploy、`/health` とページ export を確認済み。
詳細は [docs/phase35_cf_ingest.md](docs/phase35_cf_ingest.md)。

Phase 4 — **特徴量 Registry（`features/`）**。PIT 経由のみの versioned 特徴量セット。
`as_of` 必須・`features/` は `pit.get_*` 以外の fact 経路を使わない（静的テストで強制）。
`return_1d`, `momentum_n`, `volatility_n` を同梱。詳細は [docs/features.md](docs/features.md)。

> 開示系（EDINET 由来の大株主・持ち合い・大量保有）は独立した EDINET DB ではなく、**J-Quants の EDINET 系 API**（`/v2/edinet/major-shareholders`、`/v2/edinet/cross-shareholdings`、`/v2/edinet/large-volume-shareholders`、および `/v2/fins/...`）で統合する方針。Phase 1 では J-Quants 上記エンドポイント + JSDA が対象。

ランタイムは **local 主系**（`LocalHttpClient` / httpx）。Cloudflare は Phase 3.5 から取得閉路も担う（Premium core）。詳細は [docs/data_sources.md](docs/data_sources.md)。

**次は Phase 5（Paper 縦通し）** です。

詳細は [docs/architecture.md](docs/architecture.md) と [docs/roadmap.md](docs/roadmap.md) を参照してください。

## ディレクトリの見方

| パス | 役割 |
|------|------|
| `docs/` | アーキテクチャ・ロードマップ等の文書 |
| `ingestion/` | 外部データ取得（**Phase 1 実装**: J-Quants / JSDA） |
| `pit/` | **PIT Data API**（**Phase 2 実装**: `as_of` 必須の読み出し専用 API） |
| `core/` | **コアエンジン**（**Phase 3 実装**: PIT 経由のみのブラックボックスバックテスト） |
| `features/` | **特徴量 Registry**（**Phase 4 実装**: PIT 経由のみ・versioned・`as_of` 必須） |
| `risk/` | リスク管理（後続） |
| `strategies/` | 戦略定義・Paper 関連（後続） |
| `fof/` | Fund of Funds 層（後続） |
| `agents/` | 役割エージェント（後続） |
| `platform/` | Cloudflare 等プラットフォーム設定・Secrets の置き場所（**Phase 3.5**: ingestion-premium Worker） |
| `cf_platform/` | Python 側の CF 連携ヘルパ（**Phase 3.5**: 検証ロジック・natural_key の真相） |
| `storage/` | SQLite スキーマ・ライタ（**Phase 1 実装**） |
| `scripts/` | 運用・開発用スクリプト（`run_ingestion_once.py`・`sync_d1_to_sqlite.py`） |
| `tests/` | テスト（オフライン・鍵不要で green） |

## 開発言語・ツール

- **Python 3.11+**（`pyproject.toml` で `requires-python = ">=3.11"`）
- HTTP は **httpx**（local ランタイム）
- ランタイム・デプロイは後続で **Cloudflare**（Workers / Workflows / Secrets 等）を想定
- CI/CD は Cloudflare 側で行う方針（GitHub Actions には載せない）
- 実験の枝分かれは後続で Cloudflare Artifacts を想定

確定は後続 Phase で更新します。

## セットアップとテスト

```bash
# Python 3.11 環境を用意（例: uv）
uv venv --python 3.11 .venv && source .venv/bin/activate
pip install -e ".[dev]"

# テスト（API 鍵不要・オフラインで green）
python -m pytest tests/ -q
python -m unittest tests.test_smoke -v
```

## Phase 1 の取得（ローカル）

```bash
# JSDA のみ（鍵不要）
python scripts/run_ingestion_once.py --source jsda --runtime local

# 2 ソースすべて（J-Quants の鍵は CF proxy 既定、未設定時は環境変数）
python scripts/run_ingestion_once.py --source all

# Cloudflare ランタイムは Phase 1 では取得しない（exit 2）
python scripts/run_ingestion_once.py --source all --runtime cloudflare
```

終了コード: `0`=取得/登録あり, `1`=予期せぬエラー, `2`=何も実行せず（CF ランタイム or 全ソース skip）。

## Secrets

API キー等はコードに埋め込まない。名前の一覧のみ [platform/secrets.example.md](platform/secrets.example.md) を参照。  
`JQUANTS_API_KEY` の **正本は Cloudflare Secret**（Worker が保持）。ローカルは **CF proxy を既定で利用**（環境変数 `INGESTION_PROXY_URL`/`INGESTION_PROXY_TOKEN` または `~/.config/quant-platform/ingestion_proxy_{url,token}` を設定すると有効。proxy 未設定時のみ環境変数 `JQUANTS_API_KEY` の直接利用にフォールバック）。
