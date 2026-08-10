# quant-platform

日本株・開示・債券データを用いた量化研究／Paper／FoF 基盤。  
正本は GitHub プライベートリポジトリ 1 本（本リポジトリ）。

## 現状（Phase 0）

**Phase 0（リポジトリと土台）が完了した状態です。**  
データ取得・戦略・エージェント・コアエンジンの実装はまだありません。  
**次は Phase 1（Ingestion: J-Quants / EDINET DB / JSDA）** です。

詳細は [docs/architecture.md](docs/architecture.md) と [docs/roadmap.md](docs/roadmap.md) を参照してください。

## ディレクトリの見方

| パス | 役割 |
|------|------|
| `docs/` | アーキテクチャ・ロードマップ等の文書 |
| `ingestion/` | 外部データ取得（Phase 1 以降） |
| `core/` | コアエンジン（後続 Phase） |
| `features/` | 特徴量 Registry（後続） |
| `risk/` | リスク管理（後続） |
| `strategies/` | 戦略定義・Paper 関連（後続） |
| `fof/` | Fund of Funds 層（後続） |
| `agents/` | 役割エージェント（後続） |
| `platform/` | Cloudflare 等プラットフォーム設定・Secrets の置き場所 |
| `storage/` | スキーマ・ストレージ設計の置き場所（後続） |
| `scripts/` | 運用・開発用スクリプト（後続） |
| `tests/` | テスト |

## 開発言語・ツール（仮置き）

- **Python 3.11+** を推奨（研究・データ処理・テスト）
- ランタイム・デプロイは後続で **Cloudflare**（Workers / Workflows / Secrets 等）を想定
- CI/CD は Cloudflare 側で行う方針（GitHub Actions には載せない）
- 実験の枝分かれは後続で Cloudflare Artifacts を想定

確定は後続 Phase で更新します。

## テストの回し方

```bash
python -m pytest tests/ -q
```

（`pytest` が無い場合は `pip install pytest` のうえ実行。スモークは `python -m unittest tests.test_smoke -v` でも可。）

## Secrets

API キー等はコードに埋め込まない。名前の一覧のみ [platform/secrets.example.md](platform/secrets.example.md) を参照。  
値は Cloudflare Secrets / 環境変数で管理する。
