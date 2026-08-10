# quant-platform

日本株・開示・債券データを用いた量化研究／Paper／FoF 基盤。  
正本は GitHub リポジトリ 1 本（公開・非公開は運用で変更可）。

## 現状（Phase 1）

**Phase 1（Ingestion）が完了した状態です。** 2 データソースの取得・正規化・格納が動きます:

- **J-Quants** API V2（銘柄一覧 / 日足 / カレンダー / 財務サマリ任意）
- **JSDA** 公社債取引統計（CSV/XLSX）

> 開示系（EDINET 由来の書面・財務詳細）は独立した EDINET DB ではなく、**J-Quants の EDINET 系 API**（`/v2/documents`、`/v2/fins/...`）で後続 Phase に統合する方針。Phase 1 では J-Quants 上記エンドポイント + JSDA が対象。

ランタイムは **local 主系**（`LocalHttpClient` / httpx）。Cloudflare は Pattern B でストレージ読取のみ（Phase 1 では取得しない）。詳細は [docs/data_sources.md](docs/data_sources.md)。

**次は Phase 2（PIT Data API）** です。

詳細は [docs/architecture.md](docs/architecture.md) と [docs/roadmap.md](docs/roadmap.md) を参照してください。

## ディレクトリの見方

| パス | 役割 |
|------|------|
| `docs/` | アーキテクチャ・ロードマップ等の文書 |
| `ingestion/` | 外部データ取得（**Phase 1 実装**: J-Quants / JSDA） |
| `core/` | コアエンジン（後続 Phase） |
| `features/` | 特徴量 Registry（後続） |
| `risk/` | リスク管理（後続） |
| `strategies/` | 戦略定義・Paper 関連（後続） |
| `fof/` | Fund of Funds 層（後続） |
| `agents/` | 役割エージェント（後続） |
| `platform/` | Cloudflare 等プラットフォーム設定・Secrets の置き場所 |
| `storage/` | SQLite スキーマ・ライタ（**Phase 1 実装**） |
| `scripts/` | 運用・開発用スクリプト（**Phase 1**: `run_ingestion_once.py`） |
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
