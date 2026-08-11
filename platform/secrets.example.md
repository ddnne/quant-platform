# Secrets（名前のみ）

値は書かない。Cloudflare Secrets または実行環境の環境変数として設定する。

## Phase 1 で使用

- `JQUANTS_API_KEY` — Cloudflare Worker のみ。local 直接利用は `UNSAFE_DEV_DIRECT_JQUANTS=1` を明示した開発時だけ。
- `JQUANTS_PROXY_TOKEN` — allowlist 済み upstream GET 専用。
- `INGESTION_RUN_TOKEN` — manual ingest / migration rebuild 専用。
- `DATA_EXPORT_TOKEN` — structured export 専用。
- `INGESTION_RUNTIME` — `local`（既定）/ `cloudflare`。CLI `--runtime` で上書き。

### J-Quants 秘匿プロキシ（推奨）

J-Quants 鍵は Cloudflare Worker `quant-platform-ingestion-secrets` のみが保持。local はプロキシ経由で取得するため、以下のいずれかでプロキシ座標（URL + 共有トークン）を設定（`ingestion/common/secrets.py` が解決）:

1. 環境変数 `JQUANTS_PROXY_URL` / `JQUANTS_PROXY_TOKEN`
2. ファイル `~/.config/quant-platform/jquants_proxy_url` / `jquants_proxy_token`（1 行目）

両方設定時のみ有効。片方のみなら `None`（未認証プロキシは不使用）。`--no-jquants-proxy` で直接取得に強制。トークンは鍵扱い（ログ/コミット禁止）。

プロキシ権限は `data_contracts/jquants_premium_core.json` に列挙された path の upstream
`GET` と `data_contracts/jquants_proxy_addons.json` に固定した既存 addon 5 path のみに
限定する。任意の `/v2/*` や書き込み method は許可せず、新 endpoint は共有 contract に
明示追加されるまで fail-closed とする。

> JSDA は鍵不要（公開統計ページ）。`--source jsda` は環境変数なしで実行可能。

## その他

必要に応じて後続 Phase で名前を追加する（例: AI Gateway、執行系）。  
**値や本番キーをこのリポジトリにコミットしないこと。**
