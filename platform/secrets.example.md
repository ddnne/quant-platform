# Secrets（名前のみ）

値は書かない。Cloudflare Secrets または実行環境の環境変数として設定する。

## Phase 1 で使用

- `JQUANTS_API_KEY` — J-Quants API V2（ヘッダ `x-api-key`）。**直接取得時のみ必須**。Cloudflare 秘匿プロキシ経由（推奨）なら local には不要。未設定かつプロキシ未設定時は skip。
- `EDINETDB_API_KEY` — EDINET DB（ヘッダ `X-API-Key`）。未設定時は skip。
- `INGESTION_RUNTIME` — `local`（既定）/ `cloudflare`。CLI `--runtime` で上書き。

### J-Quants 秘匿プロキシ（推奨）

J-Quants 鍵は Cloudflare Worker `quant-platform-ingestion-secrets` のみが保持。local はプロキシ経由で取得するため、以下のいずれかでプロキシ座標（URL + 共有トークン）を設定（`ingestion/common/secrets.py` が解決）:

1. 環境変数 `INGESTION_PROXY_URL` / `INGESTION_PROXY_TOKEN`
2. ファイル `~/.config/quant-platform/ingestion_proxy_url` / `ingestion_proxy_token`（1 行目）

両方設定時のみ有効。片方のみなら `None`（未認証プロキシは不使用）。`--no-jquants-proxy` で直接取得に強制。トークンは鍵扱い（ログ/コミット禁止）。

> JSDA は鍵不要（公開統計ページ）。`--source jsda` は環境変数なしで実行可能。

## その他

必要に応じて後続 Phase で名前を追加する（例: AI Gateway、執行系）。  
**値や本番キーをこのリポジトリにコミットしないこと。**

