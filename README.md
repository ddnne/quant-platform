# quant-platform

日本株・開示・債券データを用いた量化研究／Paper／FoF 基盤。  
正本は GitHub リポジトリ 1 本（公開・非公開は運用で変更可）。

## 現状（Phase 6）

**Phase 1（Ingestion）＋ Phase 2（PIT Data API）＋ Phase 3（コアエンジン最小）＋
Phase 3.5（CF J-Quants Premium 閉路の実装）＋ Phase 4（特徴量 Registry）＋
Phase 5（Paper 縦通し）＋ Phase 6（F0 hardening・役割 agent・StrategySpec）が完了した状態です。**

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

Phase 5 — **Paper 縦通し（`strategies/paper/`）**。`PaperRunConfig` → feature-driven 戦略 →
`core.run_backtest` → `PaperRunResult` → `JsonPaperStore` を接続する。結果は再現性 metadata と
trades を含み、既定で `data/paper/<strategy_id>/<run_id>.json` に保存する。外部 API は
ingestion-only で、戦略は DB／PIT／HTTP／secrets に直接触れない。詳細は
[docs/paper.md](docs/paper.md)。

Phase 6 — **full-code hardening + 役割 agent（`agents/`）+ StrategySpec
（`strategies/spec/`）**。Premium core 23 の canonical data contract、contract-driven
`event_time` / `available_at` / natural key、revision change feed、validated local snapshot
manifest、parallel-safe SQLite WAL paper index、stale valuation mark と explicit RAW price
basis、feature approval governance を固定した。8 役割は structured message のみを交換し、
StrategySpec は whitelist interpreter により approved feature の `ctx.feature` 呼び出しだけへ
変換される。Paper 後に独立 risk audit を保存する。詳細は
[docs/agents.md](docs/agents.md)。

> 開示系（EDINET 由来の大株主・持ち合い・大量保有）は独立した EDINET DB ではなく、**J-Quants の EDINET 系 API**（`/v2/edinet/major-shareholders`、`/v2/edinet/cross-shareholdings`、`/v2/edinet/large-volume-shareholders`、および `/v2/fins/...`）で統合する方針。Phase 1 では J-Quants 上記エンドポイント + JSDA が対象。

ランタイムは **local 主系**（`LocalHttpClient` / httpx）。Cloudflare は Phase 3.5 から取得閉路も担う（Premium core）。詳細は [docs/data_sources.md](docs/data_sources.md)。

**次は Phase 7（選抜・Knowledge・AI Gateway）** です。

詳細は [docs/architecture.md](docs/architecture.md) と [docs/roadmap.md](docs/roadmap.md) を参照してください。

## ディレクトリの見方

| パス | 役割 |
|------|------|
| `docs/` | アーキテクチャ・ロードマップ等の文書 |
| `ingestion/` | 外部データ取得（**Phase 1 実装**: J-Quants / JSDA） |
| `pit/` | **PIT Data API**（**Phase 2 実装**: `as_of` 必須の読み出し専用 API） |
| `core/` | **コアエンジン**（**Phase 3 実装**: PIT 経由のみのブラックボックスバックテスト） |
| `features/` | **特徴量 Registry**（**Phase 4 実装**: PIT 経由のみ・versioned・`as_of` 必須） |
| `risk/` | **Phase 6 実装**: Paper result と分離した immutable risk audit store |
| `strategies/` | **Phase 5–6 実装**: Paper runner／store、sample 戦略、declarative StrategySpec interpreter |
| `fof/` | Fund of Funds 層（後続） |
| `agents/` | **Phase 6 実装**: 8 役割の structured I/O と offline orchestrator |
| `platform/` | Cloudflare 等プラットフォーム設定・Secrets の置き場所（**Phase 3.5**: ingestion-premium Worker） |
| `cf_platform/` | Python 側の CF 連携ヘルパ（**Phase 3.5**: 検証ロジック・natural_key の真相） |
| `storage/` | SQLite スキーマ・ライタ（**Phase 1 実装**） |
| `scripts/` | 運用・開発用スクリプト（ingestion／sync／validation／Paper／agent CLI） |
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

## 運用完了の定義 (Ops completion)

Phase 3.5 の **運用完了** には以下の両方が必要:

- **Cron `failed=0`** — `quant-platform-ingestion-premium` の `/health` が
  `last_run.status ∈ {pass, partial-pass}` を報告し、`failed` 件数が 0 であること。
- **Live B0 strict pass** — 同じ DB で `QP_LIVE=1 python3 scripts/run_phase35_validation.py
  --db data/structured/ingestion.sqlite --tier daily` が exit 0 となること
  （LIVE_GATES: master ≳ 3,000 / bars issuers ≳ 3,000 / latest-day rows ≳ 3,000）。

**Phase 3.5/4 ops complete** は検証と accept の両レポートが緑であることを追加要件とします:

- **Validation report (weekly 緑)** — `python3 scripts/run_phase35_validation.py
  --db <DB> --tier weekly` が exit 0 (default `--require-implemented` for weekly).
  レポートは `data/reports/validation_*.json` に恒久化されるので事後監査が可能。
- **Phase 4 accept report** — `python3 scripts/run_phase4_accept.py` (offline) が
  exit 0。`QP_LIVE=1` では B0 strict + 50 銘柄サンプル + 50 日以上の BT を通すこと。

**フレームワーク完了 ≠ データ品質完了**。検証マトリクスのコード・カタログ・docs が揃っていても、
本番 cron が `failed=0` で回り、かつ live B0 strict が通って初めて運用完了と呼べる。
詳しくは [docs/phase35_validation_matrix.md](docs/phase35_validation_matrix.md) の
"Live strict gates" 節を参照。
